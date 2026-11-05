"""使用临时媒体库和真实凭证签发逻辑，以测试适配器模拟 RTC 云端结果。"""
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from services.media.rtc_token_service import AppToken, Service
from services.media import access, meter, rtc, rtc_store

SCOPES = ["media.context.sync"] + ["media.rtc." + action for action in
    ("read", "start", "stop", "notify", "heartbeat", "token", "caption")]
ACTOR = {"actor_type": "student", "actor_id": "student1", "school_id": "schoolA"}
CONTEXT = dict(status="running", role_id="tech", question_id="q1", question_order=1,
               prompt="System prompt for tech", greeting="First question", user_name="Test")


@pytest.fixture
def harness(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIA_DB_ENGINE", "sqlite")
    monkeypatch.setenv("MEDIA_SQLITE_PATH", str(tmp_path / "media.sqlite"))
    monkeypatch.setenv("SERVICE_ID", "media")
    monkeypatch.setenv("RTC_APP_ID", "test")
    monkeypatch.setenv("RTC_APP_KEY", "local-test-secret")
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(serialization.Encoding.PEM,
                                               serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    policy = {"gateway": {"keys": {"test": public}, "schools": ["schoolA", "schoolB"],
                          "grants": {"media": {"student": SCOPES}}}}
    monkeypatch.setenv("SERVICE_TRUST_POLICY", json.dumps(policy))
    access.initialize()
    rtc.initialize()
    app = FastAPI()
    app.include_router(access.router)
    app.include_router(rtc.router)
    client = TestClient(app)
    calls = {"admit": [], "start": [], "stop": []}
    monkeypatch.setattr(rtc, "agent_enabled", lambda: True)
    monkeypatch.setattr(rtc, "admit", lambda actor, operation: calls["admit"].append(operation))
    def provider_start(**kwargs):
        calls["start"].append(kwargs)
        return {"request_id": "start"}
    def provider_stop(**kwargs):
        calls["stop"].append(kwargs)
        return {"request_id": "stop"}
    monkeypatch.setattr(rtc, "start_rtc_ai_agent", provider_start)
    monkeypatch.setattr(rtc, "stop_rtc_ai_agent", provider_stop)

    def call(action, path, body=None, method="POST", actor=ACTOR):
        now = int(time.time())
        token = jwt.encode({"iss":"gateway", "aud":"media", "sub":actor["actor_id"],
                            "school_id":actor["school_id"], "actor_type":"student", "scopes":[action],
                            "iat":now, "exp":now+40, "jti":"test"}, private, algorithm="EdDSA",
                           headers={"kid":"test", "typ":"service+jwt"})
        return client.request(method, "/interviews/i/" + path, json=body,
                              headers={"Authorization": "Bearer " + token})

    assert call("media.context.sync", "context", CONTEXT, "PUT").is_success
    return call, calls


def test_token_has_short_audio_only_rights_and_owner(harness, monkeypatch):
    call, _ = harness
    monkeypatch.setenv("RTC_TOKEN_TTL_SECONDS", "86400")
    token = call("media.rtc.token", "rtc/token", {"channel_id": "bad", "user_id": "bad"}).json()
    decoded = AppToken.parse(token["token"])
    assert decoded.service.channel_id == rtc_store.channel_id("schoolA", "student1", "i")
    assert decoded.service.user_id == rtc_store.candidate_user_id("schoolA", "student1", "i")
    assert decoded.service.privilege == Service.ENABLE_AUDIO_PRIVILEGE | Service.ENABLE_PRIVILEGE
    assert token["expires_in"] == 900
    assert call("media.rtc.read", "rtc/token").status_code == 403
    for actor in ({**ACTOR, "school_id":"schoolB"}, {**ACTOR, "actor_id":"student2"}):
        assert call("media.rtc.token", "rtc/token", actor=actor).status_code == 404
    other = {**ACTOR, "school_id":"schoolB"}
    assert call("media.context.sync", "context", CONTEXT, "PUT", actor=other).is_success
    assert call("media.rtc.token", "rtc/token", actor=other).json()["channel_id"] != token["channel_id"]


def test_role_handoff_late_caption_and_stale_stop(harness):
    call, calls = harness
    first = call("media.rtc.start", "rtc/agent/start", {"prompt":"attacker"}).json()
    assert calls["start"][0]["prompt"] == CONTEXT["prompt"]
    assert call("media.rtc.start", "rtc/agent/start").json()["idempotent"]
    assert call("media.rtc.caption", "rtc/caption/validate",
                {"task_id":first["task_id"], "question_id":"q1"}).is_success
    assert call("media.context.sync", "context",
                {**CONTEXT, "question_order":2, "role_id":"hr", "question_id":"q2"}, "PUT").is_success
    second = call("media.rtc.start", "rtc/agent/start").json()
    assert second["task_id"] != first["task_id"]
    assert [c["task_id"] for c in calls["stop"]] == [first["task_id"]]
    for task, question in ((second["task_id"], "q1"), (first["task_id"], "q2")):
        assert call("media.rtc.caption", "rtc/caption/validate",
                    {"task_id":task, "question_id":question}).status_code == 409
    late_stop = call("media.rtc.stop", "rtc/agent/stop", {"expected_task_id":first["task_id"]})
    assert late_stop.json()["rtc_session"]["task_id"] == second["task_id"]
    assert call("media.rtc.notify", "rtc/agent/notify", {"message_id":"q1"}).status_code == 409
    assert calls["admit"] == ["rtc.start", "rtc.start"]


def test_concurrent_start_and_stop_while_provider_in_flight(harness, monkeypatch):
    call, calls = harness
    entered, released = threading.Event(), threading.Event()
    def slow_start(**kwargs):
        entered.set()
        assert released.wait(3)
        return {"task_id":kwargs["task_id"]}
    monkeypatch.setattr(rtc, "start_rtc_ai_agent", slow_start)
    with ThreadPoolExecutor(max_workers=2) as pool:
        launching = pool.submit(call, "media.rtc.start", "rtc/agent/start")
        assert entered.wait(3)
        second = call("media.rtc.start", "rtc/agent/start")
        assert second.json()["idempotent"] and second.json()["status"] == "starting"
        assert call("media.rtc.stop", "rtc/agent/stop").status_code == 202
        assert rtc.reconcile_rtc_sessions_once() == 0
        released.set()
        assert launching.result().json()["status"] == "stopped"
    assert len(calls["stop"]) == 1 and calls["admit"] == ["rtc.start"]


def test_recovers_timeout_and_retries_provider_stop(harness, monkeypatch):
    call, _ = harness
    def timeout(**kwargs):
        raise TimeoutError
    monkeypatch.setattr(rtc, "start_rtc_ai_agent", timeout)
    monkeypatch.setattr(rtc, "get_rtc_ai_agent", lambda **kwargs: {"status":"Running"})
    assert call("media.rtc.start", "rtc/agent/start").status_code == 502
    def current():
        return rtc_store.session({**ACTOR, "interview_id":"i"})
    assert current()["state"] == "starting"
    rtc_store.update(current(), recover_at=0)
    assert rtc.reconcile_rtc_sessions_once() == 1 and current()["state"] == "active"
    monkeypatch.setattr(rtc, "stop_rtc_ai_agent", timeout)
    assert call("media.rtc.stop", "rtc/agent/stop").status_code == 202
    assert current()["state"] == "stop_failed"
    rtc_store.update(current(), recover_at=0)
    monkeypatch.setattr(rtc, "stop_rtc_ai_agent", lambda **kw: {})
    assert rtc.reconcile_rtc_sessions_once() == 1 and current()["state"] == "stopped"


def test_quota_does_not_dispatch_or_hold_claim(harness, monkeypatch):
    call, calls = harness
    def denied(*args):
        raise HTTPException(429, {"code":"quota_exhausted", "fallback":"text"})
    monkeypatch.setattr(rtc, "admit", denied)
    assert call("media.rtc.start", "rtc/agent/start").status_code == 429
    assert not calls["start"]
    assert call("media.rtc.read", "rtc/session", method="GET").json()["rtc_session"]["state"] == "start_failed"
    assert call("media.rtc.token", "rtc/token").status_code == 429


def test_failed_start_and_completed_interview(harness, monkeypatch):
    call, _ = harness
    class Rejected(Exception):
        data = {"statusCode":400}
    def reject(**kwargs):
        raise Rejected()
    monkeypatch.setattr(rtc, "start_rtc_ai_agent", reject)
    assert call("media.rtc.start", "rtc/agent/start").status_code == 502
    assert call("media.rtc.read", "rtc/session", method="GET").json()["rtc_session"]["state"] == "start_failed"
    assert call("media.context.sync", "context", {**CONTEXT, "status":"completed"}, "PUT").is_success
    assert call("media.rtc.start", "rtc/agent/start").status_code == 409
    assert call("media.rtc.token", "rtc/token").status_code == 409
    assert call("media.rtc.stop", "rtc/agent/stop").is_success


def test_no_agent_provider_does_not_charge_start(harness, monkeypatch):
    call, calls = harness
    monkeypatch.setattr(rtc, "agent_enabled", lambda: False)
    res = call("media.rtc.start", "rtc/agent/start")
    assert res.status_code == 503 and res.json()["detail"]["fallback"] == "text"
    assert not calls["admit"] and not calls["start"]


def test_abandoned_start_foreign_worker_recovery_and_heartbeat_expiry(harness, monkeypatch):
    call, calls = harness
    ctx = {**ACTOR, "interview_id":"i"}
    # 模拟本地启动意图已提交，但尚未发出 Start 请求时进程退出。
    row = rtc_store.session(ctx, create=True)
    rtc_store.update(row, state="starting", task_id="lost", role_id="tech", recover_at=0)
    def missing(**kwargs):
        raise RuntimeError("CLIENT_ERROR_TASK_NOT_FOUND")
    monkeypatch.setattr(rtc, "get_rtc_ai_agent", missing)
    assert rtc.reconcile_rtc_sessions_once() == 1
    assert rtc_store.session(ctx)["state"] == "start_failed"

    started = call("media.rtc.start", "rtc/agent/start").json()
    row = rtc_store.session(ctx)
    old_revision = row["revision"]
    assert call("media.rtc.heartbeat", "rtc/session/heartbeat").is_success
    # 恢复进程持有旧版本时，不能忽略已经续期的心跳并停止任务。
    assert row["revision"] == old_revision and rtc.claim_stop(row) is None
    rtc_store.update(rtc_store.session(ctx), recover_at=0)
    assert rtc.reconcile_rtc_sessions_once() == 1
    assert rtc_store.session(ctx)["state"] == "stopped"
    assert calls["stop"][-1]["task_id"] == started["task_id"]


def test_notify_requires_quota_and_provider_cleanup_still_works(harness, monkeypatch):
    call, _ = harness
    assert call("media.rtc.start", "rtc/agent/start").is_success
    notified = []
    monkeypatch.setattr(rtc, "notify_rtc_ai_agent", lambda **kw: notified.append(kw) or {"status": "notified"})

    monkeypatch.setattr(rtc, "admit", meter.admit)
    monkeypatch.delenv("USAGE_SERVICE_URL", raising=False)
    def notify():
        return call("media.rtc.notify", "rtc/agent/notify", {"message_id": "q1"})

    missing = notify()
    assert missing.status_code == 503 and missing.json()["detail"]["fallback"] == "text"
    monkeypatch.setenv("SERVICE_KEY_ID", "media")
    monkeypatch.setenv("SERVICE_SIGNING_KEY", Ed25519PrivateKey.generate().private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode())
    monkeypatch.setenv("USAGE_SERVICE_URL", "https://ledger.invalid")
    keys = []
    def offline(request):
        assert request.url.host == "ledger.invalid"
        keys.append(json.loads(request.content)["request_id"])
        raise httpx.ConnectError("模拟账本离线", request=request)

    client = httpx.Client
    monkeypatch.setattr(meter.httpx, "Client", lambda **opts: client(**opts, transport=httpx.MockTransport(offline)))
    failed = notify()
    assert failed.status_code == 503 and failed.json()["detail"]["fallback"] == "text"
    assert len(keys) == 2 and len(set(keys)) == 1
    assert notified == []
    assert call("media.rtc.stop", "rtc/agent/stop").is_success
