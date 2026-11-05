"""检查职业库接管边界，SQLite 用独立库并记录实际执行的 SQL。"""
from contextlib import closing
import sqlite3
from unittest.mock import Mock

import pytest

from shared.service_db import ServiceDatabase
from services.career.store import _check_destination, _OWNED_TABLES, ensure_school


@pytest.fixture
def database(tmp_path, monkeypatch):
    path = tmp_path / "career.sqlite"
    monkeypatch.delenv("CAREER_SCHOOL_DATABASES", raising=False)
    monkeypatch.setenv("CAREER_DB_ENGINE", "sqlite")
    monkeypatch.setenv("CAREER_SQLITE_PATH", str(path))
    monkeypatch.setenv("CAREER_SCHOOL_ID", "school-A")
    return path


MARKER = "CREATE TABLE career_owner(id INTEGER PRIMARY KEY, school_id TEXT NOT NULL);"
BOUND = MARKER + "INSERT INTO career_owner VALUES(1, 'school-A');"


@pytest.mark.parametrize("ddl", [
    "CREATE TABLE sqliteX_accounts(id INTEGER);",
    "CREATE VIEW candidate_rows AS SELECT 1;",
    "CREATE VIEW career_owner AS SELECT 1 AS id, 'school-A' AS school_id;",
    BOUND + "CREATE TABLE users(id TEXT);",
    BOUND + "CREATE TABLE admin_users(id TEXT);",
    BOUND + "CREATE TABLE career_extra(id INTEGER);",
    BOUND + "CREATE VIEW job_postings AS SELECT 1;",
    BOUND + "CREATE VIEW private_students AS SELECT 1;",
    MARKER + "INSERT INTO career_owner VALUES(1, 'school-a');",
    BOUND + "INSERT INTO career_owner VALUES(2, 'school-B');",
    MARKER + "CREATE TABLE job_matches(id TEXT);",
])
def test_foreign_schema_rejected_before_first_ddl(database, monkeypatch, ddl):
    with closing(sqlite3.connect(database)) as db:
        db.executescript(ddl)
    seen = []
    connect = ServiceDatabase._connect

    def traced(store):
        conn = connect(store)
        conn.set_trace_callback(seen.append)
        return conn

    monkeypatch.setattr(ServiceDatabase, "_connect", traced)
    with pytest.raises(ValueError):
        ensure_school("school-A", seed=True)
    assert not any(sql.lstrip().upper().startswith(("CREATE ", "ALTER ", "DROP ", "INSERT ", "UPDATE ", "DELETE "))
                   for sql in seen)


def test_partial_initialization_and_previous_service_version_can_resume(database):
    with closing(sqlite3.connect(database)) as db:
        # 删除测试用自增表后，SQLite 仍保留自己的 sqlite_sequence。
        db.executescript("CREATE TABLE t(id INTEGER PRIMARY KEY AUTOINCREMENT); DROP TABLE t;" + MARKER)
    ensure_school("school-A", seed=True)
    with closing(sqlite3.connect(database)) as db:
        old = db.execute("SELECT id FROM catalog_versions").fetchall()
        assert old
        db.executescript("""CREATE TABLE career_legacy_copy (id INTEGER PRIMARY KEY, counts_json TEXT NOT NULL);
                            INSERT INTO career_legacy_copy VALUES(1, '{}');
                            DROP TABLE career_program_job_state;
                            DROP TABLE program_job_roles;
                            ANALYZE;""")
    ensure_school("school-A", seed=True)
    with closing(sqlite3.connect(database)) as db:
        assert db.execute("SELECT id FROM catalog_versions").fetchall() == old
        assert db.execute("SELECT counts_json FROM career_legacy_copy").fetchall() == [("{}",)]
        tables = {row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT GLOB 'sqlite_*'")}
        # 如果领域新增表，实际建表结果与白名单须同步更新。
        assert tables == _OWNED_TABLES


@pytest.mark.parametrize(("name", "kind", "accepted"), [
    ("career_legacy_copy", "BASE TABLE", True),
    ("program_job_roles", "BASE TABLE", True),
    ("job_matches", "VIEW", False),
    ("identity_staff", "BASE TABLE", False),
    ("Job_Matches", "BASE TABLE", False),
])
def test_mysql_schema_and_object_type_are_exact(name, kind, accepted):
    tx = Mock()
    tx.all.side_effect = [
        [{"name": "career_owner", "kind": "BASE TABLE"}, {"name": name, "kind": kind}],
        [{"id": 1, "school_id": "A"}],
    ]
    if accepted:
        _check_destination(tx, "mysql", "A")
    else:
        with pytest.raises(ValueError, match="foreign"):
            _check_destination(tx, "mysql", "A")
        assert tx.all.call_count == 1  # 遇到外来对象时连学校绑定表也不读取。
    metadata = tx.all.call_args_list[0].args[0]
    assert "TABLE_TYPE AS kind" in metadata
    assert "BINARY TABLE_SCHEMA=BINARY DATABASE()" in metadata
