"""训练完成和教学分析事件随业务事务写入待投递队列。

完成回执和每个分析版本都有稳定的事件标识。
接收端可能已经提交但响应丢失，因此同一事件可能投递多次。
"""
from contextlib import closing
import json
import os

from .jobs import RetryJob


def migrate(db, mysql):
    # 冻结事件正文，即使重试期间分数或回答发生变化，也投递原始快照。
    # 删除面试时一并清除快照中的学生答题文本。
    suffix = " ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci" if mysql else ""
    payload_type = "LONGTEXT" if mysql else "TEXT"
    with db:
        db.execute(f"""
            CREATE TABLE IF NOT EXISTS interview_delivery_events (
                job_id CHAR(64) PRIMARY KEY,
                interview_id CHAR(36) NOT NULL,
                school_id VARCHAR(128) NOT NULL,
                student_id VARCHAR(128) NOT NULL,
                prerequisite CHAR(64),
                body {payload_type} NOT NULL,
                FOREIGN KEY (interview_id) REFERENCES interview_sessions(id) ON DELETE CASCADE
            ){suffix}
        """).close()


def _binding(queue, interview_id):
    with closing(queue.db.execute("""
        SELECT a.attempt_id,a.school_id,a.student_id FROM interview_training_attempts a
        JOIN interview_sessions s ON a.interview_id=s.id AND a.student_id=s.user_id
        WHERE s.id=? AND s.status='completed'
    """, (interview_id,))) as rows:
        row = rows.fetchone()
        return dict(row) if row else None


def _save(queue, job_id, interview_id, binding, prerequisite, body):
    # 同一事件重复入队时保留原正文。
    # 分析服务收到重复投递后会核对摘要。
    conflict = "ON DUPLICATE KEY UPDATE job_id=job_id" if queue.mysql else "ON CONFLICT(job_id) DO NOTHING"
    queue.db.execute(f"""
        INSERT INTO interview_delivery_events(job_id,interview_id,school_id,student_id,prerequisite,body)
        VALUES (?,?,?,?,?,?) {conflict}
    """, (job_id, interview_id, binding["school_id"], binding["student_id"], prerequisite,
          json.dumps(body, ensure_ascii=False, separators=(",", ":")))).close()


def _complete_job(queue, interview_id, binding):
    key = queue.enqueue("train_complete", interview_id, binding["attempt_id"], "1")
    _save(queue, key, interview_id, binding, None, {"event_id": key, "interview_id": interview_id})
    return key


def enqueue_training_complete(queue, interview_id):
    """仅为已完成且由训练服务确认绑定的尝试登记完成事件。"""
    binding = _binding(queue, interview_id)
    return _complete_job(queue, interview_id, binding) if binding else None


def _observations(db, report):
    timeline = report["timeline_review"]
    if isinstance(timeline, str):
        timeline = json.loads(timeline)
    scores = {row["message_id"]: row.get("dimension_scores") or {} for row in timeline if row.get("message_id")}
    # 不同题目可能有相同的预览或题干，不能靠文本匹配得分。
    # 从冻结原题追溯本场提问消息，只取直接回复该消息的学生答案。
    with closing(db.execute("""
        SELECT q.frozen_question_id,m.id,m.content FROM interview_training_questions q
        JOIN interview_turns t ON t.interview_id=q.interview_id AND t.question_id=q.message_id
        JOIN interview_messages m ON m.interview_id=q.interview_id AND m.id=t.answer_id
            AND m.reply_to_message_id=q.message_id
        WHERE q.interview_id=? AND m.sender_type='candidate' AND m.message_type IN ('answer','transcript')
        ORDER BY q.position,m.order_index,m.id
    """, (report["interview_id"],))) as rows:
        return [{"question_id": row["frozen_question_id"], "original_answer": row["content"],
                 "dimension": dimension, "score": score}
                for row in rows for dimension, score in sorted(scores.get(row["id"], {}).items())]


def enqueue_analytics(queue, report, number):
    """在提交报告版本的同一事务中保存该版本的逐题证据。"""
    interview_id = report["interview_id"]
    binding = _binding(queue, interview_id)
    if not binding:
        return None
    from services.assessment.storage_mode import assessment_owner
    completion_key = None if assessment_owner() else _complete_job(queue, interview_id, binding)
    key = queue.enqueue("analytics", interview_id, report["id"], str(number))
    _save(queue, key, interview_id, binding, completion_key, {
        "event_id": key, "version": number, "attempt_id": binding["attempt_id"],
        "questions": _observations(queue.db, report),
    })
    return key


def post_event(service, path, scope, school, body):
    import httpx
    from shared.service_http import service_origin
    from shared.service_security import service_headers

    origin = service_origin(service)
    headers = service_headers(service, actor_id=os.environ["SERVICE_ID"], actor_type="system",
                              school_id=school, scopes=[scope])
    with httpx.Client(timeout=10, follow_redirects=False, trust_env=False) as client:
        response = client.post(origin + path, json=body, headers=headers)
    response.raise_for_status()
    return response.json()


def prepare_delivery(queue, job):
    from shared.service_http import resource_segment

    with closing(queue.db.execute("SELECT * FROM interview_delivery_events WHERE job_id=?", (job["id"],))) as rows:
        event = rows.fetchone()
    if not event:
        # 若面试仍存在却缺少快照，说明待投递记录不完整。
        # 若面试刚被并发删除，queue.retry 会结束这项任务。
        raise RuntimeError("Delivery snapshot unavailable")
    if event["school_id"] != os.environ.get("LEGACY_SCHOOL_ID"):
        raise RuntimeError("Event school does not match the deployment")
    body = json.loads(event["body"])
    if job["kind"] == "project":
        ack = post_event("assessment", "/internal/interview-projections", "assessment.project",
                         event["school_id"], body)
        if not isinstance(ack, dict) or (ack.get("interview_id"), ack.get("sequence_no")) != (
                job["interview_id"], body["sequence_no"]):
            raise RuntimeError("Assessment receipt does not match the submitted projection")

        def discard_delivered_evidence():
            # queue.finish 校验租约后，在源库事务中一并清除正文并确认任务完成。
            # 只有仍待重试的投递需要保留转写文本。
            queue.db.execute("DELETE FROM interview_delivery_events WHERE job_id=?", (job["id"],)).close()

        return discard_delivered_evidence
    elif job["kind"] == "train_complete":
        path = "/attempts/" + resource_segment(job["subject_id"]) + "/complete"
        ack = post_event("training", path, "training.complete", event["school_id"], body)
        expected = {"attempt_id": job["subject_id"], "interview_id": job["interview_id"],
                    "school_id": event["school_id"], "student_id": event["student_id"], "status": "completed"}
        if not isinstance(ack, dict) or any(ack.get(k) != v for k, v in expected.items()):
            raise RuntimeError("Training receipt does not match the attempt")
    elif job["kind"] == "analytics":
        dependency = queue.get(event["prerequisite"]) if event["prerequisite"] else None
        if event["prerequisite"] and (not dependency or dependency["state"] != "done"):
            return lambda: RetryJob(delay_seconds=3)
        ack = post_event("analytics", "/v1/completions", "analytics.completion.write", event["school_id"], body)
        # 事件延迟到达时，接收端可能已处理更高版本。
        # 接收端在同一事务中记录事件，并仅在版本更新时替换评分。
        if (not isinstance(ack, dict) or ack.get("attempt_id") != body["attempt_id"]
                or type(ack.get("version")) is not int or ack["version"] < body["version"]):
            raise RuntimeError("Analytics receipt does not match the revision")
    else:
        raise ValueError("Unknown delivery kind")
    return lambda: None
