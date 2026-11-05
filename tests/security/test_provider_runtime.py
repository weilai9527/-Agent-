"""验证各工作负载通过服务验签读取其公开字段，并在控制服务不可用时停止读取。"""
import json
import os
from unittest.mock import patch

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import HTTPException
from fastapi.testclient import TestClient

from services.providers import app as control
from shared import provider_settings as settings
from shared.service_security import service_headers


def signer():
    key = Ed25519PrivateKey.generate()
    private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption()).decode()
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    return private, public


@pytest.fixture
def setup(tmp_path, monkeypatch):
    names = ["ops", "assessment", "media", "career", "profile", "interview", "admin-gateway", "student-gateway", "training"]
    keys = {name: signer() for name in names}
    # 故意扩大签名层权限，用以验证路由的额外授权边界。
    grants = {role: [settings.RUNTIME_SCOPE, "providers.configure", "providers.read", "providers.diagnose"]
              for role in ("admin", "teacher", "student", "system")}
    policy = {name: {"keys": {"test": pair[1]}, "schools": ["platform", "school-a"],
                     "grants": {"providers": grants}} for name, pair in keys.items()}
    owner = {"SERVICE_ID": "providers", "SERVICE_TRUST_POLICY": json.dumps(policy),
             "PROVIDERS_DB_ENGINE": "sqlite", "PROVIDERS_SQLITE_PATH": str(tmp_path / "owner.sqlite"),
             "PROVIDER_PLATFORM_ADMIN_IDS": "operator-1", "OPENAI_API_KEY": "synthetic-owner-secret"}
    def headers(name, scope=settings.RUNTIME_SCOPE, *, role="system", actor=None, school="platform"):
        with patch.dict(os.environ, SERVICE_ID=name, SERVICE_KEY_ID="test", SERVICE_SIGNING_KEY=keys[name][0]):
            return service_headers("providers", actor_id=actor or name, actor_type=role, school_id=school, scopes=[scope])

    monkeypatch.setattr(settings, "_cache", None)
    with patch.dict(os.environ, owner, clear=True), TestClient(control.app) as client:
        write = headers("ops", "providers.configure", role="admin", actor="operator-1")
        yield client, owner, headers, write, keys


def test_machine_endpoint_ignores_browser_claims_and_enforces_caller_identity(setup):
    client, _, headers, write, _ = setup
    endpoint = "/internal/runtime-settings"
    saved = {"reportOpenaiModel": "model-1", "reportTimeout": 20, "qwenOmniVoice": "voice-2"}
    assert client.patch("/settings", headers=write, json=saved).status_code == 200
    assert client.get(endpoint, headers={"X-Service-ID": "assessment"}).status_code == 401
    denied = [
        headers("admin-gateway"), headers("student-gateway"), headers("training"),
        headers("media", role="admin"), headers("assessment", school="school-a"),
        headers("assessment", actor="media"), headers("interview", "providers.read"),
    ]
    for credential in denied:
        assert client.get(endpoint, headers=credential).status_code == 403
    # 推理进程即使意外获得管理动作，也不能成为平台管理员。
    assert client.patch("/settings", headers=headers("assessment", "providers.configure", role="admin",
                                                     actor="operator-1"), json=saved).status_code == 403
    for name, subset in (("assessment", {"reportOpenaiModel": "model-1", "reportTimeout": "20"}),
                         ("media", {"qwenOmniVoice": "voice-2"}),
                         ("profile", {"reportOpenaiModel": "model-1"})):
        data = client.get(endpoint, headers=headers(name))
        assert data.status_code == 200 and data.headers["cache-control"] == "no-store"
        assert data.json() == {"consumer": name, "school_id": "platform", "settings": subset}
        assert "secret" not in data.text and "Configured" not in data.text


def test_consumer_updates_after_cache_expiry_and_outage_fails_closed(setup, monkeypatch):
    client, owner, _, write, keys = setup
    requests = []
    failed = False
    clock = [100]
    monkeypatch.setattr(settings, "monotonic", lambda: clock[0])

    def dispatch(_transport, request):
        requests.append(request.url)
        assert request.url == httpx.URL("https://control.test/internal/runtime-settings")
        if failed:
            raise httpx.ReadTimeout("Synthetic provider control outage")
        with patch.dict(os.environ, owner, clear=True):
            result = client.get(request.url.path, headers=request.headers)
        return httpx.Response(result.status_code, content=result.content, headers=result.headers)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", dispatch)
    def save(model):
        with patch.dict(os.environ, owner, clear=True):
            assert client.patch("/settings", headers=write, json={"reportOpenaiModel": model}).status_code == 200

    consumer = {"SERVICE_ID": "assessment", "SERVICE_KEY_ID": "test", "SERVICE_SIGNING_KEY": keys["assessment"][0],
                "PROVIDERS_SERVICE_URL": "https://control.test", "OPENAI_API_KEY": "only-local-model-secret",
                "OPENAI_FOLLOWUP_MODEL": "stale-local-value"}
    with patch.dict(os.environ, consumer, clear=True):
        assert "PROVIDERS_DB_ENGINE" not in os.environ and "PROVIDERS_SQLITE_PATH" not in os.environ
        with pytest.raises(HTTPException):
            settings.config_store()
        save("version-1")
        assert settings.runtime_settings()["OPENAI_FOLLOWUP_MODEL"] == "version-1"
        assert settings.runtime_settings()["OPENAI_API_KEY"] == "only-local-model-secret"
        save("version-2")
        assert settings.runtime_settings()["OPENAI_FOLLOWUP_MODEL"] == "version-1"
        clock[0] += settings.RUNTIME_TTL
        assert settings.runtime_settings()["OPENAI_FOLLOWUP_MODEL"] == "version-2" and len(requests) == 2
        failed = True
        clock[0] += settings.RUNTIME_TTL
        for _ in range(3):
            with pytest.raises(HTTPException) as unavailable:
                settings.runtime_settings()
            assert unavailable.value.status_code == 503
        assert len(requests) == 3
        failed = False
        clock[0] += 2
        assert settings.runtime_settings()["OPENAI_FOLLOWUP_MODEL"] == "version-2"
        assert len(requests) == 4


@pytest.mark.parametrize("bad", [
    {"consumer": "media", "school_id": "platform", "settings": {}},
    {"consumer": "assessment", "school_id": "student-school", "settings": {}},
    {"consumer": "assessment", "school_id": "platform", "settings": {"reportOpenaiApiKey": "bad"}},
    {"consumer": "assessment", "school_id": "platform", "settings": {"qwenOmniVoice": "unexpected"}},
    {"consumer": "assessment", "school_id": "platform", "settings": {"reportOpenaiBaseUrl": "https://unapproved.test"}},
])
def test_consumer_rejects_unbound_fields_and_unapproved_egress(setup, monkeypatch, bad):
    _, _, _, _, keys = setup
    def dispatch(_transport, _request):
        return httpx.Response(200, json=bad)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", dispatch)
    with patch.dict(os.environ, {"SERVICE_ID": "assessment", "SERVICE_KEY_ID": "test",
                                "SERVICE_SIGNING_KEY": keys["assessment"][0], "PROVIDERS_SERVICE_URL": "https://control.test"},
                    clear=True), pytest.raises(HTTPException) as failure:
        settings.runtime_settings()
    assert failure.value.status_code == 503


def test_missing_control_url_does_not_enable_static_config_or_sql(monkeypatch):
    with patch.dict(os.environ, {"SERVICE_ID": "media", "QWEN_OMNI_REALTIME_MODEL": "local-model"}, clear=True):
        with pytest.raises(HTTPException) as denied:
            settings.runtime_settings()
        assert denied.value.status_code == 503
        monkeypatch.setenv("PROVIDERS_DB_ENGINE", "sqlite")
        with pytest.raises(HTTPException):
            settings.runtime_settings()
        monkeypatch.setenv("PROVIDERS_SERVICE_URL", "http://not-loopback.invalid")
        with pytest.raises(HTTPException):
            settings.runtime_settings()

def test_diagnostics_require_distinct_permission_and_one_bounded_request(setup, monkeypatch):
    client, _, headers, write, _ = setup
    probe = headers("ops", "providers.diagnose", role="admin", actor="operator-1")
    endpoint = "https://api.openai.com/v1/chat/completions"
    calls = []
    def dispatch(_transport, request):
        calls.append(request)
        assert str(request.url) == endpoint
        assert request.headers["Authorization"] == "Bearer synthetic-owner-secret"
        if len(calls) == 2:
            return httpx.Response(307, headers={"Location": "https://unauthorized.test/extract"})
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"status":"ok"}'}}]})
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", dispatch)
    assert client.post("/diagnostics", headers=write).status_code == 403
    assert client.post("/diagnostics", headers=headers("ops", "providers.diagnose", role="admin",
                                                     actor="operator-1", school="school-a")).status_code == 403
    assert not calls
    first = client.post("/diagnostics", headers=probe)
    assert first.status_code == 200 and first.json()["providers"][0]["status"] == "ok"
    second = client.post("/diagnostics", headers=probe)
    assert second.json()["providers"][0]["status"] == "error" and len(calls) == 2
    assert "synthetic-owner-secret" not in first.text + second.text
    monkeypatch.delenv("OPENAI_API_KEY")
    assert client.post("/diagnostics", headers=probe).status_code == 503
    assert len(calls) == 2
