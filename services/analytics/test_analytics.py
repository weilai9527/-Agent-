"""使用临时 SQLite 和真实签名鉴权，上游依赖在进程内模拟。"""
from concurrent.futures import ThreadPoolExecutor
import json

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from shared.service_security import service_headers
from . import peers
from .app import app


@pytest.fixture
def harness(tmp_path, monkeypatch):
    scopes = {"system": ["analytics.completion.write"], "student": ["analytics.self.read"],
              "teacher": ["analytics.teaching.read", "analytics.practice.assign"], "admin": ["analytics.teaching.read"]}
    accounts = {"assessment": ["system"], "student-gw": ["student"], "staff-gw": ["teacher", "admin"],
                "rogue": ["system"]}
    grants = {}
    keys = {}
    for caller, roles in accounts.items():
        key = Ed25519PrivateKey.generate()
        keys[caller] = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                         serialization.NoEncryption()).decode()
        public = key.public_key().public_bytes(serialization.Encoding.PEM,
                                               serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        grants[caller] = {"keys": {"local": public}, "schools": ["s", "other"],
                          "grants": {"analytics": {role: scopes[role] for role in roles}}}
    monkeypatch.setenv("SERVICE_ID", "analytics")
    monkeypatch.setenv("SERVICE_TRUST_POLICY", json.dumps(grants))
    monkeypatch.setenv("SERVICE_KEY_ID", "local")
    monkeypatch.setenv("ANALYTICS_DB_ENGINE", "sqlite")
    monkeypatch.setenv("ANALYTICS_SQLITE_PATH", str(tmp_path / "analytics.sqlite"))

    def auth(role, actor, school="s", scope=None, caller=None):
        caller = caller or {"system": "assessment", "teacher": "staff-gw", "admin": "staff-gw",
                            "student": "student-gw"}[role]
        with monkeypatch.context() as mp:
            mp.setenv("SERVICE_ID", caller)
            mp.setenv("SERVICE_SIGNING_KEY", keys[caller])
            return service_headers("analytics", actor_id=actor, school_id=school, actor_type=role,
                                   scopes=[scope or scopes[role][0]])

    attempts = {}
    membership = {"c": ["learner", "peer"], "hidden": ["other-student"]}
    forwarded = []
    def upstream(ctx, service, scope, method, path, body=None):
        if scope == "training.verify":
            attempt = attempts.get(path.removeprefix("/attempts/"))
            if not attempt:
                raise HTTPException(404)
            return attempt
        if scope == "training.assign":
            forwarded.append((ctx, body))
            return {"task_id": "practice-task"}
        if scope == "identity.classes.read":
            return {"items": [{"class_id": "c", "name": "Class C"}]}
        assert scope == "identity.roster.read"
        assert body["class_ids"] == ["c"]
        return {"classes": [{"class_id": c, "student_ids": membership[c]} for c in body["class_ids"]]}
    monkeypatch.setattr(peers, "call", upstream)
    with TestClient(app) as client:
        yield client, auth, attempts, membership, forwarded


def seed(attempts, aid="try", **more):
    attempts[aid] = {"school_id": "s", "student_id": "learner", "teacher_id": "t", "class_id": "c",
                     "task_id": "task", "attempt_id": aid, "interview_id": "interview-" + aid, "status": "completed", "job_role": "工艺师",
                     "questions": [{"question_id": "q", "prompt": "冻结的原题？"}], **more}


def event(aid="try", **changes):
    return {"attempt_id": aid, "event_id": "score-" + aid, "version": 1,
            "questions": [{"question_id": "q", "original_answer": "原回答", "dimension": "沟通", "score": 48}],
            **changes}


def test_revision_races_and_atomic_rollback(harness):
    client, auth, attempts, _, _ = harness
    headers = auth("system", "worker")
    seed(attempts)
    original = event()
    revised = event(version=2, event_id="v2", questions=[{**original["questions"][0], "score": 92}])
    def post(body):
        return client.post("/v1/completions", headers=headers, json=body)
    with ThreadPoolExecutor(max_workers=5) as pool:
        responses = list(pool.map(post, [original, original, revised, original, revised]))
    assert all(r.status_code == 200 for r in responses), [(r.status_code, r.text) for r in responses]
    assert sum(r.json()["applied"] for r in responses) in (1, 2)
    assert post({**original, "event_id": "late-v1"}).json() == {"attempt_id": "try", "version": 2, "applied": False}
    assert post({**revised, "questions": []}).status_code == 409
    assert post({**revised, "event_id": "different", "questions": []}).status_code == 409
    assert post({**revised, "event_id": "different"}).status_code == 200
    db = app.state.db
    with db.transaction() as tx:
        assert tx.one("SELECT COUNT(*) AS n FROM analytics_scores") == {"n": 1}
        assert tx.one("SELECT score FROM analytics_scores") == {"score": 92}
        assert tx.one("SELECT COUNT(*) AS n FROM analytics_events") == {"n": 4}
    assert client.get("/v1/me/weaknesses", headers=auth("student", "learner")).json() == {"items": []}


def test_event_rejects_unbound_or_untrusted_evidence(harness):
    client, auth, attempts, _, _ = harness
    headers = auth("system", "worker")
    def publish(body, credential=headers):
        return client.post("/v1/completions", headers=credential, json=body).status_code
    seed(attempts, status="started")
    assert publish(event()) == 409
    seed(attempts, school_id="other")
    assert publish(event()) == 404
    seed(attempts)
    assert publish(event(student_id="impostor")) == 422
    assert publish(event(questions=[{**event()["questions"][0], "question_id": "invented"}])) == 422
    assert publish(event(), auth("system", "worker", caller="rogue")) == 403
    assert publish(event(), auth("student", "learner")) == 403
    assert publish(event(), {}) == 401
    with app.state.db.transaction() as tx:
        assert tx.one("SELECT COUNT(*) AS n FROM analytics_events") == {"n": 0}


def test_teacher_and_admin_scope_and_original_practice(harness):
    client, auth, attempts, members, forwarded = harness
    publisher = auth("system", "worker")
    for aid, override in (("try", {}), ("other-teacher", {"teacher_id": "u"}),
                          ("other-class", {"class_id": "hidden"}), ("peer", {"student_id": "peer"})):
        seed(attempts, aid, **override)
        assert client.post("/v1/completions", json=event(aid), headers=publisher).status_code == 200
    seed(attempts, "other-school", school_id="other")
    assert client.post("/v1/completions", json=event("other-school"), headers=auth("system", "worker", "other")).is_success
    teacher = auth("teacher", "t")
    def visible(headers):
        response = client.get("/v1/teaching/weaknesses", headers=headers)
        assert response.status_code == 200
        return {r["attempt_id"] for r in response.json()["items"]}
    assert visible(teacher) == {"try", "peer"}
    assert visible(auth("admin", "school-admin")) == {"try", "peer", "other-teacher"}
    assert client.get("/v1/teaching/summary?class_id=hidden", headers=teacher).json()["attempts"] == 0
    own = client.get("/v1/me/weaknesses", headers=auth("student", "learner")).json()["items"]
    assert {r["attempt_id"] for r in own} == {"try", "other-class", "other-teacher"}
    assert client.get("/v1/me/weaknesses", headers=auth("student", "stranger")).json()["items"] == []
    assert own[0]["question_text"] == "冻结的原题？"
    assert own[0]["original_answer"] == "原回答"
    assignment = auth("teacher", "t", scope="analytics.practice.assign")
    body = {"attempt_id": "try", "question_id": "q", "request_id": "once",
            "deadline": "2030-01-01T00:00:00Z", "max_attempts": 2}
    url = "/v1/teaching/practice"
    assert client.post(url, headers=assignment, json={**body, "student_id": "other"}).status_code == 422
    assert client.post(url, headers=assignment, json={**body, "attempt_id": "other-teacher"}).status_code == 404
    assert client.post(url, headers=assignment, json=body).json() == {"task_id": "practice-task"}
    ctx, payload = forwarded.pop()
    assert ctx["actor_id"] == "t" and ctx["school_id"] == "s"
    assert payload["source_attempt_id"] == "try" and payload["prompt"] == "冻结的原题？"
    assert set(payload) == {"source_attempt_id", "question_id", "request_id", "deadline", "prompt", "max_attempts"}
    members["c"].remove("learner")
    assert visible(teacher) == {"peer"}
    assert client.post(url, headers=assignment, json=body).status_code == 404
    assert not forwarded


def test_question_mean_and_dimension_breakdowns(harness):
    client, auth, attempts, _, _ = harness
    seed(attempts, questions=[{"question_id": "q", "prompt": "q"}, {"question_id": "q2", "prompt": "q2"}])
    rows = event()["questions"]
    rows += [{**rows[0], "dimension": "礼仪", "score": 72},
             {**rows[0], "question_id": "q2", "score": 90}]
    assert client.post("/v1/completions", json=event(questions=rows), headers=auth("system", "worker")).is_success
    summary = client.get("/v1/teaching/summary", headers=auth("teacher", "t")).json()
    assert (summary["attempts"], summary["completed_questions"], summary["average_score"]) == (1, 2, 75)
    assert summary["by_class"][0]["key"] == "c"
    assert summary["by_task"][0]["key"] == "task"
    assert summary["by_job"][0]["key"] == "工艺师"
    assert {g["key"]: g["average_score"] for g in summary["by_dimension"]} == {"礼仪": 72, "沟通": 69}
    for name, value in (("task_id", "other"), ("job_role", "其他"), ("dimension", "其他")):
        msg = client.get("/v1/teaching/summary", params={name: value}, headers=auth("teacher", "t")).json()
        assert msg["attempts"] == 0 and msg["average_score"] is None


def test_coverage_and_weak_cohort_use_scoped_frozen_questions(harness):
    client, auth, attempts, roster, _ = harness
    publisher = auth("system", "worker")
    teacher = auth("teacher", "t")
    url = "/v1/teaching/summary"
    frozen = [{"question_id": "q", "prompt": "第一题"}, {"question_id": "q2", "prompt": "第二题"}]
    first = event()["questions"][0]
    two = [first, {**first, "question_id": "q2", "dimension": "推理", "score": 88}]
    for aid, student, observations in (("full", "learner", two), ("partial", "peer", [first]),
                                        ("empty", "learner", []), ("legacy", "learner", [first]),
                                        ("outside", "outsider", two)):
        seed(attempts, aid, questions=frozen, student_id=student)
        assert client.post("/v1/completions", json=event(aid, questions=observations), headers=publisher).is_success
    seed(attempts, "other-school", school_id="other", questions=frozen)
    assert client.post("/v1/completions", json=event("other-school", questions=two),
                       headers=auth("system", "worker", "other")).is_success
    # 旧版发布端没有冻结题数；历史已评分题仍可查看，整份任务的覆盖应标为未知。
    with app.state.db.transaction(write=True) as tx:
        tx.execute("DELETE FROM analytics_attempt_context WHERE school_id='s' AND attempt_id='legacy'")
    def counts(group):
        return tuple(group[k] for k in ("attempts", "scored_attempts", "valid_attempts",
                                        "insufficient_attempts", "unknown_coverage_attempts"))
    result = client.get(url, headers=teacher).json()
    assert counts(result) == counts(result["by_class"][0]) == (4, 3, 1, 2, 1)
    assert result["completed_questions"] == 4
    assert result["class_weaknesses"] == [{"class_id": "c", "dimension": "沟通", "weak_questions": 3,
                                           "scored_questions": 3, "affected_students": 2, "average_score": 48.0}]
    reasoning = client.get(url, params={"dimension": "推理"}, headers=teacher).json()
    assert counts(reasoning) == counts(reasoning["by_dimension"][0]) == (1, 1, 1, 0, 0)
    weak = client.get("/v1/teaching/weaknesses", headers=teacher).json()["items"]
    assert {r["interview_id"] for r in weak} == {"interview-full", "interview-partial", None}
    full = next(r for r in weak if r["attempt_id"] == "full")
    assert (full["task_id"], full["question_id"], full["question_text"]) == ("task", "q", "第一题")

    # 新版本可减少评分覆盖；迟到旧版本不能恢复过期题分。达标题次仍计入班级分母。
    revised = event("full", version=2, event_id="v2", questions=[{**first, "score": 75}])
    assert client.post("/v1/completions", json=revised, headers=publisher).json()["applied"]
    assert not client.post("/v1/completions", json=event("full", questions=two), headers=publisher).json()["applied"]
    result = client.get(url, headers=teacher).json()
    assert counts(result) == (4, 3, 0, 3, 1)
    assert result["class_weaknesses"][0] == {"class_id": "c", "dimension": "沟通", "weak_questions": 2,
                                             "scored_questions": 3, "affected_students": 2, "average_score": 57}
    roster["c"].remove("peer")
    result = client.get(url, headers=teacher).json()
    assert counts(result) == (3, 2, 0, 2, 1)
    assert result["class_weaknesses"][0]["affected_students"] == 1
    assert not client.post("/v1/completions", json=event("legacy"), headers=publisher).json()["applied"]
    assert counts(client.get(url, headers=teacher).json()) == (3, 2, 0, 3, 0)
