"""管理台读取与修改采用相同的学校和动作边界。"""
import json
import os

from shared.service_security import service_headers
from services.identity.app import app
from services.identity.staff_adapter import _management_permissions
from services.identity.test_staff import api


def test_staff_directory_revisions_and_filtered_school_audit(api, monkeypatch):
    client, header, _ = api
    policy = json.loads(os.environ["SERVICE_TRUST_POLICY"])
    policy["admin-gateway"]["grants"]["identity"]["admin"].append("audit.read")
    monkeypatch.setenv("SERVICE_TRUST_POLICY", json.dumps(policy))

    def audit_header(school):
        monkeypatch.setenv("SERVICE_ID", "admin-gateway")
        result = service_headers("identity", actor_id="manager", school_id=school,
                                 actor_type="admin", scopes=["audit.read"])
        monkeypatch.setenv("SERVICE_ID", "identity")
        return result

    with app.state.store.transaction(write=True) as tx:
        tx.execute("UPDATE identity_staff SET name='Same name' WHERE actor_id='reader'")
        tx.execute("UPDATE identity_staff SET name='Other school only' WHERE school_id='B' AND actor_id='reader'")
        tx.execute("UPDATE identity_staff SET permissions=? WHERE actor_id='manager'",
                   (json.dumps(["permissions.manage", "audit.read"]),))
    list_url = "/v1/staff"
    page = client.get(list_url, headers=header("A", "admin"), params={"q": "Same name"}).json()
    assert page["total"] == 1 and "student.read" in page["actions"]
    account = page["items"][0]
    assert account["school_id"] == "A" and "password_hash" not in account
    for search in ("Other school only", "%"):
        assert client.get(list_url, headers=header("A", "admin"), params={"q": search}).json()["total"] == 0
    update = {"actor_type": "teacher", "status": "normal", "permissions": ["student.read"],
              "expected_revision": account["revision"]}
    path = list_url + "/reader/grants"
    assert client.put(path, headers=header("A", "admin"), json=update).status_code == 200
    assert client.put(path, headers=header("A", "admin"), json=update | {"permissions":[]}).status_code == 409
    assert client.put(list_url + "/manager/grants", headers=header("A", "admin"), json=update).status_code == 403
    row = client.get(list_url, headers=header("B", "admin"), params={"q": "reader"}).json()["items"][0]
    assert row["permissions"] == ["report.read"]
    assert client.get("/v1/audit", headers=audit_header("B")).json()["items"] == []
    with app.state.store.transaction(write=True) as tx:
        for number in range(4):
            tx.execute("""INSERT INTO identity_audit(school_id,id,actor_id,action,target_id,success,created_at)
                          VALUES ('A',?,'manager','test.action','student-1',1,'2026-01-01 00:00:00')""",
                       (str(number),))
    target = "/v1/audit"
    params = {"action":"test.action","actor_id":"manager","limit":2}
    first = client.get(target, headers=audit_header("A"), params=params).json()
    second = client.get(target, headers=audit_header("A"), params=params | {"before":first["next"]}).json()
    assert [r["id"] for r in first["items"] + second["items"]] == ["3", "2", "1", "0"]
    assert second["next"] is None
    assert client.get(target, headers=audit_header("B"), params={"before":"2"}).status_code == 400
    with app.state.store.transaction(write=True) as tx:
        tx.execute("UPDATE identity_staff SET school_wide=0 WHERE school_id='A' AND actor_id='manager'")
    assert client.get(list_url, headers=header("A", "admin")).status_code == 403
    assert client.get(target, headers=audit_header("A")).status_code == 403


def test_snapshot_exposes_only_executable_actions():
    grants = {"organization.read", "organization.manage", "student.read", "student.import", "student.reset",
              "student.status", "permissions.manage", "audit.read", "roster.import"}
    teacher = _management_permissions({"actor_type":"teacher", "school_wide":False}, grants)
    assert {key for key, allowed in teacher.items() if allowed} == {
        "canUseSchoolManagement", "canReadOrganization", "canReadStudentAccounts", "canImportRoster"}
    assert not any(_management_permissions({"actor_type":"admin", "school_wide":True}, set()).values())
    manager = _management_permissions({"actor_type":"admin", "school_wide":True}, grants)
    assert not manager["canReadStudentProfile"]
    assert all(value for key, value in manager.items() if key != "canReadStudentProfile")
    assert _management_permissions({"actor_type":"admin", "school_wide":True}, grants | {"profile.student.read"})["canReadStudentProfile"]
