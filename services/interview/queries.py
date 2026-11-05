"""当前进程持有的面试输入及不可变投影，只按所属学生读取。"""
from __future__ import annotations

from fastapi import HTTPException, Request
from services.interview.storage import all_rows, db, one
from shared.interviewer_policy import load_snapshot


def error(status_code: int, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"error": message})


def json_body(body: dict | None) -> dict:
    return body or {}


def require_auth(request: Request):
    """服务依赖在验证委派令牌后写入当前学生，缺少身份时拒绝访问。"""
    student = getattr(request.state, "interview_student", None)
    if not student:
        raise HTTPException(401, "缺少已验证的学生身份。")
    return student

def find_interview_by_user_id(interview_id: str, user_id: str) -> dict | None:
    interview = one(
        """
        SELECT id, user_id, target_role, experience_level, interview_type, company_context,
               focus_areas, resume_context, difficulty, interviewer_style, status, created_at, updated_at,
               started_at, completed_at
        FROM interview_sessions
        WHERE id = ? AND user_id = ?
        """,
        (interview_id, user_id),
    )
    if interview:
        interview["interviewer_strategy"] = load_snapshot(db, interview_id)
    return interview


def list_agents_by_interview_id(interview_id: str) -> list[dict]:
    return all_rows(
        """
        SELECT id, interview_id, agent_name, agent_type, agent_role, strategy, order_index,
               status, created_at, updated_at
        FROM interview_agents
        WHERE interview_id = ?
        ORDER BY order_index ASC, created_at ASC
        """,
        (interview_id,),
    )


def find_agent_by_interview_id(agent_id: str, interview_id: str) -> dict | None:
    return one(
        """
        SELECT id, interview_id, agent_name, agent_type, agent_role, strategy, order_index,
               status, created_at, updated_at
        FROM interview_agents
        WHERE id = ? AND interview_id = ?
        """,
        (agent_id, interview_id),
    )


def list_messages_by_interview_id(interview_id: str) -> list[dict]:
    return all_rows(
        """
        SELECT messages.id, messages.interview_id, messages.agent_id,
               agents.agent_name, agents.agent_type,
               messages.sender_type, messages.message_type, messages.content,
               messages.transcript_text, messages.source, messages.source_ref,
               messages.reply_to_message_id, messages.round_agent_id, training.frozen_question_id,
               messages.order_index, messages.created_at
        FROM interview_messages AS messages
        LEFT JOIN interview_agents AS agents ON agents.id = messages.agent_id
        LEFT JOIN interview_training_questions AS training ON training.message_id = messages.id
        WHERE messages.interview_id = ?
        ORDER BY messages.order_index ASC, messages.created_at ASC
        """,
        (interview_id,),
    )


def find_message_by_interview_id(message_id: str, interview_id: str) -> dict | None:
    return one(
        """
        SELECT messages.id, messages.interview_id, messages.agent_id,
               agents.agent_name, agents.agent_type,
               messages.sender_type, messages.message_type, messages.content,
               messages.transcript_text, messages.source, messages.source_ref,
               messages.reply_to_message_id, messages.round_agent_id, training.frozen_question_id,
               messages.order_index, messages.created_at
        FROM interview_messages AS messages
        LEFT JOIN interview_agents AS agents ON agents.id = messages.agent_id
        LEFT JOIN interview_training_questions AS training ON training.message_id = messages.id
        WHERE messages.id = ? AND messages.interview_id = ?
        """,
        (message_id, interview_id),
    )
