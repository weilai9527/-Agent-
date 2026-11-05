"""在一次性数据库中复现目标库误配以及旧组织表在分页边界隐藏外校数据的情况。"""

import sqlite3
from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from services.career.migrate import migrate
from services.profile.app import app


@pytest.fixture
def paths(monkeypatch, tmp_path):
    source, target = tmp_path/"legacy.sqlite", tmp_path/"destination.sqlite"
    for name,value in {
        "LEGACY_SOURCE_DB_ENGINE":"sqlite", "LEGACY_SOURCE_SQLITE_PATH":str(source),
        "PROFILE_DB_ENGINE":"sqlite", "PROFILE_SQLITE_PATH":str(target), "LEGACY_SCHOOL_ID":"A",
    }.items():
        monkeypatch.setenv(name,value)
    return source, target


def legacy_settings(db):
    db.execute("CREATE TABLE resume_form_settings(id TEXT PRIMARY KEY, updated_at TEXT, colleges TEXT)")
    db.execute("""INSERT INTO resume_form_settings VALUES ('options','2026-01-01','[{"name":"原学校学院"}]')""")


@pytest.mark.parametrize("marker", ["campus_colleges","campus_programs","campus_classes","student_enrollments",
                                   "student_registrations","org_staff_classes"])
@pytest.mark.parametrize("school_value", ["B","a",None])
def test_school_evidence_outside_settings_table_blocks_writes(paths,marker,school_value):
    source, target = paths
    with closing(sqlite3.connect(source)) as old:
        legacy_settings(old)
        # 学校线索未必与简历同表，也未必有可用于分页的 id 列。
        old.execute(f"CREATE TABLE {marker} (school_id TEXT COLLATE NOCASE)")
        old.execute(f"INSERT INTO {marker} VALUES (?)", (school_value,))
        old.commit()
    with pytest.raises(ValueError, match="Mixed or unidentified"):
        migrate("profile-settings","A")
    assert not target.exists()


@pytest.mark.parametrize("service",["profile-settings","profile","career"])
def test_composite_keys_cannot_hide_other_school_at_page_boundary(paths,service,monkeypatch):
    source, target = paths
    for name,value in {"CAREER_DB_ENGINE":"sqlite","CAREER_SQLITE_PATH":str(target),"CAREER_SCHOOL_ID":"A"}.items():
        monkeypatch.setenv(name,value)
    with closing(sqlite3.connect(source)) as old:
        # 第 250 行是 A/z；旧的 WHERE id > 'z' 游标会跳过下一行 B/z。
        old.execute("CREATE TABLE users (school_id TEXT COLLATE NOCASE, id TEXT, PRIMARY KEY(school_id,id))")
        old.executemany("INSERT INTO users VALUES ('A',?)", [(f"x{i:03}",) for i in range(249)])
        old.executemany("INSERT INTO users VALUES (?,'z')", [("A",),("B",)])
        old.execute("CREATE TABLE profiles(id TEXT PRIMARY KEY,user_id TEXT)")
        old.execute("CREATE TABLE job_postings(id TEXT PRIMARY KEY)")
        legacy_settings(old)
        old.commit()
    with pytest.raises(ValueError,match="Mixed or unidentified"):
        migrate(service,"A")
    assert not target.exists()


def test_no_school_markers_accepts_explicit_school_even_when_settings_are_separate(paths):
    source, target = paths
    with closing(sqlite3.connect(source)) as old:
        legacy_settings(old)
        old.commit()
    assert migrate("profile-settings","A") == {"form_settings":"imported"}
    with closing(sqlite3.connect(target)) as db:
        assert db.execute("SELECT school_id FROM profile_school_form_settings").fetchall()==[("A",)]


@pytest.mark.parametrize("operation",["startup","profile-settings","profile"])
def test_foreign_target_is_unchanged_before_first_profile_ddl(paths,operation):
    source, target = paths
    with closing(sqlite3.connect(target)) as db:
        db.execute("CREATE TABLE users(id TEXT PRIMARY KEY)")
        db.execute("INSERT INTO users VALUES ('unchanged')")
        db.commit()
    with closing(sqlite3.connect(source)) as old:
        legacy_settings(old)
        old.execute("CREATE TABLE users(id TEXT PRIMARY KEY)")
        old.execute("CREATE TABLE profiles(id TEXT PRIMARY KEY,user_id TEXT)")
        old.commit()
    previous_bytes=target.read_bytes()
    with pytest.raises(ValueError,match="独立"):
        if operation=="startup":
            with TestClient(app):
                pass
        else:
            migrate(operation,"A")
    assert target.read_bytes()==previous_bytes


def test_duplicate_cursor_or_current_owner_cannot_be_silently_skipped(paths):
    from services.career.migrate import pages
    from shared.service_db import ServiceDatabase

    source, target = paths
    with closing(sqlite3.connect(source)) as old:
        old.execute("CREATE TABLE users(id TEXT PRIMARY KEY)")
        old.execute("INSERT INTO users VALUES ('student')")
        old.execute("CREATE TABLE profiles(id TEXT, user_id TEXT)")
        old.executemany("INSERT INTO profiles VALUES ('z','student')", [(),()])
        old.commit()
    with ServiceDatabase.from_env("legacy_source").transaction() as tx:
        with pytest.raises(ValueError,match="Non-unique"):
            list(pages(tx,"profiles"))
    with pytest.raises(ValueError,match="unique student record"):
        migrate("profile","A")
    assert not target.exists()


@pytest.mark.parametrize("operation",["startup","profile-settings"])
def test_profile_named_view_is_rejected_before_ddl(paths,operation):
    source, target = paths
    with closing(sqlite3.connect(source)) as old:
        legacy_settings(old)
        old.commit()
    with closing(sqlite3.connect(target)) as db:
        db.execute("CREATE VIEW profile_versions AS SELECT 1 AS version")
        db.commit()
    previous=target.read_bytes()
    with pytest.raises(ValueError,match="独立"):
        if operation=="startup":
            with TestClient(app):
                pass
        else:
            migrate(operation,"A")
    assert previous==target.read_bytes()
