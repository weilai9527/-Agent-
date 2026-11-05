"""隔离校库中的教职工查阅测试。网关、身份和简历服务均执行真实路由与签名校验。"""
from contextlib import ExitStack
import hashlib
import json
import logging
import os
from pathlib import Path
import sqlite3
import time
from types import SimpleNamespace
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
import httpx
import pytest

from shared.account_security import hash_staff_token as hash_token
from services.gateway.native_admin import create_app
from services.identity.app import app as identity
from services.identity.staff import COOKIE
from services.profile import store
from services.profile.app import app as profiles


ACTION = "profile.student.read"
BROWSER = "/api/admin/students/{}/profile"
OWNER = "/v1/admin/students/{}/profile"
INTROSPECT = "/internal/sessions/staff/resolve"
AUTHORIZE = "/internal/staff/authorize-student"
SECRET = "TEST_PRIVATE_RESUME_TEXT_ONLY"
VISIBLE = "负责测试教学平台"
ROLE = {"A": "后端开发工程师", "B": "数据分析师"}


def seed_staff_and_students(db):
    with db.transaction(write=True) as tx:
        for school in ("A", "B"):
            tx.execute("INSERT INTO org_colleges VALUES (?,'d','学院','active')", (school,))
            tx.execute("INSERT INTO org_programs VALUES (?,'p','d','专业','active')", (school,))
            for group in ("own", "other"):
                tx.execute("INSERT INTO org_classes VALUES (?,?,'p',?,'active')", (school, group, group))
            for who, grants in (("teacher", [ACTION]), ("roster-reader", ["student.read"])):
                tx.execute("""INSERT INTO identity_staff
                    (school_id,actor_id,email,password_hash,name,actor_type,status,permissions,school_wide)
                    VALUES (?,?,?,'unused',?,'teacher','normal',?,0)""",
                           (school, who, who + "@test.invalid", who, json.dumps(grants)))
                tx.execute("INSERT INTO org_staff_classes VALUES (?,?,'own')", (school, who))
                tx.execute("INSERT INTO identity_staff_sessions VALUES (?,?,?,?)",
                           (hash_token(school + "-" + who), school, who, int(time.time()) + 600))
            for sid, group in (("student", "own"), ("outside", "other"), ("empty", "own")):
                tx.execute("""INSERT INTO identity_student_credentials
                    (school_id,actor_id,student_no,name,password_hash,status,must_change_password)
                    VALUES (?,?,?,?,'unused','normal',0)""", (school, sid, sid, sid))
                tx.execute("INSERT INTO org_enrollments VALUES (?,?,?,'active')", (school, sid, group))


@pytest.fixture
def school(tmp_path, monkeypatch, caplog):
    env = {
        "SERVICE_ID": "admin-gateway", "SERVICE_KEY_ID": "test", "APP_ENV": "test",
        "IDENTITY_SESSION_MODE": "native", "ASSESSMENT_STORAGE_MODE": "isolated", "LEGACY_SCHOOL_ID": "A",
        "PROFILE_SERVICE_URL": "https://profile.test", "IDENTITY_SERVICE_URL": "https://identity.test",
        "PROFILE_DB_ENGINE": "sqlite", "PROFILE_SQLITE_PATH": str(tmp_path / "profile.sqlite"),
        "IDENTITY_DB_ENGINE": "sqlite", "IDENTITY_SQLITE_PATH": str(tmp_path / "identity.sqlite"),
        "DB_ENGINE": "sqlite", "SQLITE_PATH": str(tmp_path / "forbidden-legacy.sqlite"),
        "OPERATIONS_JOURNAL_DIR": str(tmp_path / "audit"), "OPERATIONS_SERVICE_URL": "https://operations.test",
    }
    private, policy = {}, {}
    grants = {"admin-gateway": {"identity": {"system": ["identity.session.resolve"]},
                                "profile": {"teacher": [ACTION]}},
              "profile": {"identity": {"teacher": ["identity.student.authorize"]}}}
    for peer, permissions in {**grants, "identity": {}}.items():
        key = Ed25519PrivateKey.generate()
        private[peer] = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()).decode()
        public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        policy[peer] = {"schools":["A","B"], "keys":{"test":public.decode()}, "grants":permissions}
    env.update(SERVICE_SIGNING_KEY=private["admin-gateway"], SERVICE_TRUST_POLICY=json.dumps(policy))
    for name, value in env.items():
        monkeypatch.setenv(name, value)

    # 对网关和两个服务的数据库访问做记录，即使源码尝试读取旧库后吞掉异常，测试仍能发现。
    accesses = []
    connect = sqlite3.connect
    def guarded(path, *args, **kwargs):
        accesses.append(Path(path).resolve())
        if accesses[-1] not in {tmp_path.resolve() / "profile.sqlite", tmp_path.resolve() / "identity.sqlite"}:
            raise AssertionError("出现非本次验收的数据库连接")
        return connect(path, *args, **kwargs)
    monkeypatch.setattr(sqlite3, "connect", guarded)
    with ExitStack() as stack:
        peers = {name: stack.enter_context(TestClient(app)) for name, app in
                 (("identity", identity), ("profile", profiles))}
        seed_staff_and_students(identity.state.store)
        for name in ("A", "B"):
            for sid in ("student", "outside"):
                store.save(profiles.state.db, (name, sid), "form", {
                    "resume_text": SECRET + "\n姓名：张博文\n电话：13800000000\n邮箱：student@private.invalid", "resume_filename": "private-upload.pdf",
                    "avatar_url":"https://private.invalid/avatar", "portfolio_links":"https://private.invalid/portfolio",
                    "target_role": ROLE[name], "skills":"Python", "education_level":"本科",
                    "project_experience": VISIBLE,
                }, {"works": "TEST_PRIVATE_FORM"})
        calls, offline = [], set()
        def deliver(req, body):
            receiver = req.url.host.split(".")[0]
            if receiver == "operations":
                # 暂停日志投递，以便直接检查网关持久化的审计数据。
                raise httpx.ConnectError("测试诊断服务离线", request=req)
            calls.append((os.environ["SERVICE_ID"], receiver, req.url.path))
            if req.url.path in offline:
                raise httpx.ConnectError("测试上游离线", request=req)
            assert receiver in peers and "cookie" not in req.headers
            if req.url.path == AUTHORIZE:
                assert json.loads(body)["action"] == ACTION
            with patch.dict(os.environ, SERVICE_ID=receiver, SERVICE_SIGNING_KEY=private[receiver]):
                response = peers[receiver].send(httpx.Request(req.method, req.url, headers=req.headers, content=body))
            return httpx.Response(response.status_code, content=response.content, headers=response.headers)

        def sync_dispatch(_transport, req):
            return deliver(req, req.read())
        async def async_dispatch(_transport, req):
            return deliver(req, await req.aread())
        monkeypatch.setattr(httpx.HTTPTransport, "handle_request", sync_dispatch)
        monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", async_dispatch)
        client = stack.enter_context(TestClient(create_app(), base_url="https://gateway.test"))
        client.cookies.set(COOKIE, "A-teacher")
        logger = logging.getLogger("interview.operations")
        logger.addHandler(caplog.handler)
        stack.callback(logger.removeHandler, caplog.handler)
        yield SimpleNamespace(client=client, db=identity.state.store, profiles=profiles.state.db,
                              offline=offline, calls=calls, audit=tmp_path/"audit")
    assert set(accesses) == {tmp_path.resolve() / "profile.sqlite", tmp_path.resolve() / "identity.sqlite"}


def test_authorized_projection_is_read_only_and_audited(school, caplog):
    client = school.client
    url = BROWSER.format("student")
    result = client.get(url, headers={"X-School-Id": "B", "X-Actor-Type": "admin"})
    assert result.status_code == 200, result.text
    data = result.json()
    assert set(data) == {"school_id", "student_id", "version", "profile"}
    assert (data["school_id"], data["student_id"], data["version"]) == ("A", "student", 1)
    view = data["profile"]
    assert set(view) == {"target_role", "skills", "education_level", "project_experience", "resume_summary"}
    assert (view["target_role"], view["skills"], view["education_level"], view["project_experience"]) == (
        ROLE["A"], "Python", "本科", VISIBLE)
    assert all(isinstance(value, str) for value in view.values())
    assert "no-store" in result.headers.get("Cache-Control", "")
    for private in (SECRET, "private-upload.pdf", "private.invalid", "TEST_PRIVATE_FORM", ROLE["B"], "张博文", "13800000000"):
        assert private not in result.text
    assert school.calls == [("admin-gateway", "identity", INTROSPECT),
                            ("admin-gateway", "profile", OWNER.format("student")),
                            ("profile", "identity", AUTHORIZE)]
    for method in ("PUT", "PATCH", "POST", "DELETE"):
        assert client.request(method, url, json={"resume_text":"attempt"}).status_code in (404, 405)

    events = [json.loads(path.read_text()) for path in school.audit.rglob("*.json")]
    reads = [row for row in events if row["event_type"] == ACTION and row["success"]]
    assert len(reads) == 1
    assert reads[0]["actor_id"] == "teacher" and reads[0]["actor_type"] == "teacher"
    logged = [json.loads(r.getMessage()) for r in caplog.records if r.name == "interview.operations"]
    captured = [e for e in logged if e["event_type"] == ACTION and e["success"]]
    target_digest = "sha256-" + hashlib.sha256(b"student").hexdigest()
    assert captured and all(e.get("target_type") == "student_profile" and e["actor_id"] == "teacher"
                            and e["status_code"] == 200 for e in captured)
    assert all(e.get("target_id") in (None, target_digest) and not e.get("targets") for e in captured)
    with school.profiles.transaction() as tx:
        access = tx.all("SELECT * FROM profile_access_audit")
    assert len(access) == 1
    assert {k: access[0][k] for k in ("school_id", "actor_id", "actor_type", "student_id", "version", "result")} == {
        "school_id": "A", "actor_id": "teacher", "actor_type": "teacher", "student_id": "student",
        "version": 1, "result": "allowed"}
    audit_text = json.dumps([events, logged, access], ensure_ascii=False, default=str)
    for private in (SECRET, VISIBLE, ROLE["A"], "TEST_PRIVATE_FORM", "private.invalid", "A-teacher", "张博文", "13800000000"):
        assert private not in audit_text


def test_scope_revocation_and_same_id_in_other_school(school, monkeypatch):
    client = school.client
    assert client.get(BROWSER.format("student")).status_code == 200
    assert client.get(BROWSER.format("outside")).status_code == 403
    client.cookies.set(COOKIE, "A-roster-reader")
    count = len(school.calls)
    assert client.get(BROWSER.format("student")).status_code == 403
    assert school.calls[count:] == [("admin-gateway", "identity", INTROSPECT)]
    client.cookies.set(COOKIE, "A-teacher")
    with school.db.transaction(write=True) as tx:
        tx.execute("DELETE FROM org_staff_classes WHERE school_id='A' AND staff_id='teacher' AND class_id='own'")
    assert client.get(BROWSER.format("student")).status_code == 403
    # 模拟指向另一所学校的入口，使用相同教师和学生 ID，A 校会话不能在 B 校解析。
    with monkeypatch.context() as binding:
        binding.setenv("LEGACY_SCHOOL_ID", "B")
        with TestClient(create_app(), base_url="https://school-b.test") as other:
            other.cookies.set(COOKIE, "A-teacher")
            assert other.get(BROWSER.format("student")).status_code == 401
            other.cookies.set(COOKIE, "B-teacher")
            result = other.get(BROWSER.format("student"))
            assert result.status_code == 200
            assert result.json()["school_id"] == "B" and result.json()["profile"]["target_role"] == ROLE["B"]
    with school.profiles.transaction() as tx:
        denied = tx.all("SELECT school_id,student_id,version FROM profile_access_audit WHERE result='denied'")
    assert {(r["school_id"], r["student_id"], r["version"]) for r in denied} == {
        ("A", "outside", None), ("A", "student", None)}


def test_peer_failure_missing_config_and_missing_snapshot_do_not_use_old_store(school, monkeypatch):
    url = BROWSER.format("student")
    for path in (INTROSPECT, AUTHORIZE, OWNER.format("student")):
        school.offline.add(path)
        response = school.client.get(url)
        assert response.status_code in (502, 503) and "profile" not in response.json() and SECRET not in response.text
        school.offline.remove(path)
    for key in ("IDENTITY_SERVICE_URL", "PROFILE_SERVICE_URL"):
        with monkeypatch.context() as config:
            config.delenv(key)
            assert school.client.get(url).status_code in (502, 503)
    assert school.client.get(BROWSER.format("empty")).status_code == 404
    with school.profiles.transaction() as tx:
        failed = tx.all("SELECT school_id,student_id,version,result FROM profile_access_audit")
    assert {(r["student_id"], r["version"], r["result"]) for r in failed} == {
        ("empty", None, "not_found"), ("student", None, "unavailable")}
    assert all(r["school_id"] == "A" for r in failed)



def test_sensitive_path_identifiers_are_not_written_to_audit(school, caplog):
    probes = ("synthetic-student+probe@example.invalid", "13800009999")
    for target in probes:
        assert school.client.get(BROWSER.format(target)).status_code == 403
    log = [json.loads(r.getMessage()) for r in caplog.records if r.name == "interview.operations"]
    digests = {"sha256-" + hashlib.sha256(target.encode()).hexdigest() for target in probes}
    rejected = [e for e in log if e["event_type"] == ACTION and not e["success"]]
    assert len(rejected) == len(probes)
    assert all(e["actor_id"] == "teacher" and e["status_code"] == 403 and not e.get("targets") for e in rejected)
    assert all(e.get("target_id") is None or e["target_id"] in digests for e in rejected)
    with school.profiles.transaction() as tx:
        reads = tx.all("SELECT * FROM profile_access_audit")
    assert {(r["student_id"], r["result"]) for r in reads} == {(d, "denied") for d in digests}
    journal = [json.loads(p.read_text()) for p in school.audit.rglob("*.json")]
    assert len([e for e in journal if e["event_type"] == ACTION and not e["success"]]) == 2
    audit = json.dumps([log, journal, reads], ensure_ascii=False, default=str)
    assert all(value not in audit for value in (*probes, SECRET))
