"""通过隔离的签名 HTTP 对端验证媒体网关；旧 Cookie、本地数据库和浏览器自报身份均不能授权。"""
import json
import sqlite3

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.media import gateway


@pytest.fixture
def browser(monkeypatch):
    key = Ed25519PrivateKey.generate()
    for k, v in {
        "SERVICE_SIGNING_KEY": key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                 serialization.NoEncryption()).decode(),
        "SERVICE_ID": "student-gateway", "SERVICE_KEY_ID": "test", "LEGACY_SCHOOL_ID": "school",
        "IDENTITY_SERVICE_URL": "https://identity.test", "INTERVIEW_SERVICE_URL": "https://interview.test",
        "MEDIA_SERVICE_URL": "https://media.test",
    }.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(sqlite3, "connect", lambda *a, **kw: pytest.fail("媒体代理尝试读取本地库"))
    calls = []
    context = {"greeting": "本轮原题", "role_id": "role"}

    def peer(request):
        service = request.url.host.split(".")[0]
        claims = jwt.decode(request.headers["authorization"].split()[1], key.public_key(), algorithms=["EdDSA"],
                            issuer="student-gateway", audience=service)
        assert claims["school_id"] == "school" and "cookie" not in request.headers
        scope, = claims["scopes"]
        calls.append(scope)
        body = json.loads(request.content) if request.content else {}
        if service == "identity":
            assert (claims["actor_type"], scope, body["token"]) == ("system", "identity.session.resolve", "opaque")
            return httpx.Response(200, json={"school_id": "school", "actor_id": "student",
                                             "actor_type": "student", "scopes": [body["action"]]})
        assert claims["sub"] == "student" and claims["actor_type"] == "student"
        if service == "interview":
            assert request.method == "GET" and scope == "interview.media.context"
            if request.url.path.endswith("/other/media-context"):
                return httpx.Response(404)
            if request.url.path.endswith("/offline/media-context"):
                raise httpx.ConnectError("offline", request=request)
            assert request.url.path == "/internal/interviews/i/media-context"
            return httpx.Response(200, json={"interview_id": "i", "student_id": "student", "school_id": "school",
                                             "context": context})
        if scope == "media.context.sync":
            assert request.method == "PUT" and body == context
            return httpx.Response(200, json={"status": "running"})
        if scope == "media.speech.synthesize":
            return httpx.Response(200, content=b"audio-bytes", headers={"Content-Type": "audio/mpeg",
                                  "X-Qwen-TTS-Provider": "standard", "X-Private": "hidden"})
        assert scope == "media.rtc.token"
        return httpx.Response(429, json={"detail": {"code": "quota_exhausted", "fallback": "text"}})

    async def async_peer(transport, request):
        return peer(request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", lambda transport, request: peer(request))
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", async_peer)
    app = FastAPI()
    app.include_router(gateway.router)
    with TestClient(app) as client:
        client.cookies.set("interview_session", "old-cookie")
        yield client, calls


def test_proxy_uses_native_cookie_signed_context_and_quota(browser):
    client, calls = browser
    prefix = "/api/interviews/i"
    assert client.post(prefix + "/rtc/token").status_code == 401
    assert not calls
    client.cookies.set("identity_student_session", "opaque")
    assert client.post("/api/interviews/other/rtc/token").status_code == 404
    assert "media.context.sync" not in calls
    calls.clear()
    response = client.post(prefix + "/qwen/speech", json={"text": "本轮原题", "provider": "standard"})
    assert response.status_code == 200 and response.content == b"audio-bytes"
    assert response.headers["X-Qwen-TTS-Provider"] == "standard" and "X-Private" not in response.headers
    denied = client.post(prefix + "/rtc/token", json={"prompt": "伪造"}, headers={"X-School-Id": "other"})
    assert denied.status_code == 429 and denied.json()["detail"]["fallback"] == "text"
    assert calls == ["identity.session.resolve", "interview.media.context", "media.context.sync",
                     "media.speech.synthesize", "identity.session.resolve", "interview.media.context",
                     "media.context.sync", "media.rtc.token"]
    assert client.put(prefix + "/context", json={}).status_code in {404, 405}


def test_context_missing_or_offline_never_reaches_media(browser, monkeypatch):
    client, calls = browser
    client.cookies.set("identity_student_session", "opaque")
    assert client.post("/api/interviews/offline/rtc/token").status_code == 503
    monkeypatch.delenv("INTERVIEW_SERVICE_URL")
    assert client.post("/api/interviews/i/rtc/token").status_code == 503
    assert calls == ["identity.session.resolve", "interview.media.context", "identity.session.resolve"]


def test_snapshot_uses_injected_interview_prompt_builder():
    calls = []

    def build(interview, roles, history, analysis):
        calls.append((roles[0]["id"], history[-1]["id"], analysis))
        return "冻结的角色提示"

    roles = [{"id": "r1", "status": "completed", "agent_name": "前序角色"},
             {"id": "r2", "status": "active", "agent_name": "当前角色"}]
    question = {"id": "q", "sender_type": "agent", "message_type": "question", "content": "本轮原题",
                "agent_id": "r2", "order_index": 4}
    snapshot = gateway.make_snapshot({"status": "running"}, roles, [question],
                                     analysis={"version": 1}, prompt_builder=build)
    assert calls == [("r2", "q", {"version": 1})]
    assert snapshot["prompt"] == "冻结的角色提示" and snapshot["greeting"] == "本轮原题"
    assert snapshot["role_id"] == "r2" and snapshot["question_order"] == 4
