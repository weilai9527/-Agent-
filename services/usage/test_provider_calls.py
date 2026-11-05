"""在离线测试传输中验证真实 HTTP 发送点、重试和备用模型选择。"""
from dataclasses import replace

import httpx
import pytest

from services.assessment.ai_evaluation import _call_with_fallback
from shared.text_provider import FollowupProvider
from services.usage.provider_calls import PendingProviderCall, ProviderAttemptFailed, model_request_id, provider_call_context


FIRST = FollowupProvider("qwen", "private-test-credential", "https://dashscope.aliyuncs.com/compatible-mode/v1",
                         "model-a", 8, 0.2, 32, retries=1)
SECOND = replace(FIRST, model="model-b")
MESSAGES = [{"role": "user", "content": "private interview text"}]
GOOD = {"choices": [{"message": {"content": '{"score": 17}'}}]}


def install_transport(monkeypatch, events):
    calls = []
    client = httpx.Client

    def dispatch(request):
        calls.append(request)
        event = events[len(calls) - 1]
        if isinstance(event, Exception):
            raise event
        status, data = event
        return httpx.Response(status, json=data)

    monkeypatch.setattr("shared.text_provider.httpx.Client",
                        lambda **kw: client(transport=httpx.MockTransport(dispatch), **kw))
    monkeypatch.setattr("shared.text_provider.time.sleep", lambda _: None)
    return calls


def evaluate():
    return _call_with_fallback([FIRST, SECOND], MESSAGES)


@pytest.mark.parametrize(("event", "outcome", "slot"), [
    (httpx.ConnectTimeout("pre-dispatch"), "unsent", (FIRST.model, 1)),
    (httpx.ConnectError("pre-dispatch"), "unsent", (FIRST.model, 1)),
    (httpx.PoolTimeout("pre-dispatch"), "unsent", (FIRST.model, 1)),
    ((429, {"error": "refused"}), "rejected", (FIRST.model, 1)),
    ((403, {"error": "denied"}), "rejected", (SECOND.model, 0)),
    ((200, {"choices": []}), "invalid", (SECOND.model, 0)),
])
def test_each_retry_or_fallback_requires_its_own_wrapper(monkeypatch, event, outcome, slot):
    calls = install_transport(monkeypatch, [event, (200, GOOD)])
    attempts = []
    failures = []

    def wrapper(meta, send):
        # 任务日志仅获得请求的关联标识和供应商元数据。
        assert "private" not in repr(meta)
        assert len(calls) == len(attempts)
        attempts.append((meta.model, meta.attempt))
        try:
            return send()
        except ProviderAttemptFailed as exc:
            failures.append(exc.outcome)
            raise

    with provider_call_context(wrapper):
        assert evaluate()[0] == {"score": 17}
    assert attempts == [(FIRST.model, 0), slot]
    assert failures == [outcome] and len(calls) == 2


@pytest.mark.parametrize("failure", [
    httpx.ReadTimeout("Bearer secret"), httpx.WriteError("partial"),
    httpx.RemoteProtocolError("dropped response"), (408, {}), (500, {}), (503, {}), (307, {}),
])
def test_ambiguous_dispatch_stops_http_retry_and_fallback(monkeypatch, failure):
    calls = install_transport(monkeypatch, [failure])
    failures = []

    def wrapper(meta, send):
        try:
            return send()
        except ProviderAttemptFailed as exc:
            failures.append((exc.outcome, exc.status))
            assert "secret" not in str(exc)
            raise

    with provider_call_context(wrapper), pytest.raises(PendingProviderCall):
        evaluate()
    assert len(calls) == 1
    assert failures == [("unknown", failure[0] if isinstance(failure, tuple) else None)]


def test_job_replay_uses_content_and_persisted_failure_without_http(monkeypatch):
    calls = install_transport(monkeypatch, [(429, {}), (200, GOOD)])
    journal = {}

    def wrapper(meta, send):
        if meta not in journal:
            try:
                journal[meta] = send()
            except ProviderAttemptFailed as exc:
                journal[meta] = (exc.outcome, exc.status)
        value = journal[meta]
        if isinstance(value, tuple):
            raise ProviderAttemptFailed(*value)
        return value

    with provider_call_context(wrapper):
        first = evaluate()
        assert first == evaluate()
    assert {a.attempt for a in journal} == {0, 1}
    assert len({a.request_hash for a in journal}) == 1
    assert len(calls) == 2 and "private" not in repr(journal)


def test_journal_error_never_falls_back_and_context_restores_legacy_retry(monkeypatch):
    calls = install_transport(monkeypatch, [(503, {}), (200, GOOD)])

    def bad_wrapper(meta, send):
        raise ValueError("private ledger detail")

    with provider_call_context(bad_wrapper), pytest.raises(PendingProviderCall, match="journal"):
        evaluate()
    assert not calls
    # 未接入任务计量的调用方保留原有的 HTTP 5xx 重试行为。
    assert evaluate()[0] == {"score": 17} and len(calls) == 2


def test_only_journal_scoped_sends_include_their_own_correlation_id(monkeypatch):
    calls = install_transport(monkeypatch, [(429, {}), (200, GOOD), (200, GOOD), (200, GOOD)])
    slots = ["a" * 64, "b" * 64]

    def wrapper(meta, send):
        with model_request_id(slots[meta.attempt]):
            return send()

    with provider_call_context(wrapper):
        assert evaluate()[0] == {"score": 17}
    # 即使当前上下文中已有其他请求编号，未接入计量的调用也不能继承工作进程的关联头。
    assert evaluate()[0] == {"score": 17}
    with model_request_id("c" * 64):
        assert evaluate()[0] == {"score": 17}
    assert [r.headers.get("X-Client-Request-Id") for r in calls] == [*slots, None, None]
    assert all("Idempotency-Key" not in r.headers for r in calls)
