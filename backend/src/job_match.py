"""简历 ↔ 招聘岗位对比：规则打分 + AI 建议。

规则部分由 shared.recruitment 提供，保证稳定可解释；AI 部分复用已有的
OpenAI 兼容文本供应商，仅用于补充措辞化的建议与面试关注点。
"""

from __future__ import annotations

import json
import os
from typing import Any

from shared.recruitment import score_resume_against_posting

from .kimi_followup import call_provider_json, get_task_providers


JOB_MATCH_PROMPT_VERSION = "job-match-v1"


def _normalize_list(value: Any, limit: int = 5, max_length: int = 120) -> list[str]:
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, (list, tuple)):
        items = [str(item) for item in value]
    else:
        return []
    result: list[str] = []
    for item in items:
        text = " ".join(str(item).split()).strip()
        if not text:
            continue
        result.append(text[:max_length])
        if len(result) >= limit:
            break
    return result


def _ai_analysis(
    *,
    resume_text: str,
    target_role: str,
    posting: dict[str, Any],
    rule_result: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None, str | None]:
    """返回 (AI 结果, provider, model)；不可用时返回 (None, None, None)。"""
    providers = get_task_providers(
        "JOB_MATCH_PROVIDER_ORDER",
        max_tokens_env="JOB_MATCH_MAX_TOKENS",
        timeout_env="JOB_MATCH_TIMEOUT",
        default_max_tokens=1200,
        default_timeout=30,
        retries_env="JOB_MATCH_HTTP_RETRIES",
        default_retries=1,
    )
    if not providers:
        return None, None, None

    system = (
        "你是中文求职顾问。只输出一个 JSON 对象，不要输出 Markdown，也不要编造简历中不存在的经历。"
        "建议必须具体、可执行，并与岗位要求逐条对应；每条不超过 80 个汉字。"
    )
    schema = {
        "summary": "",
        "strengths": [""],
        "gaps": [""],
        "suggestions": [""],
        "interviewFocus": [""],
    }
    user = "\n".join(
        [
            f"目标岗位：{target_role or posting.get('title') or '未填写'}",
            f"招聘岗位：{posting.get('title') or '未提供'} @ {posting.get('company') or '未提供'}",
            f"岗位技能要求：{posting.get('skillsText') or posting.get('skills') or '未提供'}",
            f"岗位职责与要求：\n{(posting.get('requirements') or posting.get('description') or '未提供')[:3000]}",
            f"候选人简历：\n{resume_text[:3000]}",
            "规则引擎的初步结论（可修正但不要自相矛盾）：",
            json.dumps(
                {
                    "matchScore": rule_result.get("matchScore"),
                    "matchedSkills": rule_result.get("matchedSkills"),
                    "missingSkills": rule_result.get("missingSkills"),
                },
                ensure_ascii=False,
            ),
            "请严格返回以下 JSON 结构：",
            json.dumps(schema, ensure_ascii=False),
        ]
    )
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]

    attempts = max(1, min(3, int(os.environ.get("JOB_MATCH_PROVIDER_ATTEMPTS", "2"))))
    for provider in providers[:attempts]:
        try:
            return call_provider_json(provider, messages), provider.name, provider.model
        except Exception:
            continue
    return None, None, None


def build_job_match(
    *,
    resume_text: str,
    resume_skills: str = "",
    target_role: str = "",
    posting: dict[str, Any],
) -> dict[str, Any]:
    """规则打分 + AI 建议，返回可直接落库和展示的对比结果。"""
    result = score_resume_against_posting(
        resume_text=resume_text,
        resume_skills=resume_skills,
        target_role=target_role,
        posting=posting,
    )
    result["promptVersion"] = JOB_MATCH_PROMPT_VERSION

    ai, provider, model = _ai_analysis(
        resume_text=resume_text,
        target_role=target_role,
        posting=posting,
        rule_result=result,
    )
    if not ai:
        result["provider"] = "local"
        result["model"] = "rules-v1"
        result["fallback"] = True
        return result

    summary = " ".join(str(ai.get("summary") or "").split()).strip()
    if summary:
        result["summary"] = summary[:400]
    strengths = _normalize_list(ai.get("strengths"))
    gaps = _normalize_list(ai.get("gaps"))
    suggestions = _normalize_list(ai.get("suggestions"))
    interview_focus = _normalize_list(ai.get("interviewFocus"))
    if strengths:
        result["strengths"] = strengths
    if gaps:
        result["gaps"] = gaps
    if suggestions:
        result["suggestions"] = suggestions
    if interview_focus:
        result["interviewFocus"] = interview_focus

    result["provider"] = provider or "local"
    result["model"] = model or "rules-v1"
    result["fallback"] = False
    return result
