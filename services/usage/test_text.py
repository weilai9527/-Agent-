"""使用临时签名密钥和配额库，通过 ASGI 接口验证文字计量客户端契约。"""
import json
import time
from unittest.mock import patch

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import HTTPException
from fastapi.testclient import TestClient

from services.usage import text
from services.usage.app import app

ACTOR = {"actor_id": "worker-student", "school_id": "school", "actor_type": "student"}
JOB = {"interview_id": "interview", "operation_id": "submission", "purpose": "followup.v1"}


@pytest.fixture
def service(tmp_path, monkeypatch):
    signing = Ed25519PrivateKey.generate()
    policy = {"interview": {"keys": {"tmp": signing.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()},
        "schools": ["school"], "grants": {"usage": {"student": ["usage.reserve", "usage.dispatch", "usage.settle"]}}}}
    monkeypatch.setenv("SERVICE_KEY_ID", "tmp")
    monkeypatch.setenv("SERVICE_SIGNING_KEY", signing.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode())
    monkeypatch.setenv("SERVICE_TRUST_POLICY", json.dumps(policy))
    monkeypatch.setenv("SERVICE_ID", "usage")
    monkeypatch.setenv("USAGE_SERVICE_URL", "https://usage.internal")
    monkeypatch.setenv("USAGE_DB_ENGINE", "sqlite")
    monkeypatch.setenv("USAGE_SQLITE_PATH", str(tmp_path / "usage.sqlite"))
    with TestClient(app) as usage:
        # 服务启动已核对账本身份；以下请求由测试调用方重新签名。
        monkeypatch.setenv("SERVICE_ID", "interview")
        app.state.ledger.configure("school", 1, 1)
        def dispatch(request):
            assert request.url.host == "usage.internal"
            # 生产上调用方与验签服务各有独立进程和身份。
            with patch.dict("os.environ", {"SERVICE_ID": "usage"}):
                res = usage.post(request.url.path, headers={"Authorization": request.headers["Authorization"]},
                                 json=json.loads(request.content))
                return httpx.Response(res.status_code, json=res.json())
        client = httpx.Client
        monkeypatch.setattr(text.httpx, "Client",
                            lambda **kwargs: client(transport=httpx.MockTransport(dispatch), **kwargs))
        yield app.state.ledger


def test_stable_operation_replay_exact_settlement_and_refund(service):
    def reserve():
        return text.reserve_text(ACTOR, **JOB)
    first = reserve()
    assert first.state == "reserved" and first == reserve()
    assert service.quota("school")["text"]["reserved"] == 1
    blocked = text.reserve_text(ACTOR, **{**JOB, "purpose": "evaluation.v1"})
    assert blocked.state == "deferred" and blocked.reason == "quota_exhausted"
    assert blocked.request_id != first.request_id
    for _ in range(2):
        assert text.settle_text(ACTOR, first.reservation_id, actual_units=0)["actual_units"] == 0
    assert reserve().state == "settled" and reserve().actual_units == 0
    second = text.reserve_text(ACTOR, **{**JOB, "operation_id": "next"})
    assert second.state == "reserved"
    for _ in range(2):
        text.settle_text(ACTOR, second.reservation_id, actual_units=1)
    assert service.quota("school")["text"] == {"limit":1, "used":1, "reserved":0, "available":0}
    with pytest.raises(HTTPException) as conflict:
        text.settle_text(ACTOR, second.reservation_id, actual_units=0)
    assert conflict.value.status_code == 409


def test_expired_or_insufficient_lease_does_not_admit(service, monkeypatch):
    now = int(time.time())
    monkeypatch.setattr(service, "_now", lambda tx: now - 295)
    first = text.reserve_text(ACTOR, **JOB)
    assert first.state == "deferred" and first.reason == "insufficient_lease"
    monkeypatch.setattr(service, "_now", lambda tx: now + 5)
    expired = text.reserve_text(ACTOR, **JOB)
    assert expired.state == "deferred" and expired.reason == "reservation_expired"
    assert expired.reservation_id == first.reservation_id


def test_identity_errors_and_missing_configuration(service, monkeypatch):
    first = text.reserve_text(ACTOR, **JOB)
    with pytest.raises(HTTPException) as other:
        text.settle_text({**ACTOR, "actor_id":"intruder"}, first.reservation_id, actual_units=1)
    assert other.value.status_code == 404
    with pytest.raises(HTTPException) as school:
        text.reserve_text({**ACTOR, "school_id":"outside"}, **JOB)
    assert school.value.status_code == 403
    monkeypatch.delenv("USAGE_SERVICE_URL")
    unavailable = text.reserve_text(ACTOR, **JOB)
    assert unavailable.state == "deferred" and unavailable.reason == "usage_unavailable"
    with pytest.raises(HTTPException) as pending:
        text.settle_text(ACTOR, first.reservation_id, actual_units=1)
    assert pending.value.status_code == 503
    assert service.quota("school")["text"]["used"] == 0

def test_dispatch_keeps_capacity_until_confirmed_even_after_ttl(service, monkeypatch):
    now = int(time.time())
    monkeypatch.setattr(service, "_now", lambda tx: now)
    first = text.reserve_text(ACTOR, **JOB)
    assert text.begin_text(ACTOR, first.reservation_id)["state"] == "in_flight"
    now += 1000
    assert text.reserve_text(ACTOR, **JOB).state == "in_flight"
    assert text.begin_text(ACTOR, first.reservation_id)["state"] == "in_flight"
    assert service.quota("school")["text"]["available"] == 0
    assert text.reserve_text(ACTOR, **{**JOB, "purpose": "another"}).reason == "quota_exhausted"
    with pytest.raises(HTTPException) as other:
        text.begin_text({**ACTOR, "actor_id": "other"}, first.reservation_id)
    assert other.value.status_code == 404
    for _ in range(2):
        assert text.settle_text(ACTOR, first.reservation_id, actual_units=1)["actual_units"] == 1
    assert service.quota("school")["text"] == {"limit": 1, "used": 1, "reserved": 0, "available": 0}
    with pytest.raises(HTTPException) as finalized:
        text.begin_text(ACTOR, first.reservation_id)
    assert finalized.value.status_code == 409


def test_begin_cannot_revive_expired_hold(service, monkeypatch):
    now = int(time.time())
    monkeypatch.setattr(service, "_now", lambda tx: now)
    hold = text.reserve_text(ACTOR, **JOB, required_seconds=1, ttl_seconds=3)
    now += 3
    with pytest.raises(HTTPException) as expired:
        text.begin_text(ACTOR, hold.reservation_id)
    assert expired.value.status_code == 409
    assert service.quota("school")["text"]["available"] == 1
