"""使用真实 Ed25519 签名及按学校隔离的临时数据库测试接口。"""
import io
import json
import time
from uuid import uuid4
from zipfile import ZipFile

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi import HTTPException
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook

from services.career import matches, postings
from services.career.app import app
from services.career.store import ensure_school, school_databases, transaction


@pytest.fixture
def api(tmp_path, monkeypatch):
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode()
    admin = ["posting.admin.read", "posting.write", "posting.delete", "posting.import", "posting.sync",
             "jd.read", "jd.write", "jd.approve", "jd.delete", "match.admin.read", "catalog.admin.read",
             "catalog.write", "catalog.publish", "catalog.review", "catalog.import", "program_jobs.read", "program_jobs.write"]
    grants = {"admin": admin, "teacher": admin, "student": ["posting.read", "match.create", "match.read",
              "catalog.read", "catalog.enrich", "catalog.suggest"], "system": ["catalog.read"]}
    policy = {"gateway": {"keys": {"test": public}, "schools": ["a", "b"], "grants": {"career": grants}}}
    policy["profile"] = {"keys": {"test": public}, "schools": ["a", "b"], "grants": {"career": {"student": ["catalog.read"]}}}
    monkeypatch.setenv("SERVICE_ID", "career")
    monkeypatch.setenv("SERVICE_TRUST_POLICY", json.dumps(policy))
    monkeypatch.setenv("CAREER_DB_ENGINE", "sqlite")
    monkeypatch.setenv("CAREER_SCHOOL_DATABASES", json.dumps({s: str(tmp_path / f"{s}.db") for s in "ab"}))
    with TestClient(app) as client:
        def call(method, path, action, *, user="student1", school="a", role="student", caller="gateway", **kwargs):
            now = int(time.time())
            token = jwt.encode({"iss": caller, "sub": user, "school_id": school, "actor_type": role,
                                "scopes": [action], "aud": "career", "iat": now, "exp": now + 45,
                                "jti": str(uuid4())}, key, algorithm="EdDSA",
                               headers={"kid": "test", "typ": "service+jwt"})
            return client.request(method, path, headers={"Authorization": f"Bearer {token}"}, **kwargs)
        yield call


def test_school_and_published_catalog(api):
    path = "/v1/admin/catalog/versions"
    reply = api("POST", path, "catalog.write", role="admin", json={"code": "a-private", "name": "draft"})
    assert reply.status_code == 201, reply.text
    private = reply.json()["version"]["id"]
    assert api("GET", "/v1/catalog/tree?version=a-private", "catalog.read").status_code == 404
    assert api("GET", "/v1/admin/catalog/tree?version=a-private", "catalog.admin.read", role="admin",
               school="b").status_code == 404
    assert api("POST", f"{path}/{private}/publish", "catalog.write", role="admin").status_code == 403
    assert api("GET", "/v1/catalog/tree", "catalog.read").json()["colleges"]
    assert api("GET", "/v1/catalog/tree", "catalog.read", school="z").status_code == 403
    assert api("GET", "/v1/admin/catalog/versions", "catalog.read").status_code == 403


def test_duplicate_suggestion_and_review(api):
    payload = {"names": ["太空星舰测绘师"], "record": True, "event_id": "hash"}
    for _ in range(2):
        response = api("POST", "/v1/catalog/suggestions", "catalog.suggest", json=payload)
        assert response.status_code == 200, response.text
    assert api("POST", "/v1/catalog/directions", "catalog.enrich", json=payload).status_code == 400
    path = "/v1/admin/catalog/job-suggestions"
    result = api("GET", path, "catalog.admin.read", role="admin").json()["suggestions"]
    assert len(result) == 1 and result[0]["occurrence_count"] == 1
    review = f"{path}/{result[0]['id']}/review"
    assert api("POST", review, "catalog.review", role="admin", school="b", json={"status": "approved"}).status_code == 404
    assert api("POST", review, "catalog.review", role="admin", json={"status": "approved"}).json()["suggestion"]["review_status"] == "approved"


async def snapshot(service, method, path, *, actor, scope):
    assert (service, method, path, scope) == ("profile", "GET", "/api/profile/versions/current", "profile.snapshot.read")
    return {**actor, "version": 3, "profile": {"user_id": actor["actor_id"], "resume_text": "Python SQL privacy-marker-42"}}


def test_private_match_and_review(api, monkeypatch):
    monkeypatch.setattr(matches, "request_json", snapshot)
    jd = "Python and SQL developer with a background in databases"
    path = "/v1/job-matches"
    for student in ("student1", "student2"):
        reply = api("POST", path, "match.create", user=student, json={"jd_text": jd})
        assert reply.status_code == 201, reply.text
        record = reply.json()["job_match"]
        assert record["result"]["profileVersion"] == 3 and "privacy-marker" not in reply.text
    record_id = record["id"]
    assert api("GET", path + "/" + record_id, "match.read", user="student1").status_code == 404
    assert api("GET", path + "/" + record_id, "match.read", user="student2", school="b").status_code == 404
    path = "/v1/admin/job-matches"
    scoped = {"student_ids": ["student1"]}
    rows = api("GET", path + "?limit=1", "match.admin.read", role="teacher", json=scoped).json()["matches"]
    assert [r["user_id"] for r in rows] == ["student1"]
    assert api("GET", path + "/" + record_id, "match.admin.read", role="teacher", json=scoped).status_code == 404
    assert api("GET", path, "match.admin.read", role="teacher", json={"student_ids": None}).status_code == 403
    assert api("GET", path, "match.admin.read", role="admin").status_code == 422
    path = "/v1/admin/jd-submissions"
    jds = api("GET", path, "jd.read", role="admin", json=scoped).json()["submissions"]
    assert len(jds) == 1
    update = path + "/" + jds[0]["id"]
    denied = api("PUT", update, "jd.write", role="admin", json={**scoped, "payload": {"status": " Approved "}})
    assert denied.status_code == 409
    approve = update + "/approve"
    assert api("POST", approve, "jd.approve", role="admin", json={"student_ids": []}).status_code == 404
    for _ in range(2):
        assert api("POST", approve, "jd.approve", role="admin", json=scoped).status_code == 200
    published = api("GET", "/v1/job-postings", "posting.read").json()["postings"]
    assert len(published) == 1
    assert api("GET", "/v1/job-postings", "posting.read", school="b").json()["postings"] == []


def test_snapshot_failure_and_invalid_input(api, monkeypatch):
    path = "/v1/job-matches"
    for bad in ({"jd_text": "short"}, {"jd_text": "j" * 20001}, {"resume_text": "injected"}):
        assert api("POST", path, "match.create", json=bad).status_code in {400, 422}
    async def unavailable(*args, **kwargs):
        raise HTTPException(503, "Profile unavailable")
    monkeypatch.setattr(matches, "request_json", unavailable)
    assert api("POST", path, "match.create", json={"jd_text": "j" * 20}).status_code == 503
    async def wrong_owner(*args, **kwargs):
        return {"school_id": "b", "actor_id": "student1", "profile": {"user_id": "student1"}, "version": 1}
    monkeypatch.setattr(matches, "request_json", wrong_owner)
    assert api("POST", path, "match.create", json={"jd_text": "j" * 20}).status_code == 502
    assert api("GET", path, "match.read").json()["matches"] == []


def test_sync_and_spreadsheet(api, monkeypatch):
    incoming = [{"title": "Python engineer", "id": "1"}]
    monkeypatch.setenv("JOB_POSTING_SYNC_SCHOOL_ID", "a")
    monkeypatch.setenv("JOB_POSTING_SYNC_ENDPOINT", "https://configured.invalid/test")
    monkeypatch.setattr(postings, "fetch_job_feed", lambda: incoming)
    path = "/v1/admin/job-postings"
    for school, payload, status in (("b", None, 400), ("a", {"url": "http://evil/"}, 400)):
        assert api("POST", path + "/sync", "posting.sync", role="admin", school=school, json=payload).status_code == status
    for count in ("created", "updated"):
        assert api("POST", path + "/sync", "posting.sync", role="admin").json()[count] == 1
    workbook = Workbook()
    workbook.active.append(["岗位名称", "企业名称"])
    workbook.active.append(["Development", "Acme"])
    stream = io.BytesIO()
    workbook.save(stream)
    upload = {"file": ("data.xlsx", stream.getvalue())}
    assert api("POST", path + "/import", "posting.import", role="admin", files=upload).json()["created"] == 1
    assert api("POST", path, "posting.write", role="admin", json={"title": "=1+1"}).status_code == 201
    exported = api("GET", path + "/export", "posting.admin.read", role="admin")
    assert exported.status_code == 200
    sheet = load_workbook(io.BytesIO(exported.content)).active
    assert all(cell.data_type != "f" for row in sheet.iter_rows() for cell in row)


def test_archive_limits_and_malformed_input(api):
    path = "/v1/admin/job-postings/import"
    bomb = io.BytesIO()
    with ZipFile(bomb, "w") as archive:
        archive.writestr("xl/worksheets/sheet1.xml", '<worksheet><dimension ref="A1:XFD1048576"/></worksheet>')
    for data, status in ((bomb.getvalue(), 400), (b"bad", 400), (b"x" * (5 * 1024 * 1024 + 1), 413)):
        assert api("POST", path, "posting.import", role="admin", files={"file": ("test.xlsx", data)}).status_code == status


def test_database_rebinding(api, tmp_path, monkeypatch):
    monkeypatch.setenv("CAREER_SCHOOL_DATABASES", json.dumps({"c": str(tmp_path / "a.db")}))
    with pytest.raises(HTTPException, match="another school"):
        with transaction("c"):
            pass
    monkeypatch.setenv("CAREER_SCHOOL_DATABASES", json.dumps({s: str(tmp_path / "a.db") for s in "ab"}))
    with pytest.raises(ValueError, match="cannot share"):
        school_databases()


def test_catalog_workbook_roundtrip(api):
    draft = api("POST", "/v1/admin/catalog/versions", "catalog.write", role="admin",
                json={"code": "new", "name": "Native draft"}).json()["version"]["id"]
    workbook = Workbook()
    workbook.remove(workbook.active)
    specs = [
        ("学院", ["编码", "名称"], ["C", "Design"]),
        ("专业", ["编码", "名称", "学院编码"], ["M", "UX", "C"]),
        ("培养方向", ["编码", "名称", "专业编码"], ["T", "UX research", "M"]),
        ("就业方向", ["编码", "名称", "培养方向编码"], ["E", "Research", "T"]),
        ("岗位", ["编码", "名称", "就业方向编码"], ["J", "Researcher", "E"]),
        ("能力", ["编码", "名称", "类别"], ["A", "Research", "communication"]),
        ("岗位能力", ["岗位编码", "能力编码", "要求等级", "权重"], ["J", "A", 3, 4]),
    ]
    for name, header, row in specs:
        sheet = workbook.create_sheet(name)
        sheet.append(header)
        sheet.append(row)
    stream = io.BytesIO()
    workbook.save(stream)
    path = f"/v1/admin/catalog/versions/{draft}"
    response = api("POST", path + "/imports", "catalog.import", role="admin",
                   files={"file": ("catalog.xlsx", stream.getvalue())})
    assert response.status_code == 201, response.text
    assert response.json()["import_job"]["imported_rows"] == 7
    assert api("POST", path + "/publish", "catalog.publish", role="admin").status_code == 200
    result = api("GET", "/v1/catalog/tree?version=new", "catalog.read").json()
    assert result["colleges"][0]["majors"][0]["name"] == "UX"
    assert api("GET", "/v1/catalog/tree?version=new", "catalog.read", school="b").status_code == 404


def test_case_sensitive_and_long_owner(api, monkeypatch):
    monkeypatch.setattr(matches, "request_json", snapshot)
    user = "CaseSensitive" + "x"*95
    assert api("POST", "/v1/job-matches", "match.create", user=user, json={"jd_text": "Python engineer with experience"}).status_code == 201
    assert not api("GET", "/v1/job-matches", "match.read", user=user.lower()).json()["matches"]
    jds = api("GET", "/v1/admin/jd-submissions", "jd.read", role="admin", json={"student_ids": [user]}).json()
    assert [r["user_id"] for r in jds["submissions"]] == [user]



def test_refuse_nonempty_legacy_db(tmp_path, monkeypatch):
    import sqlite3
    from contextlib import closing
    path = tmp_path / "foreign.db"
    with closing(sqlite3.connect(path)) as db:
        db.execute("CREATE TABLE job_matches(id TEXT)")
    monkeypatch.setenv("CAREER_DB_ENGINE", "sqlite")
    monkeypatch.setenv("CAREER_SCHOOL_DATABASES", json.dumps({"school": str(path)}))
    with pytest.raises(ValueError, match="empty"):
        ensure_school("school")
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == [("job_matches",)]


def test_candidate_limit_does_not_capture_interview_media():
    from fastapi import FastAPI
    from services.career.limits import BodyLimit
    gateway = FastAPI()
    gateway.add_middleware(BodyLimit, browser_student_only=True)

    @gateway.get("/api/job-matches")
    def private():
        return []

    @gateway.post("/api/interview/media")
    def media():
        return {"ok": True}

    with TestClient(gateway) as client:
        assert client.get("/api/job-matches").headers["cache-control"] == "private, no-store"
        large = {"Content-Length": str(3 * 1024 * 1024)}
        assert client.post("/api/job-matches", headers=large).status_code == 413
        assert client.post("/api/interview/media", headers=large).status_code == 200


def test_advice_only_sends_dictionary_findings_and_cannot_override_score(api, monkeypatch):
    from types import SimpleNamespace
    from services.profile import model_policy

    requests = []
    def answer(messages):
        requests.append(json.dumps(messages, ensure_ascii=False))
        return {"summary": "  改进  测试 ", "strengths": ["可信建议", {}, ""], "matchScore": 100,
                "matrices": [], "provider": "untrusted"}
    def select(school_id, task):
        assert task == "career"
        return SimpleNamespace(provider="trusted" if school_id == "a" else "local", model="named-model", cache_key="key",
                               generate=answer)
    monkeypatch.setattr(model_policy, "select_model", select)
    monkeypatch.setattr(matches, "request_json", snapshot)
    path = "/v1/admin/job-postings"
    body = {"title": "ROLE_PRIVATE", "company": "EMPLOYER_PRIVATE", "requirements": "Use Python JD_PRIVATE",
            "skills": "Python、UNLISTED_PRIVATE"}
    for school in ("a", "b"):
        response = api("POST", path, "posting.write", role="admin", school=school, json=body)
        posting = response.json()["posting"]
        reply = api("POST", "/v1/job-matches", "match.create", school=school, user="SUBJECT_PRIVATE",
                    json={"job_posting_id": posting["id"], "student": {"name": "NAME_PRIVATE"}})
        assert reply.status_code == 201, reply.text
        record = reply.json()["job_match"]
        if school == "a":
            assert record["result"]["summary"] == "改进 测试" and record["result"]["strengths"] == ["可信建议"]
            assert (record["provider"], record["model"]) == ("trusted", "named-model")
            assert record["result"]["provider"] == record["provider"]
            assert record["result"]["matchScore"] == record["match_score"] < 100
            assert record["result"]["matrices"]
        else:
            assert record["provider"] == "local" and record["result"]["fallback"] is False
    assert len(requests) == 1
    assert "Python" in requests[0] and "UNLISTED" not in requests[0]
    assert "PRIVATE" not in requests[0] and "privacy-marker" not in requests[0]


@pytest.mark.parametrize("bad_response", ["timeout", {"matchScore": 100}, {"summary": ["bad"], "gaps": [None]}])
def test_model_failure_saves_only_rule_result(api, monkeypatch, bad_response):
    from types import SimpleNamespace
    from services.profile import model_policy

    def generate(_):
        if bad_response == "timeout":
            raise model_policy.ModelUnavailable("private provider diagnostic")
        return bad_response
    monkeypatch.setattr(model_policy, "select_model", lambda *a, **k: SimpleNamespace(provider="trusted",
                        model="private-model", cache_key="key", generate=generate))
    monkeypatch.setattr(matches, "request_json", snapshot)
    reply = api("POST", "/v1/job-matches", "match.create", json={"jd_text": "Python role requiring testing"})
    assert reply.status_code == 201
    record = reply.json()["job_match"]
    assert record["provider"] == "local" and record["result"]["fallback"] is True
    assert record["model"] == "rules-v1" and "private provider diagnostic" not in reply.text


def test_match_policy_error_fails_without_insert(api, monkeypatch):
    from services.profile import model_policy

    def invalid(*args, **kwargs):
        raise HTTPException(503, "invalid model configuration")
    monkeypatch.setattr(model_policy, "select_model", invalid)
    monkeypatch.setattr(matches, "request_json", snapshot)
    reply = api("POST", "/v1/job-matches", "match.create", json={"jd_text": "Python developer with SQL"})
    assert reply.status_code == 503 and api("GET", "/v1/job-matches", "match.read").json()["matches"] == []
    assert not api("GET", "/v1/admin/jd-submissions", "jd.read", role="admin", json={"student_ids": None}).json()["submissions"]


@pytest.mark.parametrize("update,expected", [({"requirements": "new requirement"}, 409), ({"published": False}, 404)])
def test_edit_during_inference_discards_stale_match(api, monkeypatch, update, expected):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from types import SimpleNamespace
    from services.profile import model_policy

    started, release = Event(), Event()
    def slow(_):
        started.set()
        assert release.wait(timeout=8)
        return {"suggestions": ["Old advice"]}
    monkeypatch.setattr(model_policy, "select_model", lambda *a, **k: SimpleNamespace(provider="trusted",
                        model="test-model", cache_key="key", generate=slow))
    monkeypatch.setattr(matches, "request_json", snapshot)
    path = "/v1/admin/job-postings"
    posting = api("POST", path, "posting.write", role="admin", json={"title": "Engineer"}).json()["posting"]
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(api, "POST", "/v1/job-matches", "match.create", json={"job_posting_id": posting["id"]})
        try:
            assert started.wait(timeout=5)
            edited = api("PUT", path + "/" + posting["id"], "posting.write", role="admin", json=update)
            assert edited.status_code == 200, edited.text
        finally:
            release.set()
        assert future.result(timeout=10).status_code == expected
    assert not api("GET", "/v1/job-matches", "match.read").json()["matches"]



def test_revoked_model_result_not_persisted(api, monkeypatch):
    from types import SimpleNamespace
    from services.profile import model_policy

    def revoke(_):
        plan.cache_key = "new"
        return {"summary": "stale"}
    plan = SimpleNamespace(provider="trusted", model="m", cache_key="old", generate=revoke)
    monkeypatch.setattr(model_policy, "select_model", lambda *a, **k: plan)
    monkeypatch.setattr(matches, "request_json", snapshot)
    reply = api("POST", "/v1/job-matches", "match.create", json={"jd_text": "Python developer with SQL"})
    assert reply.status_code == 409
    assert api("GET", "/v1/job-matches", "match.read").json()["matches"] == []


def test_api_and_legacy_use_same_single_authorized_wire_projection(api, monkeypatch):
    import httpx
    from backend.src.job_match import build_job_match
    from services.profile import model_policy

    from shared import provider_settings

    monkeypatch.delenv("PROVIDERS_DB_ENGINE", raising=False)
    monkeypatch.setenv("CAREER_MODEL_BY_SCHOOL", '{"a":"custom"}')
    monkeypatch.setenv("LEGACY_SCHOOL_ID", "a")
    monkeypatch.setenv("AI_API_KEY", "synthetic-test-token")
    monkeypatch.setenv("PROVIDERS_SERVICE_URL", "https://control.invalid")
    monkeypatch.setattr(provider_settings, "_cache", None)

    def fetched(origin, caller):
        assert (origin, caller) == ("https://control.invalid", "career")
        return {"AI_BASE_URL": "https://approved.invalid/v1", "AI_MODEL": "advice-test"}

    monkeypatch.setattr(provider_settings, "_fetch_settings", fetched)
    monkeypatch.setenv("PROVIDER_ALLOWED_CUSTOM_ENDPOINTS", "https://approved.invalid/v1")
    monkeypatch.setenv("FOLLOWUP_PROVIDER_ORDER", "openai,kimi")
    monkeypatch.setenv("PRIVATE_MODEL_TIMEOUT_SECONDS", "2")
    calls = []
    def respond(provider, url, headers, payload):
        assert url == "https://approved.invalid/v1/chat/completions"
        assert provider.retries == 0 and payload["model"] == "advice-test"
        calls.append(json.dumps(payload, ensure_ascii=False))
        return httpx.Response(200, request=httpx.Request("POST", url),
                              json={"choices":[{"message":{"content":'{"summary":"授权建议"}'}}]})
    monkeypatch.setattr(model_policy, "_bounded_post", respond)
    monkeypatch.setattr(matches, "request_json", snapshot)
    reply = api("POST", "/v1/job-matches", "match.create", json={"jd_text": "PRIVATE_JD Python role with SQL"})
    assert reply.status_code == 201 and reply.json()["job_match"]["result"]["summary"] == "授权建议"
    legacy = build_job_match(resume_text="PRIVATE_RESUME Python", target_role="PRIVATE_ROLE",
                             posting={"title":"PRIVATE_TITLE", "skills":"PRIVATE_SKILL、Python"})
    assert legacy["provider"] == "custom" and legacy["fallback"] is False
    assert len(calls) == 2 and all("Python" in wire and "PRIVATE" not in wire for wire in calls)
    assert "privacy-marker" not in calls[0]

    # 部署密钥或通用模型顺序不能授权其他学校，撤销允许的地址后也不能改发其他供应商。
    assert api("POST", "/v1/job-matches", "match.create", school="b",
               json={"jd_text": "Python developer required"}).json()["job_match"]["provider"] == "local"
    monkeypatch.delenv("PROVIDER_ALLOWED_CUSTOM_ENDPOINTS")
    denied = api("POST", "/v1/job-matches", "match.create", json={"jd_text": "Python developer required"})
    assert denied.status_code == 503 and len(calls) == 2


def test_saturated_and_timed_out_model_keeps_bounded_local_matches(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event, Lock
    import httpx
    from services.career.scoring import score_and_enhance
    from services.profile import model_policy

    # 让四个测试请求持续占用模型连接，即使调用方已经超时，第五个请求仍应使用规则结果。
    started, release, lock = Event(), Event(), Lock()
    calls = []
    def blocked(_provider, url, headers, payload):
        with lock:
            calls.append(1)
            if len(calls) == 4:
                started.set()
        assert release.wait(5)
        return httpx.Response(200, request=httpx.Request("POST", url),
                              json={"choices": [{"message": {"content": '{"summary":"late"}'}}]})
    monkeypatch.setattr(model_policy, "_bounded_post", blocked)
    cfg = model_policy.models.FollowupProvider("openai", "test-key", "https://api.openai.com/v1",
                                               "test", 0.2, 0.0, 100, retries=0)
    plan = model_policy.ModelPlan("openai", "test", "synthetic", cfg)
    def score():
        return score_and_enhance("school", resume_text="Python engineer", posting={"title": "Python"}, plan=plan)
    with ThreadPoolExecutor(4) as pool:
        pending = [pool.submit(score) for _ in range(4)]
        try:
            assert started.wait(3)
            assert all(future.result(timeout=2)["fallback"] for future in pending)
            assert score()["fallback"] and len(calls) == 4
        finally:
            release.set()
