"""用合成的报告和训练记录验证来源校验及拒绝路径。"""

from copy import deepcopy

import httpx
import pytest
from fastapi import HTTPException

from services.credentials import sources


def principal(kind="teacher", principal_id="teacher-1", action="credential.approve"):
    return {"actor_type": kind, "actor_id": principal_id, "school_id": "demo-school",
            "caller": "admin-gateway", "scopes": [action]}


@pytest.fixture
def peers(monkeypatch):
    records = {
        "assessment": {"school_id": "demo-school", "report_id": "report-1",
                       "student_id": "student-1", "interview_id": "interview-1",
                       "version": 3, "digest": "c" * 64, "extra_private_field": "hidden"},
        "training": {"school_id": "demo-school", "student_id": "student-1", "task_id": "task-1",
                     "teacher_id": "teacher-1", "interview_id": "interview-1",
                     "status": "completed", "attempt_id": "attempt-1", "questions": ["hidden"]},
    }
    requests = []

    def fetch(actor, service, path, scope):
        requests.append((deepcopy(actor), service, path, scope))
        return deepcopy(records[service])

    def check_action(actor, sid, action):
        requests.append((deepcopy(actor), "identity", sid, action))

    monkeypatch.setattr(sources, "check_student_action", check_action)
    monkeypatch.setattr(sources, "_get", fetch)
    return records, requests


def test_only_bound_references_leave_sources(peers):
    actor = principal()
    result = sources.current_evidence(actor, "report-1")
    assert result == {"report_id": "report-1", "school_id": "demo-school",
                      "student_id": "student-1", "teacher_id": "teacher-1",
                      "interview_id": "interview-1", "attempt_id": "attempt-1",
                      "training_id": "task-1", "version": 3, "digest": "c" * 64}
    sources.authorize(actor, "credential.approve", result)
    assert peers[1] == [
        (actor, "assessment", "/internal/credential-evidence/report-1", "assessment.credential-evidence"),
        (actor, "training", "/interviews/interview-1/attempt", "training.verify"),
        (actor, "identity", "student-1", "credential.approve"),
        (actor, "training", "/interviews/interview-1/attempt", "training.verify")]


@pytest.mark.parametrize("service,key,value,code", [
    ("assessment", "report_id", "report-2", 404), ("assessment", "school_id", "other-school", 404),
    ("assessment", "version", True, 502), ("assessment", "version", None, 502),
    ("assessment", "digest", "", 502), ("assessment", "interview_id", "..", 502),
    ("training", "status", "started", 409), ("training", "student_id", "student-2", 409),
    ("training", "teacher_id", "teacher-2", 404), ("training", "interview_id", "other", 404),
    ("training", "school_id", "other-school", 404), ("training", "attempt_id", "", 502),
])
def test_invalid_bindings_are_closed(peers, service, key, value, code):
    peers[0][service][key] = value
    with pytest.raises(HTTPException) as denied:
        sources.current_evidence(principal(), "report-1")
    assert denied.value.status_code == code


def test_student_cannot_fetch_peers_report(peers):
    with pytest.raises(HTTPException) as denied:
        sources.current_evidence(principal("student", "student-2", "credential.apply"), "report-1")
    assert denied.value.status_code == 404
    assert len(peers[1]) == 1


@pytest.mark.parametrize("actor,action", [
    (principal("admin", "admin-1"), "credential.approve"),
    (principal("system", "worker"), "credential.approve"),
    (principal(action="credential.read"), "credential.issue"),
    (principal("student", "student-1", "credential.revoke"), "credential.revoke"),
])
def test_per_action_delegation_and_roles(peers, actor, action):
    data = sources.current_evidence(principal(), "report-1")
    peers[1].clear()
    with pytest.raises(HTTPException) as denied:
        sources.authorize(actor, action, data)
    assert denied.value.status_code == 403
    assert not peers[1]


def test_revocation_uses_current_object_access_after_report_changes(peers):
    actor = principal(action="credential.revoke")
    historical = sources.current_evidence(actor, "report-1")
    peers[0]["assessment"]["version"] += 1
    peers[1].clear()
    sources.authorize(actor, "credential.revoke", historical)
    assert [item[1] for item in peers[1]] == ["identity", "training"]
    peers[0]["training"]["attempt_id"] = "rebound-attempt"
    with pytest.raises(HTTPException) as denied:
        sources.authorize(actor, "credential.revoke", historical)
    assert denied.value.status_code == 404


@pytest.mark.parametrize("status,expected", [(403, 404), (404, 404), (409, 409), (302, 503), (500, 503)])
def test_peer_denials_and_redirects_never_grant_access(monkeypatch, status, expected):
    monkeypatch.setenv("TRAINING_SERVICE_URL", "https://fixture.invalid")
    headers = []

    def capture(service, **kwargs):
        headers.append((service, kwargs))
        return {"Authorization": "Bearer fixture-only"}

    # 保留真实 HTTP 客户端对地址、请求头和状态码的处理，替换传输层以隔离网络。
    client_class = httpx.Client

    def fixture_client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return client_class(transport=httpx.MockTransport(
            lambda request: httpx.Response(status, headers={"Location": "https://unused.invalid"})
        ), **kwargs)

    monkeypatch.setattr(sources, "service_headers", capture)
    monkeypatch.setattr(sources.httpx, "Client", fixture_client)
    with pytest.raises(HTTPException) as denied:
        sources._get(principal(), "training", "/attempts/sample", "training.verify")
    assert denied.value.status_code == expected
    assert headers == [("training", {"actor_id": "teacher-1", "school_id": "demo-school",
                                     "actor_type": "teacher", "scopes": ["training.verify"]})]


@pytest.mark.parametrize("wrong", [{"serial": "e"*32}, {"proof_digest": "f"*64}, {"school_id": "other"},
                                   {"generation": True}, {"report_id": "other"}, {"version": True}])
def test_permit_receipt_must_bind_the_complete_reserved_envelope(monkeypatch, wrong):
    evidence = {"report_id": "r", "student_id": "s", "school_id": "demo-school",
                "interview_id": "i", "version": 1, "digest": "d"*64}
    candidate = {"serial": "1"*32, "generation": 1}

    def substitute(actor, service, path, scope, body):
        assert service == "assessment" and scope == "assessment.credential-authorize"
        assert path == "/internal/credential-evidence/r/authorize"
        return {**body, **evidence, **wrong}
    monkeypatch.setattr(sources, "_exchange", substitute)
    with pytest.raises(HTTPException) as ex:
        sources.authorize_issuance(principal(action="credential.issue"), "a"*64,
                                   evidence, candidate, "c"*64)
    assert ex.value.status_code == 502


def test_staff_verification_requires_native_identity(monkeypatch):
    monkeypatch.setenv("IDENTITY_SESSION_MODE", "legacy")
    with pytest.raises(HTTPException) as denied:
        sources.check_student_action(principal(), "student-1", "credential.approve")
    assert denied.value.status_code == 503
