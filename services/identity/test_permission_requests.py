import json
import os
from concurrent.futures import ThreadPoolExecutor

from shared.service_security import service_headers
from services.identity.app import app
from services.identity.permission_requests import SELF
from services.identity.test_staff import api

ME = "/v1/me/permission-requests"
ALL = "/v1/permission-requests"


def signed(monkeypatch, actor="reader", role="teacher", scope=SELF, school="A"):
    monkeypatch.setenv("SERVICE_ID", "admin-gateway")
    headers = service_headers("identity", actor_id=actor, school_id=school, actor_type=role, scopes=[scope])
    monkeypatch.setenv("SERVICE_ID", "identity")
    return headers


def trust(monkeypatch):
    policy = json.loads(os.environ["SERVICE_TRUST_POLICY"])
    grants = policy["admin-gateway"]["grants"]["identity"]
    grants["admin"].extend([SELF, "organization.manage"])
    grants["teacher"] = [SELF]
    monkeypatch.setenv("SERVICE_TRUST_POLICY", json.dumps(policy))


def test_self_requests_decision_roles_scope_replay_and_audit(api, monkeypatch):
    client, header, password = api
    trust(monkeypatch)
    read = signed(monkeypatch)
    mgr = header("A", "admin")
    foreign = header("B", "admin")
    req = {"actions": ["score.adjust"], "classes": ["mine"], "reason": "授课需要", "request_key": "first"}
    with app.state.store.transaction(write=True) as tx:
        tx.execute("INSERT INTO org_colleges VALUES ('A','c','C','active')")
        tx.execute("INSERT INTO org_programs VALUES ('A','p','c','P','active')")
        tx.execute("INSERT INTO org_classes VALUES ('A','mine','p','Mine','active')")
        tx.execute("INSERT INTO org_colleges VALUES ('B','c','C','active')")
        tx.execute("INSERT INTO org_programs VALUES ('B','p','c','P','active')")
        tx.execute("INSERT INTO org_classes VALUES ('B','foreign','p','Foreign','active')")
    assert client.post(ME, headers=read, json=req | {"actions":["permissions.manage"]}).status_code == 422
    assert client.post(ME, headers=read, json=req | {"classes":["foreign"]}).status_code == 422
    assert client.post(ME, headers=read, json=req | {"applicant":"manager"}).status_code == 422
    assert client.get(ALL, headers=read).status_code == 403
    with ThreadPoolExecutor(2) as pool:
        responses = list(pool.map(lambda _:client.post(ME, headers=read, json=req), range(2)))
    assert all(r.status_code == 200 for r in responses)
    assert responses[0].json() == responses[1].json()
    key = responses[0].json()["id"]
    assert client.post(ME, headers=read, json=req | {"reason":"改动请求"}).status_code == 409
    assert len(client.get(ME, headers=read).json()["items"]) == 1
    assert client.get(ALL, headers=foreign).json()["items"] == []
    path = ALL + "/" + key + "/decision"
    approval = {"status":"approved", "note":"确认负责本班"}
    assert client.post(path, headers=foreign, json=approval).status_code == 404
    assert client.post(path, headers=mgr, json=approval).status_code == 403  # 未获组织管理权限
    with app.state.store.transaction(write=True) as tx:
        tx.execute("""UPDATE identity_staff SET permissions=? WHERE school_id='A' AND actor_id='manager'""",
                   (json.dumps(["permissions.manage","organization.manage"]),))
    with ThreadPoolExecutor(2) as pool:
        responses = list(pool.map(lambda _:client.post(path, headers=mgr, json=approval), range(2)))
    assert [r.status_code for r in responses] == [200,200]
    item = client.get(ME, headers=read).json()["items"][0]
    assert (item["status"], item["reviewer"], item["decision_note"]) == ("approved","manager","确认负责本班")
    with app.state.store.transaction() as tx:
        assert tx.one("SELECT COUNT(*) AS n FROM org_staff_classes WHERE school_id='A' AND staff_id='reader'")["n"] == 1
        assert tx.one("SELECT COUNT(*) AS n FROM identity_audit WHERE target_id=?", (key,))["n"] == 2
    other = client.get(ME, headers=signed(monkeypatch, school="B")).json()
    assert not other["items"] and "score.adjust" in other["actions"]
    assert "score.adjust" not in client.get(ME, headers=read).json()["actions"]
    # 重放已批准的旧申请不能恢复后来直接撤销的权限。
    base = {"actor_type":"teacher", "permissions":["report.read"], "status":"normal"}
    assert client.put("/v1/staff/reader/grants", headers=mgr, json=base).status_code == 200
    assert client.post(path, headers=mgr, json=approval).status_code == 200
    assert "score.adjust" in client.get(ME, headers=read).json()["actions"]


def test_pending_snapshot_invalidated_on_aba_and_decision_cannot_self_approve(api, monkeypatch):
    client, header, _ = api
    trust(monkeypatch)
    read, mgr = signed(monkeypatch), header("A", "admin")
    request = {"actions":["score.adjust"], "reason":"岗位教学", "request_key":"r1"}
    key = client.post(ME, headers=read, json=request).json()["id"]
    body = {"actor_type":"teacher", "permissions":["report.read","score.adjust"]}
    assert client.put("/v1/staff/reader/grants", headers=mgr, json=body).status_code == 200
    assert client.put("/v1/staff/reader/grants", headers=mgr, json=body | {"permissions":["report.read"]}).status_code == 200
    path = ALL + "/" + key + "/decision"
    decision = {"status":"approved","note":"已核验"}
    assert client.post(path, headers=mgr, json=decision).status_code == 409
    assert client.get(ME, headers=read).json()["items"][0]["status"] == "stale"

    mgr_self = signed(monkeypatch, actor="manager", role="admin")
    key = client.post(ME, headers=mgr_self, json=request | {"actions":["organization.read"]}).json()["id"]
    assert client.post(ALL + "/" + key + "/decision", headers=mgr, json=decision).status_code == 403
    key = client.post(ME, headers=read, json=request | {"request_key":"r2"}).json()["id"]
    reject = {"status":"rejected", "note":"当前任务不需要"}
    assert client.post(ALL + "/" + key + "/decision", headers=mgr, json=reject).status_code == 200
    assert client.post(ALL + "/" + key + "/decision", headers=mgr, json=decision).status_code == 409
    with app.state.store.transaction(write=True) as tx:
        tx.execute("UPDATE identity_staff SET school_wide=0 WHERE school_id='A' AND actor_id='manager'")
    assert client.get(ALL, headers=mgr).status_code == 403


def test_native_browser_request_approval_and_new_session(api, monkeypatch, tmp_path):
    """使用独立浏览器会话和真实 Ed25519 凭据验证授权变更。"""
    monkeypatch.setenv("OPERATIONS_JOURNAL_DIR", str(tmp_path / "gateway-audit"))
    monkeypatch.setenv("OPERATIONS_SERVICE_URL", "https://operations.test")
    from functools import partial
    import httpx
    from fastapi.testclient import TestClient
    from services.gateway.native_admin import create_app

    identity, _, password = api
    trust(monkeypatch)
    monkeypatch.setenv("IDENTITY_SESSION_MODE", "native")
    monkeypatch.setenv("LEGACY_SCHOOL_ID", "A")
    monkeypatch.setenv("IDENTITY_SERVICE_URL", "https://identity.test")
    monkeypatch.setenv("ADMIN_FRONTEND_ORIGIN", "https://admin.test")
    monkeypatch.setenv("SERVICE_ID", "admin-gateway")
    policy = json.loads(os.environ["SERVICE_TRUST_POLICY"])
    policy["admin-gateway"]["grants"]["identity"]["system"].append("identity.session.proxy")
    monkeypatch.setenv("SERVICE_TRUST_POLICY", json.dumps(policy))

    def relay(request):
        # 本用例还验证诊断下游离线时，新授权仍通过独立身份服务生效，审计由临时持久卷待投递。
        if request.url.host == "operations.test":
            return httpx.Response(503, json={"detail":"测试中的诊断服务离线"})
        assert request.url.host == "identity.test" and request.headers["authorization"].startswith("Bearer ")
        with monkeypatch.context() as peer:
            peer.setenv("SERVICE_ID", "identity")
            response = identity.send(request)
        return httpx.Response(response.status_code, headers=response.headers, content=response.content)

    transport = httpx.MockTransport(relay)
    monkeypatch.setattr(httpx, "Client", partial(httpx.Client, transport=transport))
    monkeypatch.setattr(httpx, "AsyncClient", partial(httpx.AsyncClient, transport=transport))
    gateway = create_app()
    prefix, origin = "/api/admin/identity", "https://admin.test"
    with TestClient(gateway, base_url=origin, headers={"Origin":origin}) as teacher, \
         TestClient(gateway, base_url=origin, headers={"Origin":origin}) as principal:
        login = "/api/admin/auth/login"
        teacher_login = {"email":"reader@school.test", "password":password}
        assert teacher.post(login, json=teacher_login).status_code == 200
        assert principal.post(login, json={"email":"manager@school.test", "password":password}).status_code == 200
        assert teacher.get("/api/admin/snapshot").json()["permissions"]["canRequestStaffAccess"]
        assert teacher.get(prefix + ALL).status_code == 403
        req = {"actions":["training.read"], "reason":"教学", "request_key":"gateway-test"}
        assert teacher.post(prefix + ME, headers={"Origin":"https://other.test"}, json=req).status_code == 403
        key = teacher.post(prefix + ME, json=req).json()["id"]
        assert principal.get(prefix + ALL).json()["items"][0]["id"] == key
        result = principal.post(prefix + ALL + "/" + key + "/decision", json={"status":"approved","note":"同意"})
        assert result.status_code == 200, result.text
        assert teacher.get("/api/admin/auth/me").status_code == 401
        assert "training.read" in teacher.post(login, json=teacher_login).json()["admin"]["permissions"]
        assert teacher.get(prefix + ME).json()["items"][0]["status"] == "approved"
