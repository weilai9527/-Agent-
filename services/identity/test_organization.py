"""用独立 SQLite 学校样本验证签名服务请求的组织边界。"""
import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from shared.service_db import ServiceDatabase
from shared.service_security import service_headers
from services.identity.app import app
from services.identity.organization import migrate_legacy, student_access


@pytest.fixture
def api(tmp_path, monkeypatch):
    path = str(tmp_path / "isolated.sqlite")
    monkeypatch.setenv("IDENTITY_SQLITE_PATH", path)
    monkeypatch.setenv("IDENTITY_DB_ENGINE", "sqlite")
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    grants = ["identity.classes.read", "identity.roster.read", "organization.read", "organization.manage",
              "identity.student.authorize", "audit.read", "roster.import"]
    monkeypatch.setenv("SERVICE_TRUST_POLICY", json.dumps({"caller": {"keys": {"k": public.decode()},
                       "schools": ["A", "B"], "grants": {"identity": {"admin": grants, "teacher": grants}}}}))
    monkeypatch.setenv("SERVICE_KEY_ID", "k")
    monkeypatch.setenv("SERVICE_SIGNING_KEY", key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode())
    def headers(action, actor="root", school="A", role=None):
        # 生产环境由独立服务进程持有各自 SERVICE_ID。
        monkeypatch.setenv("SERVICE_ID", "caller")
        signed = service_headers("identity", actor_id=actor, school_id=school,
                                 actor_type=role or ("admin" if actor == "root" else "teacher"), scopes=[action])
        monkeypatch.setenv("SERVICE_ID", "identity")
        return signed

    with TestClient(app) as client:
        with app.state.store.transaction(write=True) as tx:
            for school in ("A", "B"):
                for actor, role, perms in (("root", "admin", grants), ("prof", "teacher", ["training.assign", "roster.import"]),
                                           ("other", "teacher", ["training.assign"]), ("reader", "teacher", ["report.read"])):
                    tx.execute("""INSERT INTO identity_staff
                        (school_id,actor_id,email,password_hash,name,actor_type,status,permissions,school_wide)
                        VALUES (?,?,?,'unused',?,?,'normal',?,?)""",
                               (school, actor, actor+"@example.com", actor, role, json.dumps(perms), int(actor=="root")))
                for student in ("s1", "s2", "s3"):
                    tx.execute("""INSERT INTO identity_student_credentials
                        (school_id,actor_id,student_no,name,password_hash,status,must_change_password)
                        VALUES (?,?,?,?,'unused','normal',0)""", (school,student,student,student))
        yield client, headers, app.state.store


def setup_nodes(client, headers, school="A"):
    body = {"colleges": [{"id": "dep", "name": "Department"}],
            "programs": [{"id": "prog", "name": "Software", "college_id": "dep"}],
            "classes": [{"id": "c1", "program_id": "prog", "name": school + " section 1", "staff_ids": ["prof"]},
                        {"id": "c2", "program_id": "prog", "name": school + " section 2", "staff_ids": ["other"]}]}
    reply = client.post("/v1/organization/import", headers=headers("organization.manage",school=school), json=body)
    assert reply.status_code == 200, reply.text


def test_tenant_scoped_roster_and_atomic_class_moves(api):
    client, headers, store = api
    for school in ("A", "B"):
        setup_nodes(client, headers, school)
    # 两所学校刻意使用相同班级、学生和教师编号以验证租户隔离。
    def enroll(school, group, students, actor="root", status="active"):
        return client.post(f"/v1/classes/{group}/roster/import", headers=headers("roster.import", actor, school),
                           json={"student_ids": students,"status": status})
    assert enroll("A", "c1", ["s1"]).status_code == 200
    assert enroll("A", "c2", ["s2"]).status_code == 200
    assert enroll("B", "c1", ["s2"]).status_code == 200
    listed = client.get("/classes", headers={**headers("identity.classes.read","prof"),"X-School-Id":"B"}).json()["items"]
    assert [r["name"] for r in listed] == ["A section 1"]
    def roster(school, ids, actor="prof"):
        return client.post("/classes/roster", json={"class_ids": ids}, headers=headers("identity.roster.read",actor,school))
    assert roster("A", ["c1"]).json()["classes"] == [{"class_id": "c1","student_ids":["s1"]}]
    assert roster("B", ["c1"]).json()["classes"] == [{"class_id": "c1","student_ids":["s2"]}]
    assert roster("A", ["c1", "c2"]).status_code == 403
    assert roster("A", ["c1"], actor="reader").status_code == 403
    before = client.get("/v1/audit", headers=headers("audit.read")).json()["items"]
    # 第二条越权时，第一条及其审计也应一起回滚。
    assert enroll("A", "c1", ["s1","s2"], "prof", "inactive").status_code == 403
    assert enroll("A", "c1", ["s3"], "prof").status_code == 403
    assert roster("A", ["c1"]).json()["classes"][0]["student_ids"] == ["s1"]
    assert client.get("/v1/audit", headers=headers("audit.read")).json()["items"] == before
    assert all(row["target_id"] != "B" for row in before)
    with store.transaction() as tx:
        ctx = {"school_id": "A", "actor_id":"prof","actor_type":"teacher"}
        assert student_access(tx,ctx,"s1") and not student_access(tx,ctx,"s2")
        assert not student_access(tx,dict(ctx, actor_type="admin"),"s1")
    with store.transaction(write=True) as tx:
        tx.execute("UPDATE identity_student_credentials SET status='disabled' WHERE school_id='A' AND actor_id='s1'")
    assert roster("A", ["c1"]).json()["classes"][0]["student_ids"] == []
    assert client.post("/v1/organization/import",headers=headers("organization.manage"),
                       json={"classes":[{"id":"c1","program_id":"prog","name":"A section 1","staff_ids":[]}]}).status_code == 200
    assert roster("A", ["c1"]).status_code == 403
    assert roster("B", ["c1"]).status_code == 200


def test_internal_action_probe_checks_role_grant_and_student_scope(api):
    client, headers, store = api
    setup_nodes(client, headers)
    with store.transaction(write=True) as tx:
        tx.execute("UPDATE identity_staff SET permissions=? WHERE actor_id='prof'", (json.dumps(["report.read"]),))
        tx.execute("INSERT INTO org_enrollments VALUES ('A','s1','c1','active'), ('A','s2','c2','active')")
    def probe(action, actor="prof", student="s1", school="A"):
        return client.post("/internal/staff/authorize-student",
                           headers=headers("identity.student.authorize", actor, school),
                           json={"action": action, "student_id": student})
    assert probe("report.read").json() == {"school_id":"A", "actor_id":"prof", "actor_type":"teacher",
                                          "action":"report.read", "student_id":"s1"}
    for action in ("score.adjust", "report.review", "report.export", "credential.approve", "credential.revoke"):
        assert probe(action).status_code == 403
    with store.transaction(write=True) as tx:
        tx.execute("UPDATE identity_staff SET permissions=? WHERE school_id='A'", (json.dumps(["score.adjust"]),))
    assert probe("score.adjust").status_code == 200
    assert probe("score.adjust", student="s2").status_code == 403
    assert probe("score.adjust", school="B").status_code == 403
    assert probe("score.adjust", actor="root").status_code == 403
    assert probe("permissions.manage").status_code == 422
    assert client.post("/internal/staff/authorize-student", json={"student_id":"s1", "action":"score.adjust"},
                       headers={"X-Actor-Id":"prof", "X-School-Id":"A"}).status_code == 401


def test_legacy_scope_expansion_is_strict_and_cutover_replay_preserves_revocation(api, tmp_path):
    _, _, target = api
    source = ServiceDatabase.from_env("old", {"OLD_DB_ENGINE":"sqlite","OLD_SQLITE_PATH":str(tmp_path/"old.sqlite")})
    source.ensure_schema((
        "CREATE TABLE campus_colleges (id TEXT,name TEXT,status TEXT)",
        "CREATE TABLE campus_programs (id TEXT,name TEXT,status TEXT,college_id TEXT)",
        "CREATE TABLE campus_classes (id TEXT,name TEXT,status TEXT,program_id TEXT)",
        "CREATE TABLE student_enrollments (user_id TEXT,class_id TEXT,status TEXT)",
        "CREATE TABLE student_registrations (id TEXT,student_no TEXT,deleted_at TEXT)",
        "CREATE TABLE admin_users (id TEXT,student_scope TEXT)",
        "CREATE TABLE admin_audit_logs (id TEXT,admin_user_id TEXT,action TEXT,target_id TEXT,success INT,summary TEXT,created_at TEXT)",
    ))
    with source.transaction(write=True) as tx:
        tx.execute("INSERT INTO campus_colleges VALUES ('d','Department','active')")
        tx.execute("INSERT INTO campus_programs VALUES ('p','Program','active','d')")
        tx.execute("INSERT INTO campus_classes VALUES ('c','Class','active','p')")
        tx.execute("INSERT INTO student_enrollments VALUES ('s1','c','active'),('ghost','c','active')")
        tx.execute("INSERT INTO student_registrations VALUES ('registration','old-number','2026-03-01')")
        tx.execute("INSERT INTO admin_users VALUES (?,?),(?,?)", ("prof",'[{"college":"d","program":"p"}]',"other",'[{}]'))
        tx.execute("INSERT INTO admin_audit_logs VALUES ('e','prof','old.import','c',1,'summary','2026-04-01 00:00:00')")
    with source.transaction() as old, target.transaction(write=True) as tx:
        migrate_legacy(tx, old, "A")
        assert tx.all("SELECT staff_id FROM org_staff_classes") == [{"staff_id":"prof"}]
        assert tx.all("SELECT student_id FROM org_enrollments") == [{"student_id":"s1"}]
        assert tx.one("SELECT school_id,action FROM identity_audit WHERE id='e'") == {"school_id":"A","action":"old.import"}
        archived = tx.one("SELECT legacy_record FROM identity_legacy_organization WHERE source_table='student_registrations'")
        assert json.loads(archived["legacy_record"])["deleted_at"] == "2026-03-01"
        tx.execute("DELETE FROM org_staff_classes")
        migrate_legacy(tx, old, "A")
        assert tx.all("SELECT * FROM org_staff_classes") == []


def test_admin_org_controls_named_queries_and_assignment_conflicts(api):
    client, headers, store = api
    for school in ("A", "B"):
        setup_nodes(client, headers, school)
    with store.transaction(write=True) as tx:
        tx.execute("UPDATE identity_student_credentials SET name='同名',student_no=UPPER(student_no)")
        tx.execute("INSERT INTO org_enrollments VALUES ('A','s1','c1','active'),('A','s2','c2','active'),('B','s2','c1','active')")
    path = "/v1/organization/roster-candidates"
    # 只有写权限的职员可提交已知标识，不能搜索姓名。
    assert client.get(path, params={"q":"同名"}, headers=headers("roster.import", "prof")).status_code == 403
    with store.transaction(write=True) as tx:
        tx.execute("UPDATE identity_staff SET permissions=? WHERE actor_id='prof' AND school_id='A'",
                   (json.dumps(["organization.read", "roster.import"]),))
    found = client.get(path, params={"q":"同名"}, headers=headers("roster.import", "prof"))
    assert found.status_code == 200, found.text
    assert [r["actor_id"] for r in found.json()["items"]] == ["s1"]
    # 只有全校管理员可搜索尚未归班的学生。
    assert [r["actor_id"] for r in client.get(path, params={"q":"s3"}, headers=headers("roster.import")).json()["items"]] == ["s3"]
    roster = client.get("/v1/classes/c1/roster", headers=headers("organization.read", "prof")).json()
    assert roster == {"class_id":"c1","has_more":False,"items":[{"actor_id":"s1","student_no":"S1","name":"同名"}]}
    assert client.get("/v1/classes/c2/roster", headers=headers("organization.read", "prof")).status_code == 403
    assert client.get("/v1/classes/c1/staff", headers=headers("organization.manage", "prof")).status_code == 403
    service = "/v1/classes/c1/staff"
    staff = client.get(service, headers=headers("organization.manage")).json()
    assert [r["actor_id"] for r in staff["assigned"]] == ["prof"]
    assert all(set(r) == {"actor_id", "name", "actor_type"} for r in staff["items"])
    update = {"expected_staff_ids":["prof"],"staff_ids":["other"]}
    assert client.put(service, json=update, headers=headers("organization.manage")).status_code == 200
    assert client.put(service, json=update, headers=headers("organization.manage")).status_code == 409
    with store.transaction() as tx:
        assert tx.all("""SELECT target_id,summary FROM identity_audit WHERE school_id='A'
                      AND action='organization.class.staff.remove'""") == [{"target_id":"c1","summary":"prof"}]
    assert client.get("/v1/classes/c1/roster", headers=headers("organization.read", "prof")).status_code == 403
    assert client.get(service, headers=headers("organization.manage", school="B")).json()["assigned"][0]["actor_id"] == "prof"
