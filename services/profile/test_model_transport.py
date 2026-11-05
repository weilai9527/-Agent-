"""使用模拟传输验证模型的单校授权与 HTTP 限制，测试无需外网。"""
import asyncio
import json
import os
import time

import httpx
import pytest
from fastapi import HTTPException

from services.profile import model_policy
from services.career.scoring import score_and_enhance


@pytest.fixture
def configured(monkeypatch):
    # 本测试验证模型传输边界，只提供模型控制服务会返回的合成公开参数。
    # 推理进程不读取控制库，也不需要为测试开启已退役的环境配置回退。
    monkeypatch.setattr(model_policy.models, "runtime_settings", lambda: {
        key: os.environ[key] for key in ("AI_BASE_URL", "AI_MODEL")
    })
    monkeypatch.delenv("PROVIDERS_DB_ENGINE", raising=False)
    monkeypatch.delenv("PRIVATE_MODEL_CA_FILE", raising=False)
    monkeypatch.setenv("AI_API_KEY", "synthetic-private-key")
    monkeypatch.setenv("AI_BASE_URL", "https://allowed.invalid/v1")
    monkeypatch.setenv("AI_MODEL", "synthetic")
    monkeypatch.setenv("PROVIDER_ALLOWED_CUSTOM_ENDPOINTS", "https://allowed.invalid/v1")
    monkeypatch.setenv("PROFILE_MODEL_BY_SCHOOL", '{"A":"custom"}')
    monkeypatch.setenv("CAREER_MODEL_BY_SCHOOL", '{"B":"custom"}')
    monkeypatch.setenv("CUSTOM_TRUST_ENV", "true")
    monkeypatch.setenv("PROVIDER_HTTP_RETRIES", "4")
    original = httpx.AsyncClient

    def install(handler):
        def local(**options):
            assert options["trust_env"] is False and options["follow_redirects"] is False
            return original(transport=httpx.MockTransport(handler), **options)
        monkeypatch.setattr(httpx, "AsyncClient", local)
    return install


def test_local_is_the_default_even_with_general_credentials(configured, monkeypatch):
    calls = []
    configured(lambda request: calls.append(request))
    monkeypatch.setenv("JOB_MATCH_PROVIDER_ORDER", "custom")
    monkeypatch.setenv("RESUME_ANALYSIS_PROVIDER_ORDER", "custom")
    monkeypatch.setenv("FOLLOWUP_PROVIDER_ORDER", "custom")
    monkeypatch.delenv("PROFILE_MODEL_BY_SCHOOL")
    profile = {"nickname": "不能出站", "resume_text": "数据库设计和 Python 开发"}
    result = model_policy.analyze_profile(model_policy.select_model("B", "profile"), profile)
    assert result["provider"] == "local" and not result["fallback"]
    assert score_and_enhance("A", resume_text=profile["resume_text"], posting={"title":"Python"})["provider"] == "local"
    assert calls == []


@pytest.mark.parametrize("response", ["redirect", "oversize", "gzip", "malformed", "provider_error"])
def test_private_models_reject_responses_without_retry_or_sensitive_error(configured, response):
    seen = []
    def handle(request):
        seen.append(str(request.url))
        assert request.headers["authorization"] == "Bearer synthetic-private-key"
        if response == "redirect":
            return httpx.Response(307, headers={"location":"https://elsewhere.invalid/v1"})
        if response == "oversize":
            return httpx.Response(200, content=b"x" * (129*1024))
        if response == "gzip":
            import gzip
            return httpx.Response(200, headers={"content-encoding":"gzip"}, content=gzip.compress(b"{}"))
        if response == "malformed":
            return httpx.Response(200, json={"choices": [{"message": None}]})
        return httpx.Response(500, text="SECRET-debug-detail")
    configured(handle)
    plan = model_policy.select_model("A", "profile")
    with pytest.raises(model_policy.ModelUnavailable) as error:
        plan.generate([{"role":"user", "content":"synthetic"}])
    assert "SECRET" not in str(error.value)
    assert seen == ["https://allowed.invalid/v1/chat/completions"]


def test_single_attempt_has_a_total_deadline(configured, monkeypatch):
    seen = []
    async def slow(_):
        seen.append(1)
        await asyncio.sleep(10)
    configured(slow)
    monkeypatch.setenv("PRIVATE_MODEL_TIMEOUT_SECONDS", "0.1")
    start = time.monotonic()
    with pytest.raises(model_policy.ModelUnavailable):
        model_policy.select_model("A","profile").generate([])
    assert time.monotonic() - start < 1 and seen == [1]


def test_only_an_explicit_grant_can_select_an_allowed_endpoint(configured, monkeypatch):
    seen = []
    configured(lambda request: seen.append(request))
    monkeypatch.setenv("AI_BASE_URL", "https://unapproved.invalid/v1")
    with pytest.raises(HTTPException) as error:
        model_policy.select_model("A", "profile")
    assert error.value.status_code == 503 and seen == []
    assert model_policy.select_model("a","profile").provider == "local"
    monkeypatch.setenv("PROFILE_MODEL_BY_SCHOOL", '{"*":"openai"}')
    with pytest.raises(HTTPException):
        model_policy.select_model("A", "profile")


def test_scoring_and_resume_keep_private_task_contract_and_minimize_actual_http_payload(configured, monkeypatch):
    monkeypatch.setenv("LEGACY_SCHOOL_ID","A")
    monkeypatch.setenv("CAREER_MODEL_BY_SCHOOL",'{"A":"custom"}')
    private = "张某某 12345678 fake-actor fake-school 13512345678 example@example.test"
    wire = []

    def handle(request):
        assert request.url.host == "allowed.invalid"
        data = json.loads(request.content)
        wire.append(json.dumps(data, ensure_ascii=False))
        reply = ({"candidate_summary":"Python 工程实践","core_skills":["Python"],
                  "recommended_directions":[{"name":"后端开发","score":80}]}
                 if len(wire)==1 else {"suggestions":["补充数据库事务测试。"],"matchScore":-100})
        return httpx.Response(200,json={"choices":[{"message":{"content":json.dumps(reply)}}]})

    configured(handle)
    result = model_policy.analyze_profile(model_policy.legacy_model("profile"),
                                          {"nickname":private, "resume_text":private + "实现 Python 项目并测试数据库。"})
    args = {"resume_text":private+"开发 Python", "posting":{"title":private,"requirements":private+" Python SQL"}}
    match = score_and_enhance("A", resume_skills="", target_role="", plan=model_policy.legacy_model("career"), **args)
    assert result["provider"] == match["provider"] == "custom"
    assert result["analysis"]["recommended_directions"][0]["name"] == "后端开发"
    assert match["suggestions"] == ["补充数据库事务测试。"]
    assert 0 <= match["matchScore"] <= 100 and not match["fallback"]
    assert len(wire) == 2 and all("Python" in body for body in wire)
    assert not any(value in body for body in wire for value in private.split())


def test_config_store_failure_is_safe_and_does_not_affect_unauthorized_tenants(configured, monkeypatch):
    import sqlite3

    def unavailable(_):
        raise sqlite3.OperationalError("sensitive-database-detail")
    monkeypatch.setattr(model_policy.models, "_provider_config", unavailable)
    with pytest.raises(HTTPException) as err:
        model_policy.select_model("A", "profile")
    assert err.value.status_code == 503 and "sensitive-database" not in err.value.detail
    assert model_policy.select_model("B", "profile").provider == "local"
