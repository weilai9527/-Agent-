"""使用独立 SQLite 专库及签名的身份服务，分别验证面试和报告查询。"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


@pytest.mark.parametrize("owner", ["interview", "assessment"])
def test_native_record_owner(tmp_path, owner):
    root = Path(__file__).resolve().parents[2]
    for folder in ("admin_backend/src", "backend/src", "backend/rtc_token_lib", "shared", "services"):
        for source in (root / folder).rglob("*.py"):
            dest = tmp_path / source.relative_to(root)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, dest)
    shutil.copyfile(__file__, tmp_path / "exercise.py")
    env = {key: os.environ[key] for key in ("PATH", "PYTHONPATH") if key in os.environ}
    env.update(APP_ENV="test", SERVICE_ID=owner, LEGACY_SCHOOL_ID="A", ASSESSMENT_STORAGE_MODE="isolated",
               IDENTITY_SESSION_MODE="native", IDENTITY_SERVICE_URL="https://identity.test",
               IDENTITY_DB_ENGINE="sqlite", IDENTITY_SQLITE_PATH=str(tmp_path / "identity.db"))
    prefix = "ASSESSMENT_" if owner == "assessment" else "INTERVIEW_"
    env.update({prefix + "DB_ENGINE": "sqlite", prefix + "SQLITE_PATH": str(tmp_path / (owner + ".db"))})
    proc = subprocess.run([sys.executable, "exercise.py"], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=45)
    assert proc.returncode == 0, proc.stderr


def exercise():
    from importlib import import_module
    from unittest.mock import patch
    import httpx
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from fastapi.testclient import TestClient
    from services.identity.app import app as identity
    from shared.service_security import service_headers

    owner = os.environ["SERVICE_ID"]
    api = import_module("services." + owner + ".app").app
    from services.interview.storage import db

    wire = owner + ".records.read"
    keys = {}
    policy = {}
    for caller, grants in (("admin-gateway", {owner: {"teacher": [wire, "assessment.score","interview.templates.read"], "admin": [wire,"interview.templates.read"]}}),
                           (owner, {"identity": {"teacher": ["identity.records.scope"], "admin": ["identity.records.scope"]}})):
        key = Ed25519PrivateKey.generate()
        keys[caller] = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                         serialization.NoEncryption()).decode()
        public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        policy[caller] = {"keys": {"test": public}, "schools": ["A", "B"], "grants": grants}
    os.environ.update(SERVICE_KEY_ID="test", SERVICE_SIGNING_KEY=keys[owner], SERVICE_TRUST_POLICY=json.dumps(policy))

    def signed(who="teacher", school="A", scope=wire):
        with patch.dict(os.environ, SERVICE_ID="admin-gateway", SERVICE_SIGNING_KEY=keys["admin-gateway"]):
            return service_headers(owner, actor_id=who, school_id=school, actor_type="admin" if who == "admin" else "teacher",
                                   scopes=[scope])

    async def dispatch(transport, request):
        assert request.url.host == "identity.test"
        with patch.dict(os.environ, SERVICE_ID="identity"):
            return await httpx.ASGITransport(app=identity).handle_async_request(request)

    def seed_identity(tx):
        for school in ("A", "B"):
            tx.execute("INSERT INTO org_colleges VALUES (?,'d','Department','active')", (school,))
            tx.execute("INSERT INTO org_programs VALUES (?,'p','d','Program','active')", (school,))
            for group in ("mine", "outside"):
                tx.execute("INSERT INTO org_classes VALUES (?,?,'p',?,'active')", (school, group, group))
            for who, grants in (("teacher", ["viewInterviews", "viewReports"]), ("admin", ["viewInterviews", "viewReports","interview.templates.read"]),
                                ("templates", ["interview.templates.read"]), ("both", ["interview.templates.read","viewInterviews"]), ("only-interviews", ["viewInterviews"]), ("only-reports", ["viewReports"])):
                tx.execute("INSERT INTO identity_staff VALUES (?,?,?,?,?,?, 'normal',?,?)",
                           (school, who, who+"@test.invalid", "!", who, "admin" if who == "admin" else "teacher",
                            json.dumps(grants), int(who == "admin")))
                tx.execute("INSERT INTO org_staff_classes VALUES (?,?,'mine')", (school, who))
            for sid in ("s", "S", "z"):
                tx.execute("""INSERT INTO identity_student_credentials
                    (school_id,actor_id,student_no,name,status,password_hash,must_change_password)
                    VALUES (?,?,?,?, 'normal','!',0)""", (school, sid, sid, "student-"+sid))
            tx.execute("INSERT INTO org_enrollments VALUES (?,'s','mine','active')", (school,))
            tx.execute("INSERT INTO org_enrollments VALUES (?,'S','outside','active')", (school,))

    with TestClient(identity), TestClient(api) as client, patch.object(httpx.AsyncHTTPTransport, "handle_async_request", dispatch):
        with identity.state.store.transaction(write=True) as tx:
            seed_identity(tx)
        with db:
            for iid, sid in (("a", "s"), ("b", "s"), ("foreign", "S"), ("alone", "z")):
                db.execute("""INSERT INTO interview_sessions(id,user_id,target_role,status,created_at,updated_at)
                    VALUES (?,?,'DB engineer',?,'2020-01-02 03:04:05','2020-01-02 03:04:05')""", (iid, sid, "running" if iid == "b" else "completed")).close()
                if owner == "assessment":
                    db.execute("""INSERT INTO interview_reports
                        (id,interview_id,user_id,total_score,grade,pass_recommendation,ability_radar,agent_feedback,
                         timeline_review,summary,suggestions,created_at,generation_status) VALUES (?,?,?,0,'D','no','{}','[]','[]',
                         'past report','[]','2020-01-02 03:04:05',?)""", (iid, iid, sid, "succeeded" if iid in ("a", "alone") else "queued")).close()
            db.execute("INSERT INTO interview_training_attempts VALUES ('b','attempt','A','s')").close()
            for idx in range(21):
                db.execute("""INSERT INTO interview_messages(id,interview_id,sender_type,message_type,content,order_index)
                    VALUES (?,'a','candidate','transcript','historic answer',?)""", (f"msg{idx:02}", idx//2)).close()
        url = "/v1/records"
        def get(path="", who="teacher", **params):
            return client.get(url + path, headers=signed(who), params=params)

        assert client.get(url).status_code == 401
        assert client.get(url, headers=signed(school="B")).status_code == 403
        assert get(who="only-reports" if owner == "interview" else "only-interviews").status_code == 403
        assert get(who="only-interviews" if owner == "interview" else "only-reports").status_code == 200
        assert [r["id"] for r in get(q="STUDENT-S").json()["items"]] == ["a", "b"]
        assert get(q="%").json()["items"] == []  # 百分号按普通字符查询，不能扩大权限范围。
        assert get(student_id="z").json()["items"] == []
        assert get(class_name="outside").json()["items"] == []
        assert [r["id"] for r in get(class_name="MiN").json()["items"]] == ["a", "b"]
        assert get(class_id="outside").status_code == 403
        assert get("/foreign").status_code == 404
        # 同一份当前授课关系既约束明细也约束汇总；学校级查看还包括未归班学生。
        if owner == "interview":
            with db:
                for iid in ("a","b","foreign"):
                    db.execute("""INSERT INTO interview_agents(id,interview_id,agent_name,agent_type,agent_role,strategy,order_index)
                                  VALUES (?,?,'系统面试官','technical','后端','检查可复现依据',1)""",(iid+"-instance",iid)).close()
            def templates(who, school="A", **filters):
                return client.get("/v1/agent-templates",headers=signed(who,school,"interview.templates.read"),params=filters)
            assert templates("teacher").status_code==403
            admin_recent = templates("admin",name="系统面试官",recent=True).json()["recentUsage"]
            assert {r["candidate"] for r in admin_recent} == {"student-s", "student-S"}

            assert templates("templates").json()["items"][0]["usageCount"]==2
            assert templates("templates",name="系统面试官",recent=True).status_code==403
            assert templates("both","B").status_code==403
            assert {r["interview_id"] for r in templates("both",name="系统面试官",recent=True).json()["recentUsage"]}=={"a","b"}
            with identity.state.store.transaction(write=True) as tx:
                tx.execute("DELETE FROM org_staff_classes WHERE school_id='A' AND staff_id='both'")
            assert templates("both",name="系统面试官",recent=True).status_code==404
        dashboard = "/v1/workbench"
        scoped = client.get(dashboard, headers=signed(), params={"college_id": "d", "class_id": "mine"})
        assert scoped.status_code == 200, scoped.text
        assert scoped.json()["total"] == 2
        assert {row["id"] for row in scoped.json()["recent"]} == {"a", "b"}
        assert client.get(dashboard, headers=signed("admin")).json()["total"] == 4
        assert client.get(dashboard, headers=signed(), params={"class_id": "outside"}).status_code == 403
        assert client.get(dashboard, headers=signed(school="B")).status_code == 403
        assert get("/A").status_code == 404
        assert get("/alone", "admin").status_code == 200
        assert get(class_id="mine", kind="practice").json()["items"][0]["id"] == "a"
        assert [r["id"] for r in get(kind="training").json()["items"]] == ["b"]
        first = get(limit=1).json()
        assert [(r["id"], r["student_id"], r["kind"]) for r in first["items"]] == [("a", "s", "practice")]
        token = first["next_cursor"]
        tampered = ("X" if token[0] != "X" else "Y") + token[1:]
        assert get(cursor=tampered).status_code == 422
        assert get(limit=1, cursor=token).json()["items"][0]["id"] == "b"
        assert get(limit=1, cursor=token, kind="training").status_code == 422
        state = "running" if owner == "interview" else "pending"
        narrow = {"college_id": "d", "class_id": "mine", "state": state, "kind": "training",
                  "start_date": "2020-01-02", "end_date": "2020-01-02"}
        assert [row["id"] for row in get(**narrow).json()["items"]] == ["b"]
        assert get(**{**narrow, "college_id": "outside"}).status_code == 403
        assert get(**{**narrow, "start_date": "2020-01-03"}).status_code == 422
        assert get(end_date="2020-01-01").json()["items"] == []
        assert get(state="pending" if owner == "interview" else "running").status_code == 422
        if owner == "interview":
            assert get(score_band="below70").status_code == 422
        else:
            assert get(score_band="near80").status_code == 422
            assert get(cursor=token, score_band="gte90").status_code == 422
        for key in ("college_id", "class_id", "start_date", "end_date", "state"):
            assert get(cursor=token, **{key: narrow[key]}).status_code == 422
        assert get(who="admin", cursor=token).status_code == 422
        assert client.get(url+"?class_id=mine&class_id=outside", headers=signed()).status_code == 422
        for args in ({"actor_id":"admin"}, {"school_id":"B"}, {"limit":999}, {"cursor":"%%%"},
                     {"student_id":"s/.."}, {"cursor":"eyJjbGFzcyI6IioifQ"}):
            assert get(**args).status_code == 422
        assert get(student_id="s' OR 1=1").status_code == 422
        assert get(student_id="s'--").json()["items"] == []
        detail = get("/a").json()
        assert detail["student_id"] == "s" and "2020" in str(get().json()["items"][0]["created_at"])
        if owner == "assessment":
            assert detail["summary"] == "past report" and detail["total_score"] == 0
            assert get("/b").json()["total_score"] is None
            # a 是有原答的历史零分，alone 是无原答的历史占位零分，三个入口保持同一口径。
            expected = {"a": 0, "alone": None}
            for rows in (get(who="admin").json()["items"],
                         client.get(dashboard, headers=signed("admin")).json()["recent"]):
                assert {r["id"]: r["total_score"] for r in rows if r["id"] in expected} == expected
            for rid, score in expected.items():
                assert get("/" + rid, who="admin").json()["total_score"] == score
            assert client.patch("/api/admin/reports/a/score", json={"total_score":95,"expected_version":1,"reason":"no"},
                                headers=signed()).status_code == 403
        else:
            assert len(detail["turns"]) == 20 and detail["next_cursor"]
            assert get("/a",cursor=detail["next_cursor"]).json()["turns"][0]["id"] == "msg20"
            assert get("/b",cursor=detail["next_cursor"]).status_code == 422
        with identity.state.store.transaction(write=True) as tx:
            for i in range(102):
                sid = f"0-empty-{i:03}"
                tx.execute("""INSERT INTO identity_student_credentials
                      (school_id,actor_id,student_no,name,status,password_hash,must_change_password)
                      VALUES ('A',?,?,?,'normal','!',0)""", (sid, sid, sid))
        empty = get(who="admin").json()
        assert empty["items"] == [] and empty["next_cursor"]
        assert len(get(who="admin", cursor=empty["next_cursor"]).json()["items"]) == 4
        with identity.state.store.transaction(write=True) as tx:
            tx.execute("UPDATE org_enrollments SET class_id='outside' WHERE school_id='A' AND student_id='s'")
        assert get(cursor=token).json() == {"items":[], "next_cursor":None}
        assert client.get(dashboard, headers=signed()).json()["total"] == 0
        assert get("/a").status_code == 404 and get("/a","admin").status_code == 200
        with identity.state.store.transaction(write=True) as tx:
            tx.execute("UPDATE identity_staff SET permissions='[]' WHERE school_id='A' AND actor_id='teacher'")
        assert get().status_code == get("/a").status_code == get("/missing").status_code == 403
        with patch.object(httpx.AsyncHTTPTransport, "handle_async_request", side_effect=httpx.ConnectError("offline")):
            assert get(who="admin").status_code == 503
            assert client.get(dashboard, headers=signed("admin")).status_code == 503


if __name__ == "__main__":
    exercise()
