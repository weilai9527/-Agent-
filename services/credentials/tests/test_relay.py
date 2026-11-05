"""用实际签名的服务请求测试投递进程与本地存证接口。"""
import json
import os
from unittest.mock import patch

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from services.credentials import relay, storage
from services.provenance.app import create_app
from shared.service_db import ServiceDatabase


EVENT = {"school_id": "test-school", "event_id": "d" * 32, "digest": "e" * 64}
TX_HASH = "0x" + "f" * 64


@pytest.fixture
def outbox(tmp_path, monkeypatch):
    db = ServiceDatabase.from_env("credentials", {
        "CREDENTIALS_DB_ENGINE": "sqlite", "CREDENTIALS_SQLITE_PATH": str(tmp_path / "cred.sqlite"),
    })
    storage.initialize(db)
    with db.transaction(write=True) as tx:
        tx.execute("INSERT INTO credential_outbox (school_id,event_id,digest) VALUES (?,?,?)",
                   (EVENT["school_id"], EVENT["event_id"], EVENT["digest"]))

    key = Ed25519PrivateKey.generate()
    monkeypatch.setenv("SERVICE_SIGNING_KEY", key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode())
    pub = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    monkeypatch.setenv("SERVICE_ID", "credentials")
    monkeypatch.setenv("SERVICE_KEY_ID", "fixture-v1")
    monkeypatch.setenv("SERVICE_TRUST_POLICY", json.dumps({"credentials": {
        "schools": [EVENT["school_id"]], "keys": {"fixture-v1": pub},
        "grants": {"provenance": {"system": ["provenance.submit", "provenance.read"]}},
    }}))
    monkeypatch.setenv("PROVENANCE_SERVICE_URL", "http://127.0.0.1")
    return db


def current(db):
    with db.transaction() as tx:
        return tx.one("SELECT * FROM credential_outbox WHERE event_id=?", (EVENT["event_id"],))


def test_ack_loss_and_retry_against_durable_receiver(outbox, monkeypatch, tmp_path):
    inbox = ServiceDatabase.from_env("provenance", {
        "PROVENANCE_DB_ENGINE": "sqlite", "PROVENANCE_SQLITE_PATH": str(tmp_path / "inbox.sqlite"),
    })
    with TestClient(create_app(inbox)) as target:
        submissions = []

        def request(method, url, *, headers, **options):
            with patch.dict(os.environ, {"SERVICE_ID": "provenance"}):
                reply = target.request(method, url, headers=headers, json=options.get("json"))
            if method == "POST":
                assert reply.status_code == 200
                submissions.append(options["json"])
                if len(submissions) == 1:
                    raise httpx.ReadTimeout("simulated lost acknowledgement")
            return reply

        monkeypatch.setattr(relay.httpx, "request", request)
        assert relay.anchor_status(EVENT) == {"status": "unconfirmed"}
        assert relay.deliver_one(outbox, now=10)
        assert current(outbox)["delivered"] == 0
        assert current(outbox)["next_try"] == 12
        assert not relay.deliver_one(outbox, now=11)
        assert relay.deliver_one(outbox, now=12)
        assert not relay.deliver_one(outbox, now=30)
        assert current(outbox)["tries"] == 2
        assert current(outbox)["delivered"] == 1
        assert submissions == [{"event_id": EVENT["event_id"], "digest": EVENT["digest"]}] * 2
        with inbox.transaction() as tx:
            assert tx.one("SELECT COUNT(*) AS n FROM provenance_anchors")["n"] == 1
        assert relay.anchor_status(EVENT) == {"status": "pending"}
        assert relay.anchor_status(dict(EVENT, school_id="wrong-tenant")) == {"status": "unconfirmed"}


@pytest.mark.parametrize("changes", [
    {"digest": "1" * 64}, {"event_id": "1" * 32}, {"tx_hash": "bad"},
    {"network": None}, {"network": "real-maybe"}, {"block_number": True},
    {"block_number": -2}, {"block_number": None}, {"status": "unknown"},
])
def test_confirmation_requires_matching_complete_receipt(outbox, changes, monkeypatch):
    receipt = dict(EVENT, status="confirmed", network="fixture", tx_hash=TX_HASH, block_number=0)
    receipt.update(changes)
    monkeypatch.setattr(relay.httpx, "request", lambda *a, **kw: httpx.Response(200, json=receipt,
                        request=httpx.Request("GET", "http://127.0.0.1")))
    assert relay.anchor_status(EVENT) == {"status": "unconfirmed"}


@pytest.mark.parametrize(("network", "fixture"), [("fixture", True), ("eip155:1337", False)])
def test_receipt_projects_only_public_fields(outbox, monkeypatch, network, fixture):
    private_reply = dict(EVENT, status="confirmed", network=network, tx_hash=TX_HASH,
                         block_number=21, notes="test private metadata")
    monkeypatch.setattr(relay.httpx, "request", lambda *a, **kw: httpx.Response(200, json=private_reply,
                        request=httpx.Request("GET", "http://127.0.0.1")))
    assert relay.anchor_status(EVENT) == {"status": "confirmed", "network": network,
            "tx_hash": TX_HASH, "block_number": 21, "fixture": fixture}


def test_stale_failed_delivery_cannot_undo_a_newer_lease(outbox, monkeypatch):
    def expire_then_reclaim(event, submit):
        assert submit
        if event["tries"] == 0:
            assert not relay.deliver_one(outbox, now=29)
            assert relay.deliver_one(outbox, now=30)
            raise httpx.ReadTimeout("old lease")

    monkeypatch.setattr(relay, "_exchange", expire_then_reclaim)
    assert relay.deliver_one(outbox, now=0)
    assert current(outbox)["delivered"] == 1
    assert current(outbox)["tries"] == 2


def test_bad_origin_fails_closed_and_unrelayed_events_require_no_remote_lookup(outbox, monkeypatch):
    monkeypatch.setenv("PROVENANCE_SERVICE_URL", "http://remote.invalid")
    monkeypatch.setattr(relay.httpx, "request", lambda *a, **kw: pytest.fail("unexpected HTTP call"))
    assert relay.anchor_status(dict(EVENT, delivered=1)) == {"status": "unconfirmed"}
    assert relay.anchor_status(current(outbox)) == {"status": "pending"}
    assert relay.deliver_one(outbox, now=20)
    assert not current(outbox)["delivered"]
    assert current(outbox)["next_try"] == 22


def test_public_verifier_uses_distinct_downstream_identity(outbox, monkeypatch):
    monkeypatch.setenv("SERVICE_ID", "credentials-verifier")
    received = []

    def headers(audience, **identity):
        received.append((audience, identity))
        return {"Authorization": "fixture"}

    monkeypatch.setattr(relay, "service_headers", headers)
    def answer(*args, **kwargs):
        return httpx.Response(200, json=dict(EVENT, status="pending"),
                              request=httpx.Request("GET", "http://127.0.0.1"))
    monkeypatch.setattr(relay.httpx, "request", answer)
    assert relay.anchor_status(EVENT) == {"status": "pending"}
    with pytest.raises(ValueError):
        relay._exchange(EVENT, submit=True)
    assert received == [("provenance", {"actor_id": "credentials-verifier", "actor_type": "system",
                        "school_id": EVENT["school_id"], "scopes": ["provenance.read"]})]


@pytest.mark.parametrize("service", [None, "legacy-gateway", "credentials-verifier"])
def test_untrusted_publishers_cannot_lease_or_retry(outbox, monkeypatch, service):
    if service is None:
        monkeypatch.delenv("SERVICE_ID")
    else:
        monkeypatch.setenv("SERVICE_ID", service)
    monkeypatch.setattr(relay.httpx, "request", lambda *a, **kw: pytest.fail("unexpected HTTP call"))
    with pytest.raises(ValueError):
        relay.deliver_one(outbox, now=50)
    assert current(outbox)["tries"] == 0
    if service != "credentials-verifier":
        assert relay.anchor_status(EVENT) == {"status": "unconfirmed"}


@pytest.mark.parametrize("setting", ["CREDENTIALS_SIGNING_KEYS_JSON", "PROVENANCE_SUBMIT_TOKEN"])
def test_relay_cli_refuses_misplaced_secrets_before_opening_db(monkeypatch, setting):
    monkeypatch.setenv("SERVICE_ID", "credentials")
    monkeypatch.setenv(setting, "fixture")
    monkeypatch.setattr(storage, "database", lambda: pytest.fail("unexpected database access"))
    with pytest.raises(ValueError):
        relay.main()
