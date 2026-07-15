from __future__ import annotations

import json
import math
import os
import re
from typing import Any

import httpx

from .kimi_followup import call_provider_json, get_task_providers


EVALUATION_PROMPT_VERSION = "evaluation-v2"
REPORT_PROMPT_VERSION = "report-v3"
DIMENSIONS = (
    "technical_accuracy",
    "technical_depth",
    "expression_clarity",
    "business_understanding",
    "tradeoff_reasoning",
    "risk_awareness",
    "result_quantification",
    "role_fit",
)


class AiEvaluationError(RuntimeError):
    pass


def _score(value: Any, default: int = 60) -> int:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    if not math.isfinite(number):
        number = default
    return max(1, min(100, round(number)))


def _text(value: Any, default: str, limit: int = 2000) -> str:
    if isinstance(value, list):
        value = "\n".join(str(item).strip() for item in value if str(item).strip())
    result = str(value or "").strip()
    return (result or default)[:limit]


def normalize_evaluation(value: dict[str, Any]) -> dict[str, Any]:
    raw_dimensions = value.get("dimension_scores")
    if not isinstance(raw_dimensions, dict):
        raw_dimensions = {}
    overall = _score(value.get("score"))
    dimensions = {name: _score(raw_dimensions.get(name), overall) for name in DIMENSIONS}
    return {
        "score": overall,
        "strengths": _text(value.get("strengths"), "回答与问题相关，具备继续复盘的基础。"),
        "issues": _text(value.get("issues"), "回答细节、方案取舍和结果证据仍可补充。"),
        "suggestions": _text(value.get("suggestions"), "补充具体职责、关键决策和量化结果。"),
        "dimension_scores": dimensions,
    }


def normalize_report(value: dict[str, Any], *, fallback_report: dict[str, Any]) -> dict[str, Any]:
    total_score = _score(value.get("total_score"), fallback_report["total_score"])
    recommendation = str(value.get("pass_recommendation") or "").strip()
    if recommendation not in {"strong_pass", "pass", "borderline", "no_pass"}:
        recommendation = fallback_report["pass_recommendation"]
    radar = value.get("ability_radar")
    if not isinstance(radar, dict):
        radar = fallback_report["ability_radar"]
    normalized_radar = {name: _score(radar.get(name), total_score) for name in DIMENSIONS}
    feedback = value.get("agent_feedback")
    if not isinstance(feedback, list):
        feedback = fallback_report["agent_feedback"]
    timeline = value.get("timeline_review")
    if not isinstance(timeline, list):
        timeline = fallback_report["timeline_review"]
    grade = str(value.get("grade") or "").strip().upper()
    if grade not in {"A", "B", "C", "D", "E"}:
        grade = fallback_report["grade"]
    return {
        "total_score": total_score,
        "grade": grade,
        "pass_recommendation": recommendation,
        "ability_radar": normalized_radar,
        "agent_feedback": feedback[:20],
        "timeline_review": timeline[:80],
        "summary": _text(value.get("summary"), fallback_report["summary"], 4000),
        "suggestions": _text(value.get("suggestions"), fallback_report["suggestions"], 4000),
    }


def _compact_messages(messages: list[dict[str, Any]], limit: int = 16) -> str:
    lines = []
    for message in messages[-limit:]:
        speaker = "候选人" if message.get("sender_type") == "candidate" else message.get("agent_name") or "面试官"
        content = re.sub(r"\s+", " ", str(message.get("content") or "")).strip()[:600]
        if content:
            lines.append(f"{speaker}：{content}")
    return "\n".join(lines) or "暂无对话"


def _call_with_fallback(
    providers,
    messages: list[dict[str, str]],
    *,
    max_attempts: int = 2,
) -> tuple[dict[str, Any], Any, bool, str | None]:
    if not providers:
        raise AiEvaluationError("未配置可用的 AI 评分供应商。")
    errors: list[str] = []
    bounded_providers = providers[:max(1, min(5, max_attempts))]
    for index, provider in enumerate(bounded_providers):
        try:
            return call_provider_json(provider, messages), provider, index > 0, " | ".join(errors) or None
        except (httpx.HTTPError, json.JSONDecodeError, ValueError, IndexError, KeyError) as exc:
            errors.append(f"{provider.name}: {exc}")
    raise AiEvaluationError("所有 AI 供应商均调用失败：" + " | ".join(errors))


def generate_ai_evaluation(
    *,
    interview: dict[str, Any],
    agent: dict[str, Any] | None,
    question: str,
    answer: str,
    messages: list[dict[str, Any]],
    resume_analysis: dict[str, Any] | None,
) -> dict[str, Any]:
    system = """你是严谨的中文技术面试评分员。只输出 JSON，不得输出 Markdown。按统一锚点评分：1-30基本未回答或明显错误；31-50相关但缺细节；51-70完整且基本合理；71-90有深入分析、数据、风险和权衡；91-100达到优秀候选人水平。不得根据回答长度虚高评分，也不得臆造候选人未提到的事实。"""
    schema = {"score": 0, "strengths": [""], "issues": [""], "suggestions": [""], "dimension_scores": {name: 0 for name in DIMENSIONS}}
    user = "\n".join(
        [
            f"目标岗位：{interview.get('target_role') or '未填写'}",
            f"难度：{interview.get('difficulty') or '标准'}",
            f"当前面试官：{agent.get('agent_name') if agent else '面试官'}",
            f"当前问题：{question or '未记录'}",
            f"候选人回答：{answer}",
            f"最近对话：\n{_compact_messages(messages, 8)}",
            f"简历摘要：{json.dumps(resume_analysis or {}, ensure_ascii=False)[:2500]}",
            "请给出可复核的具体评价。严格返回以下 JSON 结构，所有分数为 1-100：",
            json.dumps(schema, ensure_ascii=False),
        ]
    )
    raw, provider, fallback, prior_error = _call_with_fallback(
        get_task_providers(
            "EVALUATION_PROVIDER_ORDER",
            max_tokens_env="AI_EVALUATION_MAX_TOKENS",
            timeout_env="AI_EVALUATION_TIMEOUT",
            default_max_tokens=1200,
            default_timeout=10,
            retries_env="AI_EVALUATION_HTTP_RETRIES",
            default_retries=0,
        ),
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        max_attempts=int(os.environ.get("AI_EVALUATION_PROVIDER_ATTEMPTS", "2")),
    )
    return {
        **normalize_evaluation(raw),
        "provider": provider.name,
        "model": provider.model,
        "prompt_version": EVALUATION_PROMPT_VERSION,
        # A secondary AI provider is still an AI result, not a local-rule fallback.
        "fallback": False,
        "provider_fallback": fallback,
        "generation_error": prior_error,
    }


def generate_ai_report(
    *,
    interview: dict[str, Any],
    agents: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    evaluations: list[dict[str, Any]],
    fallback_report: dict[str, Any],
) -> dict[str, Any]:
    system = """你是中文招聘面试报告审核员。只输出一个完整 JSON 对象，不得输出 Markdown。必须以单题评价和真实对话为证据，保持评分一致性，不得虚构经历。摘要不超过 300 个汉字；建议最多 3 条，每条不超过 80 个汉字。不要复述完整对话、时间线或输入数据。"""
    compact_evaluations = [
        {"score": item.get("score"), "strengths": item.get("strengths"), "issues": item.get("issues"), "dimension_scores": item.get("dimension_scores"), "message_content": str(item.get("message_content") or "")[:500]}
        for item in evaluations[:30]
    ]
    # Timeline and interviewer metadata are deterministic data already stored by
    # the application. Asking the model to echo them made long JSON responses
    # hit output limits and become truncated. normalize_report will merge these
    # omitted fields from fallback_report after the model returns.
    schema = {
        "total_score": 0,
        "grade": "A|B|C|D|E",
        "pass_recommendation": "strong_pass|pass|borderline|no_pass",
        "ability_radar": {name: 0 for name in DIMENSIONS},
        "summary": "不超过300字的证据化总结",
        "suggestions": ["最多3条，每条不超过80字"],
    }
    user = "\n".join(
        [
            f"目标岗位：{interview.get('target_role') or '未填写'}",
            f"面试配置：{interview.get('interview_type') or '综合面试'} / {interview.get('difficulty') or '标准'}",
            f"面试官：{json.dumps([{k: a.get(k) for k in ('id', 'agent_name', 'agent_type')} for a in agents], ensure_ascii=False)}",
            f"单题评价：{json.dumps(compact_evaluations, ensure_ascii=False)[:12000]}",
            f"对话：\n{_compact_messages(messages, 30)}",
            "严格返回以下 JSON 结构，所有雷达分为 1-100：",
            json.dumps(schema, ensure_ascii=False)[:12000],
        ]
    )
    raw, provider, fallback, prior_error = _call_with_fallback(
        get_task_providers(
            "REPORT_PROVIDER_ORDER",
            max_tokens_env="AI_REPORT_MAX_TOKENS",
            timeout_env="AI_REPORT_TIMEOUT",
            default_max_tokens=2600,
            default_timeout=60,
            retries_env="AI_REPORT_HTTP_RETRIES",
            default_retries=0,
        ),
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        max_attempts=int(os.environ.get("AI_REPORT_PROVIDER_ATTEMPTS", "2")),
    )
    return {
        **normalize_report(raw, fallback_report=fallback_report),
        "provider": provider.name,
        "model": provider.model,
        "prompt_version": REPORT_PROMPT_VERSION,
        # Switching from the primary provider to another AI provider must not be
        # presented as a local rules fallback in the report UI.
        "fallback": False,
        "provider_fallback": fallback,
        "generation_error": prior_error,
    }
