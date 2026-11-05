"""从正式 ASGI 入口验证默认模式、旧环境误配和故障隔离。"""
import importlib
import json
import os
import shutil
import subprocess
import sys
from importlib.util import find_spec
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
LEGACY = {"backend.src.main", "backend.src.database", "admin_backend.src.main", "admin_backend.src.database"}


@pytest.fixture(scope="module")
def source_copy(tmp_path_factory):
    # 两个旧模块在导入时即可加载环境文件、建表和启动工作。子进程只看到源码副本。
    directory = tmp_path_factory.mktemp("emergency-imports")
    for component in ("backend/src", "backend/offline", "backend/rtc_token_lib", "admin_backend/src",
                      "admin_backend/offline", "deploy", "services", "shared"):
        for file in (ROOT / component).rglob("*.py"):
            target = directory / file.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(file, target)
    shutil.copyfile(__file__, directory / "probe.py")
    return directory


def run_probe(directory, kind, name, **settings):
    packages = {str(Path(find_spec(p).origin).parent.parent)
                for p in ("pytest", "openpyxl", "fastapi", "cryptography", "jwt", "httpx")}
    env = {k: os.environ[k] for k in ("PATH", "SYSTEMROOT", "TMPDIR") if k in os.environ}
    env.update(APP_ENV="production", PYTHONPATH=os.pathsep.join(sorted(packages)), PYTHONUTF8="1",
               LEGACY_SCHOOL_ID="school-fixture", OPERATIONS_JOURNAL_DIR=str(directory / "journal"),
               OPERATIONS_SERVICE_URL="https://operations.test", ADMIN_FRONTEND_ORIGIN="https://gateway.test",
               FRONTEND_ORIGIN="https://gateway.test", **settings)
    result = subprocess.run([sys.executable, "probe.py", kind, name], cwd=directory, env=env,
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr[-4000:]


@pytest.mark.parametrize("name", ["student", "admin"])
def test_normal_entry_defaults_to_native_and_does_not_use_old_cookie(source_copy, name):
    run_probe(source_copy, "native", name, SERVICE_ID=("student" if name == "student" else "admin") + "-gateway")


@pytest.mark.parametrize("setting,value", [("IDENTITY_SESSION_MODE", "legacy"), ("ASSESSMENT_STORAGE_MODE", "shared")])
@pytest.mark.parametrize("name", ["student", "admin"])
def test_ordinary_gateway_rejects_explicit_old_mode_before_owner_import(source_copy, name, setting, value):
    run_probe(source_copy, "conflict", name, SERVICE_ID=name + "-gateway", **{setting: value})


@pytest.mark.parametrize("name", ["backend.src.main", "admin_backend.src.main", "backend.offline.main", "admin_backend.offline.main"])
def test_direct_monolith_without_emergency_ticket_cannot_open_business(source_copy, name):
    # 故意使用可用的假库路径及凭据，防止“没配数据库所以启动失败”掩盖真实绕过。
    run_probe(source_copy, "direct", name, DB_ENGINE="sqlite", SQLITE_PATH=str(source_copy / "direct.sqlite"),
              ADMIN_MASTER_EMAIL="root@fixture.test", ADMIN_MASTER_PASSWORD="Synthetic-Recovery-Only-42!")


def test_normal_assessment_owns_its_storage_by_default(source_copy):
    run_probe(source_copy, "isolated", "assessment", SERVICE_ID="assessment")


def test_assessment_default_native_mode_rechecks_student_after_delegation(source_copy):
    # 会话签发后，学校仍可能停用账号。省略模式变量不能把这一复核短路。
    run_probe(source_copy, "disabled-student", "assessment", SERVICE_ID="assessment",
              ASSESSMENT_DB_ENGINE="sqlite", ASSESSMENT_SQLITE_PATH=str(source_copy / "assessment.sqlite"))


def test_retired_messages_handler_does_not_log_another_students_identity(source_copy):
    run_probe(source_copy, "message-log", "interview", SERVICE_ID="interview",
              INTERVIEW_DB_ENGINE="sqlite", INTERVIEW_SQLITE_PATH=str(source_copy / "interview.sqlite"))


def guard(event, args):
    if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto"}:
        raise AssertionError("安全验证不应访问网络")
    if event == "open" and isinstance(args[0], str) and Path(args[0]).name == ".env":
        raise AssertionError("安全验证不应打开实际环境文件")
    if event == "sqlite3.connect" and str(args[0]) not in {
        os.getenv("ASSESSMENT_SQLITE_PATH"), os.getenv("INTERVIEW_SQLITE_PATH"),
    }:
        raise AssertionError("入口触达旧业务数据库")


def explicit_refusal(exc):
    # 缺依赖或 TCP 失败不能证明安全边界生效，只接受运行模式检查自身的拒绝。
    return any(word in str(exc).lower() for word in (
        "legacy", "shared", "native", "isolated", "emergency", "monolith", "gateway", "旧", "原生", "应急", "网关", "入口",
    ))


def probe(kind, name):
    from fastapi import HTTPException
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    sys.addaudithook(guard)
    if kind == "isolated":
        from services.assessment.storage_mode import isolated
        assert isolated(), "普通启动使用了共享评估库"
        return

    if kind == "message-log":
        from contextlib import redirect_stderr, redirect_stdout
        import io
        from services.interview import runtime

        canary = "private-owner-fixture"
        with runtime.db:
            runtime.db.execute("INSERT INTO interview_sessions(id,user_id,target_role) VALUES (?,?,?)",
                               ("opaque-session", canary, "QA")).close()
        output = io.StringIO()
        with redirect_stdout(output), redirect_stderr(output), pytest.raises(HTTPException) as missing:
            runtime.list_messages("opaque-session", user={"id":"different-student"})
        assert missing.value.status_code == 404
        assert canary not in str(missing.value.detail) + output.getvalue(), "拒绝访问时披露了其他学生的标识"
        return

    if kind == "disabled-student":
        from unittest.mock import patch
        import httpx
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from shared.service_security import service_headers

        key = Ed25519PrivateKey.generate()
        scopes = ["assessment.read"]
        public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        os.environ.update(IDENTITY_SERVICE_URL="https://identity.test", SERVICE_KEY_ID="test",
            SERVICE_SIGNING_KEY=key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                 serialization.NoEncryption()).decode(),
            SERVICE_TRUST_POLICY=json.dumps({"student-gateway":{"schools":["school-fixture"],"keys":{"test":public.decode()},
                                            "grants":{"assessment":{"student":scopes}}}}))
        os.environ["SERVICE_ID"] = "student-gateway"
        signed = service_headers("assessment", actor_type="student", actor_id="disabled",
                                 school_id="school-fixture", scopes=scopes)
        os.environ["SERVICE_ID"] = "assessment"
        checked = []

        async def disabled(_transport, request):
            checked.append((request.url.host, request.url.path))
            return httpx.Response(403, json={"detail":"account disabled"})

        from services.assessment.app import app
        with patch.object(httpx.AsyncHTTPTransport, "handle_async_request", disabled), TestClient(app) as client:
            response = client.get("/api/reports", headers=signed)
        assert response.status_code == 403, "未显式设置 native 时，已停用学生仍然可以读取评估"
        assert checked == [("identity.test", "/internal/students/me")]
        return

    target = name if kind == "direct" else "services.gateway." + name
    if kind == "direct":
        try:
            app = importlib.import_module(target).app
            with TestClient(app, base_url="https://gateway.test") as client:
                # 允许入口在开始提供服务之前，或在任何业务请求抵达旧处理器之前关闭。
                login = "/api/auth/login" if name == "backend.src.main" else "/api/admin/auth/login"
                response = client.post(login, json={"email":"root@fixture.test", "password":"Synthetic-Recovery-Only-42!"})
                assert response.status_code in (403, 404, 405, 410, 503) and not response.cookies
        except (RuntimeError, ValueError, HTTPException) as exc:
            assert explicit_refusal(exc), exc
        return

    if kind == "conflict":
        with pytest.raises((RuntimeError, ValueError, HTTPException)) as denied:
            with TestClient(importlib.import_module(target).app):
                pass
        assert explicit_refusal(denied.value), denied.value
        assert not LEGACY.intersection(sys.modules)
        return

    from unittest.mock import patch
    import httpx
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = Ed25519PrivateKey.generate()
    os.environ.update(SERVICE_KEY_ID="test", SERVICE_SIGNING_KEY=key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode(),
        IDENTITY_SERVICE_URL="https://identity.test", PROFILE_SERVICE_URL="https://profile.test",
        ASSESSMENT_SERVICE_URL="https://assessment.test")
    role = "student" if name == "student" else "teacher"
    owner = "profile" if name == "student" else "assessment"
    url = "/api/profile" if name == "student" else "/api/admin/reports/sample/score"
    method = "PUT" if name == "student" else "PATCH"
    calls = []
    identity_down = False

    def identity(_transport, request):
        assert request.url.host == "identity.test" and request.url.path.endswith("/resolve")
        calls.append("identity")
        if identity_down:
            raise httpx.ConnectError("synthetic outage")
        body = json.loads(request.content)
        assert body["token"] == "N" * 43
        return httpx.Response(200, json={"actor_id":"actor", "actor_type":role,
                                        "school_id":"school-fixture", "scopes":[body["action"]]})

    async def unavailable(_transport, request):
        if request.url.host == "operations.test":
            # 审计事件有单独的接收方；业务服务故障时仍允许网关投递日志。
            assert request.url.path == "/internal/security-events"
            return httpx.Response(200, json={"id": json.loads(request.content)["event_id"]})
        assert request.url.host == owner + ".test"
        calls.append(owner)
        raise httpx.ConnectError("synthetic outage")

    with patch.object(httpx.HTTPTransport, "handle_request", identity), \
            patch.object(httpx.AsyncHTTPTransport, "handle_async_request", unavailable), \
            TestClient(importlib.import_module(target).app, base_url="https://gateway.test") as client:
        health_url = "/api/health" if name == "student" else "/api/admin/health"
        assert client.get(health_url).json().get("service") == name + "-gateway"
        client.cookies.set("interview_session" if name == "student" else "admin_session", "L" * 43)
        headers = {"Origin":"https://gateway.test", "X-Actor-Type":"admin", "X-School-ID":"other",
                   "Authorization":"Bearer synthetic-old-credential"}
        assert client.request(method, url, headers=headers, json={}).status_code == 401
        assert not calls
        if name == "student":
            with pytest.raises(WebSocketDisconnect), client.websocket_connect(
                "/ws/interviews/sample/qwen/omni-realtime", headers=headers
            ):
                pytest.fail("旧 cookie 被允许建立原生语音连接")
        client.cookies.set("identity_student_session" if name == "student" else "identity_staff_session", "N" * 43)
        for identity_down, expected in ((False, ["identity",owner]), (True, ["identity"])):
            calls.clear()
            response = client.request(method, url, headers=headers, json={})
            assert response.status_code in (502, 503), response.text
            assert calls == expected
    assert not LEGACY.intersection(sys.modules), "远端故障后加载了原单体"


if __name__ == "__main__":
    probe(*sys.argv[1:])
