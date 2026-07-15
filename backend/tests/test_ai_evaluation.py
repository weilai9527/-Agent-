from dataclasses import replace

import pytest

from backend.src.ai_evaluation import AiEvaluationError, DIMENSIONS, _call_with_fallback, generate_ai_report, normalize_evaluation, normalize_report
from backend.src.kimi_followup import FollowupProvider


def test_normalize_evaluation_clamps_scores_and_lists():
    result = normalize_evaluation(
        {
            "score": 120,
            "strengths": ["有数据", "有取舍"],
            "issues": ["风险不足"],
            "suggestions": "补充回滚方案",
            "dimension_scores": {"technical_depth": -5, "role_fit": 88},
        }
    )
    assert result["score"] == 100
    assert result["dimension_scores"]["technical_depth"] == 1
    assert result["dimension_scores"]["role_fit"] == 88
    assert set(result["dimension_scores"]) == set(DIMENSIONS)
    assert result["strengths"] == "有数据\n有取舍"


def test_normalize_report_rejects_invalid_enums_and_preserves_fallback_shape():
    fallback = {
        "total_score": 72,
        "grade": "C",
        "pass_recommendation": "borderline",
        "ability_radar": {"technical_depth": 70},
        "agent_feedback": [{"agent_name": "技术面试官", "score": 72, "comment": "正常"}],
        "timeline_review": [],
        "summary": "本地摘要",
        "suggestions": "本地建议",
    }
    result = normalize_report(
        {
            "total_score": 81,
            "grade": "S",
            "pass_recommendation": "hire",
            "ability_radar": {"technical_depth": 85},
            "summary": "AI 摘要",
        },
        fallback_report=fallback,
    )
    assert result["total_score"] == 81
    assert result["grade"] == "C"
    assert result["pass_recommendation"] == "borderline"
    assert result["agent_feedback"] == fallback["agent_feedback"]
    assert set(result["ability_radar"]) == set(DIMENSIONS)


def test_ai_provider_fallback_stops_at_configured_attempt_limit(monkeypatch):
    provider = FollowupProvider("first", "key", "https://example.test", "model", 1, 0, 10)
    providers = [provider, replace(provider, name="second"), replace(provider, name="third")]
    calls = []

    def fail(current_provider, _messages):
        calls.append(current_provider.name)
        raise ValueError("provider unavailable")

    monkeypatch.setattr("backend.src.ai_evaluation.call_provider_json", fail)

    with pytest.raises(AiEvaluationError):
        _call_with_fallback(providers, [{"role": "user", "content": "test"}], max_attempts=2)

    assert calls == ["first", "second"]


def test_secondary_ai_provider_is_not_marked_as_local_fallback(monkeypatch):
    provider = FollowupProvider("openai", "key", "https://example.test", "model", 1, 0, 10)
    fallback_report = {
        "total_score": 72,
        "grade": "C",
        "pass_recommendation": "borderline",
        "ability_radar": {name: 72 for name in DIMENSIONS},
        "agent_feedback": [],
        "timeline_review": [],
        "summary": "本地摘要",
        "suggestions": "本地建议",
    }

    monkeypatch.setattr("backend.src.ai_evaluation.get_task_providers", lambda *args, **kwargs: [provider])
    monkeypatch.setattr(
        "backend.src.ai_evaluation._call_with_fallback",
        lambda *args, **kwargs: (
            {
                **fallback_report,
                "total_score": 80,
                "grade": "B",
                "pass_recommendation": "pass",
                "summary": "AI 摘要",
            },
            provider,
            True,
            "qwen: HTTP 401",
        ),
    )

    result = generate_ai_report(
        interview={"target_role": "后端工程师"},
        agents=[],
        messages=[],
        evaluations=[],
        fallback_report=fallback_report,
    )

    assert result["provider"] == "openai"
    assert result["fallback"] is False
    assert result["provider_fallback"] is True
    assert result["generation_error"] == "qwen: HTTP 401"


def test_report_without_repeated_timeline_uses_deterministic_fallback_data(monkeypatch):
    provider = FollowupProvider("qwen", "key", "https://example.test", "model", 1, 0, 10)
    fallback_report = {
        "total_score": 72,
        "grade": "C",
        "pass_recommendation": "borderline",
        "ability_radar": {name: 72 for name in DIMENSIONS},
        "agent_feedback": [{"agent_name": "技术面试官", "score": 72, "comment": "本地汇总"}],
        "timeline_review": [{"message_id": "message-1", "content_preview": "确定性时间线"}],
        "summary": "本地摘要",
        "suggestions": "本地建议",
    }
    raw = {
        "total_score": 82,
        "grade": "B",
        "pass_recommendation": "pass",
        "ability_radar": {name: 80 for name in DIMENSIONS},
        "summary": "AI 摘要",
        "suggestions": ["AI 建议"],
    }

    monkeypatch.setattr(
        "backend.src.ai_evaluation._call_with_fallback",
        lambda *args, **kwargs: (raw, provider, False, None),
    )

    result = generate_ai_report(
        interview={"target_role": "后端工程师"},
        agents=[],
        messages=[],
        evaluations=[],
        fallback_report=fallback_report,
    )

    assert result["agent_feedback"] == fallback_report["agent_feedback"]
    assert result["timeline_review"] == fallback_report["timeline_review"]
