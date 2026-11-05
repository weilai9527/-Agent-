"""通过公开接口和模拟会话验证签名身份的选择。"""
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
import pytest

from services.career.admin_adapter import admin_career_route
from services.identity import gateway
from shared import service_http


def gateway_client(monkeypatch, *, native=False, students=("mine",), url="http://127.0.0.1:9010"):
    if not native:
        from shared import offline_fixture

        # 旧会话行为仅在隔离夹具内测试，测试结束后恢复进程的夹具开关。
        monkeypatch.setenv("DB_ENGINE", "sqlite")
        monkeypatch.setenv("SQLITE_PATH", ":memory:")
        monkeypatch.setenv("SERVICE_ID", "offline-fixture")
        monkeypatch.setattr(offline_fixture, "_enabled", False)
        offline_fixture.enable_offline_fixture()
    monkeypatch.setenv("IDENTITY_SESSION_MODE", "native" if native else "legacy")
    monkeypatch.setenv("LEGACY_SCHOOL_ID", "my-school")
    if url is None:
        monkeypatch.delenv("CAREER_SERVICE_URL", raising=False)
    else:
        monkeypatch.setenv("CAREER_SERVICE_URL", url)
    legacy_account = {"id": "same-id", "actor_type": "teacher"}
    def legacy_auth(request: Request):
        assert not native
        if request.cookies.get("admin_session") != "old":
            raise HTTPException(401)
        return legacy_account
    def native_auth(request, action, kind):
        assert native and kind == "staff" and action == "jd.approve"
        if request.cookies.get("identity_staff_session") != "new":
            raise HTTPException(401)
        return {"actor_id": "same-id", "actor_type": "teacher", "school_id": "native-school", "scopes": [action]}
    monkeypatch.setattr(gateway, "resolve_native", native_auth)
    def rows(_sql, _params):
        assert not native
        return [{"id": s} for s in students]
    def origin(request):
        if request.headers.get("origin") not in (None, "https://allowed.test"):
            raise HTTPException(403)
    app = FastAPI()
    route = admin_career_route("jd.approve", validate_origin=origin, student_scope=lambda u: u.get("scope", []),
                               scope_sql=lambda scope, col: ("1=1", ()), all_rows=rows, audit=lambda *a, **k: None)
    @app.post("/api/admin/jd-submissions/{submission_id}/approve")
    @route
    def approve(request: Request, submission_id: str, admin: dict = Depends(legacy_auth)):
        raise AssertionError("A service-backed route read the legacy database")
    return TestClient(app), legacy_account


@pytest.mark.parametrize("native", [False, True])
def test_auth_action_and_roster_come_from_server(monkeypatch, native):
    client, _ = gateway_client(monkeypatch, native=native)
    delegation = []
    async def remote(service, method, path, *, actor, scope, body=None, params=None):
        if service == "identity":
            assert native and actor["school_id"] == "native-school" and actor["actor_type"] == "teacher"
            if path == "/classes":
                assert scope == "identity.classes.read"
                return {"items": [{"class_id": "class-x"}]}
            assert scope == "identity.roster.read" and body == {"class_ids": ["class-x"]}
            return {"classes": [{"class_id": "class-x", "student_ids": ["native-student"]}]}
        assert (method, path, scope) == ("POST", "/v1/admin/jd-submissions/item/approve", "jd.approve")
        delegation.append((actor, body))
        return {"ok": True}
    monkeypatch.setattr(service_http, "request_json", remote)
    path = "/api/admin/jd-submissions/item/approve"
    assert client.post(path).status_code == 401
    client.cookies.set("admin_session", "old")
    if native:
        assert client.post(path).status_code == 401
        client.cookies.set("identity_staff_session", "new")
    assert client.post(path, headers={"Origin": "https://denied.test"}).status_code == 403
    forged = {"student_ids": None, "school_id": "other", "jd_text": "synthetic"}
    response = client.post(path + "?student_ids=other", json=forged, headers={"X-Career-Students": "*"})
    assert response.status_code == 200, response.text
    [(actor, envelope)] = delegation
    assert actor == {"actor_id": "same-id", "actor_type": "teacher", "school_id": "native-school" if native else "my-school"}
    assert envelope == {"student_ids": ["native-student" if native else "mine"], "payload": {"jd_text": "synthetic"}}


def test_teacher_cannot_delegate_all_students_and_invalid_input_is_rejected(monkeypatch):
    client, account = gateway_client(monkeypatch)
    account["scope"] = None
    client.cookies.set("admin_session", "old")
    path = "/api/admin/jd-submissions/id/approve"
    assert client.post(path, json={}).status_code == 403
    account["school_id"] = "other-school"
    assert client.post(path, json={}).status_code == 403
    del account["school_id"]
    assert client.post(path, json=[]).status_code == 400
    assert client.post(path, content=b"x" * (1024 * 1024 + 1)).status_code == 413


def test_missing_service_after_native_cutover_does_not_call_legacy(monkeypatch):
    client, _ = gateway_client(monkeypatch, native=True, url=None)
    client.cookies.set("identity_staff_session", "new")
    # 即使目标服务离线，也只能通过身份服务查询原生会话的学生范围。
    transport = service_http.request_json
    async def request_json(service, method, path, **kwargs):
        if service == "identity":
            return {"items": []}
        return await transport(service, method, path, **kwargs)
    monkeypatch.setattr(service_http, "request_json", request_json)
    response = client.post("/api/admin/jd-submissions/id/approve", json={})
    assert response.status_code == 503


def test_public_upload_is_bounded_before_multipart_parser(monkeypatch):
    from fastapi import File, UploadFile
    from services.career.limits import BodyLimit
    import starlette.formparsers

    app = FastAPI()
    app.add_middleware(BodyLimit, browser_admin_only=True)
    @app.post("/api/admin/job-postings/import")
    async def parse(upload: UploadFile = File(...)):
        raise AssertionError("oversized upload reached the endpoint")
    @app.post("/api/admin/unrelated")
    async def unrelated():
        return {"ok": True}
    client = TestClient(app)
    path = "/api/admin/job-postings/import"
    stream = b"X" * (6 * 1024 * 1024)
    # 声明的正文过大时，在创建上传临时文件前拒绝请求。
    def forbid_spool(*args, **kw):
        raise AssertionError("oversized request opened a temporary file")
    monkeypatch.setattr(starlette.formparsers, "SpooledTemporaryFile", forbid_spool)
    headers = {"content-type": "multipart/form-data; boundary=a", "content-length": str(len(stream))}
    assert client.post(path, content=stream, headers=headers).status_code == 413
    # 即使客户端一次发送一个超大分块，也应在解析前拒绝。
    headers.pop("content-length")
    assert client.post(path, content=iter([stream]), headers=headers).status_code == 413
    assert client.post("/api/admin/unrelated", content=stream).status_code == 200


def test_legacy_jd_scope_and_approval_retry(tmp_path):
    """在仅包含代码的临时工作区启动旧模块，避免读取部署环境配置。"""
    from importlib.util import find_spec
    from tempfile import gettempdir
    import os
    from pathlib import Path
    import shutil
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[2]
    for component in ("backend/src", "backend/offline", "admin_backend/src", "admin_backend/offline", "shared", "services"):
        for source in (root / component).rglob("*.py"):
            target = tmp_path / source.relative_to(root)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    packages = {str(Path(find_spec(name).origin).parent.parent)
                for name in ("pytest", "openpyxl", "fastapi", "cryptography", "jwt")}
    env = {"PATH": os.environ["PATH"], "PYTHONPATH": os.pathsep.join(sorted(packages)), "TMPDIR": gettempdir(),
           "DB_ENGINE": "sqlite", "SQLITE_PATH": str(tmp_path / "legacy.db"), "APP_ENV": "test",
           "ADMIN_MASTER_EMAIL": "master@example.test", "ADMIN_MASTER_PASSWORD": "Synthetic-Test-Password"}
    result = subprocess.run([sys.executable, "-c",
        "from services.career.test_admin_adapter import _verify_legacy_jd; _verify_legacy_jd()"],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stderr


def _verify_legacy_jd():
    import json
    from shared.offline_fixture import enable_offline_fixture
    enable_offline_fixture()
    from admin_backend.offline import main
    from shared.recruitment import create_jd_submission

    db = main.db
    uid = main.one("SELECT id FROM admin_users WHERE email='master@example.test'")["id"]
    email = "teacher@example.test"
    actor = {"id": uid, "actor_type": "teacher", "email": email, "permissions": ["jd.read", "jd.approve"],
             "student_scope": json.dumps([{"college": "c", "class": "mine"}])}
    main.app.dependency_overrides[main.require_admin] = lambda: actor
    db.execute("INSERT INTO campus_colleges(id,code,name) VALUES ('c','c','c')")
    db.execute("INSERT INTO campus_programs(id,college_id,name) VALUES ('p','c','p')")
    for class_id in ("mine", "other"):
        db.execute("INSERT INTO campus_classes(id,program_id,name,invite_code) VALUES (?,'p',?,?)",
                   (class_id, class_id, class_id))
    jds = {}
    for user, group, status in (("mine", "mine", "active"), ("other", "other", "active"), ("former", "mine", "inactive")):
        db.execute("INSERT INTO users(id,email,password_hash,name) VALUES (?,?,'synthetic',?)",
                   (user, user + "@example.test", user))
        main.upsert_student_enrollment(user, class_id=group, status=status)
        jds[user] = create_jd_submission(db, user_id=user, job_title=user, jd_text="Synthetic")["id"]
    jds["staff"] = create_jd_submission(db, job_title="staff")["id"]
    db.commit()
    with TestClient(main.app) as client:
        prefix = "/api/admin/jd-submissions"
        result = client.get(prefix, params={"limit": 1})
        assert result.status_code == 200 and [v["id"] for v in result.json()["submissions"]] == [jds["mine"]]
        assert result.headers["Cache-Control"] == "private, no-store"
        for key in ("other", "former", "staff"):
            assert client.post(f"{prefix}/{jds[key]}/approve", json={}).status_code == 404
        assert client.put(f"{prefix}/{jds['mine']}", json={"status": "approved"}).status_code == 403
        actor["permissions"].append("jd.write")
        assert client.put(f"{prefix}/{jds['mine']}", json={"status": " Approved "}).status_code == 409
        url = f"{prefix}/{jds['mine']}/approve"
        first = client.post(url, json={})
        assert first.status_code == 200, first.text
        second = client.post(url, json={"job_title": "Retry mutation ignored"})
        assert second.json()["posting"] == first.json()["posting"]
        assert main.one("SELECT COUNT(*) n FROM job_postings WHERE source_ref=?", (jds["mine"],))["n"] == 1
