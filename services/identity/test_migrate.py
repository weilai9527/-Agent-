"""使用一次性磁盘 SQLite 快照及原生表结构验证离线切换。"""
import hashlib
import json
import os
import sqlite3
from contextlib import closing

import pytest
from fastapi import HTTPException

from services.identity.migrate import migrate
from services.identity.organization import student_access
from services.identity.staff import require_staff
from shared.service_db import ServiceDatabase


def store(path):
    return ServiceDatabase.from_env("fixture", {"FIXTURE_DB_ENGINE": "sqlite", "FIXTURE_SQLITE_PATH": str(path)})


def snapshot(path, *, old_roles=False):
    """两校刻意复用账号标识、学号和姓名。"""
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.executescript("""
            CREATE TABLE admin_users (id TEXT PRIMARY KEY, email TEXT UNIQUE, name TEXT, role TEXT,
                status TEXT, permissions TEXT, student_scope TEXT, password_hash TEXT);
            CREATE TABLE users (id TEXT PRIMARY KEY, student_no TEXT UNIQUE, name TEXT, status TEXT,
                password_hash TEXT, must_change_password INTEGER);
            CREATE TABLE campus_colleges (id TEXT PRIMARY KEY, name TEXT, status TEXT);
            CREATE TABLE campus_programs (id TEXT PRIMARY KEY, name TEXT, status TEXT, college_id TEXT);
            CREATE TABLE campus_classes (id TEXT PRIMARY KEY, name TEXT, status TEXT, program_id TEXT, advisor TEXT);
            CREATE TABLE student_enrollments (id TEXT PRIMARY KEY, class_id TEXT, user_id TEXT, status TEXT);
            CREATE TABLE student_registrations (id TEXT PRIMARY KEY, user_id TEXT, imported_by TEXT, deleted_at TEXT);
            CREATE TABLE admin_permission_requests (id TEXT PRIMARY KEY, admin_user_id TEXT, permissions TEXT,
                reason TEXT, status TEXT);
            CREATE TABLE admin_audit_logs (id TEXT PRIMARY KEY, admin_user_id TEXT, action TEXT,
                target_id TEXT, success INTEGER, summary TEXT, created_at TIMESTAMP, ip_address TEXT);
            CREATE TABLE security_audit_events (id TEXT PRIMARY KEY, payload_json TEXT);
            INSERT INTO campus_colleges VALUES ('college','学院','active');
            INSERT INTO campus_programs VALUES ('p1','专业','active','college'), ('p2','专业','active','college');
            INSERT INTO campus_classes VALUES ('c1','一班','active','p1','李老师'), ('c2','一班','active','p2','李老师');
            INSERT INTO users VALUES ('s1','stu-001','王同学','normal','existing-student-hash',1),
                ('s2','STU-002','王同学','normal','different-hash',0);
            INSERT INTO student_enrollments VALUES ('e1','c1','s1','active'), ('e2','c2','s2','active');
            INSERT INTO student_registrations VALUES ('r1','s1','importer','2026-01-02');
            INSERT INTO admin_permission_requests VALUES ('req','reader','["score.adjust"]','requested only','pending');
            INSERT INTO admin_audit_logs VALUES ('old','reader','report.view','document',1,'查看',
                '2026-01-01 01:02:03','127.0.0.1');
            INSERT INTO security_audit_events VALUES ('shared-audit','{"event_type":"security.access_denied"}');
        """)
        # 有未知键的历史范围整条丢弃，以免把一个班的授权扩大到两个同名班级。
        scope = json.dumps([{"college":"college", "program":"p1", "class":"c1"},
                            {"college":"college", "class_id":"c2"}])
        conn.executemany("""INSERT INTO admin_users
            (id,email,name,role,status,permissions,student_scope,password_hash) VALUES (?,?,?,?,?,?,?,?)""", [
            ("master", "Master@example.edu", "校管理员", "管理员", "normal", "[]", "[]", "master-hash"),
            ("instructor", "prof@example.edu", "李老师", "授课教师", "normal", '["score.adjust"]', scope, "teacher-hash"),
            ("reader", "reader@example.edu", "李老师", "超级管理员", "normal", '["viewReports"]', scope, "reader-hash"),
        ])
        if not old_roles:
            conn.execute("ALTER TABLE admin_users ADD COLUMN actor_type TEXT NOT NULL DEFAULT 'admin'")
            conn.execute("UPDATE admin_users SET actor_type='teacher' WHERE id='instructor'")
    return store(path)


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_two_school_cutover_preserves_history_grants_namespaces_and_revocations(tmp_path, monkeypatch):
    target = store(tmp_path / "target.sqlite")
    for school, old_roles in (("east", False), ("west", True)):
        monkeypatch.setenv("LEGACY_SCHOOL_ID", school)
        path = tmp_path / (school + ".sqlite")
        source = snapshot(path, old_roles=old_roles)
        original = file_hash(path)
        assert migrate(source, target, school, "master@example.edu") == {
            "staff": 3, "students": 2, "permission_requests": 1,
        }
        with target.transaction() as tx:
            creds = tx.one("""SELECT actor_id,password_hash,student_no,must_change_password
                FROM identity_student_credentials WHERE school_id=? AND actor_id='s1'""", (school,))
            assert creds == {"actor_id":"s1", "password_hash":"existing-student-hash", "student_no":"STU-001",
                             "must_change_password":1}
            # 迁移的主管理员也须单独申请学生档案读取；历史角色显示名不能提升权限。
            with pytest.raises(HTTPException) as denied:
                require_staff(tx, {"school_id":school,"actor_id":"master","actor_type":"admin"}, "profile.student.read")
            assert denied.value.status_code == 403
            reader = {"school_id":school,"actor_id":"reader","actor_type":"admin"}
            assert require_staff(tx, reader, "report.read")["school_wide"] == 0
            for action in ("report.review", "report.export", "score.adjust", "credential.approve", "credential.revoke"):
                with pytest.raises(HTTPException) as denied:
                    require_staff(tx, reader, action)
                assert denied.value.status_code == 403
            assert student_access(tx, reader, "s1")
            assert not student_access(tx, reader, "s2")
            # 历史角色显示名不能授予教师改分权限。
            teacher = dict(reader, actor_id="instructor", actor_type="admin" if old_roles else "teacher")
            if old_roles:
                with pytest.raises(HTTPException) as denied:
                    require_staff(tx, teacher, "score.adjust")
                assert denied.value.status_code == 403
            else:
                require_staff(tx, teacher, "score.adjust")
                assert student_access(tx, teacher, "s1") and not student_access(tx, teacher, "s2")
            logs = tx.all("SELECT actor_id,action,target_id FROM identity_audit WHERE school_id=? ORDER BY action", (school,))
            assert logs == [
                {"actor_id":"migration","action":"identity.cutover","target_id":school},
                {"actor_id":"reader","action":"report.view","target_id":"document"},
            ]
            archive = tx.one("""SELECT legacy_record FROM identity_legacy_organization
                WHERE school_id=? AND source_table='admin_audit_logs' AND record_id='old'""", (school,))
            assert json.loads(archive["legacy_record"])["ip_address"] == "127.0.0.1"
            assert json.loads(tx.one("""SELECT legacy_record FROM identity_legacy_permission_requests
                WHERE school_id=? AND id='req'""", (school,))["legacy_record"])["status"] == "pending"
        with target.transaction(write=True) as tx:
            tx.execute("UPDATE identity_staff SET permissions='[]' WHERE school_id=? AND actor_id='reader'", (school,))
            tx.execute("DELETE FROM org_staff_classes WHERE school_id=? AND staff_id='reader'", (school,))
            tx.execute("""UPDATE identity_student_credentials SET password_hash='changed' WHERE school_id=? AND
                actor_id='s1'""", (school,))
        assert migrate(source, target, school, "master@example.edu") == {"already_migrated": True}
        with target.transaction() as tx:
            assert not student_access(tx, reader, "s1")
            with pytest.raises(HTTPException):
                require_staff(tx, reader, "report.read")
            assert tx.one("SELECT password_hash FROM identity_student_credentials WHERE school_id=? AND actor_id='s1'",
                          (school,))["password_hash"] == "changed"
            assert tx.one("SELECT COUNT(*) AS n FROM identity_audit WHERE school_id=?", (school,))["n"] == 2
        with source.transaction() as tx:
            # 全局安全流水仍归来源审计系统保管。
            assert tx.one("SELECT id FROM security_audit_events") == {"id":"shared-audit"}
        assert file_hash(path) == original
    with target.transaction() as tx:
        assert tx.all("""SELECT school_id,actor_type FROM identity_staff WHERE actor_id='instructor'
                         ORDER BY school_id""") == [
            {"school_id":"east","actor_type":"teacher"}, {"school_id":"west","actor_type":"admin"}]


def test_foreign_permission_request_rolls_back_whole_cutover_and_retry_succeeds(tmp_path, monkeypatch):
    source = snapshot(tmp_path / "legacy.sqlite")
    target = store(tmp_path / "target.sqlite")
    monkeypatch.setenv("LEGACY_SCHOOL_ID", "east")
    with source.transaction(write=True) as tx:
        tx.execute("ALTER TABLE admin_permission_requests ADD COLUMN school_id TEXT")
        tx.execute("UPDATE admin_permission_requests SET school_id='west'")
    with pytest.raises(ValueError):
        migrate(source, target, "east", "Master@example.edu")
    # 末尾校验失败时，允许 DDL 已提交；账号、归档、日志和完成标记必须全部回滚。
    with target.transaction() as tx:
        for table in ("identity_staff", "identity_student_credentials", "org_colleges", "org_staff_classes",
                      "org_enrollments", "identity_legacy_organization", "identity_audit",
                      "org_legacy_migration", "identity_legacy_permission_requests", "identity_cutover"):
            assert tx.one(f"SELECT COUNT(*) AS n FROM {table}") == {"n":0}, table
    with source.transaction(write=True) as tx:
        tx.execute("UPDATE admin_permission_requests SET school_id='east'")
    assert migrate(source, target, "east", "Master@example.edu")["staff"] == 3


def test_reject_same_database_before_schema_creation(tmp_path, monkeypatch):
    path = tmp_path / "source.sqlite"
    source = snapshot(path)
    alias = tmp_path / "target.sqlite"
    os.link(path, alias)
    monkeypatch.setenv("LEGACY_SCHOOL_ID", "east")
    original = file_hash(path)
    with pytest.raises(ValueError, match="separate"):
        migrate(source, store(alias), "east", "Master@example.edu")
    assert file_hash(path) == original


def test_snapshot_predating_grant_columns_starts_without_implicit_scope(tmp_path, monkeypatch):
    source = snapshot(tmp_path / "oldest.sqlite", old_roles=True)
    target = store(tmp_path / "target.sqlite")
    monkeypatch.setenv("LEGACY_SCHOOL_ID", "east")
    with source.transaction(write=True) as tx:
        tx.execute("ALTER TABLE admin_users DROP COLUMN permissions")
        tx.execute("ALTER TABLE admin_users DROP COLUMN student_scope")
    migrate(source, target, "east", "Master@example.edu")
    with target.transaction() as tx:
        assert tx.all("SELECT * FROM org_staff_classes") == []
        account = tx.one("SELECT actor_type,school_wide,permissions FROM identity_staff WHERE actor_id='instructor'")
        assert account == {"actor_type":"admin","school_wide":0,"permissions":"[]"}


def test_registration_backfill_preserves_history_and_excludes_old_passwords(tmp_path, monkeypatch):
    """已有账号保持原编号，旧名单软删除保留；重跑不覆盖人工修正或导入临时凭据。"""
    src, dst = snapshot(tmp_path/"source.sqlite"), store(tmp_path/"target.sqlite")
    monkeypatch.setenv("LEGACY_SCHOOL_ID", "east")
    with src.transaction(write=True) as tx:
        tx.execute("ALTER TABLE users ADD COLUMN counselor TEXT")
        tx.execute("UPDATE users SET counselor='辅导员旧值' WHERE id='s1'")
        tx.execute("ALTER TABLE student_registrations ADD COLUMN temporary_password TEXT")
        tx.execute("UPDATE student_registrations SET temporary_password='绝不迁出的口令'")
    migrate(src, dst, "east", "Master@example.edu")
    with dst.transaction(write=True) as tx:
        row = tx.one("SELECT * FROM identity_registrations WHERE school_id='east' AND actor_id='s1'")
        assert row["archived"] == 1 and row["opened"] == 1 and row["counselor"] == "辅导员旧值"
        archive = tx.one("SELECT legacy_record FROM identity_legacy_organization WHERE school_id='east' AND source_table='student_registrations'")
        assert "temporary_password" not in archive["legacy_record"] and "绝不迁出的口令" not in archive["legacy_record"]
        tx.execute("UPDATE identity_registrations SET counselor='人工修正' WHERE actor_id='s1'")
    migrate(src, dst, "east", "Master@example.edu")
    with dst.transaction() as tx:
        assert tx.one("SELECT counselor FROM identity_registrations WHERE actor_id='s1'")["counselor"] == "人工修正"
