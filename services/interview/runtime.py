"""面试域的应用逻辑：创建场次、推进问答、固化训练证据并登记投递。"""
from __future__ import annotations

import json
import random
import os
from services.interview.decision import decide_turn
from services.interview.followup import KimiFollowupError, generate_kimi_followup, generate_opening_question
from fastapi import BackgroundTasks, Depends, HTTPException, Request, Response
from services.interview import assessment_events, profile_context, training_rounds
from services.interview.inputs import INTERVIEW_STATUSES, parse_agent_input, parse_interview_input, parse_message_input, read_text_field
from services.interview.progress import append_message, commit_turn, complete_pending_question, locked_session, managed_progress, turn_by
from services.interview.prompts import create_initial_question
from services.interview.queries import error, find_agent_by_interview_id, find_interview_by_user_id, find_message_by_interview_id, json_body, list_agents_by_interview_id, list_messages_by_interview_id, require_auth
from services.interview.job_store import interview_jobs
from services.interview.storage import all_rows, db, one
from shared.interviewer_policy import load_policy, load_snapshot, select_strategy
from typing import Any
from uuid import uuid4
from services.interview.bootstrap import initialize_interview

initialize_interview()


DEFAULT_AGENT_TEMPLATES = [
    {
        "agent_name": "技术一面 Agent",
        "agent_type": "technical",
        "agent_role": "负责考察候选人的核心技术基础、项目细节和编码思路。",
        "strategy": "先围绕目标岗位确认技术栈，再根据重点方向逐步追问实现细节。",
    },
    {
        "agent_name": "架构二面 Agent",
        "agent_type": "architecture",
        "agent_role": "负责考察系统设计、工程权衡、性能和稳定性意识。",
        "strategy": "从业务场景切入，观察候选人如何拆解模块、设计数据流和处理边界。",
    },
    {
        "agent_name": "HR Agent",
        "agent_type": "hr",
        "agent_role": "负责考察职业动机、沟通表达、团队协作和岗位匹配度。",
        "strategy": "用行为面试问题理解候选人的经历、偏好和稳定性。",
    },
]


def resume_analysis_for_prompt(user, *, interview_id, cached_only=False):
    """只读取建场时冻结的数据；历史面试不补入学生当前的简历。"""
    return (profile_context.load(interview_id) or {}).get("analysis") or None

def select_resume_point(analysis: dict, interview: dict, messages: list[dict]) -> dict:
    # 首问从当前学生的项目、技能和风险点中加权抽样。已问过的内容降权，仍有机会抽中。
    asked_text = "\n".join(str(message.get("content") or "") for message in messages if message.get("sender_type") == "agent")
    candidates: list[dict[str, Any]] = []
    target_role = str(interview.get("target_role") or "").lower()

    for project in analysis.get("projects", []) if isinstance(analysis.get("projects"), list) else []:
        if not isinstance(project, dict):
            continue
        name = str(project.get("name") or "").strip()
        if not name:
            continue
        if name in asked_text:
            weight = 2
        else:
            joined = " ".join([name, " ".join(project.get("highlights", []) if isinstance(project.get("highlights"), list) else [])]).lower()
            weight = 7 if target_role and target_role in joined else 5
        candidates.append({"type": "project", "value": name, "project": project, "weight": weight})

    for skill in analysis.get("core_skills", []) if isinstance(analysis.get("core_skills"), list) else []:
        value = str(skill).strip()
        if value:
            candidates.append({"type": "skill", "value": value, "weight": 4 if value in asked_text else 6})

    for risk in analysis.get("risk_points", []) if isinstance(analysis.get("risk_points"), list) else []:
        value = str(risk).strip()
        if value:
            candidates.append({"type": "risk", "value": value, "weight": 2 if value in asked_text else 3})

    if not candidates:
        return {"type": "project", "value": "项目经历", "weight": 1}

    weights = [max(1, int(candidate.get("weight") or 1)) for candidate in candidates]
    selected = random.SystemRandom().choices(candidates, weights=weights, k=1)[0]
    return {key: value for key, value in selected.items() if key != "weight"}


def normalize_status(status: Any) -> str | None:
    value = str(status or "").strip()
    return value if value in INTERVIEW_STATUSES else None


def create_default_agents(interview_id: str) -> None:
    snapshot = load_snapshot(db, interview_id)
    for index, agent in enumerate(DEFAULT_AGENT_TEMPLATES):
        if snapshot:
            role = snapshot["roles"][agent["agent_type"]]
            agent = {**agent, "agent_role": role["focus"], "strategy": role["strategy"]}
        db.execute(
            """
            INSERT INTO interview_agents (
              id, interview_id, agent_name, agent_type, agent_role, strategy, order_index, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid4()),
                interview_id,
                agent["agent_name"],
                agent["agent_type"],
                agent["agent_role"],
                agent["strategy"],
                index,
                "pending",
            ),
        )


def ensure_default_agents(interview_id: str, user_id: str) -> None:
    existing = one("SELECT COUNT(*) AS count FROM interview_agents WHERE interview_id = ?", (interview_id,))
    if not existing or existing["count"] == 0:
        with locked_session(interview_id, user_id) as session:
            if session and not list_agents_by_interview_id(interview_id):
                create_default_agents(interview_id)


def next_agent_order_index(interview_id: str) -> int:
    row = one("SELECT MAX(order_index) AS max_order_index FROM interview_agents WHERE interview_id = ?", (interview_id,))
    value = row["max_order_index"] if row else None
    return int(value) + 1 if isinstance(value, int) else 0


def find_message_by_source_ref(interview_id: str, source: str, source_ref: str) -> dict | None:
    if not source_ref:
        return None
    row = one(
        "SELECT id FROM interview_messages WHERE interview_id = ? AND source = ? AND source_ref = ?",
        (interview_id, source, source_ref),
    )
    return find_message_by_interview_id(row["id"], interview_id) if row else None


def latest_interview_question(interview_id: str) -> dict | None:
    row = one(
        """
        SELECT id
        FROM interview_messages
        WHERE interview_id = ? AND sender_type = 'agent' AND message_type IN ('question', 'follow_up')
        ORDER BY order_index DESC, created_at DESC
        LIMIT 1
        """,
        (interview_id,),
    )
    return find_message_by_interview_id(row["id"], interview_id) if row else None


def next_message_order_index(interview_id: str) -> int:
    row = one("SELECT MAX(order_index) AS max_order_index FROM interview_messages WHERE interview_id = ?", (interview_id,))
    value = row["max_order_index"] if row else None
    return int(value) + 1 if isinstance(value, int) else 0


def get_interviewer_policy(user: dict = Depends(require_auth)):
    return {"policy": load_policy(db)}


def create_interview(body: dict | None = None, user: dict = Depends(require_auth)):
    interview = parse_interview_input(json_body(body))
    try:
        policy = load_policy(db)
        selection = json_body(body).get("interviewer_strategy")
        if selection is None and policy["studentCanChoose"]:
            selection = {key: interview[field] for key, field in (("style", "interviewer_style"), ("focus", "focus_areas")) if interview[field] in policy["allowed"][key]}
        snapshot = select_strategy(policy, selection)
    except ValueError as exc:
        raise error(400, str(exc)) from exc
    interview["interviewer_style"] = snapshot["selection"]["style"]
    interview["focus_areas"] = snapshot["selection"]["focus"]
    interview_id = str(uuid4())
    resume_snapshot = profile_context.capture(user["id"])
    with db:
        db.execute(
            """
            INSERT INTO interview_sessions (
              id, user_id, target_role, experience_level, interview_type, company_context,
              focus_areas, resume_context, difficulty, interviewer_style, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                interview_id,
                user["id"],
                interview["target_role"],
                interview["experience_level"],
                interview["interview_type"],
                interview["company_context"],
                interview["focus_areas"],
                interview["resume_context"],
                interview["difficulty"],
                interview["interviewer_style"],
                "draft",
            ),
        )
        db.execute("INSERT INTO interview_strategy_snapshots (interview_id, config) VALUES (?, ?)", (interview_id, json.dumps(snapshot, ensure_ascii=False)))
        profile_context.save(interview_id, resume_snapshot)
        create_default_agents(interview_id)
        assessment_events.capture_if_enabled(interview_id)
    return {"interview": find_interview_by_user_id(interview_id, user["id"]), "agents": list_agents_by_interview_id(interview_id)}


def list_interviews(request: Request, user: dict = Depends(require_auth)):
    raw_status = request.query_params.get("status")
    status = normalize_status(raw_status) if raw_status else None
    if raw_status and not status:
        raise error(400, "面试状态不正确。")
    if status:
        interviews = all_rows(
            """
            SELECT id, user_id, target_role, experience_level, interview_type, company_context,
                   focus_areas, resume_context, difficulty, interviewer_style, status, created_at, updated_at,
                   started_at, completed_at
            FROM interview_sessions
            WHERE user_id = ? AND status = ?
            ORDER BY updated_at DESC, created_at DESC
            """,
            (user["id"], status),
        )
    else:
        interviews = all_rows(
            """
            SELECT id, user_id, target_role, experience_level, interview_type, company_context,
                   focus_areas, resume_context, difficulty, interviewer_style, status, created_at, updated_at,
                   started_at, completed_at
            FROM interview_sessions
            WHERE user_id = ?
            ORDER BY updated_at DESC, created_at DESC
            """,
            (user["id"],),
        )
    return {"interviews": interviews}


def get_interview(interview_id: str, user: dict = Depends(require_auth)):
    interview = find_interview_by_user_id(interview_id, user["id"])
    if not interview:
        raise error(404, "面试不存在。")
    return {"interview": interview}


def update_interview(interview_id: str, body: dict | None = None, user: dict = Depends(require_auth)):
    with locked_session(interview_id, user["id"]) as session:
        require_open_session(session)
        interview = find_interview_by_user_id(interview_id, user["id"])
        if one("SELECT attempt_id FROM interview_training_attempts WHERE interview_id=?", (interview_id,)):
            raise error(409, "教学任务已绑定，面试设置不能修改。")
        if any(key in json_body(body) for key in ("interviewer_style", "focus_areas", "interviewer_strategy")) and interview.get("interviewer_strategy"):
            raise error(409, "本场面试官策略已固定，请创建新面试以使用不同策略。")
        parsed = parse_interview_input(json_body(body), partial=True)
        next_interview = {**interview, **parsed}
        db.execute(
            """
            UPDATE interview_sessions
            SET target_role = ?, experience_level = ?, interview_type = ?, company_context = ?,
                focus_areas = ?, resume_context = ?, difficulty = ?, interviewer_style = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND user_id = ?
            """,
            (
                next_interview["target_role"],
                next_interview["experience_level"],
                next_interview["interview_type"],
                next_interview["company_context"],
                next_interview["focus_areas"],
                next_interview["resume_context"],
                next_interview["difficulty"],
                next_interview["interviewer_style"],
                interview["id"],
                user["id"],
            ),
        ).close()
    return {"interview": find_interview_by_user_id(interview["id"], user["id"])}


def start_interview(interview_id: str, user: dict = Depends(require_auth)):
    interview = find_interview_by_user_id(interview_id, user["id"])
    if not interview:
        raise error(404, "面试不存在。")
    if interview["status"] == "completed":
        raise error(409, "已完成的面试不能重新开始。")
    if interview["status"] == "draft":
        db.execute(
            """
            UPDATE interview_sessions
            SET status = 'running', started_at = COALESCE(started_at, CURRENT_TIMESTAMP),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND user_id = ? AND status = 'draft'
            """,
            (interview["id"], user["id"]),
        )
        db.commit()
    return {"interview": find_interview_by_user_id(interview["id"], user["id"])}


def create_opening_question(interview_id: str, body: dict | None = None, user: dict = Depends(require_auth)):
    interview = find_interview_by_user_id(interview_id, user["id"])
    if not interview:
        raise error(404, "面试不存在。")
    if interview["status"] == "completed":
        raise error(409, "已完成的面试不能继续生成首问。")
    messages = list_messages_by_interview_id(interview["id"])
    if messages and not bool(json_body(body).get("force")):
        raise error(409, "当前面试已有消息，不能重复生成首问。")

    ensure_default_agents(interview["id"], user["id"])
    agents = list_agents_by_interview_id(interview["id"])
    active_agent = next((agent for agent in agents if agent["status"] == "active"), None)
    if not active_agent:
        active_agent = next((agent for agent in agents if agent["status"] != "completed"), agents[0] if agents else None)

    resume_analysis_row = profile_context.load(interview_id) or {"analysis": {}}
    analysis = resume_analysis_row.get("analysis") or {}
    selected_resume_point = select_resume_point(analysis, interview, messages)
    result = generate_opening_question(
        interview=interview,
        active_agent=active_agent,
        resume_analysis=analysis,
        selected_resume_point=selected_resume_point,
    )
    return {
        "question": result["question"],
        "provider": result.get("provider"),
        "fallback": bool(result.get("fallback")),
        "error": result.get("error"),
        "selected_resume_point": selected_resume_point,
        "resume_analysis": resume_analysis_row,
    }


def require_open_session(session):
    if not session:
        raise error(404, "面试不存在。")
    if session["status"] == "completed":
        raise error(409, "本场面试已经结束。")


def serialize_progress(interview_id, state, recover_spoken):
    turn = turn_by(interview_id, state["last_submission_id"]) if state["last_submission_id"] else None
    pending = turn and turn["action"] == "ask_follow_up" and not state["question_id"]
    question_id = state["question_id"]
    if pending and recover_spoken:
        question_id = complete_pending_question(interview_id, turn, json.loads(turn["decision_json"])["question"])
        pending = False
    return {
        "question": find_message_by_interview_id(question_id, interview_id) if question_id else None,
        "active_agent": find_agent_by_interview_id(state["agent_id"], interview_id) if state["agent_id"] else None,
        "action": turn["action"] if turn else None,
        "pending_spoken_submission_id": turn["submission_id"] if pending else None,
    }


def current_question(interview_id: str, body: dict | None = None, user: dict = Depends(require_auth)):
    interview = find_interview_by_user_id(interview_id, user["id"])
    if not interview:
        raise error(404, "面试不存在。")
    finished = {"question": None, "active_agent": None, "action": "finish_interview", "pending_spoken_submission_id": None}
    if interview["status"] == "completed":
        return finished
    opening = None
    if not managed_progress(interview_id) and not latest_interview_question(interview_id):
        # 模型生成首问可能耗时，取得会话锁后须重新核验服务端当前状态。
        try:
            opening = create_opening_question(interview_id, user=user)["question"]
        except HTTPException as exc:
            if exc.status_code not in (400, 409):
                raise

    with locked_session(interview_id, user["id"]) as session:
        if session and session["status"] == "completed":
            return finished
        require_open_session(session)
        state = managed_progress(interview_id)
        if state and not state["agent_id"] and not state["question_id"]:
            return finished
        if not state:
            agents = list_agents_by_interview_id(interview_id)
            if not agents:
                create_default_agents(interview_id)
                agents = list_agents_by_interview_id(interview_id)
            question = latest_interview_question(interview_id)
            # 接管进行中的旧版面试，并恢复可能中断的角色切换。
            agent = next((a for a in agents if a["status"] == "active"), None)
            if not agent and question:
                agent = next((a for a in agents if a["id"] == question["agent_id"] and a["status"] != "completed"), None)
            agent = agent or next((a for a in agents if a["status"] != "completed"), None)
            if not agent:
                db.execute("INSERT INTO interview_progress(interview_id) VALUES (?)", (interview_id,)).close()
                return finished
            db.execute("UPDATE interview_agents SET status='active' WHERE id=?", (agent["id"],)).close()
            if question and question["agent_id"] == agent["id"]:
                question_id = question["id"]
            else:
                question_id = append_message(interview_id, agent["id"], "question", opening or create_initial_question(interview, agent))
            db.execute("INSERT INTO interview_progress(interview_id,agent_id,question_id) VALUES (?,?,?)",
                       (interview_id, agent["id"], question_id)).close()
            messages = list_messages_by_interview_id(interview_id)
            if question and question_id == question["id"]:
                # 旧客户端会先保存回答，再请求下一题；恢复回合时要识别这条回答。
                answer = next((m for m in reversed(messages) if m["sender_type"] == "candidate"
                               and m.get("reply_to_message_id") in (None, question_id)
                               and m.get("round_agent_id") in (None, agent["id"])
                               and m["order_index"] > question["order_index"]), None)
                if answer:
                    history = [m for m in messages if m["order_index"] < answer["order_index"]]
                    decision = decide_turn(interview=interview, agents=agents, active_agent=agent,
                                           messages=history, answer=answer)
                    commit_turn(interview_id, "legacy-" + answer["id"], question, answer,
                                decision, decision["question"], existing_answer=True)
                    enqueue_score_for_answer(interview_id, answer["id"])
            state = managed_progress(interview_id)
        return serialize_progress(interview_id, state, (body or {}).get("recover_spoken") is True)


def replay_turn(interview_id, turn, question_id, message):
    answer = find_message_by_interview_id(turn["answer_id"], interview_id)
    if (turn["question_id"] != question_id or answer["content"] != message["content"]
            or answer["source"] != message["source"] or answer["transcript_text"] != message["transcript_text"]):
        raise error(409, "同一提交标识不能用于不同回答。")
    next_id = turn["next_question_id"]
    agent_id = turn["next_agent_id"]
    return {
        "answer": answer,
        "action": turn["action"],
        "question": find_message_by_interview_id(next_id, interview_id) if next_id else None,
        "active_agent": find_agent_by_interview_id(agent_id, interview_id) if agent_id else None,
        "decision": json.loads(turn["decision_json"]),
        "duplicate": True,
    }


def require_current_question(state, question_id):
    if not state or state["question_id"] != question_id:
        raise error(409, "题目进度已变化，请同步当前题后重试。")


def submit_turn(interview_id: str, body: dict, user: dict = Depends(require_auth)):
    question_id = str(body.get("question_id") or "")
    submission_id = str(body.get("submission_id") or "").strip()
    if not question_id or not submission_id or len(submission_id) > 128:
        raise error(400, "请提供有效的题目和提交标识。")
    message = parse_message_input({**body, "sender_type": "candidate", "message_type": "answer",
                                   "source_ref": submission_id, "agent_id": None})
    interview = find_interview_by_user_id(interview_id, user["id"])
    if not interview:
        raise error(404, "面试不存在。")
    # 持锁读取一致快照，在锁外生成下一题，写入前再加锁核验当前状态。
    with locked_session(interview_id, user["id"]) as session:
        prior = turn_by(interview_id, submission_id)
        if prior:
            return replay_turn(interview_id, prior, question_id, message)
        require_open_session(session)
        state = managed_progress(interview_id)
        require_current_question(state, question_id)
        question = find_message_by_interview_id(question_id, interview_id)
        answer = {**message, "id": str(uuid4()), "round_agent_id": question["agent_id"], "reply_to_message_id": question_id}
        if find_message_by_source_ref(interview_id, message["source"], submission_id):
            raise error(409, "提交标识已被其他消息使用。")
        if training_rounds.commit_if_training(interview_id, submission_id, question, answer):
            enqueue_score_for_answer(interview_id, answer["id"])
            result = replay_turn(interview_id, turn_by(interview_id, submission_id), question_id, message)
            return {**result, "duplicate": False}
        agents = list_agents_by_interview_id(interview_id)
        active = next(a for a in agents if a["id"] == state["agent_id"])
        messages = list_messages_by_interview_id(interview_id)
    decision = decide_turn(interview=interview, agents=agents, active_agent=active, messages=messages, answer=answer)
    next_question = decision["question"]
    if decision["action"] == "ask_follow_up":
        if message["source"] == "aliyun_rtc":
            next_question = None
        else:
            try:
                result = generate_kimi_followup(interview=interview, active_agent=active,
                    messages=messages, last_answer=message["content"], resume_analysis=resume_analysis_for_prompt(user, interview_id=interview_id),
                    turn_decision=decision)
                next_question = result["question"]
            except KimiFollowupError:
                pass  # 决策结果中已有适合当前角色的备用追问。
    with locked_session(interview_id, user["id"]) as session:
        prior = turn_by(interview_id, submission_id)
        if prior:
            return replay_turn(interview_id, prior, question_id, message)
        require_open_session(session)
        require_current_question(managed_progress(interview_id), question_id)
        if find_message_by_source_ref(interview_id, message["source"], submission_id):
            raise error(409, "提交标识已被其他消息使用。")
        commit_turn(interview_id, submission_id, question, answer, decision, next_question)
        enqueue_score_for_answer(interview_id, answer["id"])
        result = replay_turn(interview_id, turn_by(interview_id, submission_id), question_id, message)
        return {**result, "duplicate": False}


def save_spoken_question(interview_id: str, submission_id: str, body: dict, user: dict = Depends(require_auth)):
    with locked_session(interview_id, user["id"]) as session:
        require_open_session(session)
        state = managed_progress(interview_id)
        if not state or state["last_submission_id"] != submission_id:
            raise error(409, "已切换题目，忽略过期字幕。")
        turn = turn_by(interview_id, submission_id)
        answer = find_message_by_interview_id(turn["answer_id"], interview_id)
        if turn["action"] != "ask_follow_up" or answer["source"] != "aliyun_rtc":
            raise error(409, "当前轮次无需同步语音追问。")
        question_id = turn["next_question_id"]
        if not question_id:
            message = parse_message_input({**body, "source": "aliyun_rtc", "sender_type": "agent",
                                           "message_type": "follow_up", "agent_id": turn["next_agent_id"]})
            if find_message_by_source_ref(interview_id, "aliyun_rtc", message["source_ref"]):
                raise error(409, "字幕标识已被其他消息使用。")
            question_id = complete_pending_question(interview_id, turn, message["content"],
                                                   message["transcript_text"], message["source_ref"])
        return {"question": find_message_by_interview_id(question_id, interview_id)}


def finish_interview(interview_id: str, background_tasks: BackgroundTasks, user: dict = Depends(require_auth)):
    """结束面试、登记教学完成和投递评估证据，在一个事务内完成。"""
    with locked_session(interview_id, user["id"]) as session:
        if not session:
            raise error(404, "面试不存在。")
        training_rounds.require_all_answered(interview_id)
        if session["status"] != "completed":
            db.execute("""UPDATE interview_sessions SET status='completed',
                       started_at=COALESCE(started_at,CURRENT_TIMESTAMP),
                       completed_at=COALESCE(completed_at,CURRENT_TIMESTAMP),updated_at=CURRENT_TIMESTAMP
                       WHERE id=?""", (interview_id,)).close()
        from services.interview.delivery import enqueue_training_complete
        enqueue_training_complete(interview_jobs, interview_id)
        if os.environ.get("MEDIA_SERVICE_URL"):
            # 与面试完成一并登记；媒体短暂离线时由工作进程重试关闭，不向旧 RTC 服务发请求。
            interview_jobs.enqueue("media_close", interview_id, user["id"], "1")
        rid = assessment_events.capture(interview_jobs, interview_id)
    return {"interview": find_interview_by_user_id(interview_id, user["id"]),
            "report": {"id": rid, "interview_id": interview_id, "generation_status": "queued", "assessment_pending": True}}

def list_agents(interview_id: str, user: dict = Depends(require_auth)):
    interview = find_interview_by_user_id(interview_id, user["id"])
    if not interview:
        raise error(404, "面试不存在。")
    ensure_default_agents(interview["id"], user["id"])
    return {"agents": list_agents_by_interview_id(interview["id"])}


def create_agent(interview_id: str, body: dict | None = None, user: dict = Depends(require_auth)):
    interview = find_interview_by_user_id(interview_id, user["id"])
    if not interview:
        raise error(404, "面试不存在。")
    if interview["status"] == "completed":
        raise error(409, "已完成的面试不能新增 Agent。")
    with locked_session(interview_id, user["id"]) as session:
        require_open_session(session)
        if managed_progress(interview_id):
            raise error(409, "本场轮次已由服务端管理。")
        agent = parse_agent_input(json_body(body))
        agent_id = str(uuid4())
        order_index = agent["order_index"] if isinstance(agent.get("order_index"), int) else next_agent_order_index(interview["id"])
        db.execute(
            """
            INSERT INTO interview_agents (
              id, interview_id, agent_name, agent_type, agent_role, strategy, order_index, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                agent_id,
                interview["id"],
                agent["agent_name"],
                agent["agent_type"],
                agent["agent_role"],
                agent.get("strategy"),
                order_index,
                agent.get("status") or "pending",
            ),
        )
        return {"agent": find_agent_by_interview_id(agent_id, interview["id"])}


def update_agent(interview_id: str, agent_id: str, body: dict | None = None, user: dict = Depends(require_auth)):
    interview = find_interview_by_user_id(interview_id, user["id"])
    if not interview:
        raise error(404, "面试不存在。")
    if interview["status"] == "completed":
        raise error(409, "已完成的面试不能修改 Agent。")
    with locked_session(interview_id, user["id"]) as session:
        require_open_session(session)
        if managed_progress(interview_id):
            raise error(409, "本场轮次已由服务端管理。")
        existing = find_agent_by_interview_id(agent_id, interview["id"])
        if not existing:
            raise error(404, "Agent 不存在。")
        parsed = parse_agent_input(json_body(body), partial=True)
        next_agent = {**existing, **parsed}
        db.execute(
            """
            UPDATE interview_agents
            SET agent_name = ?, agent_type = ?, agent_role = ?, strategy = ?, order_index = ?,
                status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND interview_id = ?
            """,
            (
                next_agent["agent_name"],
                next_agent["agent_type"],
                next_agent["agent_role"],
                next_agent.get("strategy"),
                next_agent["order_index"],
                next_agent["status"],
                existing["id"],
                interview["id"],
            ),
        )
        return {"agent": find_agent_by_interview_id(existing["id"], interview["id"])}


def list_messages(interview_id: str, user: dict = Depends(require_auth)):
    interview = find_interview_by_user_id(interview_id, user["id"])
    if not interview:
        # 越权和不存在均返回相同的 404，不反查所有者或把学号写入响应与日志。
        raise error(404, "面试不存在。")
    return {"messages": list_messages_by_interview_id(interview["id"])}


def create_message(
    interview_id: str,
    response: Response,
    body: dict | None = None,
    user: dict = Depends(require_auth),
):
    interview = find_interview_by_user_id(interview_id, user["id"])
    if not interview:
        raise error(404, "面试不存在。")
    if interview["status"] == "completed":
        raise error(409, "已完成的面试不能继续写入消息。")
    message = parse_message_input(json_body(body))
    if message["agent_id"] and not find_agent_by_interview_id(message["agent_id"], interview["id"]):
        raise error(400, "Agent 不属于当前面试。")
    existing = find_message_by_source_ref(interview["id"], message["source"], message["source_ref"])
    if existing:
        response.status_code = 200
        return {"message": existing, "duplicate": True}

    message_id = str(uuid4())
    try:
        with locked_session(interview_id, user["id"]) as session:
            require_open_session(session)
            if managed_progress(interview_id):
                raise error(409, "本场轮次已由服务端管理，请从当前题提交回答。")
            reply_to_message_id = None
            round_agent_id = None
            if message["sender_type"] == "candidate":
                question = latest_interview_question(interview["id"])
                if question:
                    reply_to_message_id = question["id"]
                    round_agent_id = question.get("agent_id")
            db.execute(
                """
                INSERT INTO interview_messages (
                  id, interview_id, agent_id, sender_type, message_type, content, transcript_text,
                  source, source_ref, reply_to_message_id, round_agent_id, order_index
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    interview["id"],
                    message["agent_id"],
                    message["sender_type"],
                    message["message_type"],
                    message["content"],
                    message["transcript_text"],
                    message["source"],
                    message["source_ref"],
                    reply_to_message_id,
                    round_agent_id,
                    next_message_order_index(interview["id"]),
                ),
            ).close()
            if message["sender_type"] == "candidate":
                enqueue_score_for_answer(interview_id, message_id)
            db.execute(
                "UPDATE interview_sessions SET updated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ?",
                (interview["id"], user["id"]),
            ).close()
    except Exception:
        # 实时音视频的最终字幕重试请求可能与首次提交并发写入。
        existing = find_message_by_source_ref(interview["id"], message["source"], message["source_ref"])
        if existing:
            response.status_code = 200
            return {"message": existing, "duplicate": True}
        raise
    return {"message": find_message_by_interview_id(message_id, interview["id"]), "duplicate": False}


def generate_follow_up(interview_id: str, body: dict | None = None, user: dict = Depends(require_auth)):
    interview = find_interview_by_user_id(interview_id, user["id"])
    if not interview:
        raise error(404, "面试不存在。")
    if interview["status"] == "completed":
        raise error(409, "已完成的面试不能继续生成追问。")
    last_answer, message = read_text_field(json_body(body), "last_answer", "候选人回答", 20000, True)
    if message:
        raise error(400, message)

    ensure_default_agents(interview["id"], user["id"])
    agents = list_agents_by_interview_id(interview["id"])
    active_agent = next((agent for agent in agents if agent["status"] == "active"), None)
    if not active_agent:
        active_agent = next((agent for agent in agents if agent["status"] != "completed"), agents[0] if agents else None)
    messages = list_messages_by_interview_id(interview["id"])
    resume_analysis = resume_analysis_for_prompt(user, interview_id=interview_id)
    try:
        follow_up = generate_kimi_followup(
            interview=interview,
            active_agent=active_agent,
            messages=messages,
            last_answer=last_answer,
            resume_analysis=resume_analysis,
        )
    except KimiFollowupError as exc:
        raise error(502, str(exc))
    return follow_up


def enqueue_score_for_answer(interview_id, message_id):
    """面试端只投递证据，评分由下游独立执行。"""
    return assessment_events.capture(interview_jobs, interview_id)


def prepare_interview_job(job):
    """面试工作进程只投递已提交的训练事件和评估输入。"""
    if job["kind"] == "media_close":
        from services.media.gateway import finish
        student = one("SELECT user_id,status FROM interview_sessions WHERE id=?", (job["interview_id"],))
        if not student or student["status"] != "completed" or student["user_id"] != job["subject_id"]:
            raise ValueError("关闭媒体前无法确认面试与学生归属")
        finish(job["interview_id"], student["user_id"], os.environ["LEGACY_SCHOOL_ID"])
        return lambda: None
    from .delivery import prepare_delivery
    return prepare_delivery(interview_jobs, job)
