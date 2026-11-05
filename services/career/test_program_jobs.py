"""用临时校库验证专业可见性、岗位发布、并发更新和历史关联迁移。"""
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest
from fastapi import HTTPException
from services.career import program_jobs
from services.career.migrate import migrate
from services.career.store import transaction
from services.career.test_career import api
from services.career.test_migrate import legacy


INDEX = "/v1/admin/campus/program-jobs"
WRITE = "/v1/admin/campus/programs/Program/jobs"


@pytest.fixture
def options(api, monkeypatch):
    async def identity(service, method, path, *, actor, scope):
        assert (service, method) == ("identity", "GET")
        assert path == "/internal/staff/program-job-options" + ("/write" if scope == "program_jobs.write" else "")
        assert scope in ("program_jobs.read", "program_jobs.write")
        return {**actor, "colleges": [{"id": "college", "name": actor["school_id"] + "学院"}],
                "programs": [{"id": "Program", "name": "软件", "college_id": "college", "canEdit": actor["actor_type"] == "admin"}],
                "canEdit": actor["actor_type"] == "admin"}
    monkeypatch.setattr(program_jobs, "request_json", identity)
    def read(**args):
        return api("GET", INDEX, "program_jobs.read", role=args.pop("role", "admin"), **args)
    def write(body, path=WRITE, **args):
        return api("PUT", path, "program_jobs.write", role=args.pop("role", "admin"), json=body, **args)
    return read, write


def test_scope_revision_and_published_jobs(options):
    read, write = options
    data = read().json()
    assert data["canEdit"] and data["school_id"] == "a" and data["programs"][0]["revision"] == 0
    assert data["publishedVersion"]["status"] == "published"
    job = data["jobs"][0]
    response = write({"jobs": [{"jobRoleId": job["id"], "priority": "optional"}], "expectedRevision": 0})
    assert response.status_code == 200 and response.json()["revision"] == 1
    updated = read().json()["programs"][0]
    assert updated["jobs"] == [{"job_role_id": job["id"], "priority": "optional", "job_name": job["name"]}]
    assert read(school="b").json()["programs"][0]["jobs"] == []
    assert write({"jobRoleIds": [job["id"]]}, school="b").status_code == 400
    assert write({"jobs": []}, path=WRITE.replace("Program", "program")).status_code == 404
    assert not read(role="teacher").json()["canEdit"]
    assert write({"jobs": []}, role="teacher").status_code == 403
    assert write({"jobs": [], "expectedRevision": 0}).status_code == 409
    assert write({"jobRoleIds": [job["id"], job["id"]]}).json()["jobs"] == [
        {"jobRoleId": job["id"], "priority": "recommended"}]
    with transaction("a", write=True) as db:
        db.tx.execute("UPDATE catalog_job_roles SET enabled=0 WHERE id=?", (job["id"],))
    unavailable = read().json()
    assert job["id"] not in {r["id"] for r in unavailable["jobs"]}
    assert unavailable["programs"][0]["jobs"][0]["job_name"] is None
    assert write({"jobRoleIds": [job["id"]]}).status_code == 400
    assert write({"jobs": []}).status_code == 200


@pytest.mark.parametrize("body", [{}, {"jobs": None}, {"jobRoleIds": [], "jobs": []}, {"jobs": [{"jobRoleId": ""}]},
                                  {"jobs": [{"jobRoleId": "x"}, {"jobRoleId": "x"}]}, {"jobs": [], "school_id": "b"},
                                  {"jobs": [], "expectedRevision":True}, {"jobRoleIds":["x"]*51}])
def test_bad_request_does_not_clear_mappings(options, body):
    read, write = options
    job = read().json()["jobs"][0]["id"]
    assert write({"jobRoleIds": [job]}).status_code == 200
    assert write(body).status_code == 422
    assert read().json()["programs"][0]["jobs"][0]["job_role_id"] == job


def test_compare_and_swap_with_parallel_editors(options):
    read, write = options
    jobs = read().json()["jobs"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(lambda job: write({"jobRoleIds": [job["id"]], "expectedRevision": 0}), jobs[:2]))
    assert sorted(r.status_code for r in replies) == [200, 409]
    assert read().json()["programs"][0]["revision"] == 1


@pytest.mark.parametrize("mode,expected", [("wrong-school", 502), ("wrong-actor", 502), ("wrong-type", 502),
                                          ("hidden", 404), ("per-program", 403), ("incomplete-grant", 502), ("outage", 503)])
def test_bad_identity_response_cannot_write(options, monkeypatch, mode, expected):
    _, write = options
    async def rejected(*a, actor, **kwargs):
        if mode == "outage":
            raise HTTPException(503, "身份服务离线")
        reply = {**actor, "canEdit": True, "colleges": [{"id":"a", "name":"学院"}], "programs": []}
        if mode != "hidden":
            reply["programs"].append({"id":"Program", "college_id":"a", "name":"专业", "canEdit":mode != "per-program"})
        if mode == "incomplete-grant":
            del reply["programs"][0]["canEdit"]
        if mode in ("wrong-school", "wrong-actor", "wrong-type"):
            reply[{"wrong-school":"school_id","wrong-actor":"actor_id","wrong-type":"actor_type"}[mode]] = "wrong"
        return reply
    monkeypatch.setattr(program_jobs,"request_json",rejected)
    assert write({"jobs":[]}).status_code == expected
    with transaction("a") as db:
        assert not db.tx.one("SELECT revision FROM career_program_job_state LIMIT 1")


def test_profile_settings_projection_has_only_active_published_fields(api):
    path = "/internal/resume-form/catalog"
    r = api("GET", path, "catalog.read", caller="profile").json()
    assert set(r) == {"school_id", "colleges"} and r["school_id"] == "a"
    college = r["colleges"][0]
    assert set(college) == {"id", "name", "majors"} and set(college["majors"][0]) == {"id","name"}
    assert api("GET", path, "catalog.read", role="system").status_code == 403
    assert api("GET", path, "catalog.read").status_code == 403
    with transaction("a", write=True) as db:
        db.tx.execute("UPDATE catalog_majors SET enabled=0 WHERE id=?", (college["majors"][0]["id"],))
    new = api("GET", path, "catalog.read", caller="profile").json()["colleges"][0]
    assert college["majors"][0]["id"] not in {m["id"] for m in new["majors"]}
    with transaction("a", write=True) as db:
        db.tx.execute("UPDATE catalog_versions SET status='draft'")
    assert api("GET", path, "catalog.read", caller="profile").json() == {"school_id":"a","colleges":[]}


def old_mappings(source, school="school-A", program="p1"):
    source.executescript("""
        CREATE TABLE campus_programs(id TEXT PRIMARY KEY,school_id TEXT);
        CREATE TABLE program_job_roles(id TEXT PRIMARY KEY,program_id TEXT,job_role_id TEXT,priority TEXT,created_at TEXT);
    """)
    source.execute("INSERT INTO campus_programs VALUES ('p1', ?)", (school,))
    source.execute("INSERT INTO program_job_roles VALUES ('old-map', ?, 'removed-role', 'optional','2020-01-01')", (program,))
    source.commit()


@pytest.mark.parametrize("old_receipt", [False,True])
def test_history_copied_once_including_previously_migrated_school(legacy, old_receipt):
    source, folder = legacy
    if old_receipt:
        assert "program_job_roles" not in migrate("career", "school-A")["imported"]
    old_mappings(source)
    assert migrate("career", "school-A")["imported"]["program_job_roles"] == 1
    assert migrate("career", "school-A")["already_imported"]["program_job_roles"] == 1
    with closing(sqlite3.connect(folder / "career.sqlite")) as dest:
        assert dest.execute("SELECT * FROM program_job_roles").fetchall() == [
            ("old-map", "p1", "removed-role", "optional", "2020-01-01")]
        assert dest.execute("SELECT * FROM career_program_job_state").fetchall() == [("p1", 1)]


@pytest.mark.parametrize("school,program", [("school-a","p1"),("school-A","P1")])
def test_migration_requires_exact_program_owner(legacy, school, program):
    source, folder = legacy
    old_mappings(source, school, program)
    with pytest.raises(ValueError):
        migrate("career", "school-A")
    assert not (folder/"career.sqlite").exists()


def test_supplemental_migration_never_overwrites_native_decision(legacy):
    source, _ = legacy
    migrate("career","school-A")
    old_mappings(source)
    with transaction("school-A", write=True) as db:
        db.tx.execute("INSERT INTO career_program_job_state(program_id,revision) VALUES ('p1',3)")
    with pytest.raises(ValueError, match="无法安全补迁"):
        migrate("career","school-A")
    with transaction("school-A") as db:
        assert db.tx.one("SELECT revision FROM career_program_job_state WHERE program_id='p1'")["revision"] == 3
        assert not db.tx.one("SELECT id FROM program_job_roles")


def test_concurrent_supplemental_migration_has_one_receipt(legacy):
    source, _ = legacy
    migrate("career", "school-A")
    old_mappings(source)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: migrate("career", "school-A"), range(2)))
    assert sum(r.get("imported", {}).get("program_job_roles", 0) for r in results) == 1
    with transaction("school-A") as db:
        assert db.tx.one("SELECT COUNT(*) n FROM program_job_roles")["n"] == 1
        assert db.tx.one("SELECT revision FROM career_program_job_state WHERE program_id='p1'")["revision"] == 1
