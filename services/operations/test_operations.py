"""真实签名、独立 SQLite 库和临时持久卷下的日志隔离与崩溃恢复回归。"""

import asyncio
import json
import sqlite3
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import HTTPException
from fastapi.testclient import TestClient

from services.identity.app import app as identity
from services.operations import app as ops
from services.operations import journal
from services.operations.migrate import migrate
from shared.service_db import ServiceDatabase
from shared.service_security import service_headers


def event():
    return {
        "event_id": str(uuid4()),
        "request_id": uuid4().hex,
        "service": "admin-gateway",
        "event_type": "admin.login",
        "actor_id": "manager",
        "actor_type": "admin",
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "status_code": 200,
        "attempted_account": "secret@example.test",
        "client_ip": "192.0.2.1",
        "metadata": "s3cret-value",
    }


@pytest.fixture
def cluster(tmp_path, monkeypatch):
    for domain in ["operations", "identity"]:
        monkeypatch.setenv(domain.upper() + "_DB_ENGINE", "sqlite")
        monkeypatch.setenv(domain.upper() + "_SQLITE_PATH", str(tmp_path / (domain + ".sqlite")))
    key = Ed25519PrivateKey.generate()
    monkeypatch.setenv("SERVICE_KEY_ID", "k")
    monkeypatch.setenv(
        "SERVICE_SIGNING_KEY",
        key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        ).decode(),
    )
    public = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    grants = {
        "admin-gateway": {
            "operations": {
                "teacher": ["operations.rtc.read", "operations.audit.read"],
                "admin": ["operations.rtc.read", "operations.audit.read"],
                "system": ["operations.audit.append"],
            }
        },
        "interview": {"operations": {"student": ["operations.rtc.append", "operations.rtc.self"]}},
        "operations": {
            "identity": {"teacher": ["identity.operations.scope"], "admin": ["identity.operations.scope"]}
        },
    }
    monkeypatch.setenv(
        "SERVICE_TRUST_POLICY",
        json.dumps(
            {
                issuer: {"keys": {"k": public}, "schools": ["A", "B", "platform"], "grants": value}
                for issuer, value in grants.items()
            }
        ),
    )
    monkeypatch.setenv("SERVICE_ID", "operations")
    monkeypatch.setenv("OPERATIONS_PLATFORM_ADMIN_IDS", "operator")

    def headers(origin, school, role, subject, action, target="operations"):
        with monkeypatch.context() as env:
            env.setenv("SERVICE_ID", origin)
            return service_headers(
                target, school_id=school, actor_id=subject, actor_type=role, scopes=[action]
            )

    with TestClient(identity) as directory, TestClient(ops.app) as client:

        async def authorize(_service, _method, path, *, actor, scope, body):
            h = headers(
                "operations", actor["school_id"], actor["actor_type"], actor["actor_id"], scope, "identity"
            )
            with monkeypatch.context() as env:
                env.setenv("SERVICE_ID", "identity")
                r = directory.post(path, headers=h, json=body)
            if not r.is_success:
                raise HTTPException(r.status_code, "身份授权失败")
            return r.json()

        monkeypatch.setattr(ops, "request_json", authorize)
        with identity.state.store.transaction(write=True) as tx:
            for school in ("A", "B", "platform"):
                for role, user in (("admin", "manager"), ("admin", "operator"), ("teacher", "teacher")):
                    tx.execute(
                        "INSERT INTO identity_staff VALUES(?,?,?,?,?,?,'normal',?,?)",
                        (
                            school,
                            user,
                            user + "@school.test",
                            "unused",
                            user,
                            role,
                            json.dumps(["operations.rtc.read", "operations.audit.read"]),
                            int(role == "admin"),
                        ),
                    )
                tx.execute("INSERT INTO org_colleges VALUES (?,'col','学院','active')", (school,))
                tx.execute("INSERT INTO org_programs VALUES (?,'p','col','专业','active')", (school,))
                for cls, student in (("one", "mine"), ("two", "other")):
                    tx.execute("INSERT INTO org_classes VALUES (?,?,'p',?,'active')", (school, cls, cls))
                    tx.execute(
                        "INSERT INTO identity_student_credentials VALUES (?,?,?,?,'unused','normal',0)",
                        (school, student, student, student),
                    )
                    tx.execute("INSERT INTO org_enrollments VALUES (?,?,?,'active')", (school, student, cls))
                tx.execute("INSERT INTO org_staff_classes VALUES (?,'teacher','one')", (school,))
        yield client, headers


def test_student_and_reassigned_staff_visibility(cluster):
    client, headers = cluster
    for school, student in (("A", "mine"), ("A", "other"), ("B", "mine")):
        h = headers("interview", school, "student", student, "operations.rtc.append")
        result = client.post(
            "/internal/rtc/i",
            headers=h,
            json={
                "event_type": "token_issued",
                "session_id": "CANARY-token",
                "message": "CANARY-resume",
                "metadata": {"secret": "CANARY"},
            },
        )
        assert result.status_code == 201
    assert client.post("/internal/rtc/i", json={}).status_code == 401
    h = headers("admin-gateway", "A", "teacher", "teacher", "operations.rtc.read")
    result = client.get("/v1/connection-logs", headers=h)
    assert result.status_code == 200 and [row["student_id"] for row in result.json()["logs"]] == ["mine"]
    assert "CANARY" not in result.text
    with identity.state.store.transaction(write=True) as tx:
        tx.execute("DELETE FROM org_staff_classes WHERE school_id='A' AND staff_id='teacher'")
    assert client.get("/v1/connection-logs", headers=h).json()["logs"] == []
    h = headers("admin-gateway", "B", "admin", "manager", "operations.rtc.read")
    assert len(client.get("/v1/connection-logs", headers=h).json()["logs"]) == 1


def test_durable_redacted_delivery_and_platform_boundary(cluster, tmp_path, monkeypatch):
    client, headers = cluster
    queue = journal.GatewayJournal(tmp_path / "spool", "admin-gateway", "A")
    entry = event()
    queue.write(entry)
    pending = next(queue.directory.glob("*.json"))
    assert not any(v in pending.read_text() for v in ("CANARY", "secret@", "192.0.2", "s3cret"))

    async def unavailable(*args, **kwargs):
        raise HTTPException(503)

    monkeypatch.setattr(journal, "request_json", unavailable)
    with pytest.raises(HTTPException):
        asyncio.run(queue.drain())
    assert pending.is_file()

    async def delivered(service, method, path, *, actor, scope, body):
        h = headers("admin-gateway", actor["school_id"], actor["actor_type"], actor["actor_id"], scope)
        result = client.post(path, headers=h, json=body)
        assert result.status_code == 200
        return result.json()

    monkeypatch.setattr(journal, "request_json", delivered)
    for _ in range(2):
        queue = journal.GatewayJournal(tmp_path / "spool", "admin-gateway", "A")
        queue.write(entry)
        asyncio.run(queue.drain())
    assert not pending.exists()

    def read(school, role, actor, qs=""):
        return client.get(
            "/v1/security-logs" + qs,
            headers=headers("admin-gateway", school, role, actor, "operations.audit.read"),
        )

    assert read("A", "admin", "manager").json()["total"] == 1
    assert read("A", "teacher", "teacher").status_code == 403
    assert read("B", "admin", "manager", "?school_id=A").status_code == 403
    assert read("B", "admin", "manager").json()["total"] == 0
    assert read("platform", "admin", "manager", "?school_id=A").status_code == 403
    assert read("platform", "admin", "operator", "?school_id=A").json()["events"][0]["school_id"] == "A"


def test_offline_snapshot_import_is_atomic_and_redacts(tmp_path, monkeypatch):
    src = tmp_path / "archive.sqlite"
    target = ServiceDatabase("sqlite", tmp_path / "new.sqlite")
    monkeypatch.setenv("OPERATIONS_ARCHIVE_SCHOOL", "A")
    e = event()
    with sqlite3.connect(src) as conn:
        conn.execute(
            "CREATE TABLE security_audit_events(id,occurred_at,service,event_type,request_id,actor_id,status_code,payload_json)"
        )
        conn.execute(
            "INSERT INTO security_audit_events VALUES(?,?,?,?,?,?,?,?)",
            (
                e["event_id"],
                e["occurred_at"],
                "admin-api",
                e["event_type"],
                e["request_id"],
                e["actor_id"],
                200,
                json.dumps(e),
            ),
        )
    source = ServiceDatabase("sqlite", src)
    before = src.read_bytes()
    for _ in range(2):
        assert migrate(source, target, "A", "audit") == 1
    assert before == src.read_bytes()
    with target.transaction() as tx:
        rows = tx.all("SELECT payload FROM ops_events")
        assert len(rows) == 1 and "secret@" not in rows[0]["payload"]
    with pytest.raises(ValueError):
        migrate(source, target, "B", "audit")
    with sqlite3.connect(src) as conn:
        conn.execute(
            "UPDATE security_audit_events SET payload_json=?", (json.dumps({**e, "school_id": "B"}),)
        )
    with pytest.raises(ValueError):
        migrate(source, target, "A", "audit")


def test_rtc_archive_replay_owner_check_and_wrong_target(tmp_path, monkeypatch):
    """相同快照反复导入仅保留一份，历史答题所属人与日志归属不符时回滚整次导入。"""
    source = ServiceDatabase("sqlite", tmp_path / "rtc_old.sqlite")
    target = ServiceDatabase("sqlite", tmp_path / "rtc_new.sqlite")
    monkeypatch.setenv("OPERATIONS_ARCHIVE_SCHOOL", "A")
    first, bad = "10000000-0000-4000-8000-000000000000", "f0000000-0000-4000-8000-000000000000"
    with sqlite3.connect(source._path) as db:
        db.execute("CREATE TABLE interview_sessions(id TEXT PRIMARY KEY,user_id TEXT)")
        db.execute("INSERT INTO interview_sessions VALUES('i','student')")
        db.execute("""CREATE TABLE webrtc_diagnostic_events(id TEXT PRIMARY KEY, interview_id TEXT,user_id TEXT,created_at TEXT,
                   event_type TEXT,level TEXT,provider TEXT,session_id TEXT,connection_state TEXT,ice_connection_state TEXT,
                   ice_gathering_state TEXT,signaling_state TEXT,data_channel_state TEXT,message TEXT)""")
        db.execute(
            """INSERT INTO webrtc_diagnostic_events(id,interview_id,user_id,created_at,event_type,level,session_id,message)
                   VALUES (?,'i','student','2024-01-01 13:21:04','data_channel_opened','info','CANARY-token','CANARY-answer')""",
            (first,),
        )
    for _ in range(2):
        assert migrate(source, target, "A", "rtc") == 1
    with target.transaction() as tx:
        rows = tx.all("SELECT * FROM ops_events")
        assert len(rows) == 1 and rows[0]["actor_id"] == "student" and "CANARY" not in rows[0]["payload"]
    with sqlite3.connect(source._path) as db:
        db.execute(
            """INSERT INTO webrtc_diagnostic_events(id,interview_id,user_id,created_at,event_type,level)
                   VALUES (?,'i','impostor','2024-01-02 00:00:00','session_created','info')""",
            (bad,),
        )
    empty = ServiceDatabase("sqlite", tmp_path / "rejected.sqlite")
    with pytest.raises(ValueError, match="归属冲突"):
        migrate(source, empty, "A", "rtc")
    with empty.transaction() as tx:
        assert not tx.all("SELECT * FROM ops_events")
    with pytest.raises(ValueError):
        migrate(source, source, "A", "rtc")
    from services.operations.store import prepare

    with pytest.raises(ValueError, match="独立"):
        prepare(source)


def test_browser_cannot_supply_its_own_session_digest():
    from services.operations.events import rtc_data

    payload = {"session_ref": "a" * 24, "session_id": "原始信令令牌"}
    safe = rtc_data(payload)
    assert safe["session_ref"] != payload["session_ref"] and "原始信令令牌" not in str(safe)
    assert rtc_data(safe, from_trusted_bridge=True)["session_ref"] == safe["session_ref"]
