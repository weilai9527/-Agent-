"""通过真实签名和学生会话验证逐学生动作授权。"""
import json
import os

import pytest

from shared.account_security import hash_password
from services.identity.candidate import COOKIE, STUDENT_SCOPES
from services.identity.test_candidate import login, session_api


@pytest.fixture
def grants_api(session_api, monkeypatch):
    client, signed, store = session_api
    policy = json.loads(os.environ["SERVICE_TRUST_POLICY"])
    for role in ("teacher","admin"):
        policy["agw"]["grants"]["identity"].setdefault(role, []).append("permissions.manage")
    monkeypatch.setenv("SERVICE_TRUST_POLICY", json.dumps(policy))
    with store.transaction(write=True) as tx:
        tx.execute("UPDATE identity_staff SET permissions=?", (json.dumps(["permissions.manage"]),))
        password_hash = hash_password("TestPassword781!")
        for school in ("north","south"):
            tx.execute("""INSERT INTO identity_student_credentials VALUES
                       (?,'student-a','STU101','Student',?,'normal',0)""", (school, password_hash))
    return client, signed, store


def test_native_action_grants_isolated_and_revocable(grants_api):
    client, signed, store = grants_api
    path = "/v1/students/student-a/grants"

    def credential(school="north"):
        return signed(school,"principal","admin","permissions.manage")

    def resolve(token, action, school="north", headers=None):
        return client.post("/internal/sessions/student/resolve",
                           headers=signed(school) if headers is None else headers,
                           json={"token":token,"action":action})

    def edit(revision, scopes):
        return client.put(path, headers=credential(), json={"expected_revision":revision, "scopes":scopes})

    assert login(client, school="south", password="TestPassword781!").status_code == 200
    south = client.cookies[COOKIE]
    assert login(client, password="TestPassword781!").status_code == 200
    original = client.cookies[COOKIE]
    default = client.get(path,headers=credential()).json()
    assert default["configured"] is False and default["revision"] == 0
    assert set(default["scopes"]) == set(default["available_scopes"]) == STUDENT_SCOPES
    assert resolve(original, "profile.write").status_code == 200
    assert edit(0, ["permissions.manage", "profile.read"]).status_code == 422
    assert resolve(original, "profile.write").status_code == 200

    saved = edit(0, ["profile.read"])
    assert saved.status_code == 200 and saved.json()["revision"] == 1 and saved.json()["configured"] is True
    assert resolve(original, "profile.read").status_code == 401
    assert login(client, password="TestPassword781!").status_code == 200
    limited = client.cookies[COOKIE]
    assert resolve(limited, "profile.read").json()["actor_id"] == "student-a"
    assert resolve(limited, "profile.write").status_code == 403
    assert resolve(limited, "profile.read", headers={"Authorization":f"Bearer {limited}"}).status_code == 401
    assert resolve(south, "profile.write", school="south").status_code == 200
    assert resolve(south, "profile.write", school="north").status_code == 403
    assert edit(0, ["profile.write"]).status_code == 409
    assert resolve(limited, "profile.read").status_code == 200
    assert edit(1, []).json()["scopes"] == []
    assert client.get(path,headers=credential()).json() == {
        "school_id":"north", "student_id":"student-a", "scopes":[], "configured":True,
        "revision":2, "available_scopes":sorted(STUDENT_SCOPES)}
    assert resolve(limited, "profile.read").status_code == 401
    assert login(client, password="TestPassword781!").status_code == 200
    for action in ("profile.read","training.start","assessment.score"):
        assert resolve(client.cookies[COOKIE],action).status_code == 403
    with store.transaction() as tx:
        entries = tx.all("SELECT school_id,target_id,summary FROM identity_audit WHERE action='student.grants.replace'")
        assert len(entries) == 2
        assert all((e["school_id"],e["target_id"]) == ("north","student-a") for e in entries)
        assert sorted(json.loads(e["summary"])["revision"] for e in entries) == [1,2]


def test_authorizer_requires_local_school_wide_admin_and_named_object(grants_api):
    client, signed, store = grants_api
    with store.transaction(write=True) as tx:
        tx.execute("UPDATE identity_student_credentials SET actor_id='south-id' WHERE school_id='south'")

    def calls(sid="student-a", role="admin"):
        path = f"/v1/students/{sid}/grants"
        headers = signed("north","principal",role,"permissions.manage")
        return [client.get(path,headers=headers).status_code, client.put(path, headers=headers,
                json={"expected_revision":0,"scopes":["profile.read"]}).status_code]

    assert calls(sid="south-id") == [404,404]
    with store.transaction(write=True) as tx:
        tx.execute("UPDATE identity_staff SET school_wide=0 WHERE school_id='north'")
    assert calls() == [403,403]
    with store.transaction(write=True) as tx:
        tx.execute("UPDATE identity_staff SET school_wide=1,actor_type='teacher' WHERE school_id='north'")
    assert calls(role="teacher") == [403,403]
    with store.transaction(write=True) as tx:
        tx.execute("UPDATE identity_staff SET permissions='[]',actor_type='admin' WHERE school_id='north'")
    assert calls() == [403,403]
    with store.transaction() as tx:
        assert not tx.one("SELECT * FROM identity_student_grants")
