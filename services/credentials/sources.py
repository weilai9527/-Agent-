"""核对已发布的报告版本、对应训练的完成记录及操作者权限。

网关委派具体动作，身份服务检查教师对该学生的当前权限，
训练服务核对负责教师与任务归属。历史申请不能代替这些实时校验。
"""

import re

import httpx
from fastapi import HTTPException

from shared.service_http import resource_segment, service_origin
from shared.service_security import service_headers
from services.identity import authorization
from services.identity.gateway import session_mode


_ROLES = {
    "credential.apply": {"student"},
    "credential.read": {"student", "teacher", "admin"},
    "credential.approve": {"teacher"},
    "credential.issue": {"teacher", "admin"},
    "credential.revoke": {"teacher", "admin"},
    "credential.reissue": {"teacher", "admin"},
}


def check_student_action(actor, student_id, action):
    # 旧会话模式不能证明员工当前对该学生的权限。即使网关保留兼容入口，
    # 签发、撤销和管理查询仍要求原生身份服务作出实时决定。
    if actor["actor_type"] != "student" and session_mode() != "native":
        raise HTTPException(503, "证书管理需要原生身份授权服务。")
    authorization.check_student_action(actor, student_id, action)


def _exchange(actor, service, path, scope, *, body=None):
    url = service_origin(service) + path
    try:
        headers = service_headers(service, actor_id=actor["actor_id"], school_id=actor["school_id"],
                                  actor_type=actor["actor_type"], scopes=[scope])
        with httpx.Client(timeout=5, follow_redirects=False, trust_env=False) as client:
            if body is None:
                response = client.get(url, headers=headers)
            else:
                response = client.post(url, headers=headers, json=body)
        if response.status_code in (403, 404):
            # 用相同响应处理不存在和无权读取的资源，避免泄露其他学生的记录。
            raise HTTPException(404, "Credential source unavailable")
        if response.status_code == 409:
            raise HTTPException(409, "Credential source is not ready")
        response.raise_for_status()
        data = response.json()
    except (KeyError, ValueError, httpx.HTTPError):
        raise HTTPException(503, f"Cannot verify {service} source") from None
    if not isinstance(data, dict):
        raise HTTPException(502, f"Invalid {service} source")
    return data


def _get(actor, service, path, scope):
    return _exchange(actor, service, path, scope)


def authorize_issuance(actor, application_id, evidence, candidate, proof_digest):
    body = {"application_id": application_id, "generation": candidate["generation"],
            "serial": candidate["serial"], "version": evidence["version"], "digest": evidence["digest"],
            "proof_digest": proof_digest}
    report = resource_segment(evidence["report_id"])
    receipt = _exchange(actor, "assessment", f"/internal/credential-evidence/{report}/authorize",
                        "assessment.credential-authorize", body=body)
    expected = body | {key: evidence[key] for key in ("report_id", "student_id", "school_id", "interview_id")}
    if (receipt != expected or type(receipt.get("generation")) is not int
            or type(receipt.get("version")) is not int):
        raise HTTPException(502, "Assessment returned an unbound issuance permit")


def _source_id(row, key):
    value = row.get(key)
    if (not isinstance(value, str) or not 0 < len(value) <= 128 or value in (".", "..")
            or any(c.isspace() or ord(c) < 32 or c in "/\\%" for c in value)):
        raise HTTPException(502, "Incomplete credential source")
    return value


def _attempt(actor, interview_id):
    segment = resource_segment(interview_id)
    row = _get(actor, "training", f"/interviews/{segment}/attempt", "training.verify")
    binding = {key: _source_id(row, key) for key in
               ("interview_id", "attempt_id", "task_id", "student_id", "teacher_id", "school_id")}
    binding["training_id"] = binding.pop("task_id")
    if binding["interview_id"] != interview_id or binding["school_id"] != actor["school_id"]:
        raise HTTPException(404, "Training attempt unavailable")
    if ((actor["actor_type"] == "student" and actor["actor_id"] != binding["student_id"])
            or (actor["actor_type"] == "teacher" and actor["actor_id"] != binding["teacher_id"])):
        raise HTTPException(404, "Training attempt unavailable")
    if row.get("status") != "completed":
        raise HTTPException(409, "Completed teaching attempt required")
    return binding


def current_evidence(actor, report_id):
    """只保留本次签发依据的不可变引用。"""
    if actor["actor_type"] not in {"student", "teacher", "admin"}:
        raise HTTPException(403, "Credential action requires a human principal")
    segment = resource_segment(report_id)
    report = _get(actor, "assessment", f"/internal/credential-evidence/{segment}",
                  "assessment.credential-evidence")
    if report.get("report_id") != report_id or report.get("school_id") != actor["school_id"]:
        raise HTTPException(404, "Report unavailable")
    student_id = _source_id(report, "student_id")
    if actor["actor_type"] == "student" and student_id != actor["actor_id"]:
        raise HTTPException(404, "Report unavailable")
    version, digest = report.get("version"), report.get("digest")
    if (type(version) is not int or version < 1 or not isinstance(digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", digest)):
        raise HTTPException(502, "Assessment has no verifiable published revision")
    attempt = _attempt(actor, _source_id(report, "interview_id"))
    if student_id != attempt["student_id"]:
        raise HTTPException(409, "Assessment and training owners disagree")
    return {**attempt, "report_id": report_id, "version": version, "digest": digest}


def authorize(actor, action, evidence):
    """对历史证书也重新核对当前的训练归属和人员权限。

    改分后仍可撤销旧证书，因此撤销只检查训练绑定。审核、签发和补发
    另行核对报告版本，保证新版本只能使用自己的审批记录。
    """
    if (action not in actor["scopes"] or actor["actor_type"] not in _ROLES.get(action, ())
            or actor["school_id"] != evidence.get("school_id")):
        raise HTTPException(403, "Credential action unavailable")
    check_student_action(actor, _source_id(evidence, "student_id"), action)
    attempt = _attempt(actor, _source_id(evidence, "interview_id"))
    if any(evidence.get(key) != value for key, value in attempt.items()):
        raise HTTPException(404, "Credential training binding changed")
