import json

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from services.credentials import signing, verify_file


@pytest.fixture
def proof(monkeypatch):
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(serialization.Encoding.PEM,
                                               serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    key = private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption()).decode()
    monkeypatch.setenv("CREDENTIALS_PUBLIC_KEYS_JSON", json.dumps({"school": {"k": public}}))
    monkeypatch.setenv("CREDENTIALS_SIGNING_KEYS_JSON", json.dumps({"school": {"kid": "k", "private_key": key}}))
    payload = {"school_id": "school", "serial": "a" * 32, "issued_at": "2026-01-01T00:00:00+00:00",
               "generation": 1, "commitment": "b" * 64, "title": "模拟面试训练完成证明"}
    kid, signature = signing.sign_payload("school", payload)
    monkeypatch.delenv("CREDENTIALS_SIGNING_KEYS_JSON")
    return {"format": "teaching-credential/v1", "payload": payload, "kid": kid, "signature": signature}


def encode(proof):
    return json.dumps(proof).encode()


def test_offline_signature_check_requires_independent_issuer_and_key(proof, monkeypatch):
    verified = verify_file.verify_document(encode(proof), "school")
    assert verified == {"signature": "verified", "status": "not_checked", "issuer": "school", "serial": "a" * 32}
    assert verify_file.verify_document(encode(proof), "other")["signature"] == "invalid"
    assert verify_file.verify_document(encode(proof), "school", serial="c" * 32)["signature"] == "invalid"
    monkeypatch.delenv("CREDENTIALS_PUBLIC_KEYS_JSON")
    assert verify_file.verify_document(encode(proof), "school") == {"signature": "unknown", "status": "not_checked"}


@pytest.mark.parametrize("mutation", ["serial", "title", "signature", "school_id", "format", "kid",
                                      "untrusted-key", "embedded-url", "duplicate", "oversize"])
def test_altered_credential_never_triggers_remote_query(proof, mutation, monkeypatch):
    monkeypatch.setattr(verify_file, "current_status", lambda *_: pytest.fail("Queried a tampered document"))
    if mutation == "duplicate":
        raw = encode(proof).replace(b'{"format":', b'{"kid":"duplicate","format":', 1)
    elif mutation == "oversize":
        raw = b" " * verify_file.MAX_BYTES + encode(proof)
    else:
        if mutation in proof["payload"]:
            proof["payload"][mutation] = "c" * 32
        else:
            proof[mutation] = "https://untrusted.invalid"
        raw = encode(proof)
    assert verify_file.verify_document(raw, "school", check_status=True)["signature"] == "invalid"


@pytest.mark.parametrize("outcome,expected", [("valid", "valid"), ("revoked", "revoked"),
                                              ("redirect", "unknown"), ("offline", "unknown"),
                                              ("issuer-mismatch", "unknown"), ("wrong-body", "unknown")])
def test_online_result_is_separate_from_signature(proof, monkeypatch, outcome, expected):
    monkeypatch.setenv("CREDENTIALS_PUBLIC_SERVICE_URL", "https://school.test")
    requests = []
    def handle(_transport, request):
        requests.append(str(request.url))
        assert request.method == "GET" and not request.content and "authorization" not in request.headers
        if outcome == "offline":
            raise httpx.ConnectError("fixture outage")
        if outcome == "redirect":
            return httpx.Response(302, headers={"Location": "https://untrusted.invalid"})
        if outcome == "wrong-body":
            return httpx.Response(200, json={"valid": True})
        claims = proof["payload"]
        return httpx.Response(200, json={"valid": outcome != "revoked", "status":outcome,
                                         "issuer":"wrong" if outcome == "issuer-mismatch" else "school",
                                         "issued_at":claims["issued_at"], "title":claims["title"]})
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", handle)
    result = verify_file.verify_document(encode(proof), "school", check_status=True)
    assert result["signature"] == "verified" and result["status"] == expected
    assert requests == ["https://school.test/verify/" + proof["payload"]["serial"]]
