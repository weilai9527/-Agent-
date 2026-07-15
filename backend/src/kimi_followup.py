from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, replace
from typing import Any

import httpx

from .env import first_env_value, is_placeholder_value, reload_runtime_ai_env


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
    retries: int | None = None


def _first_env(*names: str) -> str:
    return first_env_value(*names)


def _valid_key(value: str) -> bool:
    return bool(value and not is_placeholder_value(value))


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
        api_key = _first_env("DEEPSEEK_API_KEY")
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
        api_key = _first_env("OPENAI_API_KEY", "OPENAI_REALTIME_API_KEY")
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
        api_key = _first_env("AI_API_KEY")
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
    reload_runtime_ai_env()
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


def get_task_providers(
    order_env: str,
    *,
    max_tokens_env: str,
    timeout_env: str,
    default_max_tokens: int,
    default_timeout: float | None = None,
    retries_env: str | None = None,
    default_retries: int | None = None,
) -> list[FollowupProvider]:
    """Return configured OpenAI-compatible providers with task-specific limits."""
    reload_runtime_ai_env()
    order = os.environ.get(order_env) or os.environ.get(
        "FOLLOWUP_PROVIDER_ORDER", "kimi,deepseek,qwen,openai,custom"
    )
    max_tokens = int(os.environ.get(max_tokens_env, str(default_max_tokens)))
    timeout_override = os.environ.get(timeout_env)
    retries_override = os.environ.get(retries_env) if retries_env else None
    providers: list[FollowupProvider] = []
    seen: set[str] = set()
    for name in order.split(","):
        normalized = name.strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        provider = _provider_config(normalized)
        if not provider or not provider.base_url or not provider.model:
            continue
        providers.append(
            replace(
                provider,
                max_tokens=max_tokens,
                timeout=float(timeout_override) if timeout_override else (default_timeout if default_timeout is not None else provider.timeout),
                retries=int(retries_override) if retries_override is not None else default_retries,
            )
        )
    return providers


def call_provider_json(provider: FollowupProvider, messages: list[dict[str, str]]) -> dict[str, Any]:
    """Call a configured provider and require one JSON object as its response."""
    return _extract_json_object(_call_provider_content(provider, messages, json_mode=True))


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


def _response_error_detail(response: httpx.Response) -> str:
    """Return a bounded provider error without exposing credentials or full payloads."""
    request_id = response.headers.get("x-request-id") or response.headers.get("request-id") or ""
    try:
        body = response.json()
        detail = json.dumps(body, ensure_ascii=False)
    except (ValueError, json.JSONDecodeError):
        detail = response.text
    detail = re.sub(r"\s+", " ", str(detail or "")).strip()[:500]
    parts = [f"HTTP {response.status_code}"]
    if request_id:
        parts.append(f"request_id={request_id}")
    if detail:
        parts.append(detail)
    return " | ".join(parts)


def _call_provider_content(
    provider: FollowupProvider,
    chat_messages: list[dict[str, str]],
    *,
    json_mode: bool = False,
) -> str:
    configured_retries = provider.retries if provider.retries is not None else int(os.environ.get("PROVIDER_HTTP_RETRIES", "2"))
    retries = max(0, min(4, configured_retries))
    trust_env = os.environ.get(f"{provider.name.upper()}_TRUST_ENV", "true").strip().lower() not in {"0", "false", "no"}
    payload = {
        "model": provider.model,
        "messages": chat_messages,
        "temperature": provider.temperature,
        "max_tokens": provider.max_tokens,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    last_error: Exception | None = None

    for attempt in range(retries + 1):
        try:
            with httpx.Client(timeout=provider.timeout, trust_env=trust_env) as client:
                response = client.post(
                    f"{provider.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {provider.api_key}", "Content-Type": "application/json"},
                    json=payload,
                )
            if response.is_error:
                raise httpx.HTTPStatusError(
                    _response_error_detail(response),
                    request=response.request,
                    response=response,
                )
            data = response.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            return str(content or "").strip()
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            last_error = exc
            retryable_status = isinstance(exc, httpx.HTTPStatusError) and (
                exc.response.status_code == 429 or exc.response.status_code >= 500
            )
            if isinstance(exc, httpx.HTTPStatusError) and not retryable_status:
                raise
            if attempt >= retries:
                raise
            time.sleep(0.35 * (2**attempt))

    if last_error:
        raise last_error
    raise KimiFollowupError(f"{provider.name} 请求未完成。")


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


def resume_analysis_source_text(profile: dict[str, Any] | None) -> str:
    """Use the current uploaded resume as the authoritative analysis source."""
    if not profile:
        return ""
    resume_text = str(profile.get("resume_text") or "").strip()
    if resume_text:
        return resume_text
    fallback_fields = [
        profile.get("education_level"),
        profile.get("experience_level") or profile.get("years_of_experience"),
        profile.get("skills"),
        profile.get("project_keywords"),
        profile.get("project_experience"),
    ]
    return "\n".join(str(item).strip() for item in fallback_fields if str(item or "").strip())


def _redact_personal_info(value: str) -> str:
    text = re.sub(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", "[邮箱已隐藏]", value, flags=re.I)
    text = re.sub(r"(?<!\d)(?:\+?86[-\s]?)?1[3-9]\d{9}(?!\d)", "[手机号已隐藏]", text)
    return re.sub(r"\s+", " ", text).strip()


def _normalize_candidate_summary(value: Any) -> str:
    fallback = "候选人有项目经历，可围绕真实职责、技术方案和结果指标继续验证岗位适配度。"
    if isinstance(value, str):
        summary = value
    elif isinstance(value, dict):
        safe_keys = (
            "candidate_overview",
            "personal_overview",
            "major",
            "education_level",
            "experience_level",
            "career_goal",
            "strengths",
        )
        parts = []
        for key in safe_keys:
            raw_item = value.get(key)
            if isinstance(raw_item, str) and raw_item.strip():
                parts.append(raw_item.strip())
            elif isinstance(raw_item, list):
                parts.extend(str(item).strip() for item in raw_item if isinstance(item, (str, int, float)) and str(item).strip())
        summary = "；".join(parts)
    else:
        summary = ""
    return (_redact_personal_info(summary) or fallback)[:240]


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
    directions = []
    raw_directions = value.get("recommended_directions")
    if isinstance(raw_directions, list):
        for item in raw_directions[:4]:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()[:80]
            if not name:
                continue
            try:
                score = int(float(item.get("score") or 0))
            except (TypeError, ValueError):
                score = 0
            directions.append(
                {
                    "name": name,
                    "score": max(1, min(100, score)),
                    "reasons": _normalize_list(item.get("reasons"), 4),
                    "gaps": _normalize_list(item.get("gaps"), 4),
                    "evidence": _normalize_list(item.get("evidence"), 5),
                }
            )
    directions.sort(key=lambda item: (-item["score"], item["name"]))
    return {
        "candidate_summary": _normalize_candidate_summary(value.get("candidate_summary")),
        "core_skills": _normalize_list(value.get("core_skills"), 12),
        "projects": projects,
        "risk_points": _normalize_list(value.get("risk_points"), 8),
        "recommended_directions": directions,
    }


LOCAL_DIRECTION_PROFILES = [
    {
        "name": "信息安全运维工程师",
        "keywords": ["信息安全", "网络安全", "安全防护", "防火墙", "日志分析", "应急响应", "漏洞", "linux", "网络"],
        "weights": {"信息安全": 18, "网络安全": 18, "安全防护": 14, "防火墙": 10, "日志分析": 10, "应急响应": 14, "漏洞": 8, "linux": 5, "网络": 4},
        "gaps": ["补充 Linux 与网络运维实践", "准备安全事件分析或应急响应案例"],
    },
    {
        "name": "渗透测试工程师",
        "keywords": ["渗透测试", "web安全", "漏洞复现", "burp", "sql注入", "xss", "攻防", "ctf"],
        "weights": {"渗透测试": 20, "web安全": 14, "漏洞复现": 16, "burp": 10, "sql注入": 10, "xss": 10, "攻防": 12, "ctf": 10},
        "gaps": ["补充合法授权下的渗透测试项目", "说明漏洞验证、修复与复测闭环"],
    },
    {
        "name": "后端开发工程师",
        "keywords": ["后端", "python", "java", "spring", "fastapi", "django", "接口", "数据库", "mysql", "redis"],
        "weights": {"后端": 18, "python": 5, "java": 7, "spring": 12, "fastapi": 12, "django": 10, "接口": 8, "数据库": 8, "mysql": 7, "redis": 7},
        "gaps": ["补充接口设计和数据库建模证据", "准备性能、异常处理与部署案例"],
    },
    {
        "name": "前端开发工程师",
        "keywords": ["前端", "html", "css", "javascript", "typescript", "react", "vue", "vite", "组件"],
        "weights": {"前端": 18, "html": 6, "css": 6, "javascript": 7, "typescript": 8, "react": 12, "vue": 12, "vite": 7, "组件": 8},
        "gaps": ["补充完整前端项目和个人职责", "准备工程化、性能与兼容性案例"],
    },
    {
        "name": "AI 应用开发工程师",
        "keywords": ["大模型", "智能体", "agent", "llm", "rag", "向量数据库", "模型部署", "提示词工程", "ai聊天机器人"],
        "weights": {"大模型": 18, "智能体": 16, "agent": 14, "llm": 14, "rag": 14, "向量数据库": 12, "模型部署": 10, "提示词工程": 8, "ai聊天机器人": 14},
        "gaps": ["补充大模型应用的真实业务场景", "说明评估方法、模型边界和失败案例"],
    },
    {
        "name": "测试开发工程师",
        "keywords": ["软件测试", "自动化测试", "测试用例", "pytest", "selenium", "接口测试", "质量保障"],
        "weights": {"软件测试": 18, "自动化测试": 16, "测试用例": 12, "pytest": 9, "selenium": 12, "接口测试": 14, "质量保障": 12},
        "gaps": ["补充测试设计与缺陷闭环案例", "准备自动化测试或质量平台实践"],
    },
    {
        "name": "数据分析师",
        "keywords": ["数据分析", "pandas", "numpy", "sql", "tableau", "power bi", "可视化", "统计分析"],
        "weights": {"数据分析": 18, "pandas": 10, "numpy": 8, "sql": 7, "tableau": 12, "power bi": 12, "可视化": 8, "统计分析": 14},
        "gaps": ["补充数据分析问题与业务结论", "说明数据清洗、指标口径和验证过程"],
    },
    {
        "name": "云计算与运维工程师",
        "keywords": ["云计算", "运维", "docker", "kubernetes", "k8s", "部署", "监控", "nginx", "服务器"],
        "weights": {"云计算": 18, "运维": 16, "docker": 12, "kubernetes": 16, "k8s": 16, "部署": 7, "监控": 10, "nginx": 8, "服务器": 6},
        "gaps": ["补充部署、监控和故障处理实践", "准备稳定性与自动化运维案例"],
    },
]


def _contains_direction_keyword(text: str, keyword: str) -> bool:
    lowered = keyword.lower()
    if re.fullmatch(r"[a-z0-9.+# -]+", lowered):
        return bool(re.search(rf"(?<![a-z0-9]){re.escape(lowered)}(?![a-z0-9])", text))
    return lowered in text


def build_local_direction_recommendations(profile: dict[str, Any], source_text: str) -> list[dict[str, Any]]:
    text = source_text.lower()
    results = []
    for direction in LOCAL_DIRECTION_PROFILES:
        hits = [keyword for keyword in direction["keywords"] if _contains_direction_keyword(text, keyword)]
        weights = direction.get("weights") or {}
        evidence_score = sum(int(weights.get(keyword, 6)) for keyword in hits)
        category_project_evidence = bool(hits and re.search(r"项目|负责|实现|开发|部署|优化|比赛|竞赛", source_text.lower()))
        score = min(94, 24 + evidence_score + (5 if category_project_evidence else 0))
        results.append(
            {
                "name": direction["name"],
                "score": score,
                "reasons": [f"简历中体现了{keyword}" for keyword in hits[:3]] or ["当前证据较少，可作为探索方向"],
                "gaps": direction["gaps"][:2],
                "evidence": hits[:5],
                "evidence_score": evidence_score,
            }
        )
    results.sort(key=lambda item: (-item["score"], -item["evidence_score"], item["name"]))
    for item in results:
        item.pop("evidence_score", None)
    return results[:3]


def build_local_resume_analysis(profile: dict[str, Any]) -> dict[str, Any]:
    skills = _normalize_list(profile.get("skills"), 12)
    keywords = _normalize_list(profile.get("project_keywords"), 12)
    source_text = resume_analysis_source_text(profile)
    recommended_directions = build_local_direction_recommendations(profile, source_text)
    if str(profile.get("resume_text") or "").strip():
        evidence = list(dict.fromkeys(item for direction in recommended_directions for item in direction.get("evidence", [])))
        skills = evidence[:12]
        keywords = []
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
    summary_bits = [profile.get("experience_level") or profile.get("years_of_experience") or "有一定经验"]
    direction_summary = "、".join(item["name"] for item in recommended_directions[:2]) or "待探索方向"
    return {
        "candidate_summary": f"{summary_bits[0]}，当前证据更接近{direction_summary}；推荐结果需由学生结合个人意愿确认。",
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
        "recommended_directions": recommended_directions,
    }


def analyze_resume(profile: dict[str, Any]) -> dict[str, Any]:
    providers = get_task_providers(
        "RESUME_ANALYSIS_PROVIDER_ORDER",
        max_tokens_env="RESUME_ANALYSIS_MAX_TOKENS",
        timeout_env="RESUME_ANALYSIS_TIMEOUT",
        default_max_tokens=1400,
    )
    if not providers:
        return {"analysis": build_local_resume_analysis(profile), "provider": "local", "fallback": True}

    source_text = resume_analysis_source_text(profile)
    chat_messages = [
        {
            "role": "system",
            "content": (
                "你是中文技术面试简历分析助手。请把候选人资料整理成严格 JSON，"
                "只输出 JSON，不要 Markdown。字段必须包含 candidate_summary, core_skills, projects, risk_points, recommended_directions。"
                "candidate_summary 必须是 80-160 字的中文字符串，禁止返回对象，禁止包含姓名、年龄、电话、邮箱等个人身份信息。"
            ),
        },
        {
            "role": "user",
            "content": (
                "请提取 1-5 个项目，每个项目包含 name, role, highlights, possible_questions。"
                "possible_questions 要适合电话面试首问或追问。recommended_directions 输出 2-4 个就业方向，"
                "每项包含 name、score(1-100)、reasons、gaps、evidence。岗位名称不受固定列表限制；"
                "必须依据专业、技能和项目证据综合判断，不能因为只出现 AI、参与或学习等单一泛化词就判定岗位。"
                "recommended_directions 必须按 score 从高到低排列。只能分析下面的当前简历正文，不得推测或引用旧目标岗位。"
                "\n\n当前简历正文：\n" + source_text[:16000]
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
