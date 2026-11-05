"""将冻结的教学任务与面试中的实际问答回合关联保存。"""
from uuid import uuid4

from fastapi import HTTPException

from services.interview.storage import DB_ENGINE, db, one
from services.interview.progress import append_message, commit_turn
from . import assessment_events, profile_context


def migrate():
    suffix = " ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci" if DB_ENGINE == "mysql" else ""
    with db:
        db.execute(f"CREATE TABLE IF NOT EXISTS interview_attempt_locks (attempt_id CHAR(36) PRIMARY KEY){suffix}").close()
        db.execute(f"""
            CREATE TABLE IF NOT EXISTS interview_training_attempts (
                interview_id CHAR(36) PRIMARY KEY, attempt_id CHAR(36) NOT NULL UNIQUE,
                school_id VARCHAR(128) NOT NULL, student_id CHAR(36) NOT NULL,
                FOREIGN KEY (interview_id) REFERENCES interview_sessions(id) ON DELETE CASCADE
            ){suffix}""").close()
        exact = " COLLATE utf8mb4_bin" if DB_ENGINE == "mysql" else ""
        db.execute(f"""
            CREATE TABLE IF NOT EXISTS interview_training_questions (
                interview_id CHAR(36) NOT NULL, position INTEGER NOT NULL,
                frozen_question_id VARCHAR(128){exact} NOT NULL, prompt TEXT NOT NULL, message_id CHAR(36) UNIQUE,
                PRIMARY KEY (interview_id,position), UNIQUE (interview_id,frozen_question_id),
                FOREIGN KEY (interview_id) REFERENCES interview_training_attempts(interview_id) ON DELETE CASCADE
            ){suffix}""").close()


def materialize(attempt_id, record, student, school, native_verified=False):
    """在一个事务内创建面试；题目仅取自经过核验的训练响应。"""
    if not isinstance(record, dict):
        raise HTTPException(502, "Invalid training attempt")
    if (record.get("attempt_id") != attempt_id or record.get("student_id") != student
            or record.get("school_id") != school):
        raise HTTPException(403, "Training attempt outside student scope")
    interview_id, role, questions = (record.get(k) for k in ("interview_id", "job_role", "questions"))
    if (not isinstance(interview_id, str) or not 0 < len(interview_id) <= 36 or len(attempt_id) > 36
            or not isinstance(role, str) or not 0 < len(role) <= 160
            or not isinstance(questions, list) or not 1 <= len(questions) <= 100
            or not all(isinstance(q, dict) and isinstance(q.get("question_id"), str)
                       and 0 < len(q["question_id"]) <= 128 and isinstance(q.get("prompt"), str)
                       and 0 < len(q["prompt"]) <= 4000 for q in questions)
            or len({q["question_id"] for q in questions}) != len(questions)):
        raise HTTPException(502, "Invalid training assignment")
    prior = one("SELECT interview_id,school_id,student_id FROM interview_training_attempts WHERE attempt_id=?", (attempt_id,))
    if prior:
        if (prior["interview_id"], prior["school_id"], prior["student_id"]) != (interview_id, school, student):
            raise HTTPException(409, "Training binding changed")
        return interview_id
    resume_snapshot = profile_context.capture(student)
    with db:
        # 同一尝试可能被多个网页同时领取。锁定尝试标识，避免用学生账号行充当业务锁。
        if DB_ENGINE == "sqlite":
            db.execute("BEGIN IMMEDIATE").close()
        else:
            db.execute("""INSERT INTO interview_attempt_locks(attempt_id) VALUES (?)
                       ON DUPLICATE KEY UPDATE attempt_id=attempt_id""", (attempt_id,)).close()
        binding = one("SELECT * FROM interview_training_attempts WHERE attempt_id=?", (attempt_id,))
        if binding:
            if (binding["interview_id"], binding["student_id"], binding["school_id"]) != (interview_id, student, school):
                raise HTTPException(409, "Training binding changed")
            return interview_id
        if record.get("status") != "started" or one("SELECT id FROM interview_sessions WHERE id=?", (interview_id,)):
            raise HTTPException(409, "Training attempt unavailable")
        db.execute("""INSERT INTO interview_sessions(id,user_id,target_role,interview_type,status,started_at)
                    VALUES (?,?,?,'教学训练','running',CURRENT_TIMESTAMP)""", (interview_id, student, role)).close()
        profile_context.save(interview_id, resume_snapshot)
        db.execute("INSERT INTO interview_training_attempts(interview_id,attempt_id,school_id,student_id) VALUES(?,?,?,?)",
                   (interview_id, attempt_id, school, student)).close()
        agent = str(uuid4())
        db.execute("""INSERT INTO interview_agents (id,interview_id,agent_name,agent_type,agent_role,status)
                    VALUES (?,?,'训练面试官','technical','按教学任务原题提问','active')""", (agent, interview_id)).close()
        first_id = append_message(interview_id, agent, "question", questions[0]["prompt"])
        for pos, q in enumerate(questions):
            db.execute("""INSERT INTO interview_training_questions
                        (interview_id,position,frozen_question_id,prompt,message_id) VALUES(?,?,?,?,?)""",
                       (interview_id, pos, q["question_id"], q["prompt"], first_id if pos == 0 else None)).close()
        db.execute("INSERT INTO interview_progress(interview_id,agent_id,question_id) VALUES(?,?,?)",
                   (interview_id, agent, first_id)).close()
        assessment_events.capture_if_enabled(interview_id)
    return interview_id


def commit_if_training(interview_id, submission_id, question, answer):
    """由 submit_turn 持有会话锁时调用。"""
    current = one("SELECT position FROM interview_training_questions WHERE interview_id=? AND message_id=?",
                  (interview_id, question["id"]))
    if current is None:
        return False
    next_pos = current["position"] + 1
    following = one("SELECT prompt FROM interview_training_questions WHERE interview_id=? AND position=?",
                    (interview_id, next_pos))
    prompt = following["prompt"] if following else None
    decision = {"action": "ask_follow_up" if following else "finish_interview", "reason": "assigned_questions",
                "round_count": next_pos, "question": prompt, "closing": None if following else "教学任务题目已全部完成。"}
    # 实时语音面试也只从冻结的教学任务取得下一题。
    # 同一道原题可被多次练习，每次提问都有本场独立的消息标识。
    next_message = commit_turn(interview_id, submission_id, question, answer, decision, prompt)
    if next_message:
        db.execute("UPDATE interview_training_questions SET message_id=? WHERE interview_id=? AND position=?",
                   (next_message, interview_id, next_pos)).close()
        db.execute("UPDATE interview_messages SET message_type='question' WHERE id=?", (next_message,)).close()
    return True


def require_all_answered(interview_id):
    missing = one("""SELECT q.position FROM interview_training_questions q LEFT JOIN interview_turns t
            ON t.interview_id=q.interview_id AND t.question_id=q.message_id
            WHERE q.interview_id=? AND t.answer_id IS NULL LIMIT 1""", (interview_id,))
    if missing:
        raise HTTPException(409, "请完成所有布置的题目后再结束训练。")
