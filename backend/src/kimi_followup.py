from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any

import httpx


class KimiFollowupError(RuntimeError):
    pass


class ResumeAiError(RuntimeError):
    pass


@dataclass(frozen=True)
class FollowupProvider:
    name: str
    api_key: str
    base_url: str
    model: str
    timeout: float
    temperature: float
    max_tokens: int


def _first_env(*names: str) -> str:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return ""


def _valid_key(value: str) -> bool:
    return bool(value and not value.startswith("your-"))


def _provider_config(name: str) -> FollowupProvider | None:
    normalized = name.strip().lower()
    if normalized == "kimi":
        api_key = _first_env("KIMI_API_KEY", "MOONSHOT_API_KEY")
        if not _valid_key(api_key):
            return None
        return FollowupProvider(
            name="kimi",
            api_key=api_key,
            base_url=os.environ.get("KIMI_BASE_URL", "https://api.moonshot.cn/v1").rstrip("/"),
            model=os.environ.get("KIMI_MODEL", "moonshot-v1-8k"),
            timeout=float(os.environ.get("KIMI_TIMEOUT", "20")),
            temperature=float(os.environ.get("KIMI_TEMPERATURE", "0.55")),
            max_tokens=int(os.environ.get("KIMI_MAX_TOKENS", "160")),
        )
    if normalized == "deepseek":
        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        if not _valid_key(api_key):
            return None
        return FollowupProvider(
            name="deepseek",
            api_key=api_key,
            base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/"),
            model=os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
            timeout=float(os.environ.get("DEEPSEEK_TIMEOUT", "20")),
            temperature=float(os.environ.get("DEEPSEEK_TEMPERATURE", "0.55")),
            max_tokens=int(os.environ.get("DEEPSEEK_MAX_TOKENS", "160")),
        )
    if normalized in {"qwen", "dashscope"}:
        api_key = _first_env("QWEN_API_KEY", "DASHSCOPE_API_KEY")
        if not _valid_key(api_key):
            return None
        return FollowupProvider(
            name="qwen",
            api_key=api_key,
            base_url=os.environ.get("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1").rstrip("/"),
            model=os.environ.get("QWEN_MODEL", "qwen-plus"),
            timeout=float(os.environ.get("QWEN_TIMEOUT", "20")),
            temperature=float(os.environ.get("QWEN_TEMPERATURE", "0.55")),
            max_tokens=int(os.environ.get("QWEN_MAX_TOKENS", "160")),
        )
    if normalized == "openai":
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not _valid_key(api_key):
            return None
        return FollowupProvider(
            name="openai",
            api_key=api_key,
            base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
            model=os.environ.get("OPENAI_FOLLOWUP_MODEL", "gpt-4o-mini"),
            timeout=float(os.environ.get("OPENAI_FOLLOWUP_TIMEOUT", "20")),
            temperature=float(os.environ.get("OPENAI_FOLLOWUP_TEMPERATURE", "0.55")),
            max_tokens=int(os.environ.get("OPENAI_FOLLOWUP_MAX_TOKENS", "160")),
        )
    if normalized in {"custom", "ai"}:
        api_key = os.environ.get("AI_API_KEY", "")
        if not _valid_key(api_key):
            return None
        return FollowupProvider(
            name="custom",
            api_key=api_key,
            base_url=os.environ.get("AI_BASE_URL", "").rstrip("/"),
            model=os.environ.get("AI_MODEL", ""),
            timeout=float(os.environ.get("AI_TIMEOUT", "20")),
            temperature=float(os.environ.get("AI_TEMPERATURE", "0.55")),
            max_tokens=int(os.environ.get("AI_MAX_TOKENS", "160")),
        )
    return None


def _provider_order() -> list[FollowupProvider]:
    order = os.environ.get("FOLLOWUP_PROVIDER_ORDER", "kimi,deepseek,qwen,openai,custom")
    providers = []
    seen = set()
    for name in order.split(","):
        normalized = name.strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        provider = _provider_config(normalized)
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


def _format_resume_analysis(resume_analysis: dict[str, Any] | None) -> str:
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


def _extract_json_object(content: str) -> dict[str, Any]:
    text = str(content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            raise
        parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("模型未返回 JSON 对象。")
    return parsed


def _build_messages(
    *,
    interview: dict[str, Any],
    active_agent: dict[str, Any] | None,
    messages: list[dict[str, Any]],
    last_answer: str,
    resume_analysis: dict[str, Any] | None = None,
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
            "4. 如果候选人回答很短或无效，追问应引导其补充具体经历，而不是强行推进到下一阶段。",
            "5. 优先围绕简历里的真实项目、技能和风险点追问；不要凭空添加候选人没有提过的经历。",
            "6. 电话面试语气，简洁专业，控制在 60 字以内。",
        ]
    )
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
            "请生成下一句追问：",
        ]
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def _call_provider_content(provider: FollowupProvider, chat_messages: list[dict[str, str]]) -> str:
    response = httpx.post(
        f"{provider.base_url}/chat/completions",
        headers={"Authorization": f"Bearer {provider.api_key}", "Content-Type": "application/json"},
        json={
            "model": provider.model,
            "messages": chat_messages,
            "temperature": provider.temperature,
            "max_tokens": provider.max_tokens,
        },
        timeout=provider.timeout,
    )
    response.raise_for_status()
    data = response.json()
    content = (
        data.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
    )
    return str(content or "").strip()


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
) -> dict[str, Any]:
    answer = str(last_answer or "").strip()
    if not answer:
        raise KimiFollowupError("缺少候选人回答，无法生成追问。")

    providers = _provider_order()
    if not providers:
        raise KimiFollowupError("服务端未配置可用的追问生成 API Key。")

    chat_messages = _build_messages(
        interview=interview,
        active_agent=active_agent,
        messages=messages,
        last_answer=answer,
        resume_analysis=resume_analysis,
    )
    errors = []
    for index, provider in enumerate(providers):
        try:
            return {
                "question": _call_provider(provider, chat_messages),
                "provider": provider.name,
                "fallback": index > 0,
            }
        except (httpx.HTTPError, json.JSONDecodeError, KimiFollowupError) as exc:
            errors.append(f"{provider.name}: {exc}")

    raise KimiFollowupError("追问生成失败：" + " | ".join(errors))


def _normalize_list(value: Any, limit: int = 8) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()][:limit]
    if isinstance(value, str):
        return [item.strip() for item in re.split(r"[,，、\n]", value) if item.strip()][:limit]
    return []


def _normalize_resume_analysis(value: dict[str, Any]) -> dict[str, Any]:
    projects = []
    raw_projects = value.get("projects")
    if isinstance(raw_projects, list):
        for item in raw_projects[:5]:
            if not isinstance(item, dict):
                continue
            projects.append(
                {
                    "name": str(item.get("name") or "未命名项目").strip()[:80],
                    "role": str(item.get("role") or "参与者").strip()[:80],
                    "highlights": _normalize_list(item.get("highlights"), 6),
                    "possible_questions": _normalize_list(item.get("possible_questions"), 6),
                }
            )
    return {
        "candidate_summary": str(value.get("candidate_summary") or "候选人有项目经历，可围绕真实职责、技术方案和结果指标追问。").strip()[:240],
        "core_skills": _normalize_list(value.get("core_skills"), 12),
        "projects": projects,
        "risk_points": _normalize_list(value.get("risk_points"), 8),
    }


def build_local_resume_analysis(profile: dict[str, Any]) -> dict[str, Any]:
    skills = _normalize_list(profile.get("skills"), 12)
    keywords = _normalize_list(profile.get("project_keywords"), 12)
    project_text = str(profile.get("project_experience") or "").strip()
    resume_text = str(profile.get("resume_text") or "").strip()
    source_text = "\n".join(part for part in [project_text, resume_text] if part)
    project_name = keywords[0] if keywords else "核心项目"
    highlights = keywords[:4] or skills[:4] or ["项目背景", "技术方案", "个人职责"]
    possible_questions = [
        f"{project_name}当时要解决什么业务问题？",
        "你具体负责了哪一层，和其他角色如何协作？",
        "最终效果如何衡量，有哪些量化指标？",
    ]
    if re.search(r"性能|优化|耗时|加载|渲染", source_text):
        possible_questions.append("性能瓶颈是如何定位和验证优化效果的？")
    risk_points = ["结果指标不够明确", "个人职责边界需要继续确认"]
    if not skills:
        risk_points.append("技能标签较少，需要从项目回答中反推技术深度")
    summary_bits = [
        profile.get("experience_level") or profile.get("years_of_experience") or "有一定经验",
        profile.get("target_role") or "目标岗位",
    ]
    return {
        "candidate_summary": f"{summary_bits[0]}，目标方向为{summary_bits[1]}，可围绕项目职责、技术方案和结果指标深挖。",
        "core_skills": skills or keywords[:8],
        "projects": [
            {
                "name": project_name,
                "role": "候选人简历相关项目参与者",
                "highlights": highlights,
                "possible_questions": possible_questions[:6],
            }
        ],
        "risk_points": risk_points[:8],
    }


def analyze_resume(profile: dict[str, Any]) -> dict[str, Any]:
    providers = _provider_order()
    if not providers:
        return {"analysis": build_local_resume_analysis(profile), "provider": "local", "fallback": True}

    source_text = "\n".join(
        [
            f"目标岗位：{profile.get('target_role') or '未填写'}",
            f"经验水平：{profile.get('experience_level') or profile.get('years_of_experience') or '未填写'}",
            f"技能标签：{profile.get('skills') or '未填写'}",
            f"项目关键词：{profile.get('project_keywords') or '未填写'}",
            f"项目经历：{profile.get('project_experience') or '未填写'}",
            f"简历文本：{profile.get('resume_text') or '未填写'}",
        ]
    )
    chat_messages = [
        {
            "role": "system",
            "content": (
                "你是中文技术面试简历分析助手。请把候选人资料整理成严格 JSON，"
                "只输出 JSON，不要 Markdown。字段必须包含 candidate_summary, core_skills, projects, risk_points。"
            ),
        },
        {
            "role": "user",
            "content": (
                "请提取 1-5 个项目，每个项目包含 name, role, highlights, possible_questions。"
                "possible_questions 要适合电话面试首问或追问。\n\n候选人资料：\n" + source_text[:16000]
            ),
        },
    ]
    errors = []
    for index, provider in enumerate(providers):
        try:
            content = _call_provider_content(provider, chat_messages)
            return {
                "analysis": _normalize_resume_analysis(_extract_json_object(content)),
                "provider": provider.name,
                "fallback": index > 0,
            }
        except (httpx.HTTPError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"{provider.name}: {exc}")
    return {
        "analysis": build_local_resume_analysis(profile),
        "provider": "local",
        "fallback": True,
        "error": " | ".join(errors),
    }


def generate_opening_question(
    *,
    interview: dict[str, Any],
    active_agent: dict[str, Any] | None,
    resume_analysis: dict[str, Any] | None,
    selected_resume_point: dict[str, Any],
) -> dict[str, Any]:
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
        except (httpx.HTTPError, json.JSONDecodeError, KimiFollowupError) as exc:
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
