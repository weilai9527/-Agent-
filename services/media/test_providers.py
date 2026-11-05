"""使用临时签名密钥、独立 SQLite 和测试厂商检查媒体适配器的 HTTP 契约。"""
import json
import os
import tempfile
import time
import unittest
from functools import partial
from pathlib import Path
from unittest.mock import patch

import httpx
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.media import access, providers
from shared.service_security import service_headers


class MediaProviderContract(unittest.TestCase):
    def setUp(self):
        self.temp = self.enterContext(tempfile.TemporaryDirectory())
        self.media_key = Ed25519PrivateKey.generate()
        self.gateway_key = Ed25519PrivateKey.generate()
        pub = self.gateway_key.public_key().public_bytes(serialization.Encoding.PEM,
                                                          serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        trust = {"student-gateway": {"keys": {"gateway-test": pub}, "schools": ["school-1", "school-2"],
                                    "grants": {"media": {"student": [*providers.PATHS, "media.context.sync"]}}}}
        self.enterContext(patch.dict(os.environ, {
            "MEDIA_DB_ENGINE": "sqlite", "MEDIA_SQLITE_PATH": str(Path(self.temp) / "test.sqlite"),
            "MEDIA_PROVIDER_SERVICE_URL": "https://provider.invalid",
            "MEDIA_PROVIDER_ACTIONS": ",".join(providers.PATHS), "SERVICE_ID": "media",
            "SERVICE_KEY_ID": "media-test", "SERVICE_SIGNING_KEY": self.pem(self.media_key),
            "SERVICE_TRUST_POLICY": json.dumps(trust),
        }))
        access.initialize()
        app = FastAPI()
        app.include_router(access.router)
        app.include_router(providers.router)
        self.client = self.enterContext(TestClient(app))
        self.quota = self.enterContext(patch.object(providers, "admit"))
        self.calls = []
        self.custom_response = None
        # 只替换下游传输。出站身份照常签名，由对端独立验签并检查动作授权。
        self.enterContext(patch("shared.service_http.httpx.AsyncClient", partial(
            httpx.AsyncClient, transport=httpx.MockTransport(self.peer))))
        self.sync("running")

    @staticmethod
    def pem(key):
        return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                 serialization.NoEncryption()).decode()

    def headers(self, scope, school="school-1", student="student-1"):
        with patch.dict(os.environ, {"SERVICE_ID": "student-gateway", "SERVICE_KEY_ID": "gateway-test",
                                     "SERVICE_SIGNING_KEY": self.pem(self.gateway_key)}):
            return service_headers("media", actor_id=student, school_id=school,
                                   actor_type="student", scopes=[scope])

    def sync(self, status):
        response = self.client.put("/interviews/int-1/context", headers=self.headers("media.context.sync"),
                                   json={"status": status, "role_id": "r-1", "question_id": "q-1",
                                         "question_order": 2, "prompt": "", "greeting": "", "user_name": "Test"})
        self.assertEqual(response.status_code, 200, response.text)

    def peer(self, request):
        claims = jwt.decode(request.headers["authorization"].split()[1], self.media_key.public_key(),
                            algorithms=["EdDSA"], audience="media_provider", issuer="media")
        body = json.loads(request.content)
        bind = body["binding"]
        self.assertEqual(claims["scopes"], [bind["scope"]])
        self.assertEqual((claims["school_id"], claims["sub"]), (bind["school_id"], bind["actor_id"]))
        self.assertEqual(providers.PATHS[bind["scope"]], request.url.path)
        self.calls.append(body)
        if self.custom_response:
            return self.custom_response(body)
        data = {"binding": bind}
        if bind["scope"] == providers.VIDEO:
            data.update(app_id="app-test", token="test-token", expires_at=body["max_expires_at"], vendor_secret="hidden")
        elif bind["scope"] == providers.PLAY:
            data.update(url="https://provider.invalid/test-only", recording_id="test-rec",
                        expires_at=body["max_expires_at"])
        else:
            data.update(recording_id="test-rec", state="recording" if bind["scope"] == providers.START else "ready")
        return httpx.Response(200, json=data)

    def call(self, path, scope, **args):
        return self.client.post("/interviews/int-1/media/" + path, headers=self.headers(scope, **args))

    def test_video_requires_explicit_configuration_then_admits_and_delegates_one_action(self):
        for config in [{"MEDIA_PROVIDER_ACTIONS": providers.START}, {"MEDIA_PROVIDER_SERVICE_URL": ""},
                       {"MEDIA_PROVIDER_SERVICE_URL": "http://untrusted.invalid"}]:
            with patch.dict(os.environ, config):
                denied = self.call("video/token", providers.VIDEO)
                self.assertEqual(denied.status_code, 503)
                self.assertIn("disabled", denied.text)
        self.quota.assert_not_called()
        response = self.call("video/token", providers.VIDEO)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertNotIn("vendor_secret", response.json())
        self.assertTrue(response.json()["channel_id"].startswith("room_"))
        self.assertLessEqual(response.json()["expires_at"] - time.time(), providers.GRANT_SECONDS)
        self.quota.assert_called_once()

    def test_offline_provider_returns_text_fallback_without_alternative_dispatch(self):
        def offline(_request):
            raise httpx.ConnectError("模拟录像服务离线")

        self.custom_response = offline
        failed = self.call("questions/q-1/recording/start", providers.START)
        self.assertEqual(failed.status_code, 503)
        self.assertEqual(failed.json()["detail"]["fallback"], "text")
        self.assertEqual([row["binding"]["scope"] for row in self.calls], [providers.START])

    def test_wrong_action_tenant_or_student_never_reaches_provider(self):
        self.assertEqual(self.call("video/token", providers.PLAY).status_code, 403)
        self.assertEqual(self.call("video/token", providers.VIDEO, school="school-2").status_code, 404)
        self.assertEqual(self.call("video/token", providers.VIDEO, student="student-2").status_code, 404)
        self.assertEqual(self.calls, [])
        self.quota.assert_not_called()

    def test_only_current_question_may_start_and_cleanup_does_not_charge(self):
        self.assertEqual(self.call("questions/q-2/recording/start", providers.START).status_code, 409)
        with patch.dict(os.environ, {"MEDIA_PROVIDER_ACTIONS": providers.START}):
            self.assertEqual(self.call("questions/q-1/recording/start", providers.START).status_code, 503)
        self.assertEqual(self.call("questions/q-1/recording/start", providers.START).json()["state"], "recording")
        self.sync("completed")
        self.assertEqual(self.call("questions/q-1/recording/start", providers.START).status_code, 409)
        self.assertEqual(self.call("questions/q-1/recording/stop", providers.STOP).json()["state"], "ready")
        self.quota.assert_called_once()
        self.assertEqual(self.call("questions/q-1/playback", providers.PLAY).json()["question_id"], "q-1")
        self.assertEqual(self.quota.call_count, 2)

    def test_mismatched_clip_unsigned_url_long_lived_and_missing_grants_rejected(self):
        for change in [{"binding": {}}, {"url": "http://insecure.invalid/asset"},
                       {"expires_at": int(time.time()) + 10000}, {"expires_at": 1},
                       {"recording_id": None}]:
            with self.subTest(change=change):
                self.custom_response = lambda b: httpx.Response(200, json={
                    "binding": b["binding"], "url": "https://provider.invalid/test", "recording_id": "x",
                    "expires_at": b["max_expires_at"], **change})
                self.assertEqual(self.call("questions/q-1/playback", providers.PLAY).status_code, 502)

    def test_provider_must_find_exact_question_and_provider_details_stay_private(self):
        self.custom_response = lambda body: httpx.Response(404, json={"detail": "secret-vendor-diagnostic"})
        failed = self.call("questions/missing/playback", providers.PLAY)
        self.assertEqual(failed.status_code, 404)
        self.assertNotIn("secret-vendor", failed.text)
        self.assertEqual(self.calls[0]["binding"]["question_id"], "missing")
