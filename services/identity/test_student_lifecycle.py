"""在临时校内账号上验证经签名的学生管理操作。"""
import json
import os

import pytest

from shared.account_security import hash_password
from services.identity.candidate import COOKIE
from services.identity.test_candidate import login, session_api


@pytest.fixture
def lifecycle(session_api, monkeypatch):
    client, sign, store = session_api
    policy = json.loads(os.environ["SERVICE_TRUST_POLICY"])
    grants = ["student.reset", "student.status"]
    policy["agw"]["grants"]["identity"]["admin"].extend(grants)
    policy["agw"]["grants"]["identity"]["teacher"] = grants
    monkeypatch.setenv("SERVICE_TRUST_POLICY", json.dumps(policy))
    encoded = hash_password("OriginalPassword247!")
    with store.transaction(write=True) as tx:
        tx.execute("UPDATE identity_staff SET permissions=?", (json.dumps(grants),))
        for school in ("north", "south"):
            # 两个学校刻意共用学生编号，验证密码变更、会话撤销和审计写入始终携带学校条件。
            tx.execute("""INSERT INTO identity_student_credentials
                          VALUES (?,'student-1','STU101','Student',?,'normal',0)""", (school, encoded))

    def change(action, data, *, school="north", role="admin", student="student-1", scope=None):
        path = f"/v1/students/{student}/" + ("status" if action == "student.status" else "reset-password")
        return client.request("PATCH" if action == "student.status" else "POST", path,
                              headers=sign(school, "principal", role, scope or action), json=data)

    return client, sign, store, change


def test_reset_change_disable_reenable_and_tenant_isolation(lifecycle):
    client, sign, store, change = lifecycle
    assert login(client, school="south", password="OriginalPassword247!").status_code == 200
    south = client.cookies[COOKIE]
    assert login(client, password="OriginalPassword247!").status_code == 200
    north = client.cookies[COOKIE]

    def verify(token, school="north"):
        return client.post("/internal/sessions/student/resolve", headers=sign(school),
                           json={"token": token, "action": "training.read"})

    temporary = "OneTimePassword715!"
    reset = change("student.reset", {"temporary_password": temporary})
    assert reset.status_code == 200 and temporary not in reset.text
    assert verify(north).status_code == 401
    assert verify(south, "south").status_code == 200
    assert login(client, password="OriginalPassword247!").status_code == 401
    assert login(client, password=temporary).json()["user"]["mustChangePassword"] is True
    assert verify(client.cookies[COOKIE]).status_code == 403
    new = "NewStudentPassword629!"
    assert client.post("/sessions/student/change-initial-password",
                       json={"password": new, "confirm_password": new}).status_code == 200
    current = client.cookies[COOKIE]
    assert verify(current).status_code == 200
    assert change("student.status", {"status": "disabled"}).status_code == 200
    assert verify(current).status_code == 401 and login(client, password=new).status_code == 401
    # 重置已停用账号的密码后，账号应保持停用。
    assert change("student.reset", {"temporary_password": temporary}).status_code == 200
    assert login(client, password=temporary).status_code == 401
    assert change("student.status", {"status": "normal"}).status_code == 200
    assert verify(current).status_code == 401
    assert login(client, password=temporary).json()["user"]["mustChangePassword"] is True
    assert verify(south, "south").status_code == 200

    with store.transaction() as tx:
        rows = tx.all("""SELECT school_id,actor_id,target_id,summary FROM identity_audit
                         WHERE action IN ('student.status','student.reset')""")
        assert len(rows) == 4
        assert all((r["school_id"], r["actor_id"], r["target_id"]) == ("north", "principal", "student-1") for r in rows)
        assert sorted(r["summary"] for r in rows if r["summary"]) == ["disabled", "normal"]


@pytest.mark.parametrize("action,body", [("student.status", {"status": "disabled"}),
                                         ("student.reset", {"temporary_password": "TemporaryPassword817!"})])
def test_exact_actor_human_grant_and_school_required(lifecycle, action, body):
    client, _sign, store, change = lifecycle
    assert login(client, password="OriginalPassword247!").status_code == 200
    with store.transaction(write=True) as tx:
        tx.execute("UPDATE identity_student_credentials SET actor_id='south-only' WHERE school_id='south'")
    assert change(action, body, student="south-only").status_code == 404
    assert change(action, body, scope="student.import").status_code == 403
    assert change(action, {**body, "school_id": "south"}).status_code == 422
    with store.transaction(write=True) as tx:
        tx.execute("UPDATE identity_staff SET actor_type='teacher' WHERE school_id='north'")
    assert change(action, body, role="teacher").status_code == 403
    with store.transaction(write=True) as tx:
        tx.execute("UPDATE identity_staff SET actor_type='admin',school_wide=0 WHERE school_id='north'")
    assert change(action, body).status_code == 403
    with store.transaction(write=True) as tx:
        different_grant = "student.status" if action == "student.reset" else "student.reset"
        tx.execute("UPDATE identity_staff SET school_wide=1,permissions=? WHERE school_id='north'", (json.dumps([different_grant]),))
    assert change(action, body).status_code == 403
    assert client.get("/sessions/student/me").status_code == 200
    with store.transaction() as tx:
        assert not tx.one("SELECT id FROM identity_audit WHERE action=?", (action,))


def test_required_audit_failure_rolls_back_reset_and_session_revoke(lifecycle, monkeypatch):
    client, _sign, store, change = lifecycle
    assert login(client, password="OriginalPassword247!").status_code == 200

    def unavailable(*args, **kwargs):
        raise RuntimeError("simulated audit write failure")

    with monkeypatch.context() as isolated:
        isolated.setattr("services.identity.organization.audit", unavailable)
        with pytest.raises(RuntimeError, match="simulated audit write failure"):
            change("student.reset", {"temporary_password": "TemporaryPassword817!"})
    assert client.get("/sessions/student/me").status_code == 200
    assert login(client, password="OriginalPassword247!").status_code == 200
    with store.transaction() as tx:
        assert not tx.one("SELECT id FROM identity_audit WHERE action='student.reset'")
