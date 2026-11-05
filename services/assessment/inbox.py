"""接收已认证的面试投影事件，在同一事务中保存回执、证据和待执行任务。"""
from fastapi import HTTPException

from services.interview.assessment_events import INPUTS, KEYS, digest


def _rows_valid(tables, interview, student, school):
    if not isinstance(tables, dict) or set(tables) != set(INPUTS):
        return False
    for table, columns in INPUTS.items():
        rows = tables[table]
        if not isinstance(rows, list):
            return False
        seen = set()
        for row in rows:
            if (not isinstance(row, dict) or set(row) != set(columns.split())
                    or any(type(v) not in (str, int, type(None)) for v in row.values())
                    or row.get("interview_id", row.get("id")) != interview):
                return False
            key = tuple(row[c] for c in KEYS[table])
            if None in key or key in seen:
                return False
            seen.add(key)
    sessions = tables["interview_sessions"]
    if len(sessions) != 1 or sessions[0]["user_id"] != student:
        return False
    agents = {row["id"] for row in tables["interview_agents"]}
    messages = {row["id"] for row in tables["interview_messages"]}
    for row in tables["interview_training_attempts"]:
        if (row["school_id"], row["student_id"]) != (school, student):
            return False
    for row in tables["interview_messages"] + tables["interview_turns"] + tables["interview_training_questions"]:
        if any(row.get(k) is not None and row[k] not in agents for k in
               ("agent_id", "next_agent_id", "round_agent_id")):
            return False
        if any(row.get(k) is not None and row[k] not in messages for k in
               ("question_id", "answer_id", "next_question_id", "message_id", "reply_to_message_id")):
            return False
    return True


def _put(legacy, table, row):
    keys = KEYS[table]
    predicate = " AND ".join(f"{key}=?" for key in keys)
    ids = tuple(row[key] for key in keys)
    current = legacy.one(f"SELECT * FROM {table} WHERE {predicate}", ids)
    if current:
        for field in (*keys, "interview_id", "user_id", "student_id", "school_id"):
            if field in row and current[field] != row[field]:
                raise HTTPException(409, "Conflicting projection owner")
        mutable = [key for key in row if key not in keys]
        legacy.db.execute(f"UPDATE {table} SET {','.join(f'{k}=?' for k in mutable)} WHERE {predicate}",
                          (*[row[k] for k in mutable], *ids)).close()
    else:
        legacy.db.execute(f"INSERT INTO {table} ({','.join(row)}) VALUES ({','.join('?' for _ in row)})",
                          tuple(row.values())).close()


def accept(legacy, body, actor):
    if actor["caller"] != "interview" or actor["actor_id"] != "interview" or actor["actor_type"] != "system":
        raise HTTPException(403, "Only the interview outbox may publish evidence")
    school = actor["school_id"]
    interview, student, report = (body.get(k) for k in ("interview_id", "student_id", "report_id"))
    seq, tables = body.get("sequence_no"), body.get("inputs")
    backfill = "permit_backfill" in body
    common = {"interview_id", "student_id", "school_id", "report_id", "sequence_no"}
    allowed = common | ({"permit_backfill"} if backfill else {"inputs", "history"})
    if (set(body) - allowed
            or not all(isinstance(k, str) and 0 < len(k) <= 36 for k in (interview, student, report))
            or type(seq) is not int or seq < 1 or body.get("school_id") != school
            or (backfill and seq <= 1) or (not backfill and not _rows_valid(tables, interview, student, school))):
        raise HTTPException(422, "Invalid projection")
    fingerprint = digest(body)
    result = {"interview_id": interview, "sequence_no": seq}
    db = legacy.db
    mysql = legacy.DB_ENGINE == "mysql"
    conflict = "ON DUPLICATE KEY UPDATE interview_id=interview_id" if mysql else "ON CONFLICT DO NOTHING"
    with db:
        if not mysql:
            db.execute("BEGIN IMMEDIATE").close()
        # 首条面试记录尚未建好时，第一个事件可能与其重试请求同时到达。
        # 序号 0 专门记录该事件流的归属，事件回执从序号 1 开始。
        db.execute(f"""INSERT INTO assessment_projection_inbox VALUES (?,0,?,?,?) {conflict}""",
                   (interview, school, student, digest([interview, student, school, report]))).close()
        lock = " FOR UPDATE" if mysql else ""
        head = legacy.one("SELECT * FROM assessment_projection_inbox WHERE interview_id=? AND sequence_no=0" + lock,
                          (interview,))
        if head["digest"] != digest([interview, student, school, report]):
            raise HTTPException(409, "Projection stream owner changed")
        received = legacy.one("""SELECT sequence_no,digest FROM assessment_projection_inbox
                                 WHERE interview_id=? AND sequence_no<=? ORDER BY sequence_no DESC LIMIT 1""",
                              (interview, seq))
        if received["sequence_no"] == seq:
            if received["digest"] != fingerprint:
                raise HTTPException(409, "Conflicting projection replay")
            return result
        if received["sequence_no"] != seq - 1:
            raise HTTPException(409, "Earlier projection has not arrived yet")
        # 更改证据前，与评分发布和教师复核一样锁住对应的面试记录。
        # 首次收到该场面试的证据时，在同一事务内创建记录。
        legacy.one("SELECT id FROM interview_sessions WHERE id=?" + lock, (interview,))
        if backfill:
            from .migration import restore_permits
            owned = legacy.one("SELECT id,user_id,interview_id FROM interview_reports WHERE id=?" + lock, (report,))
            if not owned or (owned["id"], owned["user_id"], owned["interview_id"]) != (report, student, interview):
                raise HTTPException(409, "Issuance permit report outside current stream")
            restore_permits(legacy, interview, student, report, school, body["permit_backfill"])
            db.execute("INSERT INTO assessment_projection_inbox VALUES (?,?,?,?,?)",
                       (interview, seq, school, student, fingerprint)).close()
            return result
        previous_answers = {
            row["id"]: legacy.answer_version(row)
            for row in legacy.all_rows("""SELECT id,content,transcript_text,reply_to_message_id,round_agent_id
                                          FROM interview_messages WHERE interview_id=? AND sender_type='candidate'""",
                                       (interview,))
        }
        for table in INPUTS:
            for row in tables[table]:
                _put(legacy, table, row)
        if "history" in body:
            if seq != 1:
                raise HTTPException(409, "Historical copy must be the first event")
            from .migration import restore_history
            restore_history(legacy, interview, student, report, school, body["history"])
        for row in tables["interview_messages"]:
            if row["sender_type"] == "candidate" and row["message_type"] in {"answer", "transcript"}:
                if previous_answers.get(row["id"]) == legacy.answer_version(row):
                    continue
                prev = legacy.find_evaluation_by_message_id(interview, row["id"])
                if seq == 1 and prev and prev.get("score") is not None:
                    continue  # 切换时已导入成功的评分，无需重复打分。
                legacy.enqueue_score_for_answer(interview, row["id"])
        if tables["interview_sessions"][0]["status"] == "completed":
            existing = legacy.find_report_by_interview_id(interview, student)
            if not existing:
                legacy.insert_queued_report(interview, {"id": student}, report_id=report)
            if not existing or existing["generation_status"] in {"queued", "failed"}:
                legacy.enqueue_report_if_completed(interview, student)
        db.execute("INSERT INTO assessment_projection_inbox VALUES (?,?,?,?,?)",
                   (interview, seq, school, student, fingerprint)).close()
    return result
