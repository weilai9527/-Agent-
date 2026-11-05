"""通过服务身份鉴权的评估接口，按学校访问面试报告。"""

import hashlib
import json
import os
from typing import Literal

import httpx
from fastapi import Depends, FastAPI, HTTPException, Response
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field

from shared.credential_reference import application_id
from shared.service_http import request_json, resource_segment, service_origin
from shared.service_security import require_service, service_headers
from .storage_mode import assessment_owner, isolated

from shared.runtime_mode import require_native_runtime

# 在初始化专库前拦截受限配置，直接 ASGI 启动也遵守同一部署边界。
require_native_runtime()

if isolated() and not assessment_owner():
    raise RuntimeError("Isolated assessment API requires SERVICE_ID=assessment")

from . import runtime as assessment
from . import versions
from .inbox import accept as accept_projection
from services.identity.authorization import check_student_action
from services.school_records import school_record_router

app = FastAPI(title="Interview assessment")
app.include_router(school_record_router("assessment"))


def _school_actor(actor, *roles):
    school_id = os.environ.get("LEGACY_SCHOOL_ID")
    if not school_id:
        raise HTTPException(503, "尚未绑定面试库所属学校。")
    if actor["school_id"] != school_id or actor["actor_type"] not in roles:
        raise HTTPException(403, "当前身份不能执行此操作。")


def _student(scope):
    async def user(actor=Depends(require_service("assessment", scope))):
        _school_actor(actor, "student")
        # 网关已验证浏览器会话，接到委派请求后仍需向身份服务核实本校账号。
        # 核验通过服务接口完成，评估端无需连接账号源库。
        row = await request_json("identity", "GET", "/internal/students/me", actor=actor,
                                 scope="identity.student.read")
        if (row.get("actor_id") != actor["actor_id"] or row.get("school_id") != actor["school_id"]
                or row.get("status") != "normal" or row.get("must_change_password") is not False):
            raise HTTPException(403, "Student outside assessment boundary")
        return {"id": actor["actor_id"], "name": row["name"]}
    return user


student_read = _student("assessment.read")
student_generate = _student("assessment.generate")
student_evaluate = _student("assessment.evaluate")


@app.get("/api/interviews/{interview_id}/evaluations")
def list_evaluations(interview_id: str, user=Depends(student_read)):
    return assessment.list_evaluations(interview_id, user=user)


@app.post("/api/interviews/{interview_id}/evaluations", status_code=201)
def evaluate(interview_id: str, response: Response, body: dict | None = None, user=Depends(student_evaluate)):
    return assessment.create_evaluation(interview_id, response, body=body, user=user)


@app.get("/api/interviews/{interview_id}/report")
async def report_for_interview(interview_id: str, user=Depends(student_read)):
    try:
        return await run_in_threadpool(assessment.get_interview_report, interview_id, user=user)
    except HTTPException as exc:
        if exc.status_code != 404 or not assessment_owner():
            raise
    # 面试结束可能已获确认，但完成事件仍待投递。
    # 报告尚未入库时，先核对面试归属，再返回排队状态。
    school = os.environ["LEGACY_SCHOOL_ID"]
    actor = {"actor_id": user["id"], "school_id": school, "actor_type": "student"}
    response = await request_json("interview", "GET", "/api/interviews/" + resource_segment(interview_id),
                                  actor=actor, scope="interview.read")
    session = response.get("interview", {})
    if (session.get("id"), session.get("user_id"), session.get("status")) != (interview_id, user["id"], "completed"):
        raise HTTPException(404, "Report unavailable")
    return {"report": {"interview_id": interview_id, "generation_status": "queued", "assessment_pending": True}}


@app.get("/api/interviews/{interview_id}/report/download")
def download(interview_id: str, user=Depends(student_read)):
    return assessment.download_interview_report(interview_id, user=user)


@app.post("/api/interviews/{interview_id}/report", status_code=201)
def generate(interview_id: str, response: Response, body: dict | None = None, user=Depends(student_generate)):
    return assessment.create_report(interview_id, response, body=body, user=user)


@app.get("/api/reports")
def list_reports(user=Depends(student_read)):
    return assessment.list_reports(user=user)


@app.get("/api/reports/{report_id}")
def get_report(report_id: str, user=Depends(student_read)):
    return assessment.get_report(report_id, user=user)


def _require_current_evidence(owner, revision):
    head = assessment.current_report_evidence_version(owner["interview_id"], owner["user_id"])
    if revision["evidence_version"] is not None and revision["evidence_version"] != head:
        raise HTTPException(409, "报告证据已变化，请等待新版报告。")
    return head


def _verified_owner(report_id, actor, roles=("teacher",), *, action=None):
    _school_actor(actor, *roles)
    owner = assessment.one("SELECT id,interview_id,user_id FROM interview_reports WHERE id=?", (report_id,))
    if not owner or owner["id"] != report_id:
        raise HTTPException(404, "报告不存在。")
    if actor["actor_type"] == "student":
        if actor["actor_id"] != owner["user_id"]:
            raise HTTPException(404, "报告不存在。")
        return owner
    if action:
        check_student_action(actor, owner["user_id"], action)
    url = service_origin("training")
    # 短期令牌仅签发给服务端指定的接收方，
    # 不转发浏览器请求头，也不采信请求体中的负责人信息。
    try:
        headers = service_headers("training", actor_id=actor["actor_id"], school_id=actor["school_id"],
                                  actor_type=actor["actor_type"], scopes=["training.verify"])
        with httpx.Client(trust_env=False, follow_redirects=False, timeout=5) as client:
            reply = client.get(f"{url}/interviews/{resource_segment(owner['interview_id'])}/attempt",
                               headers=headers)
        if reply.status_code in (403, 404):
            raise HTTPException(403, "当前教师不负责此面试。")
        reply.raise_for_status()
        attempt = reply.json()
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(503, "无法核验教学任务负责人。") from exc
    expected = {"interview_id": owner["interview_id"], "student_id": owner["user_id"],
                "school_id": actor["school_id"]}
    if actor["actor_type"] == "teacher":
        expected["teacher_id"] = actor["actor_id"]
    if not isinstance(attempt, dict) or any(attempt.get(k) != v for k, v in expected.items()):
        raise HTTPException(403, "当前教师不负责此面试。")
    return owner


class ScoreChange(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_version: int = Field(gt=0, strict=True)
    total_score: int = Field(ge=0, le=100, strict=True)
    reason: str = Field(min_length=1, max_length=2000)


class Review(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_version: int = Field(gt=0, strict=True)
    status: Literal["approved", "rejected", "pending"]
    note: str = Field(default="", max_length=2000)


@app.get("/api/admin/reports/{report_id}/history")
def report_history(report_id: str, actor=Depends(require_service("assessment", "assessment.history"))):
    owner = _verified_owner(report_id, actor, action="report.read")
    with versions.report_transaction(report_id, owner) as (report, revision):
        return {"report": {**report, "version": revision["version"]}, **versions.history(report_id)}


@app.get("/api/admin/interviews/{interview_id}/report-reference")
def staff_report_reference(interview_id: str, actor=Depends(require_service("assessment", "assessment.history"))):
    row = assessment.one("SELECT id FROM interview_reports WHERE interview_id=?", (interview_id,))
    if not row:
        raise HTTPException(404, "报告尚未生成或不可访问。")
    _verified_owner(row["id"], actor, action="report.read")
    return {"report_id": row["id"]}


@app.get("/api/admin/reports/{report_id}/export")
def staff_report_export(report_id: str, actor=Depends(require_service("assessment", "assessment.export"))):
    owner = _verified_owner(report_id, actor, roles=("teacher", "admin"), action="report.export")
    with versions.report_transaction(report_id, owner) as (report, revision):
        # 导出的文件及其访问记录必须指向同一报告版本，
        # 教师同时改分时也应保持一致。
        from uuid import uuid4
        assessment.db.execute("""INSERT INTO assessment_report_exports
            (id,report_id,version,school_id,actor_id) VALUES (?,?,?,?,?)""",
            (str(uuid4()), report_id, revision["version"], actor["school_id"], actor["actor_id"])).close()
        data = json.dumps({"report": report, "version": revision["version"]}, ensure_ascii=False, default=str)
    return Response(data, media_type="application/json", headers={
        "Cache-Control": "no-store", "Content-Disposition": 'attachment; filename="training-report.json"'})


@app.patch("/api/admin/reports/{report_id}/score")
def change_score(report_id: str, body: ScoreChange, actor=Depends(require_service("assessment", "assessment.score"))):
    owner = _verified_owner(report_id, actor, action="score.adjust")
    with versions.report_transaction(report_id, owner, body.expected_version) as (report, revision):
        if report["generation_status"] not in {"succeeded", "degraded"}:
            raise HTTPException(409, "尚无可修改的报告评分。")
        evidence = _require_current_evidence(owner, revision)
        updated = versions.change_score(report, revision, body.total_score, assessment.grade_from_score(body.total_score),
                                        assessment.pass_recommendation_from_score(body.total_score),
                                        actor["actor_id"], body.reason, evidence)
    return {"report": updated}


@app.patch("/api/admin/reports/{report_id}/review")
def review(report_id: str, body: Review, actor=Depends(require_service("assessment", "assessment.review"))):
    owner = _verified_owner(report_id, actor, action="report.review")
    with versions.report_transaction(report_id, owner, body.expected_version) as (report, revision):
        _require_current_evidence(owner, revision)
        updated = versions.review(report, revision, body.status, actor["actor_id"], body.note)
    return {"report": updated}


def _has_citations(raw_snapshot, answer_count):
    # 拒绝残缺或格式错误的历史 JSON，避免损坏的版本引发服务端错误。
    try:
        snapshot = json.loads(raw_snapshot)
        if not isinstance(snapshot, dict):
            return False
        timeline = json.loads(snapshot.get("timeline_review"))
    except (ValueError, TypeError, RecursionError):
        return False
    if not isinstance(timeline, list) or len(timeline) != answer_count:
        return False
    for answer in timeline:
        if not isinstance(answer, dict) or not all(
            isinstance(answer.get(key), str) and answer[key].strip() for key in ("message_id", "question_id")
        ):
            return False
        scores, citations = answer.get("dimension_scores"), answer.get("dimension_evidence")
        if not isinstance(scores, dict) or not scores or not isinstance(citations, dict):
            return False
        if not all(key in assessment.DIMENSIONS and type(score) in (int, float) and 0 <= score <= 100
                   and isinstance(citations.get(key), str) and citations[key].strip()
                   for key, score in scores.items()):
            return False
    return True


def _credential_evidence_locked(report_id, owner, school_id, report, current):
    origin = assessment.one("""
        SELECT version FROM assessment_report_versions WHERE report_id=?
        AND source='generated' AND evidence_version=? LIMIT 1
    """, (report_id, current["evidence_version"]))
    if (not origin or report["generation_status"] != "succeeded" or report["fallback"]
            or not report["answer_count"] or report["scored_answer_count"] != report["answer_count"]
            or current["evidence_version"] != assessment.current_report_evidence_version(
                owner["interview_id"], owner["user_id"])):
        raise HTTPException(409, "报告证据尚未就绪。")
    row = assessment.one("""
        SELECT evidence_version,source,actor_id,reason,snapshot FROM assessment_report_versions
        WHERE report_id=? AND version=?
    """, (report_id, current["version"]))
    if not _has_citations(row["snapshot"], report["answer_count"]):
        raise HTTPException(409, "报告缺少完整逐题证据。")
    evidence = {"report_id": report_id, "student_id": owner["user_id"], "school_id": school_id,
                "interview_id": owner["interview_id"], "version": current["version"]}
    canonical = json.dumps({**evidence, **row}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {**evidence, "digest": hashlib.sha256(canonical.encode("utf-8")).hexdigest()}


@app.get("/internal/credential-evidence/{report_id}")
def credential_evidence(report_id: str, actor=Depends(require_service("assessment", "assessment.credential-evidence"))):
    if actor["caller"] != "credentials":
        raise HTTPException(403, "仅供证书服务查证。")
    owner = _verified_owner(report_id, actor, roles=("student", "teacher", "admin"))
    # 在评分使用的锁内读取不可变快照和当前证据版本。
    # 等待重新生成的报告或来源不明的历史评分不能用作签发依据。
    with versions.report_transaction(report_id, owner) as (report, current):
        return _credential_evidence_locked(report_id, owner, actor["school_id"], report, current)


class IssueIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    application_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    generation: int = Field(strict=True, ge=1, le=2147483647)
    serial: str = Field(pattern=r"^[a-f0-9]{32}$")
    version: int = Field(strict=True, ge=1)
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    proof_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


def _permit(report_id, body):
    # 父报告行锁已将写入串行化，无需锁定尚不存在的许可行，
    # 以免 InnoDB 的间隙锁阻塞其他报告。
    return assessment.one("""SELECT serial,version,digest,proof_digest FROM assessment_issuance_permits
                          WHERE report_id=? AND application_id=? AND generation=?""",
                      (report_id, body.application_id, body.generation))


def _permit_receipt(stored, binding):
    if not stored or any(stored[k] != binding[k] for k in ("serial", "version", "digest", "proof_digest")):
        raise HTTPException(409, "此许可已绑定其他证书或签名。")
    return binding


@app.post("/internal/credential-evidence/{report_id}/authorize")
def authorize_issuance(report_id: str, body: IssueIntent,
                       actor=Depends(require_service("assessment", "assessment.credential-authorize"))):
    if actor["caller"] != "credentials":
        raise HTTPException(403, "仅供证书服务申请签发许可。")
    action = "credential.issue" if body.generation == 1 else "credential.reissue"
    owner = _verified_owner(report_id, actor, roles=("teacher", "admin"), action=action)
    school = actor["school_id"]
    if body.application_id != application_id(school, owner["user_id"], report_id, body.version):
        raise HTTPException(409, "申请标识与报告归属或版本不符。")
    binding = body.model_dump() | {"report_id": report_id, "school_id": school,
                                  "student_id": owner["user_id"], "interview_id": owner["interview_id"]}
    with versions.report_transaction(report_id, owner) as (report, revision):
        # 响应丢失后，重试可能晚于教师改分。
        # 先核验当前访问权限，再查已提交的许可，最后检查最新报告版本。
        previous = _permit(report_id, body)
        if previous:
            return _permit_receipt(previous, binding)
        if revision["version"] != body.version:
            raise HTTPException(409, "报告版本已变化，请重新审核。")
        head = _credential_evidence_locked(report_id, owner, school, report, revision)
        if head["digest"] != body.digest:
            raise HTTPException(409, "报告依据已变化，请重新审核。")
        # 本事务提交时签发授权正式生效。
        # 写入证据或评分的各方均使用同一组会话锁和报告锁。
        conflict = (" ON DUPLICATE KEY UPDATE serial=assessment_issuance_permits.serial"
                    if assessment.DB_ENGINE == "mysql" else " ON CONFLICT DO NOTHING")
        assessment.db.execute("""INSERT INTO assessment_issuance_permits
            (report_id,application_id,generation,serial,version,digest,proof_digest,authorized_by,school_id)
            VALUES (?,?,?,?,?,?,?,?,?)""" + conflict,
            (report_id, body.application_id, body.generation, body.serial, body.version,
             body.digest, body.proof_digest, actor["actor_id"], school)).close()
        return _permit_receipt(_permit(report_id, body), binding)


@app.post("/internal/interview-projections")
def project_interview(body: dict, actor=Depends(require_service("assessment", "assessment.project"))):
    if not assessment_owner():
        raise HTTPException(503, "Independent assessment storage is not active")
    _school_actor(actor, "system")
    return accept_projection(assessment, body, actor)

@app.get("/api/stats/me")
def skill_stats(user=Depends(student_read)):
    return assessment.get_stats(user=user)


@app.get("/api/stats/me/dimensions")
def skill_dimensions(user=Depends(student_read)):
    return assessment.get_dimensions(user=user)
