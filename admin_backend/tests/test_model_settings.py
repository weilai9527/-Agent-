"""使用临时数据库、密钥和进程内 ASGI 检查控制服务管理边界。"""
import json
import os
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from services.providers import app as providers
from shared.provider_selection import get_task_providers
from shared.provider_settings import runtime_settings, save_public_settings
from shared.service_security import service_headers


def test_provider_control_boundaries_and_hot_settings(monkeypatch, tmp_path):
    key = Ed25519PrivateKey.generate()
    signing = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption()).decode()
    public = key.public_key().public_bytes(serialization.Encoding.PEM,
                                           serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    scope = "providers.configure"
    policy = {"management-test": {"keys": {"test": public}, "schools": ["platform"],
                                   "grants": {"providers": {"admin": [scope, "providers.read"]}}}}
    monkeypatch.setenv("PROVIDER_PLATFORM_ADMIN_IDS", "admin")
    monkeypatch.setenv("SERVICE_ID", "providers")
    monkeypatch.setenv("SERVICE_TRUST_POLICY", json.dumps(policy))
    monkeypatch.setenv("PROVIDERS_DB_ENGINE", "sqlite")
    monkeypatch.setenv("PROVIDERS_SQLITE_PATH", str(tmp_path / "provider-settings.sqlite"))
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-private-value")
    monkeypatch.setenv("PROVIDER_ALLOWED_OPENAI_ENDPOINTS", "https://approved.test/v1")
    with patch.dict(os.environ, SERVICE_ID="management-test", SERVICE_SIGNING_KEY=signing, SERVICE_KEY_ID="test"):
        school_root = service_headers("providers", actor_id="other-root", school_id="platform", actor_type="admin", scopes=[scope])
        write = service_headers("providers", actor_id="admin", school_id="platform", actor_type="admin", scopes=[scope])
        read = service_headers("providers", actor_id="admin", school_id="platform", actor_type="admin",
                               scopes=["providers.read"])
    config = {"reportOpenaiBaseUrl": "https://approved.test/v1", "reportOpenaiModel": "model-v2",
              "reportTimeout": 25, "reportProviderOrder": "openai", "reportRetries": 0}
    with TestClient(providers.app) as client:
        assert client.get("/settings").status_code == 401
        assert client.patch("/settings", headers=school_root, json=config).status_code == 403
        assert client.patch("/settings", headers=read, json=config).status_code == 403
        for bad in ({"reportOpenaiApiKey": "fake-secret"}, {"reportTimeout": -2},
                    {"evaluationProviderOrder": "openai,openai"}, {"qwenOmniWorkspaceId": "x.evil.test/"},
                    {"reportKimiBaseUrl": "https://approved.test/v1"}, {"qwenOmniEndpoint": "https://evil.test/rtc"},
                    {"reportOpenaiBaseUrl": "https://approved.test/v1/x"}, {"reportOpenaiModel": "bad\nline"}):
            assert client.patch("/settings", headers=write, json=bad).status_code == 400
        res = client.patch("/settings", headers=write, json=config)
        assert res.status_code == 200, res.text
        assert res.json()["reportOpenaiApiKeyConfigured"] is True
        assert "synthetic-private" not in res.text and "Masked" not in res.text
        assert get_task_providers("REPORT_PROVIDER_ORDER", max_tokens_env="MAX_TEST_TOKENS",
                                  timeout_env="AI_REPORT_TIMEOUT", default_max_tokens=10)[0].model == "model-v2"
        # 两个管理员分别更新不同字段，服务重读后应保留两笔更改。
        with ThreadPoolExecutor(2) as pool:
            list(pool.map(save_public_settings, [{"qwenOmniVoice": "Tina2"}, {"reportOpenaiModel": "model-v3"}]))
        view = client.get("/settings", headers=read).json()
        assert view["reportOpenaiModel"] == "model-v3" and view["qwenOmniVoice"] == "Tina2"
        assert client.post("/diagnostics", headers=read).status_code == 403
    assert runtime_settings()["OPENAI_BASE_URL"] == "https://approved.test/v1"
    assert os.environ.get("OPENAI_FOLLOWUP_MODEL") != "model-v3"


def test_static_legacy_check_needs_explicit_fixture_and_revalidates_identity(tmp_path, monkeypatch):
    from backend.src import provider_diagnostics as old
    from shared import offline_fixture

    monkeypatch.setattr(offline_fixture, "_enabled", False)
    isolated = {"APP_ENV": "test", "DB_ENGINE": "sqlite", "SQLITE_PATH": str(tmp_path / "offline.sqlite"),
                "OPENAI_API_KEY": "test-only", "OPENAI_FOLLOWUP_MODEL": "fixture-model"}
    with patch.dict(os.environ, isolated, clear=True):
        with pytest.raises(HTTPException):
            runtime_settings()
        with pytest.raises(RuntimeError):
            _ = old.app
        offline_fixture.enable_offline_fixture()
        assert runtime_settings()["OPENAI_FOLLOWUP_MODEL"] == "fixture-model"
        assert old.diagnose_report_providers() == [
            {"provider": "openai", "model": "fixture-model", "configured": True, "status": "not_checked"}]
        with pytest.raises(RuntimeError):
            old.diagnose_report_providers(make_request=True)
        os.environ["SERVICE_ID"] = "media"
        with pytest.raises(HTTPException):
            runtime_settings()
        with pytest.raises(RuntimeError):
            _ = old.app
