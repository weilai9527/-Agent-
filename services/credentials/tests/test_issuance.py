"""使用临时密钥、证据和服务端点验证公开验真及校内签发生命周期。"""
import json
from concurrent.futures import ThreadPoolExecutor
from time import time
from uuid import uuid4

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient

from services.credentials import app as api
from services.credentials.tests.test_signing import keypair


SCHOOL = "fixture-school"
STUDENT = "fixture-student"
TEACHER = "fixture-teacher"
STUDENT_SCOPES = ["credential.apply", "credential.read"]
STAFF_SCOPES = ["credential.read", "credential.approve", "credential.issue",
               "credential.reissue", "credential.revoke"]


@pytest.fixture
def service(tmp_path, monkeypatch):
    gateway, service_key, school = keypair(), keypair(), keypair()
    config = {
        "SERVICE_ID": "credentials", "SERVICE_KEY_ID": "service", "SERVICE_SIGNING_KEY": service_key[1],
        "CREDENTIALS_DB_ENGINE": "sqlite", "CREDENTIALS_SQLITE_PATH": str(tmp_path / "cert.db"),
        "CREDENTIALS_PUBLIC_KEYS_JSON": json.dumps({SCHOOL: {"v1": school[0]}}),
        "CREDENTIALS_SIGNING_KEYS_JSON": json.dumps({SCHOOL: {"kid": "v1", "private_key": school[1]}}),
        "IDENTITY_SERVICE_URL": "https://identity.fixture.invalid",
        "ASSESSMENT_SERVICE_URL": "https://assessment.fixture.invalid",
        "TRAINING_SERVICE_URL": "https://training.fixture.invalid",
        "SERVICE_TRUST_POLICY": json.dumps({"gateway": {"keys": {"gw": gateway[0]},
            "schools": [SCHOOL, "other-school"], "grants": {"credentials": {
                "student": STUDENT_SCOPES, "teacher": STAFF_SCOPES, "admin": STAFF_SCOPES}}}}),
    }
    for setting in ("IDENTITY_SESSION_MODE", "ASSESSMENT_STORAGE_MODE"):
        monkeypatch.delenv(setting, raising=False)
    for key, value in config.items():
        monkeypatch.setenv(key, value)
    report = {"report_id": "r", "student_id": STUDENT, "school_id": SCHOOL,
              "interview_id": "i", "version": 1, "digest": "1" * 64}
    training = {"student_id": STUDENT, "school_id": SCHOOL, "interview_id": "i",
                "teacher_id": TEACHER, "task_id": "task", "attempt_id": "a", "status": "completed"}

    def transport(request):
        if request.url.host == "offline-identity.fixture.invalid":
            raise httpx.ConnectError("模拟身份服务中断")
        service = request.url.host.split(".")[0]
        token = jwt.decode(request.headers["authorization"].split()[1], service_key[0],
                           algorithms=["EdDSA"], audience=service, issuer="credentials")
        if service == "identity":
            assert request.method == "POST" and request.url.path == "/internal/staff/authorize-student"
            assert token["scopes"] == ["identity.student.authorize"]
            body = json.loads(request.content)
            assert body["student_id"] == STUDENT and body["action"] in STAFF_SCOPES
            return httpx.Response(200, json={**body, "actor_id": token["sub"],
                                  "actor_type": token["actor_type"], "school_id": token["school_id"]})
        if service == "assessment" and request.method == "POST":
            assert token["scopes"] == ["assessment.credential-authorize"]
            assert request.url.path == "/internal/credential-evidence/r/authorize"
            intent = json.loads(request.content)
            if (intent["version"], intent["digest"]) != (report["version"], report["digest"]):
                return httpx.Response(409)
            return httpx.Response(200, json={**report, **intent})
        if service == "assessment":
            assert token["scopes"] == ["assessment.credential-evidence"]
            assert request.url.path == "/internal/credential-evidence/r"
            return httpx.Response(200, json=report)
        assert service == "training" and request.url.path == "/interviews/i/attempt"
        assert token["scopes"] == ["training.verify"]
        if token["sub"] == "outside-class":
            return httpx.Response(404)
        return httpx.Response(200, json=training)

    # 模拟出站服务，保留 TestClient 的入站路由和真实凭据验证；测试期间不连接外部网络。
    init = httpx.Client.__init__
    def mock_http(client, *args, **kwargs):
        kwargs.setdefault("transport", httpx.MockTransport(transport))
        init(client, *args, **kwargs)
    monkeypatch.setattr(httpx.Client, "__init__", mock_http)
    with TestClient(api.app) as client:
        def call(path, action, body=None, *, role="teacher", actor=TEACHER, school_id=SCHOOL,
                 method="POST"):
            ts = int(time())
            claims = {"iss": "gateway", "sub": actor, "aud": "credentials", "actor_type": role,
                      "school_id": school_id, "scopes": [action], "iat": ts, "exp": ts + 45,
                      "jti": uuid4().hex}
            token = jwt.encode(claims, gateway[1], algorithm="EdDSA", headers={"kid": "gw", "typ": "service+jwt"})
            return client.request(method, path, json=body, headers={"Authorization": f"Bearer {token}"})
        yield client, call, report, training


def apply(call):
    result = call("/applications", "credential.apply", {"report_id": "r"}, actor=STUDENT, role="student")
    assert result.status_code == 200, result.text
    return result.json()


def review(call, row, **overrides):
    ev = row["evidence"]
    data = {"decision": "approved", "note": "fixture-note", "version": ev["version"], "digest": ev["digest"]}
    return call(f"/applications/{row['id']}/review", "credential.approve", {**data, **overrides})


def test_concurrent_lifecycle_and_public_projection(service):
    client, call, _, _ = service
    with ThreadPoolExecutor(4) as pool:
        rows = list(pool.map(lambda _: apply(call), range(4)))
        row = rows[0]
        assert all(r == row for r in rows)
        issue_path = f"/applications/{row['id']}/issue"
        assert call(issue_path, "credential.issue").status_code == 409
        assert review(call, row, digest="0" * 64).status_code == 409
        approvals = list(pool.map(lambda _: review(call, row), range(3)))
        assert all(a.status_code == 200 and a.json() == approvals[0].json() for a in approvals)
        assert review(call, row, decision="rejected").status_code == 409
        issued = list(pool.map(lambda _: call(issue_path, "credential.issue"), range(4)))
        cert = issued[0].json()
        assert all(c.status_code == 200 and c.json() == cert for c in issued)
        public = client.get(cert["verification_url"])
        assert public.headers["cache-control"] == "no-store"
        assert public.json() == {"title": api.TITLE, "issuer": SCHOOL, "issued_at": cert["issued_at"],
                                "valid": True, "status": "valid", "anchor": {"status": "pending"}}
        cert_path = "/certificates/" + cert["id"]
        assert call(cert_path + "/reissue", "credential.reissue").status_code == 409
        revoke = lambda: call(cert_path + "/revoke", "credential.revoke", {"reason": "fixture only"})
        revocations = list(pool.map(lambda _: revoke(), range(3)))
        assert all(c.status_code == 200 and c.json() == revocations[0].json() for c in revocations)
        assert client.get(cert["verification_url"]).json()["valid"] is False
        replacements = list(pool.map(lambda _: call(cert_path + "/reissue", "credential.reissue"), range(4)))
        replacement = replacements[0].json()
        assert all(c.status_code == 200 and c.json() == replacement for c in replacements)
        assert replacement["generation"] == 2 and replacement["id"] != cert["id"]
        assert client.get(cert["verification_url"]).json()["status"] == "revoked"
        assert client.get(replacement["verification_url"]).json()["valid"]
    mine = call("/me/applications", "credential.read", method="GET", role="student", actor=STUDENT)
    assert [c["id"] for c in mine.json()["items"][0]["certificates"]] == [cert["id"], replacement["id"]]
    with api.database().transaction() as tx:
        assert tx.one("SELECT COUNT(*) AS n FROM credential_outbox")["n"] == 3


def test_new_version_requires_new_approval_even_if_content_returns(service):
    client, call, report, _ = service
    first = apply(call)
    assert review(call, first).status_code == 200
    report.update(version=2)
    assert call(f"/applications/{first['id']}/issue", "credential.issue").status_code == 409
    second = apply(call)
    assert first["id"] != second["id"] and second["decision"] == "pending"
    url = f"/applications/{second['id']}/issue"
    assert call(url, "credential.issue").status_code == 409
    assert review(call, second).status_code == 200
    cert = call(url, "credential.issue").json()
    report.update(version=3)
    assert client.get(cert["verification_url"]).json()["valid"]
    assert call(f"/certificates/{cert['id']}/revoke", "credential.revoke", {"reason": "changed"}).status_code == 200
    assert call(f"/certificates/{cert['id']}/reissue", "credential.reissue").status_code == 409


def test_authority_is_tenant_role_action_and_object_specific(service):
    client, call, report, training = service
    assert client.get("/me/applications", headers={"X-Actor-Id": STUDENT}).status_code == 401
    assert call("/applications", "credential.apply", {"report_id": "r", "school_id": SCHOOL},
                actor=STUDENT, role="student").status_code == 422
    row = apply(call)
    path = f"/applications/{row['id']}/review"
    body = {"version": 1, "digest": report["digest"], "decision": "approved"}
    assert call(path, "credential.read", body).status_code == 403
    assert call(path, "credential.approve", body, role="admin").status_code == 403
    assert call(path, "credential.approve", body, school_id="other-school").status_code == 404
    assert call(path, "credential.approve", body, actor="peer-teacher").status_code == 404
    read = f"/students/{STUDENT}/applications"
    assert call(read, "credential.read", method="GET", actor="peer-teacher").json()["items"] == []
    assert call(read, "credential.read", method="GET", actor="outside-class", role="admin").json()["items"] == []
    assert call(read, "credential.read", method="GET").json()["items"] == [row]
    assert call("/me/applications", "credential.read", method="GET", role="student", actor="stranger").json()["items"] == []
    assert call("/applications", "credential.apply", {"report_id": "r"}, role="student", actor="stranger").status_code == 404
    training["status"] = "started"
    assert review(call, row).status_code == 409
    assert client.get("/verify/" + "b" * 32).status_code == 404
    assert client.post("/verify/" + "b" * 32).status_code == 405


def test_signing_rollback_and_tamper_detection(service, monkeypatch):
    client, call, _, _ = service
    row = apply(call)
    assert review(call, row).status_code == 200
    path = f"/applications/{row['id']}/issue"
    with monkeypatch.context() as m:
        m.delenv("CREDENTIALS_SIGNING_KEYS_JSON")
        assert call(path, "credential.issue").status_code == 503
    with api.database().transaction() as tx:
        assert tx.one("SELECT COUNT(*) AS n FROM credential_outbox")["n"] == 0
    cert = call(path, "credential.issue").json()
    with api.database().transaction(write=True) as tx:
        tx.execute("UPDATE credential_outbox SET digest=?", ("0" * 64,))
    assert client.get(cert["verification_url"]).json()["anchor"] == {"status": "unconfirmed"}
    with api.database().transaction(write=True) as tx:
        tx.execute("UPDATE teaching_certificates SET issued_by=? WHERE serial=?", ("forged", cert["id"]))
    assert client.get(cert["verification_url"]).json() == {"valid": False, "status": "invalid_signature"}


def test_signed_proof_is_portable_but_revocation_is_online(service, monkeypatch):
    client, call, _, _ = service
    monkeypatch.setenv("CREDENTIALS_PUBLIC_SERVICE_URL", "https://verify.fixture.invalid")
    row = apply(call)
    assert review(call, row).status_code == 200
    cert = call(f"/applications/{row['id']}/issue", "credential.issue").json()
    assert cert["verification_url"] == "https://verify.fixture.invalid/verify/" + cert["id"]
    response = call("/me/applications", "credential.read", method="GET", role="student", actor=STUDENT)
    proof = response.json()["items"][0]["certificates"][0]["proof"]
    monkeypatch.delenv("CREDENTIALS_SIGNING_KEYS_JSON")
    assert proof["payload"]["serial"] == cert["id"]
    assert api.signing.verify_payload(SCHOOL, proof["payload"], proof["kid"], proof["signature"])
    assert STUDENT not in json.dumps(proof) and TEACHER not in json.dumps(proof)
    monkeypatch.setenv("SERVICE_ID", "credentials-verifier")
    with TestClient(api.public_app) as public:
        html = public.get("/verify/" + cert["id"], headers={"Accept": "text/html"})
        assert html.status_code == 200 and "当前有效" in html.text and STUDENT not in html.text
        assert public.get("/me/applications").status_code == 404
        assert public.get("/health").status_code == 404


def test_evidence_changed_while_signing_is_never_published(service, monkeypatch):
    _, call, report, _ = service
    row = apply(call)
    assert review(call, row).status_code == 200
    sign = api.signing.sign_payload
    def advance_revision(*args):
        proof = sign(*args)
        report.update(version=2, digest="2" * 64)
        return proof
    monkeypatch.setattr(api.signing, "sign_payload", advance_revision)
    assert call(f"/applications/{row['id']}/issue", "credential.issue").status_code == 409
    with api.database().transaction() as tx:
        assert tx.one("SELECT COUNT(*) AS n FROM teaching_certificates")["n"] == 0
        assert tx.one("SELECT COUNT(*) AS n FROM credential_outbox")["n"] == 0


def test_identity_outage_does_not_publish_or_revoke(service, monkeypatch):
    client, call, _, _ = service
    row = apply(call)
    assert review(call, row).status_code == 200
    issue_path = f"/applications/{row['id']}/issue"
    with monkeypatch.context() as outage:
        outage.setenv("IDENTITY_SERVICE_URL", "https://offline-identity.fixture.invalid")
        assert call(issue_path, "credential.issue").status_code == 503
        with api.database().transaction() as tx:
            for table in ("teaching_certificates", "credential_issuance_intents", "credential_outbox"):
                assert tx.one(f"SELECT COUNT(*) AS n FROM {table}")["n"] == 0
    cert = call(issue_path, "credential.issue").json()
    revoke_path = f"/certificates/{cert['id']}/revoke"
    monkeypatch.setenv("IDENTITY_SERVICE_URL", "https://offline-identity.fixture.invalid")
    assert call(revoke_path, "credential.revoke", {"reason": "应拒绝"}).status_code == 503
    assert client.get(cert["verification_url"]).json()["status"] == "valid"
    with api.database().transaction() as tx:
        assert tx.one("SELECT COUNT(*) AS n FROM credential_outbox")["n"] == 1


@pytest.mark.parametrize("actor,secret", [
    ("credentials", None), ("credentials-verifier", "CREDENTIALS_SIGNING_KEYS_JSON"),
    ("credentials-verifier", "PROVENANCE_SUBMIT_TOKEN"),
])
def test_misconfigured_public_process_refuses_to_start(tmp_path, monkeypatch, actor, secret):
    db_path = tmp_path / "unused.db"
    monkeypatch.setenv("SERVICE_ID", actor)
    monkeypatch.setenv("CREDENTIALS_DB_ENGINE", "sqlite")
    monkeypatch.setenv("CREDENTIALS_SQLITE_PATH", str(db_path))
    monkeypatch.delenv("CREDENTIALS_SIGNING_KEYS_JSON", raising=False)
    monkeypatch.delenv("PROVENANCE_SUBMIT_TOKEN", raising=False)
    if secret:
        monkeypatch.setenv(secret, "synthetic-test-only")
    with pytest.raises(RuntimeError, match="公开"):
        with TestClient(api.public_app):
            pytest.fail("错误配置的公开进程不应启动")
    assert not db_path.exists()


@pytest.mark.parametrize("setting,value", [("IDENTITY_SESSION_MODE", "legacy"), ("ASSESSMENT_STORAGE_MODE", "shared")])
def test_issuer_rejects_old_mode_before_opening_store(tmp_path, monkeypatch, setting, value):
    path = tmp_path / "never-created.sqlite"
    monkeypatch.setenv("CREDENTIALS_DB_ENGINE", "sqlite")
    monkeypatch.setenv("CREDENTIALS_SQLITE_PATH", str(path))
    monkeypatch.setenv(setting, value)
    with pytest.raises(ValueError, match=setting):
        with TestClient(api.app):
            pytest.fail("旧版配置不应启动签发服务")
    assert not path.exists()
