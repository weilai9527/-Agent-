"""使用模拟供应商验证并发生成和分析缓存的状态转换。"""
from concurrent.futures import ThreadPoolExecutor
import json
from threading import Event
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

from services.profile import store
from services.profile.app import generate_analysis
from shared.service_db import ServiceDatabase


OWNER = ("school-A", "student-1")


@pytest.fixture
def model(tmp_path, monkeypatch):
    from services.profile import model_policy

    db = ServiceDatabase.from_env("profile", {"PROFILE_DB_ENGINE":"sqlite",
                                               "PROFILE_SQLITE_PATH":str(tmp_path/"profiles.sqlite")})
    store.ensure_schema(db)
    store.save(db, OWNER, "form", {"resume_text":"Synthetic private source for A"})
    plan = SimpleNamespace(provider="approved-test", model="test-v1", cache_key="policy-v1")
    def selected(school, task):
        assert task == "profile" and school == OWNER[0]
        return plan
    monkeypatch.setattr(model_policy, "select_model", selected)
    return db, plan, model_policy


def success(plan, profile):
    return {"analysis": {"candidate_summary": "Synthetic summary"}, "provider":plan.provider,
            "model":plan.model, "fallback":False}


def test_cache_is_specific_to_profile_version_and_policy(model, monkeypatch):
    db, plan, module = model
    calls = []
    def generate(p, profile):
        calls.append(p.cache_key)
        return success(p, profile)
    monkeypatch.setattr(module, "analyze_profile", generate)
    first = store.analyze(db, OWNER, False)
    assert first["profile_version"] == 1 and "_policy" not in first
    assert store.analyze(db, OWNER, False) == first
    assert not store.analysis_state(db, OWNER)["stale"]
    plan.cache_key = "policy-v2"
    assert store.analysis_state(db, OWNER)["stale"]
    store.analyze(db, OWNER, False)
    store.analyze(db, OWNER, True)
    # 即使正文相同，模型使用的其他字段也可能发生变化。
    store.save(db, OWNER, "form", {"skills":"new skill"})
    assert store.analysis_state(db, OWNER)["stale"]
    assert store.analyze(db, OWNER, False)["profile_version"] == 2
    assert calls == ["policy-v1", "policy-v2", "policy-v2", "policy-v2"]


def test_slow_provider_releases_lock_and_cannot_overwrite_newer_input(model, monkeypatch):
    db, plan, module = model
    entered, release = Event(), Event()
    def generate(p, profile):
        if profile["resume_text"].endswith("for A"):
            entered.set()
            assert release.wait(8)
        return success(p, profile)
    monkeypatch.setattr(module, "analyze_profile", generate)
    with ThreadPoolExecutor(1) as pool:
        obsolete = pool.submit(store.analyze, db, OWNER, True)
        try:
            assert entered.wait(4)
            with pytest.raises(HTTPException) as duplicate:
                store.analyze(db, OWNER, True)
            assert duplicate.value.status_code == 409
            store.save(db, OWNER, "form", {"resume_text":"new synthetic resume"})
            newer = store.analyze(db, OWNER, False)
            assert newer["profile_version"] == 2
        finally:
            release.set()
        with pytest.raises(HTTPException) as conflict:
            obsolete.result()
        assert conflict.value.status_code == 409
    assert store.analysis_state(db, OWNER)["resume_analysis"] == newer


def test_fallback_and_failure_can_retry_without_returning_provider_secrets(model, monkeypatch):
    db, plan, module = model
    attempts = []
    def generate(p, profile):
        attempts.append(1)
        if len(attempts) == 1:
            return {"analysis":{"candidate_summary":"local synthetic summary"}, "provider":"local",
                    "model":"local", "fallback":True, "error":"secret-provider-response"}
        if len(attempts) == 2:
            raise HTTPException(503, "Unavailable")
        return success(p, profile)
    monkeypatch.setattr(module, "analyze_profile", generate)
    fallback = store.analyze(db, OWNER, False)
    assert fallback["fallback"] and "secret-provider-response" not in str(fallback)
    assert store.analysis_state(db, OWNER)["stale"] is False
    with pytest.raises(HTTPException):
        store.analyze(db, OWNER, False)
    assert store.analysis_state(db, OWNER)["resume_analysis"] == fallback
    assert not store.analyze(db, OWNER, False)["fallback"]
    assert len(attempts) == 3


def test_browsers_cannot_select_provider_or_send_an_arbitrary_endpoint():
    for body in ({"provider":"custom"}, {"base_url":"https://untrusted.invalid"}, {"force":1}):
        with pytest.raises(HTTPException) as exc:
            generate_analysis(body, OWNER, None)
        assert exc.value.status_code == 400


def test_changed_policy_or_mismatched_provider_cannot_write(model, monkeypatch):
    db, plan, module = model
    def generate(p, profile):
        plan.cache_key = "revoked-while-running"
        return success(p, profile)
    monkeypatch.setattr(module, "analyze_profile", generate)
    with pytest.raises(HTTPException) as conflict:
        store.analyze(db, OWNER, False)
    assert conflict.value.status_code == 409
    monkeypatch.setattr(module, "analyze_profile", lambda p, profile: {**success(p, profile), "provider":"unapproved"})
    with pytest.raises(HTTPException) as failed:
        store.analyze(db, OWNER, False)
    assert failed.value.status_code == 502 and store.analysis_state(db, OWNER)["resume_analysis"] is None


def test_expired_claim_is_recoverable_and_invalid_configuration_keeps_history_readable(model, monkeypatch):
    db, plan, module = model
    monkeypatch.setattr(module, "analyze_profile", success)
    with db.transaction(write=True) as tx:
        tx.execute("""INSERT INTO profile_analysis_runs
                      (school_id,actor_id,claim_id,version,policy_key,expires_at) VALUES (?,?,?,?,?,0)""",
                   (*OWNER,"abandoned-claim",1,store.policy_key(plan)))
    previous = store.analyze(db, OWNER, False)
    def invalid(school, task):
        raise HTTPException(503, "Invalid deployment configuration")
    monkeypatch.setattr(module, "select_model", invalid)
    with pytest.raises(HTTPException) as failure:
        store.analyze(db, OWNER, False)
    assert failure.value.status_code == 503
    state = store.analysis_state(db, OWNER)
    assert state["resume_analysis"] == previous and state["stale"]


def test_tenant_model_grant_sends_only_allowed_evidence(tmp_path, monkeypatch):
    from services.profile import model_policy

    db = ServiceDatabase.from_env("profile", {"PROFILE_DB_ENGINE":"sqlite",
                                              "PROFILE_SQLITE_PATH":str(tmp_path/"privacy.sqlite")})
    store.ensure_schema(db)
    monkeypatch.setenv("PROFILE_MODEL_BY_SCHOOL", '{"school-A":"openai"}')
    provider = model_policy.models.FollowupProvider("openai","synthetic-key","https://api.openai.com/v1",
                                                   "synthetic-model",1,0,100)
    monkeypatch.setattr(model_policy.models, "_provider_config", lambda name: provider)
    wire = []
    async def controlled_response(config, url, headers, payload):
        assert config.name == "openai"
        wire.append(str(payload))
        reply = {"candidate_summary":"具有 Python 技能", "recommended_directions":[{"name":"后端开发","score":80}]}
        return httpx.Response(200, request=httpx.Request("POST", url), json={
            "choices":[{"message":{"content":json.dumps(reply)}}]})
    monkeypatch.setattr(model_policy, "_request", controlled_response)
    identity_fields = ["private-canary-294", "synthetic@example.test", "123456789012345678",
                       "private-org-28", "13800001234", "https://private.invalid/secret"]
    source = " ".join(identity_fields + ["Python", "数据库开发"])
    for school in ("school-A","school-B"):
        store.save(db, (school,OWNER[1]), "form", {"resume_text":source})
        result = store.analyze(db, (school,OWNER[1]), False)
        assert result["provider"] == ("openai" if school=="school-A" else "local")
    assert len(wire) == 1 and "Python" in wire[0]
    assert all(value not in wire[0] for value in identity_fields + list(OWNER))


def test_migrated_analysis_remains_cached_locally_until_an_explicit_new_policy(tmp_path, monkeypatch):
    from services.profile import model_policy

    db = ServiceDatabase.from_env("profile", {"PROFILE_DB_ENGINE":"sqlite",
                                              "PROFILE_SQLITE_PATH":str(tmp_path/"migrated.db")})
    store.ensure_schema(db)
    profile = {"resume_text":"测试数据，Python 和 SQL"}
    imported = {"source_hash":store.source_hash(profile), "provider":"historical",
                "analysis":{"candidate_summary":"历史模型分析","_private_model_policy":"internal-metadata"}}
    store.import_legacy(db, *OWNER, profile, resume_analysis=imported)
    monkeypatch.delenv("PROFILE_MODEL_BY_SCHOOL", raising=False)
    old = store.analysis_state(db, OWNER)
    assert not old["stale"] and store.analyze(db, OWNER, False) == old["resume_analysis"]
    assert old["resume_analysis"]["profile_version"] == 1 and "internal-metadata" not in str(old)
    monkeypatch.setattr(model_policy, "select_model", lambda *args: SimpleNamespace(
        provider="custom", cache_key="new-policy", model="new-model"))
    monkeypatch.setattr(model_policy, "analyze_profile", success)
    assert store.analysis_state(db, OWNER)["stale"]
    refreshed = store.analyze(db, OWNER, False)
    assert refreshed["provider"] == "custom" and refreshed["profile_version"] == 1
