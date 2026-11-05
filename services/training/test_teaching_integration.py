"""使用进程内 ASGI、临时密钥和独立数据库验证教学服务契约。"""
import json
import os
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.analytics.app import app as analytics
from services.training.app import app as training
from services.identity.app import app as identity
from services.gateway.routes import mount_business_routes
from shared.service_security import service_headers
from shared.account_security import hash_password


def test_assignment_to_original_question_practice(tmp_path):
    deadline = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    identity_reads = ["identity.classes.read", "identity.roster.read"]
    grants = {
        "staff-gateway": {"identity": {"system": ["identity.session.resolve"]}, "training": {"teacher": ["training.read", "training.assign"]},
                          "analytics": {"teacher": ["analytics.teaching.read", "analytics.practice.assign"]}},
        "student-gateway": {"identity": {"system": ["identity.session.resolve"]}, "training": {"student": ["training.read", "training.start"]},
                            "analytics": {"student": ["analytics.self.read"]}},
        "interview": {"training": {"system": ["training.complete"]}},
        "credentials": {"training": {"teacher": ["training.verify"]}},
        "assessment": {"analytics": {"system": ["analytics.completion.write"]}},
        "training": {"identity": {"teacher": identity_reads}},
        "analytics": {"identity": {"teacher": identity_reads}, "training": {
            "system": ["training.verify"], "teacher": ["training.assign"]}},
    }
    keypairs = {name: Ed25519PrivateKey.generate() for name in {*grants, "identity"}}
    policy = {}
    settings = {}
    for name, key in keypairs.items():
        settings[name] = {"SERVICE_ID": name, "SERVICE_KEY_ID": "test-key", "SERVICE_SIGNING_KEY":
                          key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                            serialization.NoEncryption()).decode()}
        pub = key.public_key().public_bytes(serialization.Encoding.PEM,
                                            serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        policy[name] = {"schools": ["school-a", "school-b"], "keys": {"test-key": pub}, "grants": grants.get(name, {})}

    apps = {"training": training, "analytics": analytics, "identity": identity}
    origin = "https://school.test"
    for name in ("staff-gateway", "student-gateway"):
        apps[name] = FastAPI()
        mount_business_routes(apps[name], staff=name == "staff-gateway", origins=[origin])
    with ExitStack() as stack:
        stack.enter_context(patch.dict(os.environ, {
            "TRAINING_DB_ENGINE": "sqlite", "TRAINING_SQLITE_PATH": str(tmp_path / "training.sqlite"),
            "ANALYTICS_DB_ENGINE": "sqlite", "ANALYTICS_SQLITE_PATH": str(tmp_path / "analytics.sqlite"),
            "IDENTITY_DB_ENGINE": "sqlite", "IDENTITY_SQLITE_PATH": str(tmp_path / "identity.sqlite"),
            "IDENTITY_SESSION_MODE": "native", "ADMIN_FRONTEND_ORIGIN": origin, "LEGACY_SCHOOL_ID": "school-a", "FRONTEND_ORIGIN": origin,
            "IDENTITY_SERVICE_URL": "https://identity.test", "TRAINING_SERVICE_URL": "https://training.test",
            "ANALYTICS_SERVICE_URL": "https://analytics.test", "SERVICE_TRUST_POLICY": json.dumps(policy),
        }))
        clients = {name: stack.enter_context(TestClient(app)) for name, app in apps.items()}

        # 组织和学籍写入身份服务自己的 SQLite 库。训练和分析服务只通过认证接口读取授权名册。
        password = "offline-teaching-test"
        encoded = hash_password(password)
        with identity.state.store.transaction(write=True) as tx:
            tx.execute("INSERT INTO org_colleges VALUES ('school-a','college','学院','active')")
            tx.execute("INSERT INTO org_programs VALUES ('school-a','program','college','专业','active')")
            for tid, cid in [("t1", "c1"), ("t2", "c2")]:
                tx.execute("""INSERT INTO identity_staff
                    (school_id, actor_id, email, password_hash, name, actor_type, status, permissions)
                    VALUES ('school-a', ?, ?, ?, ?, 'teacher','normal',?)""",
                           (tid, tid+"@school.test", encoded, tid, json.dumps(["training.read","training.assign"])))
                tx.execute("INSERT INTO org_classes VALUES ('school-a', ?, 'program', ?, 'active')", (cid, cid))
                tx.execute("INSERT INTO org_staff_classes VALUES ('school-a', ?, ?)", (tid, cid))
            for sid in ["s1", "s2", "late-student"]:
                tx.execute("""INSERT INTO identity_student_credentials
                    (school_id, actor_id, student_no, name, password_hash, status, must_change_password)
                    VALUES ('school-a', ?, ?, ?, ?, 'normal', 0)""", (sid, "ST-"+sid.upper(), sid, encoded))
            for sid in ["s1", "s2"]:
                tx.execute("INSERT INTO org_enrollments VALUES ('school-a', ?, 'c1', 'active')", (sid,))

        def dispatch(transport, req):
            name = req.url.host.split(".")[0]
            assert req.url.host == name + ".test" and name in clients
            # 同步嵌套调用时切换到被调用方的服务身份，模拟各进程独立部署的签名边界。
            with patch.dict(os.environ, settings[name]):
                reply = clients[name].request(req.method, req.url.raw_path.decode(),
                                              content=req.content, headers=req.headers)
            return httpx.Response(reply.status_code, headers=reply.headers, content=reply.content)

        async def dispatch_async(transport, req):
            await req.aread()
            return dispatch(transport, req)

        stack.enter_context(patch.object(httpx.HTTPTransport, "handle_request", dispatch))
        stack.enter_context(patch.object(httpx.AsyncHTTPTransport, "handle_async_request", dispatch_async))

        def call(issuer, target, role, who, method, path, scope, payload=None, *, school="school-a", expected=200):
            with patch.dict(os.environ, settings[issuer]):
                headers = service_headers(target, actor_id=who, school_id=school, actor_type=role, scopes=[scope])
            with patch.dict(os.environ, settings[target]):
                reply = clients[target].request(method, path, headers=headers, json=payload)
            assert reply.status_code == expected, (path, reply.status_code, reply.text)
            return reply.json()

        def login(kind, **fields):
            reply = clients["identity"].post("/sessions/" + kind + "/login",
                json={**fields, "school_id": "school-a", "password": password})
            assert reply.status_code == 200, reply.text
            name = "identity_" + kind + "_session"
            return name + "=" + reply.cookies[name]

        teacher_cookie = login("staff", email="t1@school.test")
        student_cookies = {sid: login("student", student_no="ST-" + sid.upper())
                           for sid in ("s1", "s2", "late-student")}

        def browser(gateway, cookie, method, path, body=None, *, expected=200, origin_header=origin):
            with patch.dict(os.environ, settings[gateway]):
                reply = clients[gateway].request(method, path, json=body, headers={
                    "Cookie": cookie, "Origin": origin_header, "X-Actor-Id": "t2", "X-School-Id": "school-b"})
            assert reply.status_code == expected, (path, reply.status_code, reply.text)
            return reply.json()

        def teacher(service, method, path, payload=None, **kwargs):
            return browser("staff-gateway", teacher_cookie, method, "/api/admin/" + service + path, payload, **kwargs)

        def student(who, method, path, payload=None, **kwargs):
            return browser("student-gateway", student_cookies[who], method, "/api/training" + path, payload, **kwargs)

        prompt = "事务提交成功但响应丢失时，你如何处理重试？"
        body = {"class_ids": ["c1"], "title": "事务与重试", "job_role": "后端开发", "deadline": deadline,
                "questions": [{"question_id": "q1", "prompt": prompt}], "max_attempts": 1, "request_id": "publish"}
        teacher("training", "POST", "/tasks", {**body, "class_ids": ["c2"]}, expected=403)
        task = teacher("training", "POST", "/tasks", body)
        assert task["student_count"] == 2
        with identity.state.store.transaction(write=True) as tx:
            tx.execute("INSERT INTO org_enrollments VALUES ('school-a','late-student','c1','active')")
        assert [c["class_id"] for c in teacher("training", "GET", "/classes")["items"]] == ["c1"]
        assert [t["task_id"] for t in student("s1", "GET", "/tasks")["items"]] == [task["task_id"]]
        teacher("analytics", "GET", "/v1/teaching/weaknesses", expected=403)
        # 网关每次读写都从身份服务重新解析权限。
        with identity.state.store.transaction(write=True) as tx:
            tx.execute("UPDATE identity_staff SET permissions=? WHERE school_id='school-a' AND actor_id='t1'",
                       (json.dumps(["training.read", "training.assign", "analytics.teaching.read",
                                    "analytics.practice.assign"]),))
        start_path = "/tasks/" + task["task_id"] + "/attempts"
        student("s1", "POST", start_path, {"request_id": "bad"}, origin_header="https://other.test", expected=403)
        student("late-student", "POST", start_path, {"request_id": "late"}, expected=404)
        attempt = student("s1", "POST", start_path, {"request_id": "start"})
        assert student("s1", "POST", start_path, {"request_id": "start"}) == attempt
        student("s1", "POST", start_path, {"request_id": "again"}, expected=409)
        aid, iid = attempt["attempt_id"], attempt["interview_id"]
        report = {"event_id": "score", "version": 1, "attempt_id": aid, "questions": [
            {"question_id": "q1", "dimension": "幂等设计", "score": 45, "original_answer": "重发请求。"}]}

        def publish(expected=200):
            return call("assessment", "analytics", "system", "worker", "POST", "/v1/completions",
                        "analytics.completion.write", report, expected=expected)

        publish(expected=409)
        for _ in range(2):
            call("interview", "training", "system", "worker", "POST", "/attempts/" + aid + "/complete",
                 "training.complete", {"event_id": "done", "interview_id": iid})
        assert publish()["applied"]
        assert not publish()["applied"]
        check = call("credentials", "training", "teacher", "t1", "GET", "/interviews/" + iid + "/attempt",
                     "training.verify")
        assert (check["status"], check["student_id"], check["teacher_id"]) == ("completed", "s1", "t1")
        call("credentials", "training", "teacher", "t2", "GET", "/attempts/" + aid, "training.verify", expected=404)
        call("credentials", "training", "teacher", "t1", "GET", "/attempts/" + aid, "training.verify",
             school="school-b", expected=404)

        weak = "/v1/teaching/weaknesses"
        rows = teacher("analytics", "GET", weak)["items"]
        assert [(r["student_id"], r["question_text"], r["original_answer"]) for r in rows] == [
            ("s1", prompt, "重发请求。")]
        assert teacher("analytics", "GET", "/v1/teaching/summary")["completed_questions"] == 1
        practice = teacher("analytics", "POST", "/v1/teaching/practice",
                           {"attempt_id": aid, "question_id": "q1", "deadline": deadline,
                            "max_attempts": 1, "request_id": "remediate"})
        assert (practice["student_count"], practice["source_attempt_id"]) == (1, aid)
        practice_path = "/tasks/" + practice["task_id"] + "/attempts"
        student("s2", "POST", practice_path, {"request_id": "other"}, expected=404)
        retake = student("s1", "POST", practice_path, {"request_id": "allowed"})
        assert retake["questions"] == body["questions"] and retake["interview_id"] != iid
        with identity.state.store.transaction(write=True) as tx:
            tx.execute("UPDATE org_enrollments SET class_id='c2' WHERE school_id='school-a' AND student_id='s1'")
        assert not teacher("analytics", "GET", weak)["items"]
        call("credentials", "training", "teacher", "t1", "GET", "/attempts/" + aid, "training.verify", expected=404)
