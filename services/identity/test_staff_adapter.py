"""用真实服务签名验证管理页面的原生登录契约。"""
import json
import os
from functools import partial

import httpx
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from shared.service_security import service_headers
from services.identity.gateway import admin_gateway_context
from services.identity.staff import COOKIE
from services.identity.staff_adapter import mount_staff_auth
from services.identity.test_staff import api


def test_staff_browser_login_snapshot_resolution_and_revocation(api, monkeypatch):
    identity, sign_resolve, password = api
    monkeypatch.setenv("IDENTITY_SESSION_MODE", "native")
    monkeypatch.setenv("IDENTITY_SERVICE_URL", "https://identity.test")
    monkeypatch.setenv("LEGACY_SCHOOL_ID", "A")
    monkeypatch.setenv("SERVICE_ID", "admin-gateway")
    policy = json.loads(os.environ["SERVICE_TRUST_POLICY"])
    policy["admin-gateway"]["grants"]["identity"]["system"].append("identity.session.proxy")
    monkeypatch.setenv("SERVICE_TRUST_POLICY", json.dumps(policy))

    def relay(request):
        # 模拟两个进程的独立身份。同步解析和异步代理分别验证各自的动作与受众。
        assert request.url.host == "identity.test"
        assert request.headers["authorization"].startswith("Bearer ")
        assert "x-actor-id" not in request.headers and "x-school-id" not in request.headers
        with monkeypatch.context() as peer:
            peer.setenv("SERVICE_ID", "identity")
            reply = identity.send(request)
        return httpx.Response(reply.status_code, headers=reply.headers, content=reply.content)

    transport = httpx.MockTransport(relay)
    monkeypatch.setattr(httpx, "Client", partial(httpx.Client, transport=transport))
    monkeypatch.setattr(httpx, "AsyncClient", partial(httpx.AsyncClient, transport=transport))
    gateway = FastAPI()

    @gateway.get("/admin/report/history")
    def history(request: Request):
        return admin_gateway_context(request, "assessment.history")

    @gateway.patch("/admin/report/score")
    def adjust(request: Request):
        return admin_gateway_context(request, "assessment.score")

    mount_staff_auth(gateway)
    spoofed = {"X-Actor-ID": "manager", "X-School-ID": "B", "X-Actor-Type": "admin",
               "X-Scopes": "score.adjust", "Authorization": "Bearer browser-supplied"}
    login = {"email": "reader@school.test", "password": password, "school_id": "B", "actor_type": "admin"}
    with TestClient(gateway, base_url="https://admin.test") as browser:
        assert browser.get("/admin/report/history", headers=spoofed).status_code == 401
        response = browser.post("/api/admin/auth/login", headers=spoofed, json={**login, "password": "wrong"})
        assert response.status_code == 401 and COOKIE not in browser.cookies
        response = browser.post("/api/admin/auth/login", headers=spoofed, json=login)
        assert response.status_code == 200, response.text
        assert "Secure" in response.headers["set-cookie"] and "HttpOnly" in response.headers["set-cookie"]
        account = response.json()["admin"]
        assert (account["id"], account["school_id"], account["actorType"]) == ("reader", "A", "teacher")
        assert account["permissions"] == ["report.read"]
        assert browser.get("/api/admin/auth/me", headers=spoofed).json()["admin"] == account
        snapshot = browser.get("/api/admin/snapshot", headers=spoofed).json()
        assert snapshot["admin"] == account and snapshot["identityMode"] == "native"
        assert not snapshot["permissions"]["canAdjustScores"] and not snapshot["permissions"]["canReviewReports"]
        read = browser.get("/admin/report/history", headers=spoofed)
        assert read.json() == {"actor_id": "reader", "school_id": "A", "actor_type": "teacher",
                               "scopes": ["assessment.history"]}
        assert browser.patch("/admin/report/score", headers=spoofed).status_code == 403
        token = browser.cookies[COOKIE]

        # 两个学校都有同名账号且均在信任策略中，B 校网关仍不得使用或撤销 A 校会话。
        with monkeypatch.context() as other_gateway:
            other_gateway.setenv("LEGACY_SCHOOL_ID", "B")
            assert browser.get("/api/admin/auth/me").status_code == 401
            assert browser.get("/admin/report/history").status_code == 401
            assert browser.post("/api/admin/auth/logout").status_code == 200
        assert browser.get("/api/admin/auth/me", headers={"Cookie": f"{COOKIE}={token}"}).status_code == 200
        assert browser.post("/api/admin/auth/logout", headers={"Cookie": f"{COOKIE}={token}"}).status_code == 200
        assert browser.get("/api/admin/snapshot", headers={"Cookie": f"{COOKIE}={token}"}).status_code == 401

    # 有效签名不能让其他系统主体冒充网关，也不能在正文中自行指定学校。
    proxy_login = {k: login[k] for k in ("email", "password")} | {"school_id": "A"}
    for subject, school in (("unrelated-system", "A"), ("gateway", "B")):
        with monkeypatch.context() as peer:
            peer.setenv("SERVICE_ID", "admin-gateway")
            headers = service_headers("identity", actor_id=subject, school_id=school, actor_type="system",
                                      scopes=["identity.session.proxy"])
            peer.setenv("SERVICE_ID", "identity")
            assert identity.post("/sessions/staff/login", headers=headers, json=proxy_login).status_code == 403

    # 已登出的会话即使保留在浏览器中，也不能通过签名内部接口重放。
    revoked = identity.post("/internal/sessions/staff/resolve", headers=sign_resolve("A"),
                            json={"token": token, "action": "report.read"})
    assert revoked.status_code == 401
