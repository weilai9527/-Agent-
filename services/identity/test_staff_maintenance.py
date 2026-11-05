"""用真实学校凭据检验职员维护的层级、改密前限权和并发版本边界。"""
import json
import os

from services.identity.app import app
from services.identity.test_staff import api
from shared.service_security import service_headers


def test_staff_reset_needs_rotation_and_cannot_take_over_higher_privilege(api, monkeypatch):
    client, _, original = api
    actions = ["staff.profile.write", "staff.password.reset", "report.read"]
    rules = json.loads(os.environ["SERVICE_TRUST_POLICY"])
    rules["admin-gateway"]["grants"]["identity"]["admin"] += actions
    monkeypatch.setenv("SERVICE_TRUST_POLICY", json.dumps(rules))
    with app.state.store.transaction(write=True) as tx:
        tx.execute("UPDATE identity_staff SET permissions=? WHERE school_id='A' AND actor_id='manager'", (json.dumps(actions),))
    def call(method, uid, suffix, body=None, school="A"):
        scope = actions[0] if suffix == "profile" else actions[1]
        monkeypatch.setenv("SERVICE_ID", "admin-gateway")
        h = service_headers("identity", actor_id="manager", actor_type="admin", school_id=school, scopes=[scope])
        monkeypatch.setenv("SERVICE_ID", "identity")
        return client.request(method, f"/v1/staff/{uid}/{suffix}", json=body, headers=h)
    def login(pw, new=None):
        return client.post("/sessions/staff/login", json={"school_id":"A", "email":"reader@school.test", "password":pw,
                                                          **({"new_password":new} if new else {})})
    assert call("GET", "manager", "password-reset").status_code == 403
    assert call("GET", "reader", "password-reset", school="B").status_code == 403
    view = call("GET", "reader", "profile").json()
    assert call("PATCH", "reader", "profile", {"name":"新教师姓名", "expected_revision":view["revision"]}).json()["name"] == "新教师姓名"
    assert call("POST", "reader", "password-reset", {"expected_revision":view["revision"]}).status_code == 409
    assert login(original).status_code == 200
    fresh = call("GET", "reader", "password-reset").json()
    secret = call("POST", "reader", "password-reset", {"expected_revision":fresh["revision"]}).json()["temporary_password"]
    assert client.get("/sessions/staff/me").status_code == 401 and login(original).status_code == 401
    pending = login(secret)
    assert pending.status_code == 428 and not pending.cookies
    new = "Synthetic-Staff-Rotated-087"
    assert login(secret, new).status_code == 200
    assert login(secret).status_code == 401 and login(new).status_code == 200
    with app.state.store.transaction(write=True) as tx:
        audit = tx.all("SELECT * FROM identity_audit")
        assert secret not in str(audit) and new not in str(audit)
        tx.execute("UPDATE identity_staff SET permissions=? WHERE school_id='A' AND actor_id='reader'", ('["score.adjust"]',))
    assert call("GET", "reader", "password-reset").status_code == 403
