"""Transactional storage for server-owned interview turns."""
from contextlib import contextmanager
import json
from uuid import uuid4

from .database import DB_ENGINE, db, one


@contextmanager
def locked_session(interview_id, user_id):
    # Serialize writers across processes, including two tabs opening the same session.
    with db:
        if DB_ENGINE == "sqlite":
            db.execute("BEGIN IMMEDIATE").close()
        suffix = " FOR UPDATE" if DB_ENGINE == "mysql" else ""
        yield one("SELECT id, status FROM interview_sessions WHERE id=? AND user_id=?" + suffix,
                  (interview_id, user_id))


def turn_by(interview_id, submission_id):
    return one("SELECT * FROM interview_turns WHERE interview_id=? AND submission_id=?",
               (interview_id, submission_id))


def managed_progress(interview_id):
    return one("SELECT * FROM interview_progress WHERE interview_id=?", (interview_id,))


def append_message(interview_id, agent_id, message_type, content, *, answer=None, question_id=None):
    candidate = answer is not None
    details = answer or {}
    message_id = details.get("id") or str(uuid4())
    order = one("SELECT COALESCE(MAX(order_index),-1)+1 AS idx FROM interview_messages WHERE interview_id=?", (interview_id,))
    db.execute("""
        INSERT INTO interview_messages (id, interview_id, agent_id, sender_type, message_type,
            content, transcript_text, source, source_ref, reply_to_message_id, round_agent_id, order_index)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
    """, (message_id, interview_id, None if candidate else agent_id, "candidate" if candidate else "agent",
          message_type, content, details.get("transcript_text"), details.get("source") or "text",
          details.get("source_ref"), question_id, agent_id if candidate else None, order["idx"])).close()
    return message_id


def commit_turn(interview_id, submission_id, question, answer, decision, next_question, *, existing_answer=False):
    agent_id = question["agent_id"]
    if existing_answer:
        db.execute("""UPDATE interview_messages SET reply_to_message_id=?, round_agent_id=?
                      WHERE id=? AND interview_id=?""",
                   (question["id"], agent_id, answer["id"], interview_id)).close()
    else:
        append_message(interview_id, agent_id, "answer", answer["content"], answer=answer, question_id=question["id"])
    action = decision["action"]
    next_agent_id = agent_id
    if action != "ask_follow_up":
        append_message(interview_id, agent_id, "system", decision["closing"])
        db.execute("UPDATE interview_agents SET status='completed' WHERE id=? AND interview_id=?",
                   (agent_id, interview_id)).close()
        next_agent_id = decision.get("next_agent_id")
        if next_agent_id:
            db.execute("UPDATE interview_agents SET status='active' WHERE id=? AND interview_id=?",
                       (next_agent_id, interview_id)).close()
    next_id = None
    if next_question:
        kind = "question" if action == "switch_agent" else "follow_up"
        next_id = append_message(interview_id, next_agent_id, kind, next_question)
    db.execute("""
        INSERT INTO interview_turns (interview_id,submission_id,question_id,agent_id,answer_id,
            next_question_id,next_agent_id,action,decision_json) VALUES (?,?,?,?,?,?,?,?,?)
    """, (interview_id, submission_id, question["id"], agent_id, answer["id"], next_id,
          next_agent_id, action, json.dumps(decision, ensure_ascii=False))).close()
    db.execute("""UPDATE interview_progress SET question_id=?,agent_id=?,last_submission_id=?
                  WHERE interview_id=?""", (next_id, next_agent_id, submission_id, interview_id)).close()
    db.execute("UPDATE interview_sessions SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (interview_id,)).close()


def complete_pending_question(interview_id, turn, content, transcript=None, source_ref=None):
    question_id = append_message(interview_id, turn["next_agent_id"], "follow_up", content)
    if transcript or source_ref:
        db.execute("""UPDATE interview_messages SET source='aliyun_rtc', transcript_text=?, source_ref=?
                      WHERE id=?""", (transcript, source_ref, question_id)).close()
    db.execute("UPDATE interview_turns SET next_question_id=? WHERE interview_id=? AND submission_id=?",
               (question_id, interview_id, turn["submission_id"])).close()
    db.execute("UPDATE interview_progress SET question_id=? WHERE interview_id=?", (question_id, interview_id)).close()
    return question_id
