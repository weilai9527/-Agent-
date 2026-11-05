"""用进程内传输验证原生学生网关的 HTTP 和 WebSocket 委派。"""
import asyncio
import json
import socket
import sqlite3

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from services.gateway.native_media import mount_native_media
from services.media import gateway_socket


@pytest.fixture
def media_client(monkeypatch):
    # 即使开发机已有数据库配置，回合快照也只能向面试服务获取。
    def forbid_io(*_args, **_kwargs):
        pytest.fail("Native media gateway attempted a socket or database connection")

    monkeypatch.setattr(socket.socket, "connect", forbid_io)
    monkeypatch.setattr(sqlite3, "connect", forbid_io)
    key = Ed25519PrivateKey.generate()
    config = {"SERVICE_SIGNING_KEY": key.private_bytes(serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode(),
              "SERVICE_ID": "student-gateway", "SERVICE_KEY_ID": "test",
              "LEGACY_SCHOOL_ID": "school", "IDENTITY_SESSION_MODE": "native"}
    for service in ("identity", "interview", "media"):
        config[service.upper() + "_SERVICE_URL"] = "https://" + service + ".test"
    for name, value in config.items():
        monkeypatch.setenv(name, value)
    calls = []
    answers = {"question": "Assigned question", "owner": "student"}

    def peer(request):
        audience = request.url.host.split(".")[0]
        claims = jwt.decode(request.headers["authorization"].split()[1], key.public_key(), algorithms=["EdDSA"],
                            audience=audience, issuer="student-gateway")
        assert "cookie" not in request.headers
        assert claims["school_id"] == "school"
        scope, = claims["scopes"]
        data = json.loads(request.content) if request.content else {}
        calls.append((audience, scope, data))
        if audience == "identity":
            assert scope == "identity.session.resolve" and claims["actor_type"] == "system"
            assert data["token"] == "opaque"
            return httpx.Response(200, json={"actor_type": "student", "school_id": "school", "actor_id": "student",
                                             "scopes": [data["action"]]})
        assert claims["sub"] == "student" and claims["actor_type"] == "student"
        if scope == "interview.media.context":
            assert request.url.path == "/internal/interviews/i/media-context" and request.method == "GET"
            return httpx.Response(200, json={"interview_id": "i", "school_id": "school", "student_id": answers["owner"],
                                             "context": {"greeting": answers["question"]}})
        if scope == "media.context.sync":
            assert data == {"greeting": answers["question"]}
            return httpx.Response(200, json={"status": "running"})
        if scope == "media.speech.synthesize":
            return httpx.Response(200, content=b"voice", headers={"Content-Type": "audio/mpeg"})
        if scope in {"media.video.publish", "media.recording.start", "media.recording.stop", "media.playback.read"}:
            assert audience == "media" and request.method == "POST"
            code = answers.get("clip_status", 200)
            return httpx.Response(code, json={"question_id": "q", "ok": code == 200},
                                  headers={"x-internal-test": "private"})
        if scope == "interview.diagnostics.write":
            return httpx.Response(201, json={"event": {"id": "event1"}})
        if scope == "interview.diagnostics.read":
            assert request.url.params.get("limit") == "1"
            return httpx.Response(200, json={"events": [{"id": "event1"}]})
        raise AssertionError((audience, scope))

    async def async_peer(_transport, request):
        return peer(request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", lambda _transport, req: peer(req))
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", async_peer)
    app = FastAPI()
    mount_native_media(app)
    with TestClient(app) as client:
        client.cookies.set("identity_student_session", "opaque")
        yield client, calls, answers


def test_owner_context_diagnostics_and_unavailable_peer(media_client, monkeypatch):
    client, calls, answers = media_client
    url = "/api/interviews/i/qwen/speech"
    assert client.post(url, json={}, headers={"Origin": "https://untrusted.invalid"}).status_code == 403
    assert not calls
    assert client.post(url, json={"text": "hi", "greeting": "injected"}).content == b"voice"
    assert [(aud, scope) for aud, scope, _ in calls] == [
        ("identity", "identity.session.resolve"), ("interview", "interview.media.context"),
        ("media", "media.context.sync"), ("media", "media.speech.synthesize")]
    calls.clear()
    answers["owner"] = "different-student"
    assert client.post(url, json={}).status_code == 502
    assert not any(aud == "media" for aud, _, _ in calls)
    monkeypatch.delenv("INTERVIEW_SERVICE_URL")
    assert client.post(url, json={}).status_code == 503
    monkeypatch.setenv("INTERVIEW_SERVICE_URL", "https://interview.test")
    monkeypatch.delenv("MEDIA_SERVICE_URL")
    diag = "/api/interviews/i/webrtc-events"
    assert client.post(diag, json={"event_type": "test"}).status_code == 201
    events = client.get(diag + "?limit=1")
    assert events.json()["events"][0]["id"] == "event1"
    assert "no-store" in events.headers["cache-control"]
    assert client.get("/internal/interviews/i/media-context").status_code == 404


def test_video_routes_preserve_scope_status_and_privacy(media_client):
    client, calls, answers = media_client
    base = "/api/interviews/i/media/"
    for path, scope in [("video/token", "media.video.publish"), ("questions/q/recording/start", "media.recording.start"),
                        ("questions/q/recording/stop", "media.recording.stop"), ("questions/q/playback", "media.playback.read")]:
        reply = client.post(base + path)
        assert reply.status_code == 200 and calls[-1][1] == scope
        assert "no-store" in reply.headers["cache-control"] and "x-internal-test" not in reply.headers
    for status in (403, 404, 409, 429, 503):
        answers["clip_status"] = status
        assert client.post(base + "questions/q/playback").status_code == status


def test_socket_revalidates_remote_context_for_control_frames(media_client, monkeypatch):
    client, calls, answers = media_client
    controls = []

    class VoicePeer:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def __aiter__(self):
            await self.stop.wait()
            yield '{"type":"done","private":"stripped"}'

        async def send(self, frame):
            if isinstance(frame, str):
                controls.append(json.loads(frame))
                if controls[-1]["type"] == "stop":
                    self.stop.set()

    def connect(_url, **_kwargs):
        peer = VoicePeer()
        peer.stop = asyncio.Event()
        return peer

    monkeypatch.setattr(gateway_socket, "DirectConnection", connect)
    url = "/ws/interviews/i/qwen/omni-realtime"
    with client.websocket_connect(url, headers={"Origin": "http://testserver"}) as ws:
        ws.send_json({"type": "start", "currentQuestion": "forged"})
        ws.send_bytes(b"pcm")
        ws.send_json({"type": "stop"})
        assert ws.receive_json() == {"type": "done"}
    assert controls == [{"type": "start", "mimeType": "audio/webm", "sampleRate": 48000}, {"type": "stop"}]
    assert sum(scope == "interview.media.context" for _, scope, _ in calls) == 3
    assert sum(scope == "media.context.sync" for _, scope, _ in calls) == 3
    answers["owner"] = "changed"
    with pytest.raises(WebSocketDisconnect), client.websocket_connect(url, headers={"Origin": "http://testserver"}):
        pass
    assert len(controls) == 2
