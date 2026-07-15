import httpx

from backend.src.kimi_followup import FollowupProvider, _call_provider_content, _provider_config


def _provider() -> FollowupProvider:
    return FollowupProvider(
        name="qwen",
        api_key="test-key",
        base_url="https://example.test/v1",
        model="test-model",
        timeout=3,
        temperature=0.2,
        max_tokens=32,
    )


def test_provider_transport_errors_are_retried(monkeypatch):
    calls = {"count": 0}
    request = httpx.Request("POST", "https://example.test/v1/chat/completions")

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            calls["count"] += 1
            if calls["count"] < 3:
                raise httpx.ConnectError("temporary TLS failure", request=request)
            return httpx.Response(
                200,
                request=request,
                json={"choices": [{"message": {"content": "OK"}}]},
            )

    monkeypatch.setenv("PROVIDER_HTTP_RETRIES", "2")
    monkeypatch.setattr("backend.src.kimi_followup.httpx.Client", FakeClient)
    monkeypatch.setattr("backend.src.kimi_followup.time.sleep", lambda *_: None)

    assert _call_provider_content(_provider(), [{"role": "user", "content": "test"}]) == "OK"
    assert calls["count"] == 3


def test_provider_auth_error_is_not_retried(monkeypatch):
    calls = {"count": 0}
    request = httpx.Request("POST", "https://example.test/v1/chat/completions")

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            calls["count"] += 1
            return httpx.Response(401, request=request, json={"error": "invalid key"})

    monkeypatch.setenv("PROVIDER_HTTP_RETRIES", "2")
    monkeypatch.setattr("backend.src.kimi_followup.httpx.Client", FakeClient)

    try:
        _call_provider_content(_provider(), [{"role": "user", "content": "test"}])
    except httpx.HTTPStatusError:
        pass
    else:
        raise AssertionError("401 must be surfaced")

    assert calls["count"] == 1


def test_json_provider_requests_structured_output(monkeypatch):
    captured = {}
    request = httpx.Request("POST", "https://example.test/v1/chat/completions")

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            captured.update(kwargs["json"])
            return httpx.Response(
                200,
                request=request,
                json={"choices": [{"message": {"content": '{"ok": true}'}}]},
            )

    monkeypatch.setattr("backend.src.kimi_followup.httpx.Client", FakeClient)
    content = _call_provider_content(
        _provider(),
        [{"role": "user", "content": "return json"}],
        json_mode=True,
    )

    assert content == '{"ok": true}'
    assert captured["response_format"] == {"type": "json_object"}


def test_openai_provider_can_reuse_realtime_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_REALTIME_API_KEY", "test-realtime-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.test/v1")
    monkeypatch.setenv("OPENAI_FOLLOWUP_MODEL", "test-model")

    provider = _provider_config("openai")

    assert provider is not None
    assert provider.api_key == "test-realtime-key"
    assert provider.model == "test-model"
