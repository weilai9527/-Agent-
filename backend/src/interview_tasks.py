"""持久化生成任务；状态变更在面试会话锁内执行。

租约令牌用于阻止迟到执行者覆盖结果。外部调用不放在数据库事务内；
如果供应商已响应但本地未保存，重试仍可能产生额外费用。
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime
from uuid import uuid4

from .database import DB_ENGINE, all_rows, db, one


def database_now():
    sql = ("SELECT UNIX_TIMESTAMP(CURRENT_TIMESTAMP(6)) AS clock" if DB_ENGINE == "mysql" else
           "SELECT (julianday('now')-2440587.5)*86400.0 AS clock")
    return float(one(sql)["clock"])


def lease_seconds() -> int:
    try:
        return max(30, min(3600, int(os.environ.get("INTERVIEW_TASK_LEASE_SECONDS", "300"))))
    except ValueError:
        return 300


def encode(value) -> str:
    def scalar(item):
        if isinstance(item, (date, datetime)):
            return item.isoformat()
        raise TypeError(f"Unsupported task input: {type(item).__name__}")
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=scalar)


def report_review_token(report):
    fields = ("id", "source_revision", "total_score", "grade", "pass_recommendation",
              "ability_radar", "agent_feedback", "timeline_review", "summary", "suggestions",
              "provider", "model", "prompt_version", "generation_status", "fallback", "generated_at")
    return hashlib.sha256(encode({key: report.get(key) for key in fields}).encode()).hexdigest()


def task_by_id(task_id):
    return one("SELECT * FROM interview_tasks WHERE id=?", (task_id,))


def task_by_key(interview_id, kind, key):
    return one("SELECT * FROM interview_tasks WHERE interview_id=? AND task_type=? AND task_key=?",
               (interview_id, kind, key))


def enqueue_locked(interview_id, kind, key, payload, revision=None):
    existing = task_by_key(interview_id, kind, key)
    if existing:
        return existing
    source = encode(payload)
    task_id = str(uuid4())
    db.execute("""INSERT INTO interview_tasks
        (id,interview_id,task_type,task_key,input_json,input_hash,input_revision)
        VALUES (?,?,?,?,?,?,?)""", (task_id, interview_id, kind, key, source,
        hashlib.sha256(source.encode()).hexdigest(), revision)).close()
    return task_by_id(task_id)


def replace_failed_followup_locked(task, payload):
    """会话锁内替换尚未提交的失败回答，保留任务标识和尝试次数。"""
    source = encode(payload)
    db.execute("""UPDATE interview_tasks SET input_json=?,input_hash=?,status='queued',
        result_json=NULL,error=NULL,lease_token=NULL,lease_until=NULL,updated_at=CURRENT_TIMESTAMP
        WHERE id=? AND task_type='followup' AND status='failed'""",
        (source, hashlib.sha256(source.encode()).hexdigest(), task["id"])).close()
    return task_by_id(task["id"])


def claim_locked(task, *, retry_failed=False, retry_completed=False):
    now = database_now()
    if task["status"] == "running" and (task.get("lease_until") or 0) > now:
        return None
    if task["status"] in {"superseded", "succeeded"} and not retry_completed:
        return None
    if task["status"] == "failed" and not retry_failed:
        return None
    token = str(uuid4())
    db.execute("""UPDATE interview_tasks SET status='running',lease_token=?,lease_until=?,
        attempt_count=attempt_count+1,error=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=?""",
        (token, now + lease_seconds(), task["id"])).close()
    return token


def owns_locked(task_id, token):
    task = task_by_id(task_id)
    return bool(task and task["status"] == "running" and task["lease_token"] == token
                and (task.get("lease_until") or 0) > database_now())


def finish_locked(task_id, token, result, status="succeeded", error=None):
    cursor = db.execute("""UPDATE interview_tasks SET status=?,result_json=?,error=?,
        lease_token=NULL,lease_until=NULL,updated_at=CURRENT_TIMESTAMP
        WHERE id=? AND status='running' AND lease_token=? AND lease_until>?""",
        (status, encode(result), error, task_id, token, database_now()))
    try:
        return cursor.rowcount == 1
    finally:
        cursor.close()


def recoverable_tasks(limit=20):
    return all_rows("""SELECT tasks.*,sessions.user_id FROM interview_tasks AS tasks
        JOIN interview_sessions AS sessions ON sessions.id=tasks.interview_id
        WHERE tasks.status='queued' OR (tasks.status='running' AND tasks.lease_until<=?)
        ORDER BY tasks.created_at,tasks.id LIMIT ?""", (database_now(), limit))
