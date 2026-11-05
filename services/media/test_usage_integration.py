"""两个独立进程以管道传输 HTTP 请求；媒体服务自行签名，用量服务实际验签并写入独立账本。"""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

import httpx
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient


def usage_peer():
    from services.usage.app import app

    with TestClient(app) as client:
        for line in sys.stdin:
            method, path, headers, body = json.loads(line)
            response = client.request(method, path, headers=headers, content=body)
            print(json.dumps([response.status_code, response.json()]), flush=True)


def test_meter_across_real_service_boundaries(tmp_path, monkeypatch):
    from services.media.app import app
    from services.media import meter
    from services.media.rtc_token_service import AppToken, Service

    keys = {name: Ed25519PrivateKey.generate() for name in ("gateway", "media")}
    policy = {}
    grants = {"gateway": {"media": {"student": ["media.context.sync", "media.rtc.token"]},
                          "usage": {"admin": ["usage.configure", "usage.read"]}},
              "media": {"usage": {"student": ["usage.reserve", "usage.settle"]}}}
    for name, key in keys.items():
        public = key.public_key().public_bytes(serialization.Encoding.PEM,
                                               serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        policy[name] = {"schools": ["school", "other"], "keys": {"test": public}, "grants": grants[name]}

    def credential(audience, scope, who="student", school="school", role="student"):
        now = int(time.time())
        token = jwt.encode({"iss": "gateway", "aud": audience, "sub": who, "school_id": school,
                            "actor_type": role, "scopes": [scope], "iat": now, "exp": now + 40,
                            "jti": uuid4().hex}, keys["gateway"], algorithm="EdDSA",
                           headers={"kid": "test", "typ": "service+jwt"})
        return {"Authorization": "Bearer " + token}

    monkeypatch.setenv("SERVICE_ID", "media")
    monkeypatch.setenv("SERVICE_KEY_ID", "test")
    monkeypatch.setenv("SERVICE_SIGNING_KEY", keys["media"].private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode())
    monkeypatch.setenv("SERVICE_TRUST_POLICY", json.dumps(policy))
    monkeypatch.setenv("MEDIA_DB_ENGINE", "sqlite")
    monkeypatch.setenv("MEDIA_SQLITE_PATH", str(tmp_path / "media.db"))
    monkeypatch.setenv("RTC_APP_ID", "test-app")
    monkeypatch.setenv("RTC_APP_KEY", "test-key")
    monkeypatch.setenv("USAGE_SERVICE_URL", "https://usage.test")

    root = Path(__file__).resolve().parents[2]
    child_env = {"PATH": os.defpath, "PYTHONPATH": str(root), "SERVICE_ID": "usage",
                 "USAGE_DB_ENGINE": "sqlite", "USAGE_SQLITE_PATH": str(tmp_path / "usage.db"),
                 "SERVICE_TRUST_POLICY": json.dumps(policy)}
    peer = subprocess.Popen([sys.executable, str(Path(__file__).resolve())], cwd=root, env=child_env,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        def send(method, path, headers, body):
            peer.stdin.write(json.dumps([method, path, dict(headers), body]) + "\n")
            peer.stdin.flush()
            return json.loads(peer.stdout.readline())

        def transport(request):
            assert request.url.host == "usage.test"
            code, data = send(request.method, request.url.path, request.headers, request.content.decode())
            return httpx.Response(code, json=data)

        base = "/internal/usage/quota"
        headers = credential("usage", "usage.configure", "manager", role="admin")
        code, quota = send("PUT", base, {**headers, "Content-Type": "application/json"},
                           json.dumps({"text": 2, "media": 1}))
        assert code == 200, quota
        original = httpx.Client
        monkeypatch.setattr(meter.httpx, "Client", lambda **kw: original(transport=httpx.MockTransport(transport), **kw))
        with TestClient(app) as media:
            ctx = {"status": "running", "question_order": 1, "question_id": "q", "role_id": "r",
                   "greeting": "question", "prompt": "prompt", "user_name": "student"}
            assert media.put("/interviews/i/context", headers=credential("media", "media.context.sync"),
                             json=ctx).status_code == 200
            token_url = "/interviews/i/rtc/token"
            for mismatch in ({"school": "other"}, {"who": "intruder"}):
                assert media.post(token_url, headers=credential("media", "media.rtc.token", **mismatch)).status_code == 404
            token = media.post(token_url, headers=credential("media", "media.rtc.token"))
            assert token.status_code == 200, token.text
            result = token.json()
            parsed = AppToken.parse(result["token"]).service
            assert parsed.channel_id == result["channel_id"] and parsed.user_id == result["user_id"]
            assert parsed.privilege == Service.ENABLE_PRIVILEGE | Service.ENABLE_AUDIO_PRIVILEGE
            denied = media.post(token_url, headers=credential("media", "media.rtc.token"))
            assert denied.status_code == 429 and denied.json()["detail"]["fallback"] == "text"
        code, quota = send("GET", base, credential("usage", "usage.read", "manager", role="admin"), "")
        assert code == 200
        assert quota["media"] == {"limit": 1, "used": 1, "reserved": 0, "available": 0}
        assert quota["text"]["available"] == 2
    finally:
        peer.stdin.close()
        try:
            peer.wait(timeout=10)
        except subprocess.TimeoutExpired:
            peer.kill()
            peer.wait()
        peer.stdout.close()
    assert peer.returncode == 0


if __name__ == "__main__":
    usage_peer()
