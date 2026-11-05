"""使用生成的学校数据测试迁移，整个过程只打开临时数据库。"""
import json
import sqlite3
from contextlib import closing

import pytest

from services.career.migrate import migrate
from shared.career_catalog import ensure_catalog_schema, seed_computer_pilot
from shared.recruitment import ensure_recruitment_schema


@pytest.fixture
def legacy(tmp_path, monkeypatch):
    path = tmp_path / "legacy.sqlite"
    for key, value in {
        "LEGACY_SCHOOL_ID": "school-A", "LEGACY_SOURCE_DB_ENGINE": "sqlite",
        "LEGACY_SOURCE_SQLITE_PATH": str(path), "PROFILE_DB_ENGINE": "sqlite",
        "PROFILE_SQLITE_PATH": str(tmp_path/"profile.sqlite"), "CAREER_SCHOOL_ID": "school-A",
        "CAREER_SQLITE_PATH": str(tmp_path/"career.sqlite"), "CAREER_DB_ENGINE": "sqlite",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("CAREER_SCHOOL_DATABASES", raising=False)
    with closing(sqlite3.connect(path)) as conn:
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE users(id TEXT PRIMARY KEY, school_id TEXT);
            CREATE TABLE profiles(id TEXT PRIMARY KEY, user_id TEXT UNIQUE, nickname TEXT);
            CREATE TABLE resume_forms(id TEXT PRIMARY KEY, user_id TEXT UNIQUE, skills TEXT);
            INSERT INTO users VALUES('student-1','school-A');
            INSERT INTO profiles VALUES('profile-1','student-1','旧名字');
            INSERT INTO resume_forms VALUES('form-1','student-1','Python');
        """)
        ensure_catalog_schema(conn, "sqlite")
        seed_computer_pilot(conn)
        ensure_recruitment_schema(conn, "sqlite")
        conn.execute("INSERT INTO job_matches(id,user_id,result_json) VALUES ('m1','student-1','{}')")
        conn.commit()
        yield conn, tmp_path


def test_migration_keeps_ids_snapshots_and_receipts(legacy):
    source, folder = legacy
    assert migrate("profile", "school-A") == {"imported": 1, "already_present": 0}
    assert migrate("profile", "school-A")["already_present"] == 1
    with closing(sqlite3.connect(folder/"profile.sqlite")) as conn:
        profile, form = conn.execute("SELECT profile,form FROM profile_versions").fetchone()
        assert json.loads(profile)["id"] == "profile-1" and json.loads(form)["skills"] == "Python"
    counts = migrate("career", "school-A")["imported"]
    assert counts["catalog_versions"] and counts["job_matches"] == 1
    assert migrate("career", "school-A") == {"already_imported": counts}
    with closing(sqlite3.connect(folder/"career.sqlite")) as conn:
        assert conn.execute("SELECT id,user_id FROM job_matches").fetchall() == [("m1", "student-1")]
        assert conn.execute("SELECT id FROM catalog_versions").fetchone() == tuple(source.execute("SELECT id FROM catalog_versions").fetchone())


@pytest.mark.parametrize("service", ["profile", "career"])
def test_mixed_source_fails_before_copy(legacy, service):
    source, folder = legacy
    source.execute("INSERT INTO users VALUES('foreign','school-a')")
    source.commit()
    with pytest.raises(ValueError, match="Mixed or unidentified"):
        migrate(service, "school-A")
    assert not (folder/(service+".sqlite")).exists()


def test_career_abort_rolls_back_prior_table_inserts(legacy):
    source, folder = legacy
    source.execute("ALTER TABLE job_matches ADD COLUMN unexpected_private_field TEXT")
    source.commit()
    with pytest.raises(ValueError, match="Unsupported source schema"):
        migrate("career", "school-A")
    with closing(sqlite3.connect(folder/"career.sqlite")) as conn:
        assert not conn.execute("SELECT id FROM catalog_versions").fetchone()
        assert not conn.execute("SELECT id FROM career_legacy_copy").fetchone()


def test_career_unknown_student_is_not_reassigned(legacy):
    source, folder = legacy
    source.execute("UPDATE job_matches SET user_id='STUDENT-1'")
    source.commit()
    with pytest.raises(ValueError, match="Cannot establish student ownership"):
        migrate("career", "school-A")
    assert not (folder/"career.sqlite").exists()


def test_private_profile_migration_cannot_copy_between_case_distinct_users(legacy):
    source, folder = legacy
    source.executescript("""
        INSERT INTO users VALUES ('STUDENT-1','school-A');
        DROP TABLE profiles;
        CREATE TABLE profiles(id TEXT PRIMARY KEY, user_id TEXT COLLATE NOCASE UNIQUE, nickname TEXT);
        INSERT INTO profiles VALUES ('private-profile','student-1','仅此学生可见');
    """)
    assert migrate("profile", "school-A") == {"imported": 1, "already_present": 0}
    with closing(sqlite3.connect(folder/"profile.sqlite")) as target:
        assert target.execute("SELECT actor_id FROM profile_versions").fetchall() == [("student-1",)]


def test_untrusted_source_view_cannot_supply_profiles(legacy):
    source, folder = legacy
    source.executescript("""
        DROP TABLE profiles;
        CREATE VIEW profiles AS SELECT 'id' AS id, 'student-1' AS user_id, '伪造档案' AS nickname;
    """)
    with pytest.raises(ValueError, match="Unexpected view"):
        migrate("profile", "school-A")
    assert not (folder/"profile.sqlite").exists()
