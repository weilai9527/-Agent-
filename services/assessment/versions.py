"""报告版本与复核事件共用原报告的事务和锁。"""

import json
from contextlib import contextmanager
from uuid import uuid4

from fastapi import HTTPException

from services.interview.storage import DB_ENGINE, all_rows, db, one
from services.interview.progress import locked_session
from services.interview.delivery import enqueue_analytics


def init_schema():
    # MySQL 的 DDL 会隐式提交，此迁移须在业务事务外运行。
    mysql = DB_ENGINE == "mysql"
    large_text = "LONGTEXT" if mysql else "TEXT"
    suffix = " ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci" if mysql else ""
    with db:
        db.execute(f"""
            CREATE TABLE IF NOT EXISTS assessment_issuance_permits (
                report_id CHAR(36) NOT NULL, application_id CHAR(64) NOT NULL, generation INT NOT NULL,
                serial CHAR(32) NOT NULL UNIQUE, version INT NOT NULL, digest CHAR(64) NOT NULL,
                proof_digest CHAR(64) NOT NULL, authorized_by VARCHAR(128) NOT NULL,
                school_id VARCHAR(128) NOT NULL, authorized_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (report_id, application_id, generation)
            ){suffix}
        """).close()
        db.execute(f"""
            CREATE TABLE IF NOT EXISTS assessment_report_versions (
                report_id CHAR(36) NOT NULL, version INT NOT NULL,
                evidence_version VARCHAR(128), source VARCHAR(24) NOT NULL,
                actor_id VARCHAR(128), reason TEXT, snapshot {large_text} NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (report_id, version),
                FOREIGN KEY (report_id) REFERENCES interview_reports(id) ON DELETE CASCADE
            ){suffix}
        """).close()
        db.execute(f"""
            CREATE TABLE IF NOT EXISTS assessment_report_reviews (
                id CHAR(36) PRIMARY KEY, report_id CHAR(36) NOT NULL, version INT NOT NULL,
                sequence_no INT NOT NULL, status VARCHAR(20) NOT NULL, actor_id VARCHAR(128),
                note TEXT, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (report_id, version, sequence_no),
                FOREIGN KEY (report_id, version) REFERENCES assessment_report_versions(report_id, version)
                    ON DELETE CASCADE
            ){suffix}
        """).close()
        db.execute(f"""
            CREATE TABLE IF NOT EXISTS assessment_report_exports (
                id CHAR(36) PRIMARY KEY, report_id CHAR(36) NOT NULL, version INT NOT NULL,
                school_id VARCHAR(128) NOT NULL, actor_id VARCHAR(128) NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            ){suffix}
        """).close()


def _for_update():
    return " FOR UPDATE" if DB_ENGINE == "mysql" else ""


def lock_report(report_id):
    return one("SELECT * FROM interview_reports WHERE id=?" + _for_update(), (report_id,))


def latest(report_id):
    # 首个快照生成前，会话锁和报告锁已使本报告的写入串行化。
    # 锁定不存在的子记录会让 InnoDB 的间隙锁波及其他报告。
    return one("""
        SELECT version,evidence_version,source FROM assessment_report_versions
        WHERE report_id=? ORDER BY version DESC LIMIT 1
    """, (report_id,))


def _append_version(report, number, evidence, source, actor_id=None, reason=None):
    db.execute("""
        INSERT INTO assessment_report_versions
            (report_id,version,evidence_version,source,actor_id,reason,snapshot)
        VALUES (?,?,?,?,?,?,?)
    """, (report["id"], number, evidence, source, actor_id, reason,
          json.dumps(report, ensure_ascii=False, default=str))).close()
    from services.interview.job_store import interview_jobs
    enqueue_analytics(interview_jobs, report, number)


def _adopt_legacy(report):
    current = latest(report["id"])
    if current or report["generation_status"] in {"queued", "failed", "pending_retry"}:
        return current
    # 首次覆盖前在报告锁内导入历史版本，沿用原审核人和审核时间。
    # 从未审核的待处理标志不计为审核事件。
    _append_version(report, 1, None, "legacy")
    if report["review_status"] != "pending" or report["reviewed_at"]:
        db.execute("""
            INSERT INTO assessment_report_reviews
                (id,report_id,version,sequence_no,status,actor_id,created_at)
            VALUES (?,?,1,1,?,?,COALESCE(?,CURRENT_TIMESTAMP))
        """, (str(uuid4()), report["id"], report["review_status"], report["reviewed_by"],
              report["reviewed_at"] or report["updated_at"])).close()
    return {"version": 1, "evidence_version": None}


def should_publish_report(report_id, evidence_version):
    """在校验租约的后台事务内调用，先检查是否需要发布，再修改报告投影。"""
    report = lock_report(report_id)
    current = _adopt_legacy(report) if report else None
    return current is None or current["evidence_version"] != evidence_version


def _unreviewed_fallback(report_id, evidence_version, current):
    if not current or current["evidence_version"] != evidence_version or current["source"] != "generated":
        return False
    # 调用方可能已在本事务内替换用于展示的报告记录。
    # 因此须核对先前的不可变快照和所有复核事件，包括重置为待审的操作。
    row = one("""
        SELECT snapshot FROM assessment_report_versions v
        WHERE v.report_id=? AND v.version=? AND NOT EXISTS (
            SELECT 1 FROM assessment_report_reviews r WHERE r.report_id=v.report_id AND r.version=v.version
        )
    """, (report_id, current["version"]))
    if not row:
        return False
    try:
        previous = json.loads(row["snapshot"])
    except (ValueError, TypeError, RecursionError):
        return False
    return (isinstance(previous, dict) and previous.get("generation_status") == "degraded"
            and previous.get("fallback") == 1)


def can_repair_degraded(report_id, evidence_version):
    """持会话锁进行预检，在校验租约的发布事务内再次核对。"""
    report = lock_report(report_id)
    return bool(report and report["generation_status"] == "degraded" and report["fallback"] == 1
                and report["review_status"] == "pending" and not report["reviewed_at"] and not report["reviewed_by"]
                and _unreviewed_fallback(report_id, evidence_version, latest(report_id)))


def record_generated_report(report_id, evidence_version, *, repairing=False):
    """租约和事务均由调用方持有，本函数不提交事务。"""
    report = lock_report(report_id)
    if report is None:
        raise RuntimeError("Report projection missing during publication")
    current = latest(report_id)
    if repairing:
        if (report["generation_status"] != "succeeded" or report["fallback"] != 0
                or not _unreviewed_fallback(report_id, evidence_version, current)):
            raise RuntimeError("Only an unreviewed generated fallback can be upgraded to success")
    elif current and current["evidence_version"] == evidence_version:
        raise RuntimeError("Duplicate evidence must be skipped before overwriting the report")
    number = current["version"] + 1 if current else 1
    _append_version(report, number, evidence_version, "generated")
    return number


@contextmanager
def report_transaction(report_id, owner, expected_version=None):
    # 服务接口鉴权在取得写锁前完成；加锁后再比对数据库中的归属，
    # 避免对其间已重新分配的记录执行操作。
    # 教师编辑与后台发布采用相同顺序，先锁会话，再锁报告。
    with locked_session(owner["interview_id"], owner["user_id"]) as session:
        report = lock_report(report_id) if session else None
        if not report or any(report[key] != owner[key] for key in ("interview_id", "user_id")):
            raise HTTPException(404, "报告不存在。")
        current = _adopt_legacy(report)
        if not current:
            raise HTTPException(409, "报告尚未发布。")
        if expected_version is not None and current["version"] != expected_version:
            raise HTTPException(409, "报告版本已变化，请刷新后重试。")
        yield report, current


def change_score(report, current, score, grade, recommendation, teacher, reason, evidence):
    db.execute("""
        UPDATE interview_reports SET total_score=?, grade=?, pass_recommendation=?,
            review_status='pending', reviewed_by=NULL, reviewed_at=NULL, updated_at=CURRENT_TIMESTAMP
        WHERE id=?
    """, (score, grade, recommendation, report["id"])).close()
    updated = lock_report(report["id"])
    number = current["version"] + 1
    _append_version(updated, number, evidence, "teacher", teacher, reason)
    return {**updated, "version": number}


def review(report, current, status, teacher, note):
    previous = one("""
        SELECT sequence_no,status,actor_id,note FROM assessment_report_reviews WHERE report_id=? AND version=?
        ORDER BY sequence_no DESC LIMIT 1
    """, (report["id"], current["version"]))
    if (previous and report["review_status"] == status and previous["status"] == status
            and previous["actor_id"] == teacher and (previous["note"] or "") == note):
        return {**report, "version": current["version"]}
    sequence_no = previous["sequence_no"] + 1 if previous else 1
    db.execute("""
        INSERT INTO assessment_report_reviews (id,report_id,version,sequence_no,status,actor_id,note)
        VALUES (?,?,?,?,?,?,?)
    """, (str(uuid4()), report["id"], current["version"], sequence_no, status, teacher, note)).close()
    db.execute("""
        UPDATE interview_reports SET review_status=?, reviewed_by=?, reviewed_at=CURRENT_TIMESTAMP,
            updated_at=CURRENT_TIMESTAMP WHERE id=?
    """, (status, teacher, report["id"])).close()
    return {**lock_report(report["id"]), "version": current["version"]}


def history(report_id):
    versions = all_rows("""
        SELECT version,evidence_version,source,actor_id,reason,snapshot,created_at
        FROM assessment_report_versions WHERE report_id=? ORDER BY version DESC
    """, (report_id,))
    for item in versions:
        item["snapshot"] = json.loads(item["snapshot"])
    reviews = all_rows("""
        SELECT id,version,sequence_no,status,actor_id,note,created_at
        FROM assessment_report_reviews WHERE report_id=? ORDER BY version DESC,sequence_no DESC
    """, (report_id,))
    return {"versions": versions, "reviews": reviews}
