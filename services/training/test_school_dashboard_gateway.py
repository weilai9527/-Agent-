"""在关闭旧数据库、面试服务与评估服务的条件下验证原生管理入口和登记摘要。"""
import json
import os
import sqlite3
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from services.gateway.native_admin import create_app
from services.identity.test_staff import api


def test_native_dashboard_without_legacy_database(api, tmp_path, monkeypatch):
    identity, _, password = api
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("SERVICE_ID", "admin-gateway")
    monkeypatch.setenv("IDENTITY_SESSION_MODE", "native")
    monkeypatch.setenv("LEGACY_SCHOOL_ID", "A")
    monkeypatch.setenv("ADMIN_FRONTEND_ORIGIN", "https://admin.test")
    for name in ("identity", "interview", "assessment"):
        monkeypatch.setenv(name.upper() + "_SERVICE_URL", "https://" + name + ".test")
    policy = json.loads(os.environ["SERVICE_TRUST_POLICY"])
    allowed = policy["admin-gateway"]["grants"]
    allowed["identity"] = {"system": ["identity.session.resolve", "identity.session.proxy"],
                           "admin": ["student.read", "registration.read", "registration.import"]}
    allowed["interview"] = {"admin": ["interview.records.read"]}
    allowed["assessment"] = {"admin": ["assessment.records.read"], "teacher": ["assessment.records.read"]}
    monkeypatch.setenv("SERVICE_TRUST_POLICY", json.dumps(policy))
    with identity.app.state.store.transaction(write=True) as tx:
        tx.execute("""UPDATE identity_staff SET permissions=? WHERE school_id='A' AND actor_id='manager'""",
                   (json.dumps(["student.read", "registration.read", "registration.import",
                                "interview.records.read", "report.read"]),))

    original_connect = sqlite3.connect

    def identity_db_only(path, *args, **kwargs):
        assert Path(path).resolve() == (tmp_path / "identity.sqlite").resolve(), "工作台请求意外访问了旧库"
        return original_connect(path, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", identity_db_only)
    offline_calls = []

    def dispatch(_self, request):
        if request.url.host in {"interview.test", "assessment.test"}:
            offline_calls.append((request.url.host, request.url.path, request.url.query))
            raise httpx.ConnectError("测试中已停用该业务服务。")
        assert request.url.host == "identity.test"
        with monkeypatch.context() as env:
            env.setenv("SERVICE_ID", "identity")
            result = identity.send(request)
        return httpx.Response(result.status_code, headers=result.headers, content=result.content)

    async def async_dispatch(transport, request):
        await request.aread()
        return dispatch(transport, request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", dispatch)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", async_dispatch)
    pending = "/api/admin/identity/v1/student-accounts/pending-summary"
    accounts = "/api/admin/identity/v1/student-accounts/summary"
    with TestClient(create_app(), base_url="https://admin.test", headers={"Origin": "https://admin.test"}) as web:
        def login(who):
            web.cookies.clear()
            res = web.post("/api/admin/auth/login", json={"email": who + "@school.test", "password": password})
            assert res.status_code == 200, res.text

        assert web.get(pending).status_code == 401
        login("manager")
        snapshot = web.get("/api/admin/snapshot").json()
        assert snapshot["identityMode"] == "native" and snapshot["permissions"]["canUseRegistrationBook"]
        assert web.get(pending).json() == {"school_id": "A", "pending_accounts": 0, "items": []}
        # 待开通从工作簿办理入口的同一份登记数据产生；该操作尚未创建登录账号。
        created = web.post("/api/admin/identity/v1/registrations/import",
                           json={"rows": [{"name": "登记学生", "student_no": "ST-101"}]})
        assert created.status_code == 200, created.text
        assert web.get(accounts).json()["accounts"] == 0
        assert web.get(pending).json() == {"school_id": "A", "pending_accounts": 1,
                                            "items": [{"name": "登记学生", "student_no": "ST-101"}]}
        for owner in ("interview", "assessment"):
            res = web.get("/api/admin/" + owner + "/v1/workbench", params={"limit": 5})
            assert res.status_code == 503, res.text
        assert offline_calls == [(owner + ".test", "/v1/workbench", b"limit=5") for owner in ("interview", "assessment")]
        login("reader")
        assert not web.get("/api/admin/snapshot").json()["permissions"]["canUseRegistrationBook"]
        assert web.get(pending, headers={"X-Actor-Type": "admin", "X-School-Id": "B"}).status_code == 403
        assert web.get(accounts).status_code == 403
