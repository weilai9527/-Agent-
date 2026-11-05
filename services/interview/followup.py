from __future__ import annotations

import json
import os
import re
import time
from shared.provider_selection import get_task_providers
from typing import Any

import httpx

from .decision import ANSWER_CONTEXT_POLICY, contextual_followup
from shared.provider_settings import runtime_settings
from shared.interviewer_policy import strategy_prompt


from shared.text_provider import (
    FollowupProvider, KimiFollowupError, _call_provider_content, _extract_json_object,
    _provider_config, call_provider_json,
)
from services.profile.analysis import (
    LOCAL_DIRECTION_PROFILES, _normalize_candidate_summary, _normalize_list, _normalize_resume_analysis,
    build_local_direction_recommendations, build_local_resume_analysis, resume_analysis_source_text,
)


class ResumeAiError(RuntimeError):
    pass


def _provider_order() -> list[FollowupProvider]:
    settings = runtime_settings()
    order = settings.get("FOLLOWUP_PROVIDER_ORDER", "kimi,deepseek,qwen,openai,custom")
    providers = []
    seen = set()
    for name in order.split(","):
        normalized = name.strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        provider = _provider_config(normalized, settings)
        if provider and provider.base_url and provider.model:
            providers.append(provider)
    return providers


def _format_recent_messages(messages: list[dict[str, Any]], limit: int = 10) -> str:
    recent = messages[-limit:]
    if not recent:
        return "暂无历史对话。"
    lines = []
    for message in recent:
        speaker = "候选人" if message.get("sender_type") == "candidate" else message.get("agent_name") or "面试官"
        content = str(message.get("content") or "").strip()
        if content:
            lines.append(f"{speaker}：{content}")
    return "\n".join(lines) or "暂无历史对话。"


def format_resume_analysis(resume_analysis: dict[str, Any] | None) -> str:
    if not resume_analysis:
        return "暂无简历结构化摘要。"
    parts = [
        f"候选人概述：{resume_analysis.get('candidate_summary') or '未提取'}",
        "核心技能：" + "、".join(str(item) for item in resume_analysis.get("core_skills", [])[:8]),
    ]
    projects = resume_analysis.get("projects", [])
    if isinstance(projects, list) and projects:
        project_lines = []
        for project in projects[:4]:
            if not isinstance(project, dict):
                continue
            highlights = "、".join(str(item) for item in project.get("highlights", [])[:4])
            project_lines.append(f"- {project.get('name') or '未命名项目'}：{project.get('role') or '职责未明'}；亮点：{highlights or '未提取'}")
        if project_lines:
            parts.append("项目摘要：\n" + "\n".join(project_lines))
    risks = resume_analysis.get("risk_points", [])
    if isinstance(risks, list) and risks:
        parts.append("风险点：" + "、".join(str(item) for item in risks[:5]))
    return "\n".join(part for part in parts if part.strip())


# 保留已有提示词构造函数使用的内部名称，实时面试也复用同一个格式化函数。
_format_resume_analysis = format_resume_analysis


def _build_messages(
    *,
    interview: dict[str, Any],
    active_agent: dict[str, Any] | None,
    messages: list[dict[str, Any]],
    last_answer: str,
    resume_analysis: dict[str, Any] | None = None,
    turn_decision: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    recent_context = _format_recent_messages(messages)
    asked_questions = "\n".join(
        f"- {message.get('content')}"
        for message in messages
        if message.get("sender_type") == "agent" and message.get("content")
    ) or "- 暂无"
    system_prompt = "\n".join(
        [
            "你是一名中文 AI 电话面试官，正在进行真实模拟面试。",
            "你的任务是基于候选人的最新回答和最近对话，生成下一句自然、具体、有上下文感的追问。",
            "要求：",
            "1. 只输出一句追问，不要输出分析、评分、标题或多题列表。",
            "2. 不要机械套模板，不要重复已问过的问题。",
            "3. 如果候选人质疑问题或表示没提到某点，要先承认并修正方向，再提出更贴合上下文的问题。",
            ANSWER_CONTEXT_POLICY,
            "5. 优先围绕简历里的真实项目、技能和风险点追问；不要凭空添加候选人没有提过的经历。",
            "6. 电话面试语气，简洁专业，控制在 60 字以内。",
            *([strategy_prompt(interview, active_agent or {})] if interview.get("interviewer_strategy") else []),
        ]
    )
    guidance = []
    if turn_decision:
        missing = [key for key, evidence in turn_decision["evidence"].items() if evidence["status"] != "supported"]
        guidance = [f"本轮待核实的维度：{'、'.join(missing) or '无'}",
                    f"结合最新回答，自然地追问这个目标：{turn_decision['question']}"]
    user_prompt = "\n".join(
        [
            f"目标岗位：{interview.get('target_role') or '未填写'}",
            f"面试类型：{interview.get('interview_type') or '综合模拟'}",
            f"难度：{interview.get('difficulty') or '标准'}",
            f"面试官风格：{interview.get('interviewer_style') or '专业追问'}",
            f"当前面试官：{active_agent.get('agent_name') if active_agent else '技术面试 Agent'}",
            f"面试官策略：{active_agent.get('strategy') if active_agent else '围绕项目经历深挖'}",
            f"简历结构化摘要：\n{_format_resume_analysis(resume_analysis)}",
            f"已问过的问题：\n{asked_questions}",
            f"最近对话：\n{recent_context}",
            f"候选人最新回答：{last_answer}",
            *guidance,
            "请生成下一句追问：",
        ]
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def _call_provider(provider: FollowupProvider, chat_messages: list[dict[str, str]]) -> str:
    question = _call_provider_content(provider, chat_messages).strip('"“”')
    if not question:
        raise KimiFollowupError(f"{provider.name} 未返回有效追问。")
    return question


def generate_kimi_followup(
    *,
    interview: dict[str, Any],
    active_agent: dict[str, Any] | None,
    messages: list[dict[str, Any]],
    last_answer: str,
    resume_analysis: dict[str, Any] | None = None,
    turn_decision: dict[str, Any] | None = None,
) -> dict[str, Any]:
    answer = str(last_answer or "").strip()
    if not answer:
        raise KimiFollowupError("缺少候选人回答，无法生成追问。")

    if turn_decision:
        scoped_question = turn_decision["question"] if turn_decision.get("followup_mode") else None
    else:
        # 旧追问接口没有持久化的轮次决策。
        agent = active_agent or {}
        asked = [str(m.get("content") or "") for m in messages if m.get("sender_type") == "agent"
                 and m.get("message_type") in {"question", "follow_up"} and m.get("agent_id") == agent.get("id")]
        _, scoped_question = contextual_followup(agent.get("agent_type"), answer, asked[-1] if asked else "", asked)
    if scoped_question:
        return {"question": scoped_question, "provider": "local", "fallback": False}

    providers = _provider_order()
    if not providers:
        raise KimiFollowupError("服务端未配置可用的追问生成 API Key。")

    chat_messages = _build_messages(
        interview=interview,
        active_agent=active_agent,
        messages=messages,
        last_answer=answer,
        resume_analysis=resume_analysis,
        turn_decision=turn_decision,
    )
    errors = []
    for index, provider in enumerate(providers):
        try:
            return {
                "question": _call_provider(provider, chat_messages),
                "provider": provider.name,
                "fallback": index > 0,
            }
        except (httpx.HTTPError, ValueError, KimiFollowupError) as exc:
            errors.append(f"{provider.name}: {exc}")

    raise KimiFollowupError("追问生成失败：" + " | ".join(errors))


def analyze_resume(profile: dict[str, Any]) -> dict[str, Any]:
    """供单校旧部署使用的兼容入口，遵循涉及私密信息的任务策略。"""
    from services.profile.model_policy import analyze_profile, legacy_model

    return analyze_profile(legacy_model("profile"), profile)


def generate_opening_question(
    *,
    interview: dict[str, Any],
    active_agent: dict[str, Any] | None,
    resume_analysis: dict[str, Any] | None,
    selected_resume_point: dict[str, Any],
) -> dict[str, Any]:
    # 调用方已选定本次提问素材。模型结合简历摘要组织问句，本地回退也沿用同一素材。
    providers = _provider_order()
    if not providers:
        return {
            "question": build_local_opening_question(interview, active_agent, resume_analysis, selected_resume_point),
            "provider": "local",
            "fallback": True,
        }

    chat_messages = [
        {
            "role": "system",
            "content": "\n".join(
                [
                    "你是一名中文 AI 电话面试官，正在生成本场面试第一问。",
                    "只输出一句自然的首问，不要标题、分析或多题列表。",
                    "必须围绕抽中的简历点展开，先点出候选人简历中的真实经历，再问业务背景、个人职责和结果衡量。",
                    "控制在 80 字以内。",
                    *([strategy_prompt(interview, active_agent or {})] if interview.get("interviewer_strategy") else []),
                ]
            ),
        },
        {
            "role": "user",
            "content": "\n".join(
                [
                    f"目标岗位：{interview.get('target_role') or '未填写'}",
                    f"面试类型：{interview.get('interview_type') or '综合模拟'}",
                    f"当前面试官：{active_agent.get('agent_name') if active_agent else '技术面试 Agent'}",
                    f"面试官策略：{active_agent.get('strategy') if active_agent else '围绕项目经历深挖'}",
                    f"简历摘要：\n{_format_resume_analysis(resume_analysis)}",
                    f"抽中的简历点：{json.dumps(selected_resume_point, ensure_ascii=False)}",
                    "请生成第一问：",
                ]
            ),
        },
    ]
    errors = []
    for index, provider in enumerate(providers):
        try:
            return {
                "question": _call_provider(provider, chat_messages),
                "provider": provider.name,
                "fallback": index > 0,
            }
        except (httpx.HTTPError, ValueError, KimiFollowupError) as exc:
            errors.append(f"{provider.name}: {exc}")
    return {
        "question": build_local_opening_question(interview, active_agent, resume_analysis, selected_resume_point),
        "provider": "local",
        "fallback": True,
        "error": " | ".join(errors),
    }


def build_local_opening_question(
    interview: dict[str, Any],
    active_agent: dict[str, Any] | None,
    resume_analysis: dict[str, Any] | None,
    selected_resume_point: dict[str, Any],
) -> str:
    role = interview.get("target_role") or "目标岗位"
    point_type = selected_resume_point.get("type")
    value = selected_resume_point.get("value") or "项目经历"
    if point_type == "skill":
        return f"我看到你简历里提到{value}，这和{role}比较相关。能结合一个真实项目说说你怎么用它解决问题，以及最后如何衡量效果吗？"
    if point_type == "risk":
        return f"我想先确认一个简历里的关键信息：{value}。你能选一个代表项目，说明你的具体职责、方案取舍和最终结果吗？"
    project_name = value
    project = selected_resume_point.get("project") or {}
    highlights = project.get("highlights") if isinstance(project, dict) else []
    highlight_text = "和" + "、".join(highlights[:2]) if highlights else ""
    agent_name = active_agent.get("agent_name") if active_agent else "面试官"
    if resume_analysis and resume_analysis.get("candidate_summary"):
        return f"我看到你简历里提到{project_name}{highlight_text}。我们先从这个项目聊起：当时要解决什么业务问题，你具体负责哪一层，效果怎么衡量？"
    return f"{agent_name}先从你的{project_name}聊起：当时项目背景是什么，你具体负责什么，最后产出或指标有什么变化？"
