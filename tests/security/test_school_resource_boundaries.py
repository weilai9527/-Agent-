"""使用签名 HTTP 请求访问独立 SQLite 库，所有上游业务事实均为合成数据。"""
import json
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import HTTPException
from fastapi.testclient import TestClient

from shared.service_security import service_headers
from services.credentials import app as credentials
from services.training import app as training


def pem_pair():
    key = Ed25519PrivateKey.generate()
    private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption()).decode()
    public = key.public_key().public_bytes(serialization.Encoding.PEM,
                                           serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    return private, public


def service_client(tmp_path, env, name, app, grants):
    private, public = pem_pair()
    env.setenv(f"{name.upper()}_DB_ENGINE", "sqlite")
    env.setenv(f"{name.upper()}_SQLITE_PATH", str(tmp_path / (name + ".sqlite")))
    env.setenv("SERVICE_ID", name)
    env.setenv("SERVICE_TRUST_POLICY", json.dumps({"gateway": {
        "keys": {"active": public}, "grants": {name: grants}, "schools": ["east", "west"],
    }}))

    def headers(role, actor_id, action, school="east"):
        with patch.dict(os.environ, SERVICE_ID="gateway", SERVICE_SIGNING_KEY=private,
                        SERVICE_KEY_ID="active"):
            return service_headers(name, actor_id=actor_id, actor_type=role, school_id=school,
                                   scopes=[action])

    return TestClient(app), headers


def test_attempt_access_requires_both_current_scope_and_the_actual_responsible_teacher(
    tmp_path, monkeypatch
):
    client, headers = service_client(tmp_path, monkeypatch, "training", training.app, {
        "teacher": ["training.assign", "training.read", "training.verify"],
        "student": ["training.start", "training.verify"],
    })
    # 两位老师都能看到这个班；只有实际下发任务的老师能改分。
    current_students = ["student-1"]
    monkeypatch.setattr(training.identity, "roster", lambda *_: {"class-1": current_students[:]})
    task = {
        "class_ids": ["class-1"], "questions": [{"question_id": "q1", "prompt": "Explain"}],
        "deadline": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        "max_attempts": 1, "title": "Test", "job_role": "Test",
    }
    with client:
        created = client.post("/tasks", json=task, headers=headers("teacher", "owner", "training.assign"))
        assert created.status_code == 200, created.text
        action = "/tasks/" + created.json()["task_id"] + "/attempts"
        start = client.post(action, json={"request_id": "first"},
                            headers=headers("student", "student-1", "training.start"))
        assert start.status_code == 200, start.text
        attempt = "/attempts/" + start.json()["attempt_id"]
        for role, actor, school in (("student", "student-2", "east"), ("teacher", "colleague", "east"),
                                    ("teacher", "owner", "west")):
            assert client.get(attempt, headers=headers(role, actor, "training.verify", school)).status_code in (403, 404)
        teacher = headers("teacher", "owner", "training.verify")
        assert client.get(attempt, headers=teacher).status_code == 200
        current_students.clear()
        assert client.get(attempt, headers=teacher).status_code in (403, 404)


def test_teacher_and_version_bound_issuance_and_revocation_during_chain_outage(tmp_path, monkeypatch):
    read, apply, approve = "credential.read", "credential.apply", "credential.approve"
    issue, revoke = "credential.issue", "credential.revoke"
    client, headers = service_client(tmp_path, monkeypatch, "credentials", credentials.app, {
        "teacher": [read, approve, issue, revoke], "student": [read, apply],
    })
    private, public = pem_pair()
    monkeypatch.setenv("CREDENTIALS_SIGNING_KEYS_JSON", json.dumps({
        "east": {"kid": "cert-key", "private_key": private},
    }))
    monkeypatch.setenv("CREDENTIALS_PUBLIC_KEYS_JSON", json.dumps({"east": {"cert-key": public}}))
    monkeypatch.delenv("PROVENANCE_SERVICE_URL", raising=False)
    evidence = {"school_id": "east", "student_id": "student-1", "interview_id": "i1",
                "report_id": "r1", "version": 1, "digest": "a" * 64}
    attempt = {**evidence, "task_id": "t1", "attempt_id": "a1", "teacher_id": "owner",
               "status": "completed"}

    def upstream(_actor, service, _path, _scope, body=None):
        # 即使上游返回来源记录，证书服务也必须核对学校、学生、负责教师及版本。
        if body is not None:
            if (body["version"], body["digest"]) != (evidence["version"], evidence["digest"]):
                raise HTTPException(409)
            return {**evidence, **body}
        return dict({"assessment": evidence, "training": attempt}[service])

    # 两位教师同在授权班级，模拟 identity 的实时动作许可。负责关系仍须由训练记录证明。
    staff_grants = {"owner": {read, approve, issue, revoke}, "colleague": {read, approve, issue, revoke}}

    def staff_authorization(actor, student_id, action):
        if (actor["school_id"] != "east" or student_id != "student-1"
                or action not in staff_grants.get(actor["actor_id"], ())):
            raise HTTPException(403)

    monkeypatch.setattr(credentials.sources.authorization, "check_student_action", staff_authorization)
    monkeypatch.setattr(credentials.sources, "_exchange", upstream)
    with client:
        student = headers("student", "student-1", apply)
        other = headers("student", "student-2", apply)
        assert client.post("/applications", json={"report_id": "r1"}, headers=other).status_code in (403, 404)
        application = client.post("/applications", json={"report_id": "r1"}, headers=student)
        assert application.status_code == 200, application.text
        url = "/applications/" + application.json()["id"]
        decision = {"version": 1, "digest": evidence["digest"], "decision": "approved"}
        for teacher, school in (("colleague", "east"), ("owner", "west")):
            result = client.post(url + "/review", json=decision,
                                 headers=headers("teacher", teacher, approve, school))
            assert result.status_code in (403, 404)
        owned_review = headers("teacher", "owner", approve)
        owned_issue = headers("teacher", "owner", issue)
        assert client.post(url + "/issue", headers=owned_issue).status_code == 409
        assert client.post(url + "/review", json=decision, headers=owned_review).status_code == 200
        # 改分后旧批准失效，签发须使用重新审核的新版本。
        evidence.update(version=2, digest="b" * 64)
        assert client.post(url + "/issue", headers=owned_issue).status_code == 409
        new_app = client.post("/applications", json={"report_id": "r1"}, headers=student)
        assert new_app.status_code == 200
        url = "/applications/" + new_app.json()["id"]
        decision.update(version=2, digest=evidence["digest"])
        assert client.post(url + "/review", json=decision, headers=owned_review).status_code == 200
        issued = client.post(url + "/issue", headers=owned_issue)
        assert issued.status_code == 200, issued.text
        serial = issued.json()["id"]
        assert client.post(url + "/issue", headers=owned_issue).json()["id"] == serial
        staff_grants["owner"].remove(issue)
        assert client.post(url + "/issue", headers=owned_issue).status_code == 403
        verify = "/verify/" + serial
        assert client.get(verify).json()["valid"] is True
        cancel = "/certificates/" + serial + "/revoke"
        assert client.post(cancel, json={"reason": "corrected"},
                           headers=headers("teacher", "colleague", revoke)).status_code in (403, 404)
        assert client.get(verify).json()["valid"] is True
        assert client.post(cancel, json={"reason": "corrected"},
                           headers=headers("teacher", "owner", revoke)).status_code == 200
        public_view = client.get(verify)
        assert public_view.headers["cache-control"] == "no-store"
        assert public_view.json()["valid"] is False and public_view.json()["status"] == "revoked"
        assert public_view.json()["anchor"]["status"] != "confirmed"
        assert "student-1" not in public_view.text and "corrected" not in public_view.text
