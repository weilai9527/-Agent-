"""通过真实签名网关验证学生登录及会话解析。"""
import json
import os
import subprocess
import sys
import textwrap

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from shared.account_security import hash_password
from shared.service_db import ServiceDatabase
from shared.service_security import service_headers
from services.identity.app import app
from services.identity.candidate import COOKIE, migrate_legacy


@pytest.fixture()
def session_api(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("LEGACY_SCHOOL_ID", "north")
    monkeypatch.setenv("IDENTITY_DB_ENGINE", "sqlite")
    monkeypatch.setenv("IDENTITY_SQLITE_PATH", str(tmp_path / "native.sqlite"))
    key = Ed25519PrivateKey.generate()
    monkeypatch.setenv("SERVICE_KEY_ID", "test-key")
    monkeypatch.setenv("SERVICE_SIGNING_KEY", key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode())
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    monkeypatch.setenv("SERVICE_TRUST_POLICY", json.dumps({"agw": {
        "schools": ["north", "south"], "keys": {"test-key": public},
        "grants": {"identity": {"system": ["identity.session.resolve"], "admin": ["student.import"],
                                "student": ["identity.student.read"]}}}}))

    def signed(school="north", actor="gateway", role="system", scope="identity.session.resolve"):
        monkeypatch.setenv("SERVICE_ID", "agw")
        headers = service_headers("identity", actor_id=actor, actor_type=role, school_id=school, scopes=[scope])
        monkeypatch.setenv("SERVICE_ID", "identity")
        return headers

    with TestClient(app, base_url="https://identity.local") as client:
        with app.state.store.transaction(write=True) as tx:
            for school in ("north", "south"):
                tx.execute("""INSERT INTO identity_staff
                    (school_id,actor_id,email,name,password_hash,actor_type,status,permissions,school_wide)
                    VALUES (?,'principal','school@example.test','school','disabled-login','admin','normal',?,1)""",
                           (school, json.dumps(["student.import"])))
        yield client, signed, app.state.store


def provision(client, signed, school="north", names=("Stu101",)):
    return client.post("/students/import", headers=signed(school, "principal", "admin", "student.import"),
                       json={"students": [{"name": "Student", "student_no": name, "temporary_password": "SchoolTemp936!"}
                                           for name in names]})


def login(client, school="north", password="SchoolTemp936!", **kw):
    return client.post("/sessions/student/login", json={"school_id": school, "student_no": "stu101",
                                                         "password": password}, **kw)


def test_login_rotation_tenant_and_scope(session_api):
    client, signed, store = session_api
    north = provision(client, signed)
    assert north.status_code == 201, north.text
    aid = north.json()["students"][0]["actor_id"]
    assert provision(client, signed, "south").json()["students"][0]["actor_id"] != aid
    assert login(client, headers={"Origin": "https://attacker.test"}).status_code == 403
    assert login(client, password="bad").status_code == 401
    reply = login(client)
    assert reply.status_code == 200 and reply.json()["user"]["mustChangePassword"]
    assert "Secure" in reply.headers["set-cookie"] and "HttpOnly" in reply.headers["set-cookie"]
    assert reply.headers["cache-control"] == "no-store"
    old = client.cookies[COOKIE]

    def resolve(token, *, school="north", action="training.start", headers=None):
        return client.post("/internal/sessions/student/resolve",
                           headers=signed(school) if headers is None else headers,
                           json={"token": token, "action": action})

    assert resolve(old, headers={"Authorization": f"Bearer {old}"}).status_code == 401
    def subject(school="north"):
        return client.get("/internal/students/me", headers=signed(school, aid, "student", "identity.student.read"))

    assert resolve(old).status_code == 403
    assert subject().status_code == 403
    assert client.post("/sessions/student/change-initial-password",
                       json={"password": "SchoolTemp936!", "confirm_password": "SchoolTemp936!"}).status_code == 400
    reply = client.post("/sessions/student/change-initial-password",
                        json={"password": "UniquePassword921!", "confirm_password": "UniquePassword921!"})
    assert reply.status_code == 200 and not reply.json()["user"]["mustChangePassword"]
    token = client.cookies[COOKIE]
    assert old != token and resolve(old).status_code == 401
    assert subject().json() == {"school_id": "north", "actor_id": aid, "name": "Student", "status": "normal",
                                 "must_change_password": False, "student_no": "STU101", "college": None}
    assert subject("south").status_code == 403
    assert resolve(token, school="south").status_code == 403
    assert resolve(token, headers=signed(actor="unexpected-system")).status_code == 403
    for forbidden in ("score.adjust", "report.review", "assessment.score", "credential.approve", "permissions.manage",
                      "usage.reserve", "media.context.sync", "training.verify"):
        assert resolve(token, action=forbidden).status_code == 403
    assert resolve(token).json() == {"actor_id": aid, "actor_type": "student", "school_id": "north", "scopes": ["training.start"]}
    assert client.post("/sessions/student/logout").status_code == 200
    assert resolve(token).status_code == 401
    assert login(client).status_code == 401
    assert login(client, password="UniquePassword921!").status_code == 200
    with store.transaction(write=True) as tx:
        tx.execute("UPDATE identity_student_credentials SET status='disabled' WHERE school_id='north'")
    assert client.get("/sessions/student/me").status_code == 401
    assert resolve(client.cookies[COOKIE]).status_code == 401
    assert subject().status_code == 403


def test_import_rollback_and_role(session_api):
    client, signed, store = session_api
    assert provision(client, signed, names=("STU101", "stu101")).status_code == 409
    with store.transaction() as tx:
        assert not tx.one("SELECT * FROM identity_audit")
        assert not tx.one("SELECT * FROM identity_student_credentials")
    with store.transaction(write=True) as tx:
        tx.execute("UPDATE identity_staff SET school_wide=0 WHERE school_id='north'")
    assert provision(client, signed).status_code == 403
    assert provision(client, signed, "south").status_code == 201


def test_login_throttle_commits_failures(session_api):
    client, signed, _store = session_api
    assert provision(client, signed).status_code == 201
    for _ in range(8):
        assert login(client, password="bad-password").status_code == 401
    assert login(client).status_code == 429
    assert login(client, school="south", password="bad-password").status_code == 401


def test_migrate_stable_ids_and_native_password(session_api, tmp_path):
    _client, _, store = session_api
    source = ServiceDatabase("sqlite", tmp_path / "legacy.sqlite")
    source.ensure_schema(["""CREATE TABLE users(id TEXT, student_no TEXT, name TEXT,
                          password_hash TEXT, must_change_password INTEGER, status TEXT)"""])
    with source.transaction(write=True) as tx:
        tx.execute("INSERT INTO users VALUES ('abc', '202610', 'Student', ?, 1, 'normal')",
                   (hash_password("SchoolTemp936!"),))
    with source.transaction() as src, store.transaction(write=True) as tx:
        assert migrate_legacy(tx, src, "north") == 1
        assert tx.one("SELECT actor_id,must_change_password FROM identity_student_credentials") == {
            "actor_id": "abc", "must_change_password": 1}
        tx.execute("UPDATE identity_student_credentials SET password_hash='rotated'")
        assert migrate_legacy(tx, src, "north") == 0
        assert tx.one("SELECT password_hash FROM identity_student_credentials") == {"password_hash": "rotated"}
        assert not tx.one("SELECT * FROM identity_student_sessions")
        with pytest.raises(ValueError):
            migrate_legacy(tx, src, "south")


def test_legacy_session_and_dynamic_tenant_guard(tmp_path):
    # 临时库隔离旧模块导入副作用，通过真实网关路径验证学生会话。
    script = textwrap.dedent("""
        import os
        from fastapi import FastAPI, HTTPException, Request
        from fastapi.testclient import TestClient
        from shared.offline_fixture import enable_offline_fixture
        from services.identity.gateway import session_mode
        # 仅设置 legacy 环境变量不能启用旧写入；显式离线夹具只在本测试的临时单库进程可用。
        try:
            session_mode()
        except HTTPException as denied:
            assert denied.status_code == 503
        else:
            raise AssertionError("正常网关接受了旧模式")
        enable_offline_fixture()
        from backend.src.database import db
        from shared.account_security import hash_student_token as hash_token
        from services.identity.gateway import candidate_gateway_context
        app = FastAPI()
        @app.get('/who')
        def who(request: Request, action: str = 'training.read'):
            return candidate_gateway_context(request, action)
        with db:
            db.execute("INSERT INTO users(id,email,name,password_hash,status) VALUES ('a','a@example.test','A','unused','normal')").close()
            db.execute("INSERT INTO sessions(id,user_id,token_hash,expires_at) VALUES ('1','a',?,'2999-01-01')", (hash_token('valid'),)).close()
        client = TestClient(app)
        fake = {'X-School-ID':'wrong','X-Actor-ID':'root','X-Actor-Type':'admin','Authorization':'Bearer valid'}
        assert client.get('/who',headers=fake).status_code == 401
        client.cookies.set('interview_session','valid')
        assert client.get('/who',headers=fake).json()=={'actor_id':'a','actor_type':'student','school_id':'north','scopes':['training.read']}
        assert client.get('/who?action=score.adjust').status_code==403
        with db: db.execute("UPDATE users SET must_change_password=1").close()
        assert client.get('/who').status_code==403
        with db:
            db.execute("UPDATE users SET must_change_password=0").close()
            db.execute("ALTER TABLE users ADD COLUMN school_id TEXT DEFAULT 'south'").close()
        assert client.get('/who').status_code==403
        os.environ['IDENTITY_SESSION_MODE']='native'
        assert client.get('/who').status_code==401
    """)
    env = dict(os.environ, APP_ENV="test", IDENTITY_SESSION_MODE="legacy", LEGACY_SCHOOL_ID="north",
               DB_ENGINE="sqlite", SQLITE_PATH=str(tmp_path / "old-db.sqlite"))
    subprocess.run([sys.executable, "-c", script], check=True, env=env)


def test_native_gateway_login_and_no_legacy_fallback(session_api, monkeypatch):
    """每一跳使用独立服务签名，贯通两个应用。"""
    import httpx
    from fastapi import FastAPI
    from services.identity import session_proxy
    from services.identity.candidate_adapter import mount_candidate_auth

    _client, signed, _store = session_api
    assert provision(_client, signed).status_code == 201
    monkeypatch.setenv("IDENTITY_SESSION_MODE", "native")
    monkeypatch.setenv("IDENTITY_SERVICE_URL", "https://identity.internal")
    policy = json.loads(os.environ["SERVICE_TRUST_POLICY"])
    policy["agw"]["grants"]["identity"]["system"].append("identity.session.proxy")
    monkeypatch.setenv("SERVICE_TRUST_POLICY", json.dumps(policy))
    outgoing = []

    async def dispatched(req):
        outgoing.append(req)
        assert req.headers["authorization"].startswith("Bearer ")
        assert req.headers.get("x-identity-client-ip") != "203.0.113.5"
        assert "unrelated" not in req.headers.get("cookie", "")
        return await httpx.ASGITransport(app=app).handle_async_request(req)

    real_client = httpx.AsyncClient
    def gateway_client(**kwargs):
        return real_client(transport=httpx.MockTransport(dispatched), **kwargs)

    monkeypatch.setattr(session_proxy.httpx, "AsyncClient", gateway_client)

    def sign(audience, *, actor_id, school_id, actor_type, scopes):
        assert audience == "identity" and scopes == ["identity.session.proxy"]
        return signed(school_id, actor_id, actor_type, scopes[0])

    monkeypatch.setattr(session_proxy, "service_headers", sign)
    gateway = FastAPI()

    @gateway.post("/api/auth/login")
    def obsolete_login():
        pytest.fail("legacy login executed in native mode")

    mount_candidate_auth(gateway)
    with TestClient(gateway, base_url="https://gateway.example.test") as browser:
        browser.cookies.set("unrelated", "should-never-leave-gateway")
        payload = {"school_id": "south", "student_no": "stu101", "password": "SchoolTemp936!"}
        spoofed = {"Authorization": "Bearer fake", "X-Identity-Client-IP": "203.0.113.5"}
        assert browser.post("/api/auth/login", json=payload, headers={"Origin": "https://untrusted"}).status_code == 403
        assert not outgoing
        assert browser.get("/api/auth/me").json() == {"user": None}
        reply = browser.post("/api/auth/login", json=payload, headers=spoofed)
        assert reply.status_code == 200, reply.text
        assert reply.json()["user"]["schoolId"] == "north"
        assert len(browser.cookies[COOKIE]) == 43
        assert "Secure" in reply.headers["set-cookie"]
        assert browser.get("/api/auth/me").json()["user"]["mustChangePassword"]
        changed = {"password": "Distinct955!", "confirmPassword": "Distinct955!"}
        assert browser.post("/api/auth/change-initial-password", json=changed).status_code == 200
        assert not browser.get("/api/auth/me").json()["user"]["mustChangePassword"]
        assert browser.post("/api/auth/logout").status_code == 200
        assert browser.get("/api/auth/me").json() == {"user": None}
        assert browser.post("/api/auth/password-reset/request").status_code == 403


def test_both_legacy_password_formats_and_damaged_digest():
    from shared.account_security import hash_staff_password as imported_hash
    from shared.account_security import verify_password
    password = "Imported-Password12!"
    for stored in (imported_hash(password), hash_password(password)):
        assert verify_password(password, stored)
        assert not verify_password("wrong", stored)
    for stored in ("scrypt$salt$A", "scrypt$salt$////", "scrypt$salt$!"):
        assert not verify_password(password, stored)


def test_native_cookie_filter_covers_legacy_http_and_websocket(monkeypatch):
    from fastapi import FastAPI, Request, WebSocket
    from services.identity.candidate_adapter import mount_candidate_auth

    gateway = FastAPI()
    monkeypatch.setenv("IDENTITY_SESSION_MODE", "native")

    @gateway.get("/legacy")
    def cookies(request: Request):
        return request.cookies

    @gateway.websocket("/legacy-ws")
    async def websocket_cookies(ws: WebSocket):
        await ws.accept()
        await ws.send_json(ws.cookies)
        await ws.close()

    mount_candidate_auth(gateway)
    token = "a" * 43
    mixed = {"Cookie": f"interview_session=old; identity_student_session={token}; other=x"}
    duplicate = [("Cookie", f"identity_student_session={token}"), ("Cookie", "identity_student_session=bad")]
    with TestClient(gateway) as client:
        assert client.get("/legacy", headers=mixed).json() == {COOKIE: token}
        assert client.get("/legacy", headers=duplicate).json() == {}
        assert client.get("/legacy", headers={"Cookie": "interview_session=old"}).json() == {}
        with client.websocket_connect("/legacy-ws", headers=mixed) as ws:
            assert ws.receive_json() == {COOKIE: token}
