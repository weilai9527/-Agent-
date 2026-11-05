"""持久记录每次付费 HTTP 尝试，让接管进程能恢复结果和结算。

任务行锁协调多个工作进程的派发，所有网络请求都在事务外执行。旧进程仅可补记它曾经派发的确切请求的回执。
派发、结算及读取结果均须持有当前任务租约。
"""
import hashlib
import json
import os
import re
from contextlib import closing
from uuid import uuid4

from fastapi import HTTPException

from .provider_calls import ProviderAttemptFailed, model_request_id
from .text import begin_text, reserve_text, settle_text


class TextJobDeferred(RuntimeError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def migrate(queue):
    suffix = " ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci" if queue.mysql else ""
    index = ", INDEX worker_model_job (job_id,state)" if queue.mysql else ""
    with queue.db:
        queue.db.execute(f"""CREATE TABLE IF NOT EXISTS worker_model_attempts (
            id CHAR(64) PRIMARY KEY, job_id CHAR(64) NOT NULL, interview_id CHAR(36) NOT NULL,
            purpose VARCHAR(255) NOT NULL, fingerprint CHAR(64) NOT NULL,
            school_id VARCHAR(128) NOT NULL, actor_id VARCHAR(128) NOT NULL,
            actor_type VARCHAR(16) NOT NULL, caller VARCHAR(128) NOT NULL,
            state VARCHAR(16) NOT NULL, generation INTEGER NOT NULL, ttl_seconds INTEGER NOT NULL,
            reservation_id CHAR(32), dispatch_token CHAR(32), worker_lease CHAR(32),
            outcome VARCHAR(16), status_code INTEGER, content LONGTEXT,
            FOREIGN KEY(interview_id) REFERENCES interview_sessions(id) ON DELETE CASCADE
            {index}
        ){suffix}""").close()
        if not queue.mysql:
            queue.db.execute("""CREATE INDEX IF NOT EXISTS worker_model_job
                ON worker_model_attempts(job_id,state)""").close()


def _owner(actor):
    parts = (actor.get("school_id"), actor.get("actor_id"), actor.get("actor_type"), os.environ.get("SERVICE_ID"))
    if not all(isinstance(s, str) and 0 < len(s) <= 128 for s in parts):
        raise TextJobDeferred("missing_usage_identity")
    return parts


def _check(queue, job, actor):
    """在队列事务内先锁定任务，再对照已持久化的身份检查归属。"""
    if not job.get("lease_token") or not queue._owns_lease(job):
        raise TextJobDeferred("worker_lease_lost")
    actual = queue._one("SELECT interview_id,state FROM interview_jobs WHERE id=?", (job["id"],))
    if actual["state"] != "running" or actual["interview_id"] != job["interview_id"]:
        raise TextJobDeferred("worker_job_mismatch")
    owner = _owner(actor)
    # 旧 MySQL 库可能不区分标识符的大小写，因此在 Python 中进行精确比较。
    with closing(queue.db.execute("""SELECT school_id,actor_id,actor_type,caller FROM worker_model_attempts
                                  WHERE job_id=?""", (job["id"],))) as rows:
        for record in rows.fetchall():
            if tuple(record[name] for name in ("school_id", "actor_id", "actor_type", "caller")) != owner:
                raise TextJobDeferred("usage_identity_changed")
    return owner


def _row(queue, slot):
    return queue._one("SELECT * FROM worker_model_attempts WHERE id=?", (slot,))


def _unresolved(queue, job):
    return queue._one("""SELECT state FROM worker_model_attempts WHERE job_id=?
                       AND state IN ('authorizing','dispatching','unknown','received') LIMIT 1""", (job["id"],))


def _settle(queue, job, actor, row):
    units = {"success": 1, "invalid": 1, "unsent": 0, "rejected": 0}
    if row["outcome"] not in units:
        raise TextJobDeferred("unconfirmed_provider_receipt")
    actual = units[row["outcome"]]
    try:
        settle_text(actor, row["reservation_id"], actual_units=actual)
    except HTTPException as exc:
        reason = "settlement_conflict" if exc.status_code == 409 else "settlement_pending"
        raise TextJobDeferred(reason) from None
    with queue._transaction():
        _check(queue, job, actor)
        queue.db.execute("""UPDATE worker_model_attempts SET state='settled'
                           WHERE id=? AND state='received'""", (row["id"],)).close()


def _reservation(actor, row, required_seconds=1):
    return reserve_text(actor, interview_id=row["interview_id"], operation_id=row["id"],
                        purpose=f"http.{row['generation']}", ttl_seconds=row["ttl_seconds"],
                        required_seconds=min(required_seconds, row["ttl_seconds"]))


def _cancel_authorization(queue, job, actor, row):
    """接管旧进程留下的授权步骤。本地日志表明该请求尚未获准发送。

    用量服务对迟到的 begin 与退款串行处理。已结算或已过期的预留不能重新进入执行中。
    即使旧进程此时收到 begin 确认，它也无法通过发送前的租约和派发凭据检查。
    """
    try:
        hold = _reservation(actor, row)
        if hold.reservation_id != row["reservation_id"]:
            raise TextJobDeferred("authorization_reconciliation_pending")
        if hold.state in {"reserved", "in_flight"} or hold.reason == "insufficient_lease":
            settle_text(actor, row["reservation_id"], actual_units=0)
        elif hold.reason != "reservation_expired" and not (hold.state == "settled" and hold.actual_units == 0):
            raise TextJobDeferred("authorization_reconciliation_pending")
    except HTTPException:
        # 尚未进入执行状态的预留可能在查询后、撤销前到期。交给下一次租约重查，仅在确认终态后解除本地派发限制。
        raise TextJobDeferred("authorization_reconciliation_pending") from None
    with queue._transaction():
        _check(queue, job, actor)
        queue.db.execute("""UPDATE worker_model_attempts SET state='prepared',generation=generation+1,
                            dispatch_token=NULL,worker_lease=NULL,reservation_id=NULL
                            WHERE id=? AND state='authorizing' AND dispatch_token=?""",
                         (row["id"], row["dispatch_token"])).close()


def reconcile_job(queue, job, actor):
    """先结算已保存的回执，即使配置或评分证据有变、原尝试已无需执行。"""
    with queue._transaction():
        _check(queue, job, actor)
        # 接管任务时，旧请求仍可能收到响应。保留其一次性回执凭据，阻止该任务派发新的模型请求。
        queue.db.execute("""UPDATE worker_model_attempts SET state='unknown' WHERE job_id=?
                            AND state='dispatching' AND worker_lease<>?""", (job["id"], job["lease_token"])).close()
        with closing(queue.db.execute("""SELECT * FROM worker_model_attempts WHERE job_id=?
                                      AND state='authorizing' AND worker_lease<>?""",
                                      (job["id"], job["lease_token"]))) as rows:
            abandoned = [dict(row) for row in rows.fetchall()]
        with closing(queue.db.execute("""SELECT id,reservation_id,outcome FROM worker_model_attempts
                                      WHERE job_id=? AND state='received'""", (job["id"],))) as rows:
            received = [dict(row) for row in rows.fetchall()]
    for row in received:
        _settle(queue, job, actor, row)
    for row in abandoned:
        _cancel_authorization(queue, job, actor, row)
    with queue._transaction():
        _check(queue, job, actor)
        if _unresolved(queue, job):
            raise TextJobDeferred("provider_reconciliation_required")


def _replay(row):
    if row["outcome"] != "success":
        raise ProviderAttemptFailed(row["outcome"], row["status_code"])
    return row["content"]


def _persist_response(queue, slot, dispatch_token, outcome, status, content):
    # 一次性凭据绑定原派发。即使接管进程已将结果记为未知，旧进程仍可补写迟到的回执。
    with queue._transaction():
        with closing(queue.db.execute("""UPDATE worker_model_attempts
                SET state=?,outcome=?,status_code=?,content=?
                WHERE id=? AND dispatch_token=? AND state IN ('dispatching','unknown')""",
                ("unknown" if outcome == "unknown" else "received", outcome, status, content, slot, dispatch_token))) as cur:
            changed = cur.rowcount
    if changed != 1:
        raise TextJobDeferred("dispatch_receipt_unavailable")


def run_request(queue, job, actor, *, purpose, request_fingerprint, dispatch,
                required_seconds=60, ttl_seconds=300):
    """返回已确认的模型输出；若该次请求已确认失败，则重现其失败类别。"""
    if (not isinstance(purpose, str) or not 0 < len(purpose) <= 255
            or not isinstance(request_fingerprint, str) or not re.fullmatch("[a-f0-9]{64}", request_fingerprint)):
        raise ValueError("Expected stable HTTP attempt slot and SHA-256 request digest")
    if (type(required_seconds) is not int or type(ttl_seconds) is not int
            or not 1 <= required_seconds <= ttl_seconds <= 3600):
        raise ValueError("Invalid model request lease duration")
    slot = hashlib.sha256(json.dumps([job["id"], purpose], ensure_ascii=False).encode()).hexdigest()
    reconcile_job(queue, job, actor)
    with queue._transaction():
        owner = _check(queue, job, actor)
        row = _row(queue, slot)
        if not row:
            queue.db.execute("""INSERT INTO worker_model_attempts
                (id,job_id,interview_id,purpose,fingerprint,school_id,actor_id,actor_type,caller,
                 state,generation,ttl_seconds) VALUES (?,?,?,?,?,?,?,?,?,'prepared',0,?)""",
                (slot, job["id"], job["interview_id"], purpose, request_fingerprint, *owner, ttl_seconds)).close()
            row = _row(queue, slot)
        if row["fingerprint"] != request_fingerprint:
            if row["state"] != "prepared":
                raise TextJobDeferred("model_request_changed")
            # 此时最多只有可到期的普通预留。推进代次，使旧模型预留的迟到确认失效。
            queue.db.execute("""UPDATE worker_model_attempts SET fingerprint=?,generation=generation+1,
                                ttl_seconds=? WHERE id=?""", (request_fingerprint, ttl_seconds, slot)).close()
            row = _row(queue, slot)
        if row["state"] == "settled":
            return _replay(row)
        if _unresolved(queue, job) or row["state"] != "prepared":
            raise TextJobDeferred("provider_reconciliation_required")

    try:
        admission = _reservation(actor, row, required_seconds)
    except HTTPException:
        raise TextJobDeferred("reservation_rejected") from None

    # 预留返回后，重新核对任务租约、其他未决请求、代次及数据库时间；旧进程拿到同一预留也不能派发。
    dispatch_token = uuid4().hex
    with queue._transaction():
        _check(queue, job, actor)
        current = _row(queue, slot)
        if not current or current["generation"] != row["generation"] or current["state"] != "prepared":
            raise TextJobDeferred("model_attempt_changed")
        if _unresolved(queue, job):
            raise TextJobDeferred("provider_reconciliation_required")
        if admission.reason == "reservation_expired":
            # 日志尚未登记派发意图，可以安全更换这笔已到期的预留。
            queue.db.execute("""UPDATE worker_model_attempts SET generation=generation+1,ttl_seconds=?
                              WHERE id=?""", (ttl_seconds, slot)).close()
        elif admission.state == "reserved":
            db_now = queue._one(f"SELECT {queue.now} AS ts", ())["ts"]
            if not admission.expires_at or admission.expires_at - db_now < required_seconds:
                raise TextJobDeferred("insufficient_lease")
            # 先保存预留号，再请求 begin。即使确认回包前进程退出，接管者也能找到并释放这笔执行预留。
            queue.db.execute("""UPDATE worker_model_attempts SET state='authorizing',
                               reservation_id=?,dispatch_token=?,worker_lease=? WHERE id=?""",
                             (admission.reservation_id, dispatch_token, job["lease_token"], slot)).close()
        elif admission.state in {"in_flight", "settled"}:
            # 若远端已进入执行状态或已结算，但本地没有派发回执，保留预留号以便查证实际执行的是哪个请求。
            queue.db.execute("""UPDATE worker_model_attempts SET state='unknown',reservation_id=?
                             WHERE id=?""", (admission.reservation_id, slot)).close()
    if admission.state != "reserved":
        raise TextJobDeferred(admission.reason or "provider_reconciliation_required")

    try:
        begin_text(actor, admission.reservation_id)
    except HTTPException:
        # 授权可能已经提交。保留凭据，接管进程须先核对并退回尚未派发的额度。
        raise TextJobDeferred("authorization_reconciliation_pending") from None

    with queue._transaction():
        _check(queue, job, actor)
        with closing(queue.db.execute("""UPDATE worker_model_attempts SET state='dispatching'
                    WHERE id=? AND state='authorizing' AND dispatch_token=? AND worker_lease=?""",
                    (slot, dispatch_token, job["lease_token"]))) as cur:
            if cur.rowcount != 1:
                raise TextJobDeferred("model_attempt_changed")

    outcome, status, content = "success", None, None
    try:
        with model_request_id(slot):
            content = dispatch()
        if not isinstance(content, str) or not content.strip():
            raise ProviderAttemptFailed("invalid")
    except ProviderAttemptFailed as exc:
        outcome, status = exc.outcome, exc.status
        if outcome not in {"unsent", "rejected", "invalid", "unknown"}:
            outcome = "unknown"
        content = None
    except Exception:
        # 登记派发后遇到无法分类的异常时，供应商可能已执行请求，因此保持待核对状态。
        outcome = "unknown"
        content = None
    _persist_response(queue, slot, dispatch_token, outcome, status, content)
    reconcile_job(queue, job, actor)
    with queue._transaction():
        _check(queue, job, actor)
        return _replay(_row(queue, slot))
