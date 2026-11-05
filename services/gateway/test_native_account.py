"""用临时学校数据验证学生网关与身份、档案及招聘服务的 ASGI 调用链。"""
import json
import os
from pathlib import Path
import subprocess
import sys
from contextlib import ExitStack
from unittest.mock import patch


def test_native_student_account_domains(tmp_path):
    env = {
        "PATH": os.environ["PATH"], "APP_ENV": "production", "IDENTITY_SESSION_MODE": "native",
        "ASSESSMENT_STORAGE_MODE": "isolated", "DB_ENGINE": "mysql", "MYSQL_HOST": "127.0.0.1", "MYSQL_PORT": "1",
        "ASSESSMENT_DB_ENGINE": "mysql", "ASSESSMENT_MYSQL_HOST": "127.0.0.1", "ASSESSMENT_MYSQL_PORT": "1",
        "LEGACY_SCHOOL_ID": "campus", "CAREER_SCHOOL_ID": "campus",
        "OPERATIONS_JOURNAL_DIR": str(tmp_path / "journal"),
        "OPERATIONS_SERVICE_URL": "https://operations.test",
    }
    if "PYTHONPATH" in os.environ:
        env["PYTHONPATH"] = os.environ["PYTHONPATH"]
    for owner in ("identity", "profile", "career"):
        env.update({f"{owner.upper()}_DB_ENGINE": "sqlite",
                    f"{owner.upper()}_SQLITE_PATH": str(tmp_path / (owner + ".sqlite")),
                    f"{owner.upper()}_SERVICE_URL": f"https://{owner}.test"})
    result = subprocess.run([sys.executable, "-m", "services.gateway.test_native_account"], env=env,
                            cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr


def exercise():
    def offline(event, args):
        if event in {"socket.connect", "socket.getaddrinfo"}:
            raise AssertionError("Test attempted external I/O")
        if event == "open" and isinstance(args[0], str) and Path(args[0]).name == ".env":
            raise AssertionError("Test attempted to open a real dotenv")
    sys.addaudithook(offline)
    import httpx
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from fastapi.testclient import TestClient
    from services.gateway.student import app as gateway

    forbidden = {"backend.src.database", "backend.src.main", "admin_backend.src.database", "admin_backend.src.main",
                 "services.assessment.app", "services.interview.app"}
    assert not forbidden.intersection(sys.modules)
    from shared.account_security import hash_password
    from services.career.app import app as career
    from services.identity.app import app as identity
    from services.profile.app import app as profile

    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    os.environ["SERVICE_KEY_ID"] = "test"
    os.environ["SERVICE_SIGNING_KEY"] = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    os.environ["SERVICE_ID"] = "gateway"
    grants = {
        "gateway": {"identity": {"system": ["identity.session.proxy", "identity.session.resolve"],
                                 "student": ["identity.student.read"]},
                    "profile": {"student": ["profile.read", "profile.write", "profile.versions.read"]},
                    "career": {"student": ["catalog.read", "posting.read", "match.create", "match.read"]}},
        "career": {"profile": {"student": ["profile.snapshot.read"]}},
        "profile": {"identity": {"student": ["organization.options.read"]},
                    "career": {"student": ["catalog.read"]}},
    }
    os.environ["SERVICE_TRUST_POLICY"] = json.dumps({
        caller: {"schools": ["campus"], "keys": {"test": public.decode()}, "grants": permissions}
        for caller, permissions in grants.items()
    })
    # 模拟诊断服务停机。安全事件写入临时持久卷，其余业务照常完成。
    down = {"operations"}
    apps = {"career": career, "identity": identity, "profile": profile}
    with ExitStack() as stack:
        peers = {k: stack.enter_context(TestClient(v)) for k, v in apps.items()}
        with identity.state.store.transaction(write=True) as tx:
            tx.execute("""INSERT INTO identity_student_credentials VALUES
                       ('campus','s1','STU101','Fixture',?,'normal',0)""", (hash_password("Candidate591!"),))

        async def dispatch_async(_transport, req):
            peer = req.url.host.split(".")[0]
            if peer in down:
                raise httpx.ConnectError("offline peer", request=req)
            # 各服务在生产中使用不同进程身份。夹具在一次同步调用结束后才切换 SERVICE_ID，
            # 避免档案并发读取组织和职业目录时，两个协程互相改写验签的 audience。
            body = await req.aread()
            with patch.dict(os.environ, SERVICE_ID=peer):
                response = peers[peer].send(httpx.Request(req.method, req.url, headers=req.headers, content=body))
            return httpx.Response(response.status_code, headers=response.headers, content=response.content)

        def dispatch_sync(_transport, req):
            assert req.url.host == "identity.test" and req.url.path == "/internal/sessions/student/resolve"
            with patch.dict(os.environ, SERVICE_ID="identity"):
                return peers["identity"].post(req.url.path, headers=req.headers, content=req.content)

        stack.enter_context(patch.object(httpx.AsyncHTTPTransport, "handle_async_request", dispatch_async))
        stack.enter_context(patch.object(httpx.HTTPTransport, "handle_request", dispatch_sync))
        client = stack.enter_context(TestClient(gateway, base_url="https://gateway.test"))
        client.cookies.set("interview_session", "legacy-must-not-authorize")
        assert client.get("/api/profile").status_code == 401
        login = client.post("/api/auth/login", json={"student_no": "STU101", "password": "Candidate591!",
                                                     "school_id": "other"})
        assert login.status_code == 200, login.text
        assert login.json()["user"]["schoolId"] == "campus"
        assert client.get("/api/profile").json()["profile"]["nickname"] == "Fixture"
        saved = client.put("/api/profile", json={"nickname": "Profile name", "skills": "Python",
                                                  "resume_text": "Python developer"})
        assert saved.status_code == 200, saved.text
        assert client.get("/api/profile/versions?limit=11").json()["versions"][0]["version"] == 1
        assert client.get("/api/profile/versions/1").json()["profile"]["nickname"] == "Profile name"
        assert client.get("/api/profile/versions/2").status_code == 404
        settings = client.get("/api/resume-form/settings")
        assert settings.status_code == 200, settings.text
        assert settings.json()["colleges"]
        assert client.get("/api/resume-form").json()["student_no"] == "STU101"
        matched = client.post("/api/job-matches", json={"student": {"name": "spoof"},
                              "jd_text": "Build and test Python database services."})
        assert matched.status_code == 201, matched.text
        assert matched.json()["job_match"]["student_name"] == "Fixture"
        assert client.get("/api/job-postings").status_code == 200

        down.add("career")
        assert client.get("/api/job-postings").status_code == 503
        assert client.get("/api/resume-form/settings").status_code == 503
        assert client.get("/api/profile").json()["profile"]["nickname"] == "Profile name"
        assert client.get("/api/auth/me").json()["user"]["id"] == "s1"
        down.remove("career")
        down.add("profile")
        assert client.get("/api/profile").status_code == 503
        assert client.get("/api/job-postings").status_code == 200
        assert client.post("/api/auth/logout").status_code == 200
        assert client.get("/api/profile").status_code == 401
    assert not forbidden.intersection(sys.modules)


if __name__ == "__main__":
    exercise()
