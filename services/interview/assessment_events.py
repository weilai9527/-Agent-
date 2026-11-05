"""面试服务统一写入待投递事件，向评估服务提供评估所需的证据。"""
from contextlib import closing
from datetime import datetime
import hashlib
import json
import os
from uuid import NAMESPACE_URL, uuid5


# 发送端和接收端共用这份字段清单，只传递评分输入。
# 用户凭据、媒体和学生联系方式均不在清单内。
# 切换到独立评估服务后生成的报告也不随输入投递。
INPUTS = {
    "interview_sessions": "id user_id target_role experience_level interview_type company_context focus_areas resume_context difficulty interviewer_style status created_at updated_at started_at completed_at",
    "interview_agents": "id interview_id agent_name agent_type agent_role strategy order_index status created_at updated_at",
    "interview_messages": "id interview_id agent_id sender_type message_type content transcript_text source source_ref reply_to_message_id round_agent_id order_index created_at",
    "interview_turns": "interview_id submission_id question_id agent_id answer_id next_question_id next_agent_id action decision_json",
    "interview_strategy_snapshots": "interview_id config",
    "interview_training_attempts": "interview_id attempt_id school_id student_id",
    "interview_training_questions": "interview_id position frozen_question_id prompt message_id",
    "interview_profile_context": "interview_id profile_version analysis_json",
}

KEYS = {
    "interview_sessions": ("id",), "interview_agents": ("id",), "interview_messages": ("id",),
    "interview_turns": ("interview_id", "submission_id"),
    "interview_strategy_snapshots": ("interview_id",),
    "interview_training_attempts": ("interview_id",),
    "interview_training_questions": ("interview_id", "position"),
    "interview_profile_context": ("interview_id",),
}


def _timestamp(value):
    if not isinstance(value, datetime):
        raise TypeError("Unexpected database value")
    return value.isoformat(sep=" ")


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":"), default=_timestamp)


def digest(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def initialize(db, mysql):
    suffix = " ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci" if mysql else ""
    with db:
        db.execute("CREATE TABLE IF NOT EXISTS interview_report_ids (interview_id CHAR(36) PRIMARY KEY, report_id CHAR(36) NOT NULL UNIQUE)"+suffix).close()
        db.execute("""CREATE TABLE IF NOT EXISTS interview_assessment_streams (
            interview_id CHAR(36) PRIMARY KEY, sequence_no BIGINT NOT NULL, digest CHAR(64) NOT NULL,
            FOREIGN KEY(interview_id) REFERENCES interview_sessions(id) ON DELETE CASCADE
        )""" + suffix).close()
        db.execute("""CREATE TABLE IF NOT EXISTS interview_assessment_imports (
            interview_id CHAR(36) PRIMARY KEY, digest CHAR(64) NOT NULL,
            FOREIGN KEY(interview_id) REFERENCES interview_sessions(id) ON DELETE CASCADE
        )""" + suffix).close()


def fetch_rows(db, query, params):
    with closing(db.execute(query, params)) as cursor:
        return [dict(row) for row in cursor.fetchall()]


def report_id(school, interview):
    return str(uuid5(NAMESPACE_URL, encoded(["assessment-report-v1", school, interview])))


def capture_if_enabled(interview):
    from services.assessment.storage_mode import emit_projections
    if emit_projections():
        # 首份草稿也在创建它的业务事务中登记投递，
        # 这样尚未作答的面试同样能计入统计。
        from services.interview.job_store import interview_jobs
        capture(interview_jobs, interview)


def capture(queue, interview, *, history=None):
    """由写入方在原有事务中持有面试锁后调用。"""
    from .delivery import _save
    school = os.environ["LEGACY_SCHOOL_ID"]
    tables = {}
    for table, fields in INPUTS.items():
        owner = "id" if table == "interview_sessions" else "interview_id"
        # 按消息顺序投递，保证接收端先插入原题，再插入引用它的回答。
        ordering = "order_index,id" if table == "interview_messages" else ",".join(KEYS[table])
        tables[table] = fetch_rows(queue.db,
            f"SELECT {','.join(fields.split())} FROM {table} WHERE {owner}=? ORDER BY {ordering}", (interview,))
    session = tables["interview_sessions"][0]
    # 旧报告编号从迁移清单中带入，不能在面试库里读取评估域的报告。
    imported_reports = (history or {}).get("interview_reports", [])
    mapped = fetch_rows(queue.db, "SELECT report_id FROM interview_report_ids WHERE interview_id=?", (interview,))
    rid = mapped[0]["report_id"] if mapped else report_id(school, interview)
    if imported_reports and not mapped:
        rid = imported_reports[0]["id"]
        queue.db.execute("INSERT INTO interview_report_ids(interview_id,report_id) VALUES (?,?)", (interview,rid)).close()
    body = {"school_id": school, "student_id": session["user_id"], "interview_id": interview,
            "report_id": rid, "inputs": tables}
    fingerprint = digest(body)
    prior = fetch_rows(queue.db, "SELECT sequence_no,digest FROM interview_assessment_streams WHERE interview_id=?",
                       (interview,))
    permit_backfill = None
    if history is not None:
        history_digest = digest(history)
        imported = fetch_rows(queue.db, "SELECT digest FROM interview_assessment_imports WHERE interview_id=?",
                              (interview,))
        if imported and imported[0]["digest"] == history_digest:
            return rid
        if prior:
            # 旧协议可能已投递过同一份冻结历史，但当时尚未传输签发许可。
            # 补齐许可时追加一个新事件，
            # 已确认的事件及其摘要保持原样，避免重复投递旧事件。
            from services.assessment.migration import PERMITS
            original = {key: value for key, value in history.items() if key != PERMITS}
            permit_backfill = history.get(PERMITS)
            if (not permit_backfill or not imported or imported[0]["digest"] != digest(original)
                    or prior[0]["digest"] != fingerprint):
                raise ValueError("Migration must precede live projections, with source grading writes stopped")
            queue.db.execute("UPDATE interview_assessment_imports SET digest=? WHERE interview_id=?",
                             (history_digest, interview)).close()
        else:
            queue.db.execute("INSERT INTO interview_assessment_imports VALUES (?,?)",
                             (interview, history_digest)).close()
    if prior and prior[0]["digest"] == fingerprint and not permit_backfill:
        return rid
    sequence = prior[0]["sequence_no"] + 1 if prior else 1
    if prior:
        queue.db.execute("UPDATE interview_assessment_streams SET sequence_no=?,digest=? WHERE interview_id=?",
                         (sequence, fingerprint, interview)).close()
    else:
        queue.db.execute("INSERT INTO interview_assessment_streams VALUES (?,?,?)",
                         (interview, sequence, fingerprint)).close()
    if permit_backfill:
        body.pop("inputs")
        body["permit_backfill"] = permit_backfill
    elif history is not None:
        body["history"] = history
    body["sequence_no"] = sequence
    key = queue.enqueue("project", interview, interview, str(sequence))
    _save(queue, key, interview, {"school_id": school, "student_id": session["user_id"]}, None,
          json.loads(encoded(body)))
    return rid
