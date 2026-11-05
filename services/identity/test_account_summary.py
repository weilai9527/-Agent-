"""在两个独立学校的身份数据上验证摘要口径、动作撤权与旧库断开。"""

import json
import os
import sqlite3
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.identity import account_summary
from services.identity.test_organization import api, setup_nodes


@pytest.fixture
def summary_api(api, monkeypatch):
    identity_client, sign, store = api
    store_path = Path(os.environ["IDENTITY_SQLITE_PATH"])
    connect = sqlite3.connect

    def identity_only(path, *args, **kwargs):
        # 若摘要错误进入旧库或其他 SQLite 存储，此测试必须直接失败。
        assert Path(path).resolve() == store_path.resolve()
        return connect(path, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", identity_only)
    policy = json.loads(os.environ["SERVICE_TRUST_POLICY"])
    for role in ("admin", "teacher"):
        policy["caller"]["grants"]["identity"][role].append("student.read")
    monkeypatch.setenv("SERVICE_TRUST_POLICY", json.dumps(policy))
    for school in ("A", "B"):
        setup_nodes(identity_client, sign, school)
        with store.transaction(write=True) as tx:
            tx.execute("UPDATE identity_staff SET permissions=? WHERE school_id=? AND actor_id IN ('prof','root')",
                       (json.dumps(["student.read"]), school))
            tx.execute("INSERT INTO org_enrollments VALUES (?,'s1','c1','active'),(?,'s2','c2','active')", (school, school))
    with store.transaction(write=True) as tx:
        tx.execute("UPDATE identity_student_credentials SET status='disabled' WHERE school_id='A' AND actor_id='s2'")
        tx.execute("UPDATE identity_student_credentials SET must_change_password=1 WHERE school_id='A' AND actor_id IN ('s2','s3')")

    # 使用相同的原生表与完整验签依赖，独立装配以免更改其他身份模块的路由。
    app = FastAPI()
    app.state.store = store
    app.include_router(account_summary.router)
    with TestClient(app) as client:
        def query(actor="root", school="A", scope="student.read", **filters):
            return client.get("/v1/student-accounts/summary", headers=sign(scope, actor, school), params=filters)
        yield query, store


def test_school_and_class_account_status_counts(summary_api):
    query, store = summary_api
    expected = {"school_id": "A", "scope": "school", "accounts": 3, "normal_accounts": 2, "disabled_accounts": 1,
                "must_change_password": 1, "assigned_accounts": 2, "unassigned_accounts": 1, "unassigned_normal_accounts": 1}
    assert query().json() == expected
    assert query(school="B").json() == {**expected, "school_id": "B", "normal_accounts": 3,
                                        "disabled_accounts": 0, "must_change_password": 0}
    assert query("prof").json() == {**expected, "scope": "classes", "accounts": 1, "normal_accounts": 1,
                                    "disabled_accounts": 0, "must_change_password": 0, "assigned_accounts": 1,
                                    "unassigned_accounts": 0, "unassigned_normal_accounts": 0}
    assert query(college_id="dep").json()["accounts"] == 2
    assert query(class_id="c2").json()["disabled_accounts"] == 1
    for response in (query("prof", class_id="c2"), query(college_id="foreign", class_id="c1")):
        assert response.status_code == 403
    with store.transaction(write=True) as tx:
        tx.execute("DELETE FROM org_staff_classes WHERE school_id='A' AND staff_id='prof'")
    assert query("prof").json()["accounts"] == 0


def test_revoked_unassigned_and_registration_only_students(summary_api):
    query, store = summary_api
    with store.transaction(write=True) as tx:
        tx.execute("""INSERT INTO identity_student_credentials
                   (school_id,actor_id,student_no,name,password_hash,status,must_change_password)
                   VALUES ('A','revoked','N04','已撤销','unused','registration_revoked',1)""")
        # 尚未创建任何账号的登记只属于开户待办，不能抬高校级账号数。
        tx.execute("""INSERT INTO identity_registrations(school_id,student_no,name,college,class_name,class_id,
                   gender,counselor,source_status,student_status,opened,archived,revision)
                   VALUES ('A','N05','仅登记','','','','','','','',0,0,1)""")
    result = query().json()
    assert (result["accounts"], result["normal_accounts"], result["disabled_accounts"]) == (4, 2, 2)
    assert (result["unassigned_accounts"], result["unassigned_normal_accounts"], result["must_change_password"]) == (2, 1, 1)


def test_empty_sample_revoked_and_wrong_action(summary_api):
    query, store = summary_api
    assert query(scope="organization.read").status_code == 403
    assert query("other").status_code == 403
    with store.transaction(write=True) as tx:
        tx.execute("UPDATE identity_staff SET status='disabled' WHERE school_id='A' AND actor_id='prof'")
        tx.execute("DELETE FROM identity_student_credentials WHERE school_id='A'")
    assert query("prof").status_code == 403
    result = query().json()
    assert result["school_id"] == "A" and all(result[k] == 0 for k in result if k not in {"scope", "school_id"})
    assert query(school="B").json()["accounts"] == 3


@pytest.fixture
def registration_queue(api, monkeypatch):
    from shared.service_security import service_headers

    client, _, store = api
    policy = json.loads(os.environ["SERVICE_TRUST_POLICY"])
    policy["caller"]["grants"]["identity"] = {"admin": ["registration.read", "student.read"],
                                              "teacher": ["registration.read"]}
    policy["admin-gateway"] = policy["caller"]
    monkeypatch.setenv("SERVICE_TRUST_POLICY", json.dumps(policy))
    with store.transaction(write=True) as tx:
        tx.execute("UPDATE identity_staff SET permissions=? WHERE actor_id IN ('root','prof')",
                   (json.dumps(["registration.read", "student.read"]),))

    def query(who="root", school="A", role="admin", scope="registration.read", caller="admin-gateway", **kwargs):
        monkeypatch.setenv("SERVICE_ID", caller)
        auth = service_headers("identity", actor_id=who, school_id=school, actor_type=role, scopes=[scope])
        monkeypatch.setenv("SERVICE_ID", "identity")
        return client.request("GET", "/v1/student-accounts/pending-summary", headers=auth, **kwargs)

    return query, store


def test_pending_queue_counts_live_registrations_only(registration_queue):
    query, store = registration_queue
    assert query().json() == {"school_id": "A", "pending_accounts": 0, "items": []}
    with store.transaction(write=True) as tx:
        for school in ("A", "B"):
            tx.execute("UPDATE identity_student_credentials SET must_change_password=1 WHERE school_id=? AND actor_id='s1'",
                       (school,))
            tx.execute("UPDATE identity_student_credentials SET status='disabled' WHERE school_id=? AND actor_id='s2'",
                       (school,))
            tx.execute("UPDATE identity_student_credentials SET status='registration_revoked' WHERE school_id=? AND actor_id='s3'",
                       (school,))
        # s1 已开通待改密、s2 单纯停用、s3 被撤销开户。仅 s3 回到登记待办。
        for school, number, opened, archived, linked, status in [
            ("A", "N01", 0, 0, None, "禁用"), ("A", "N02", 0, 0, "s3", "正常"),
            ("A", "N03", 0, 0, None, ""), ("A", "N04", 0, 0, None, ""),
            ("A", "N05", 0, 0, None, ""), ("A", "N06", 0, 0, None, ""),
            ("A", "N07", 1, 0, "s1", ""), ("A", "N08", 1, 0, "s2", ""),
            ("A", "N09", 0, 1, None, ""), ("B", "N01", 0, 0, None, ""),
        ]:
            tx.execute("""INSERT INTO identity_registrations(school_id,student_no,name,college,class_name,class_id,
                       gender,counselor,source_status,student_status,actor_id,opened,archived,revision)
                       VALUES (?,?,?,'','','','','',?,'',?,?,?,1)""",
                       (school, number, school + number, status, linked, opened, archived))
    assert query().json() == {"school_id": "A", "pending_accounts": 6, "items": [
        {"student_no": f"N0{i}", "name": f"AN0{i}"} for i in range(1, 6)]}
    assert query(school="B").json() == {"school_id": "B", "pending_accounts": 1,
                                        "items": [{"student_no": "N01", "name": "BN01"}]}


def test_pending_queue_requires_current_school_manager_and_exact_action(registration_queue):
    query, store = registration_queue
    assert query(caller="caller").status_code == 403
    assert query(scope="student.read").status_code == 403
    assert query(who="prof", role="teacher").status_code == 403
    for filters in ({"school_id": "B"}, {"class_id": "c1"}):
        assert query(params=filters).status_code == 422
    assert query(json={"school_id": "B"}).status_code == 422
    with store.transaction(write=True) as tx:
        tx.execute("UPDATE identity_staff SET school_wide=0 WHERE school_id='A' AND actor_id='root'")
    assert query().status_code == 403
    with store.transaction(write=True) as tx:
        tx.execute("UPDATE identity_staff SET school_wide=1,permissions='[]' WHERE school_id='A' AND actor_id='root'")
    assert query().status_code == 403
    with store.transaction(write=True) as tx:
        tx.execute("UPDATE identity_staff SET permissions=?,status='disabled' WHERE school_id='A' AND actor_id='root'",
                   (json.dumps(["registration.read"]),))
    assert query().status_code == 403
    assert query(school="B").status_code == 200
