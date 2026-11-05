"""经 ASGI 验证接收方线上使用的服务鉴权逻辑。"""
import base64
import json
import time
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from shared.service_security import require_service, service_headers


def encode_segment(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def token_for(key, claims, *, kid="rotation-1", algorithm="EdDSA", typ="service+jwt"):
    # 独立构造并签名恶意声明，即使官方客户端拒绝生成，接收端也须自行拒绝。
    header = {"alg": algorithm, "kid": kid, "typ": typ}
    body = ".".join(encode_segment(json.dumps(obj).encode()) for obj in (header, claims))
    signature = encode_segment(key.sign(body.encode("ascii")))
    return {"Authorization": f"Bearer {body}.{signature}"}


@pytest.fixture
def boundary(monkeypatch):
    signer = Ed25519PrivateKey.generate()
    public = signer.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()
    policy = {"gateway": {
        "keys": {"rotation-1": public},
        "schools": ["school-a"],
        "grants": {"reports": {"teacher": ["report.read"]}},
    }}
    monkeypatch.setenv("SERVICE_TRUST_POLICY", json.dumps(policy))
    monkeypatch.setenv("SERVICE_ID", "reports")
    app = FastAPI()

    @app.get("/private")
    def private(actor=Depends(require_service("reports", "report.read"))):
        return actor

    now = int(time.time())
    claims = {
        "iss": "gateway", "aud": "reports", "sub": "teacher-1",
        "school_id": "school-a", "actor_type": "teacher", "scopes": ["report.read"],
        "iat": now, "exp": now + 30, "jti": str(uuid4()),
    }
    return TestClient(app), signer, claims


def test_signed_actor_survives_transport_and_forged_proxy_headers_do_not(boundary, monkeypatch):
    client, signer, _ = boundary
    monkeypatch.setenv("SERVICE_ID", "gateway")
    monkeypatch.setenv("SERVICE_KEY_ID", "rotation-1")
    monkeypatch.setenv("SERVICE_SIGNING_KEY", signer.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode())
    headers = service_headers("reports", actor_id="teacher-1", actor_type="teacher",
                              school_id="school-a", scopes=["report.read"])
    monkeypatch.setenv("SERVICE_ID", "reports")
    spoofed = {"X-School-ID": "school-b", "X-Actor-ID": "other", "X-Actor-Type": "admin"}
    assert client.get("/private", headers=spoofed).status_code in (401, 403)
    result = client.get("/private", headers={**headers, **spoofed})
    assert result.status_code == 200
    actor = result.json()
    assert (actor["actor_id"], actor["school_id"], actor["actor_type"], actor["caller"]) == (
        "teacher-1", "school-a", "teacher", "gateway",
    )


@pytest.mark.parametrize("changes", [
    {"school_id": "school-b"}, {"actor_type": "admin"}, {"iss": "impostor"},
    {"aud": "media"}, {"sub": ""}, {"school_id": ""},
    {"scopes": []}, {"scopes": ["report.read", "credential.approve"]},
    {"scopes": "report.read"}, {"exp": 1},
])
def test_receiver_rejects_out_of_policy_even_with_valid_signature(boundary, changes):
    client, signer, claims = boundary
    # 先使用独立签发的合法令牌建立对照，再逐个篡改声明。
    assert client.get("/private", headers=token_for(signer, claims)).status_code == 200
    response = client.get("/private", headers=token_for(signer, {**claims, **changes}))
    assert response.status_code in (401, 403)


def test_key_identity_and_token_type_are_not_chosen_by_the_client(boundary):
    client, signer, claims = boundary
    for headers in (
        token_for(Ed25519PrivateKey.generate(), claims),
        token_for(signer, claims, kid="retired-key"),
        token_for(signer, claims, algorithm="HS256"),
        token_for(signer, claims, typ="JWT"),
        {"Authorization": "Bearer invalid.jwt"},
    ):
        assert client.get("/private", headers=headers).status_code in (401, 403)


def test_receiver_cannot_verify_for_another_deployment(boundary, monkeypatch):
    client, signer, claims = boundary
    monkeypatch.setenv("SERVICE_ID", "media")
    assert client.get("/private", headers=token_for(signer, claims)).status_code >= 400
