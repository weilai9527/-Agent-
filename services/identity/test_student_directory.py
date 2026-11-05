"""在独立学校样本上验证名录授权和私有表单预填。"""
import json
import os

from services.identity.test_organization import api, setup_nodes


def test_scoped_directory_and_live_department(api, monkeypatch):
    client, signed, store = api
    policy = json.loads(os.environ["SERVICE_TRUST_POLICY"])
    grants = policy["caller"]["grants"]["identity"]
    grants["admin"].append("student.read")
    grants["teacher"].append("student.read")
    grants["student"] = ["identity.student.read"]
    monkeypatch.setenv("SERVICE_TRUST_POLICY", json.dumps(policy))
    for school in ("A", "B"):
        setup_nodes(client, signed, school)
        with store.transaction(write=True) as tx:
            tx.execute("UPDATE identity_student_credentials SET name=? WHERE school_id=? AND actor_id='s1'",
                       (school+"学生", school))
            tx.execute("UPDATE org_colleges SET name=? WHERE school_id=?", (school+"学院", school))
            tx.execute("INSERT INTO org_enrollments VALUES (?,'s1','c1','active'),(?,'s2','c2','active')", (school,school))
            tx.execute("UPDATE identity_staff SET permissions=? WHERE school_id=? AND actor_id IN ('prof','root')",
                       (json.dumps(["student.read"]),school))

    def read(who, params=None, **auth):
        return client.get("/v1/students", params=params, headers=signed("student.read", who, **auth))

    def me(school="A"):
        return client.get("/internal/students/me", headers=signed("identity.student.read", "s1", school, "student"))

    first = read("prof").json()
    assert first["total"] == 1 and first["items"] == [{
        "actor_id": "s1", "name": "A学生", "student_no": "s1", "status": "normal",
        "must_change_password": False, "class_id": "c1", "class_name": "A section 1",
        "college": "A学院", "program": "Software"}]
    assert read("prof", {"q": "S1"}).json()["total"] == 1
    for term in ("s2", "B学生", "%"):
        assert read("prof", {"q": term}).json()["total"] == 0
    assert read("reader").status_code == 403
    assert read("root", {"limit": 1, "offset": 1}).json()["items"][0]["actor_id"] == "s2"
    assert read("root", {"limit": 0}).status_code == 422
    assert me().json()["college"] == "A学院" and me("B").json()["college"] == "B学院"
    assert me().json()["student_no"] == "s1"
    with store.transaction(write=True) as tx:
        tx.execute("UPDATE org_programs SET status='inactive' WHERE school_id='A'")
    assert read("prof").json()["total"] == 0 and me().json()["college"] is None
    assert read("root").json()["total"] == 3 and read("prof", school="B").json()["total"] == 1
    with store.transaction(write=True) as tx:
        tx.execute("UPDATE identity_student_credentials SET status='disabled' WHERE school_id='A' AND actor_id='s1'")
    assert me().status_code == 403
    assert read("root", {"q": "A学生"}).json()["items"][0]["status"] == "disabled"
