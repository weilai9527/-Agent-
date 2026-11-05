"""在独立创建的学校记录上验证真实会话及网关签名。"""
import json

import pytest
from fastapi.testclient import TestClient
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from shared.account_security import hash_staff_password as hash_password
from shared.service_security import service_headers
from services.identity.app import app
from services.identity.staff import COOKIE


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("IDENTITY_DB_ENGINE", "sqlite")
    monkeypatch.setenv("IDENTITY_SQLITE_PATH", str(tmp_path / "identity.sqlite"))
    key = Ed25519PrivateKey.generate()
    private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    monkeypatch.setenv("SERVICE_KEY_ID", "test")
    monkeypatch.setenv("SERVICE_SIGNING_KEY", private.decode())
    monkeypatch.setenv("SERVICE_TRUST_POLICY", json.dumps({"admin-gateway": {
        "keys": {"test": public.decode()}, "schools": ["A", "B"], "grants": {"identity": {
            "system": ["identity.session.resolve"], "admin": ["permissions.manage"]}}}}))

    def header(school, role="system"):
        is_admin = role == "admin"
        monkeypatch.setenv("SERVICE_ID", "admin-gateway")
        result = service_headers("identity", actor_id="manager" if is_admin else "gateway", school_id=school,
                                 actor_type=role, scopes=["permissions.manage" if is_admin else "identity.session.resolve"])
        monkeypatch.setenv("SERVICE_ID", "identity")
        return result

    password = "Fictional-Staff-Password"
    encoded = hash_password(password)
    with TestClient(app, base_url="https://identity.test") as client:
        with app.state.store.transaction(write=True) as tx:
            for school in ("A", "B"):
                for name, role, grants in (
                    ("manager", "admin", ["permissions.manage", "score.adjust", "credential.approve"]),
                    ("reader", "teacher", ["viewReports"]),
                ):
                    tx.execute("""INSERT INTO identity_staff VALUES (?,?,?,?,?,?,'normal',?,?)""",
                               (school, name, f"{name}@school.test", encoded, name, role,
                                json.dumps(grants), int(role == "admin")))
        yield client, header, password


def test_staff_login_and_separate_action_authorization(api):
    client, header, password = api

    def login(name):
        return client.post("/sessions/staff/login", json={"school_id": "A", "email": name+"@school.test", "password": password})

    def resolve(scope, school="A", headers=None):
        return client.post("/internal/sessions/staff/resolve", headers=header(school) if headers is None else headers,
                           json={"token": client.cookies.get(COOKIE), "action": scope})

    response = login("reader")
    assert response.status_code == 200 and "Secure" in response.headers["set-cookie"]
    assert response.json()["actor_type"] == "teacher"
    assert resolve("assessment.history").json()["scopes"] == ["assessment.history"]
    for denied in ("score.adjust", "assessment.score", "report.review", "report.export",
                   "credential.approve", "credential.revoke", "model.config.write"):
        assert resolve(denied).status_code == 403
    assert resolve("report.read", school="B").status_code == 401
    assert resolve("report.read", headers={"Authorization": "Bearer " + client.cookies[COOKIE],
                                          "X-Actor-Type": "teacher", "X-School-Id":"A"}).status_code == 401
    assert login("manager").status_code == 200
    assert resolve("assessment.score").status_code == 403
    assert resolve("credential.approve").status_code == 403


def test_grant_replacement_revokes_sessions_without_touching_other_school(api):
    client, header, password = api
    credentials = {"school_id": "A", "email": "reader@school.test", "password": password}
    assert client.post("/sessions/staff/login", json=credentials).status_code == 200
    change = {"actor_type": "teacher", "permissions": ["score.adjust"]}
    assert client.put("/v1/staff/reader/grants", json=change,
                      headers=header("B", "admin")).status_code == 200
    assert client.get("/sessions/staff/me").status_code == 200
    assert client.put("/v1/staff/reader/grants", json=change, headers=header("A", "admin")).status_code == 200
    assert client.get("/sessions/staff/me").status_code == 401
    assert client.post("/sessions/staff/login", json=credentials).status_code == 200
    assert client.post("/internal/sessions/staff/resolve", headers=header("A"),
                       json={"token":client.cookies[COOKIE], "action":"assessment.score"}).status_code == 200
    fake = {"school_id":"B","actor_type":"admin"}
    response = client.post("/v1/staff", headers=header("A","admin"),
                           json={**fake, "password":password, "name":"X","email":"x@test","permissions":[]})
    assert response.status_code == 422 and password not in response.text
    assert client.post("/sessions/staff/logout", headers={"Origin":"https://another.test"}).status_code == 403
    assert client.post("/sessions/staff/logout").status_code == 200
    assert client.get("/sessions/staff/me").status_code == 401
