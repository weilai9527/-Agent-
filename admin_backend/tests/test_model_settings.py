"""Exercise settings writes against a temporary database and env file only."""
import os
from pathlib import Path
import subprocess
import sys
import textwrap


def test_model_settings_persistence_validation_and_permissions(tmp_path):
    env = os.environ.copy()
    env.update({
        "DB_ENGINE": "sqlite", "SQLITE_PATH": str(tmp_path / "models.sqlite"),
        "APP_ENV": "production", "ADMIN_COOKIE_SECURE": "false",
        "MODEL_TEST_ENV": str(tmp_path / "models.env"),
    })
    script = textwrap.dedent('''
        import os
        from pathlib import Path
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        import admin_backend.src.main as main

        for key in list(os.environ):
            if key.startswith(("AI_", "OPENAI_", "QWEN_", "DASHSCOPE_", "REPORT_", "EVALUATION_", "FOLLOWUP_", "KIMI_", "DEEPSEEK_")):
                os.environ.pop(key)
        main.USER_BACKEND_ENV_PATH = Path(os.environ["MODEL_TEST_ENV"])
        main.USER_BACKEND_ENV_PATH.write_text("OPENAI_API_KEY=synthetic-original-key\\nQWEN_API_KEY=synthetic-qwen-key\\nUNRELATED_SETTING=keep\\n", encoding="utf-8")
        actor = {"id": "test-root", "email": main.MASTER_ADMIN_EMAIL, "role": "super_admin", "name": "Test"}
        main.app.dependency_overrides[main.require_admin] = lambda: actor
        client = TestClient(main.app)
        origin = {"Origin": "http://127.0.0.1:5174"}
        def save(body):
            return client.patch("/api/admin/settings", json=body, headers=origin)

        result = save({"reportOpenaiApiKey": "", "reportOpenaiModel": "test-report-model", "reportRetries": 0,
                       "evaluationProviderOrder": "openai,qwen", "evaluationTimeout": 15,
                       "evaluationRetries": 0, "evaluationAttempts": 2, "reportAttempts": 3,
                       "qwenOmniApiKey": "synthetic-omni-secret"})
        assert result.status_code == 200, result.text
        saved = main.read_env_file(main.USER_BACKEND_ENV_PATH)
        assert saved["OPENAI_API_KEY"] == "synthetic-original-key"
        assert saved["UNRELATED_SETTING"] == "keep"
        assert saved["AI_REPORT_HTTP_RETRIES"] == saved["AI_EVALUATION_HTTP_RETRIES"] == "0"
        assert saved["EVALUATION_PROVIDER_ORDER"] == "openai,qwen"
        assert saved["QWEN_OMNI_REALTIME_API_KEY"] == "synthetic-omni-secret"
        settings = result.json()["settings"]
        assert settings["evaluationTimeout"] == 15
        assert settings["evaluationAttempts"] == 2
        assert settings["reportAttempts"] == 3
        assert settings["qwenOmniApiKeyConfigured"] is True
        assert "synthetic-original-key" not in result.text
        assert "synthetic-omni-secret" not in result.text

        # The same environment names are consumed by the scoring provider resolver.
        from backend.src.kimi_followup import get_task_providers
        os.environ.update(saved)
        with patch("backend.src.kimi_followup.reload_runtime_ai_env"):
            providers = get_task_providers("EVALUATION_PROVIDER_ORDER", max_tokens_env="AI_EVALUATION_MAX_TOKENS",
                timeout_env="AI_EVALUATION_TIMEOUT", default_max_tokens=700, retries_env="AI_EVALUATION_HTTP_RETRIES")
        assert [p.name for p in providers] == ["openai", "qwen"]
        assert providers[0].model == "test-report-model"
        assert providers[0].timeout == 15 and providers[0].retries == 0

        additional = {}
        for label in ("Kimi", "Deepseek", "Custom"):
            additional.update({f"report{label}ApiKey": f"synthetic-{label}-private-key",
                               f"report{label}Model": f"test-{label}-model",
                               f"report{label}BaseUrl": f"https://{label.lower()}.example.test/v1"})
        additional["reportProviderOrder"] = "custom,kimi,deepseek,qwen,openai"
        result = save(additional)
        assert result.status_code == 200, result.text
        saved = main.read_env_file(main.USER_BACKEND_ENV_PATH)
        assert saved["KIMI_MODEL"] == "test-Kimi-model"
        assert saved["DEEPSEEK_BASE_URL"] == "https://deepseek.example.test/v1"
        assert saved["AI_API_KEY"] == "synthetic-Custom-private-key"
        for label in ("Kimi", "Deepseek", "Custom"):
            assert result.json()["settings"][f"report{label}ApiKeyConfigured"] is True
            assert f"synthetic-{label}-private-key" not in result.text
        with patch("backend.src.kimi_followup.reload_runtime_ai_env"):
            providers = get_task_providers("REPORT_PROVIDER_ORDER", max_tokens_env="AI_REPORT_MAX_TOKENS",
                timeout_env="AI_REPORT_TIMEOUT", default_max_tokens=700, retries_env="AI_REPORT_HTTP_RETRIES")
        assert [p.name for p in providers] == ["custom", "kimi", "deepseek", "qwen", "openai"]
        assert providers[0].base_url == "https://custom.example.test/v1"
        assert providers[1].model == "test-Kimi-model"

        before = main.USER_BACKEND_ENV_PATH.read_text(encoding="utf-8")
        for invalid in ({"evaluationRetries": -1}, {"evaluationTimeout": 999}, {"evaluationAttempts": 0},
                        {"reportRetries": 1.5}, {"evaluationProviderOrder": "openai,openai"},
                        {"qwenOmniApiKey": "bad\\nINJECTED=value"}, {"openaiRealtimeModel": "bad model"},
                        {"reportCustomBaseUrl": "file:///tmp/model"}, {"reportKimiBaseUrl": "https://user:pass@example.test"},
                        {"reportDeepseekBaseUrl": "https://example.test/?key=secret"},
                        {"reportKimiApiKey": "bad\\nINJECTED=value"}, {"reportCustomModel": "bad model"}):
            assert save(invalid).status_code == 400
            assert main.USER_BACKEND_ENV_PATH.read_text(encoding="utf-8") == before
        assert save({"qwenOmniEndpoint": "https://example.test/realtime"}).status_code == 200
        assert save({"qwenOmniEndpoint": ""}).status_code == 200
        assert main.read_env_file(main.USER_BACKEND_ENV_PATH)["QWEN_OMNI_REALTIME_WEBRTC_ENDPOINT"] == ""
        actor["role"] = "manager"
        actor["email"] = "limited@example.test"
        actor["permissions"] = ["manageModelConfig"]
        before = main.USER_BACKEND_ENV_PATH.read_text(encoding="utf-8")
        assert save({"reportOpenaiModel": "denied-model"}).status_code == 403
        assert client.post("/api/admin/settings/report-providers/test", headers=origin).status_code == 403
        assert main.USER_BACKEND_ENV_PATH.read_text(encoding="utf-8") == before
        print("PASS model settings persistence, runtime resolution, masking, validation and access control")
    ''')
    result = subprocess.run([sys.executable, "-c", script], cwd=Path(__file__).resolve().parents[2], env=env, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
