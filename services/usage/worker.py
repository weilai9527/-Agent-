"""在评分和报告的真实模型派发点执行学校配额，同时保留已付响应供任务重放。"""
import os
from functools import wraps

from services.assessment.storage_mode import assessment_owner, emit_projections
from services.interview.jobs import RetryJob
from shared.offline_fixture import require_offline_fixture
from . import journal
from .provider_calls import PendingProviderCall, provider_call_context


def initialize(queue):
    """原生评估库始终绑定学校和计量身份。服务地址丢失不应把任务变成免费执行。"""
    if emit_projections():
        return
    native = assessment_owner()
    if not native:
        require_offline_fixture()
    suffix = " ENGINE=InnoDB DEFAULT CHARSET=utf8mb4" if queue.mysql else ""
    with queue.db:
        queue.db.execute("""CREATE TABLE IF NOT EXISTS worker_text_policy (
            slot INTEGER PRIMARY KEY, school_id VARCHAR(128) NOT NULL, caller VARCHAR(128) NOT NULL)""" + suffix).close()
        if native or "USAGE_SERVICE_URL" in os.environ:
            school = os.environ.get("LEGACY_SCHOOL_ID")
            caller = expected_caller()
            if not school or not caller:
                raise RuntimeError("Text metering requires a bound school and worker identity")
            conflict = ("ON DUPLICATE KEY UPDATE slot=slot" if queue.mysql else "ON CONFLICT(slot) DO NOTHING")
            queue.db.execute("INSERT INTO worker_text_policy VALUES (1,?,?) " + conflict, (school, caller)).close()
    if policy(queue):
        journal.migrate(queue)
        engine = " ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci" if queue.mysql else ""
        with queue.db:
            queue.db.execute("""CREATE TABLE IF NOT EXISTS worker_text_runs (
                job_id CHAR(64) PRIMARY KEY, interview_id CHAR(36) NOT NULL,
                execution_no BIGINT NOT NULL, wait_reason VARCHAR(80),
                FOREIGN KEY(interview_id) REFERENCES interview_sessions(id) ON DELETE CASCADE
            )""" + engine).close()


def expected_caller():
    # HTTP 接口和后台进程竞争同一任务租约；只有绑定的工作身份能预留、恢复和结算。
    return "assessment" if assessment_owner() else os.environ.get("TEXT_USAGE_CALLER_ID", "assessment")


def policy(queue):
    return queue._one("SELECT school_id,caller FROM worker_text_policy WHERE slot=1", ())


def student(queue, job, binding):
    school = binding["school_id"]
    if (school != os.environ.get("LEGACY_SCHOOL_ID") or binding["caller"] != expected_caller()
            or os.environ.get("SERVICE_ID") != binding["caller"]):
        raise journal.TextJobDeferred("usage_worker_identity_mismatch")
    row = queue._one("SELECT id,user_id FROM interview_sessions WHERE id=?", (job["interview_id"],))
    if not row or row["id"] != job["interview_id"]:
        raise journal.TextJobDeferred("usage_missing_interview")
    if assessment_owner():
        receipt = queue._one("""SELECT school_id,student_id FROM assessment_projection_inbox
                             WHERE interview_id=? AND sequence_no=0""", (row["id"],))
        if not receipt or (receipt["school_id"], receipt["student_id"]) != (school, row["user_id"]):
            raise journal.TextJobDeferred("usage_projection_owner_mismatch")
    training = queue._one("SELECT school_id,student_id FROM interview_training_attempts WHERE interview_id=?", (row["id"],))
    if training and (training["school_id"], training["student_id"]) != (school, row["user_id"]):
        raise journal.TextJobDeferred("usage_training_owner_mismatch")
    return {"school_id": school, "actor_type": "student", "actor_id": row["user_id"]}


def execution_no(queue, job):
    with queue._transaction():
        if not queue._owns_lease(job):
            raise journal.TextJobDeferred("worker_lease_lost")
        conflict = "ON DUPLICATE KEY UPDATE job_id=job_id" if queue.mysql else "ON CONFLICT(job_id) DO NOTHING"
        queue.db.execute("""INSERT INTO worker_text_runs(job_id,interview_id,execution_no)
                         VALUES (?,?,1) """ + conflict, (job["id"], job["interview_id"])).close()
        return queue._one("SELECT execution_no FROM worker_text_runs WHERE job_id=?", (job["id"],))["execution_no"]


def wait_for_usage(queue, job, reason):
    """持有队列租约才可写入等待原因，暂缓调用不会生成分数。"""
    queue.db.execute("UPDATE worker_text_runs SET wait_reason=? WHERE job_id=?", (reason, job["id"])).close()
    messages = {"quota_exhausted": "学校文字额度已用尽，任务等待可用额度。",
                "provider_reconciliation_required": "供应商执行结果待核对，暂停重复派发。",
                "settlement_conflict": "用量结算需核对，已保存的模型响应不会重复派发。"}
    message = messages.get(reason, "文字模型任务暂缓，等待用量服务或工作租约恢复。")
    if job["kind"] == "report":
        queue.db.execute("""UPDATE interview_reports SET generation_error=? WHERE interview_id=? AND id=?
                         AND generation_status='queued'""", (message, job["interview_id"], job["subject_id"])).close()
    return RetryJob()


def prepare_metered(queue, job, prepare):
    if emit_projections():
        raise journal.TextJobDeferred("assessment_service_required")
    binding = policy(queue)
    if not binding:
        if assessment_owner() or "USAGE_SERVICE_URL" in os.environ:
            raise journal.TextJobDeferred("usage_policy_not_initialized")
        # 仅显式启用且仍绑定临时合成旧库的离线夹具可运行未计量的兼容逻辑。
        require_offline_fixture()
        return prepare(job)
    try:
        execution = execution_no(queue, job)
        actor = student(queue, job, binding)
        # 先核对已收到的模型回执。即使证据版本已更新，这些请求仍需按原账期结算。
        journal.reconcile_job(queue, job, actor)
        if not os.environ.get("USAGE_SERVICE_URL") and not queue._one(
            "SELECT id FROM worker_model_attempts WHERE job_id=? AND state='settled' LIMIT 1", (job["id"],)
        ):
            raise journal.TextJobDeferred("usage_unavailable")
        ordinal = 0

        def attempt(meta, send):
            nonlocal ordinal
            ordinal += 1
            # 准备期只覆盖用量服务的派发确认；进入执行中后，长调用和延迟结算仍保留原预留。
            return journal.run_request(queue, job, actor, purpose=f"g{execution}.call{ordinal}",
                                       request_fingerprint=meta.request_hash, dispatch=send,
                                       required_seconds=15, ttl_seconds=120)

        with provider_call_context(attempt):
            publish = prepare(job)
    except (journal.TextJobDeferred, PendingProviderCall) as exc:
        reason = getattr(exc, "reason", "provider_reconciliation_required")
        return lambda: wait_for_usage(queue, job, reason)

    def publish_and_retire():
        # 发布结果、清空临时输出和确认任务同事务提交。提交前崩溃仍重放原调用；
        # 已发布后的强制重评或已知无效输出的重试才进入新执行代次。
        result = publish()
        if isinstance(result, RetryJob) and not ordinal and queue._one(
            "SELECT id FROM worker_model_attempts WHERE job_id=? AND state='settled' AND outcome='success' LIMIT 1",
            (job["id"],),
        ):
            # 缺少模型配置的副本只能生成降级结果，保留已付回执给可重放原方案的工作进程。
            return wait_for_usage(queue, job, "model_replay_pending")
        queue.db.execute("""UPDATE worker_model_attempts SET state='published',content=NULL
                         WHERE job_id=? AND state='settled'""", (job["id"],)).close()
        queue.db.execute("""UPDATE worker_text_runs SET execution_no=execution_no+1,wait_reason=NULL
                         WHERE job_id=?""", (job["id"],)).close()
        return result
    return publish_and_retire


def metered(queue):
    """后台进程和同步 HTTP 接口共用同一份学校预算。"""
    def decorate(prepare):
        @wraps(prepare)
        def run(job):
            return prepare_metered(queue, job, prepare)
        return run
    return decorate
