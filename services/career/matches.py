"""按学生本人的不可变简历快照执行匹配，职业库不保存简历原文。"""
import hashlib
from typing import Annotated
from fastapi import APIRouter, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from services.profile.analysis import resume_analysis_source_text
from shared import recruitment as jobs
from shared.service_http import request_json
from .access import actor, found
from .scoring import score_and_enhance
from .store import transaction

router = APIRouter()
read = actor("match.read", ("student",))
Name = Annotated[str, StringConstraints(strip_whitespace=True, max_length=160)]


class Student(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Name = ""
    student_no: Name = ""
    college: Name = ""


class MatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    job_posting_id: str = Field(default="", max_length=128)
    jd_text: str = Field(default="", max_length=20000)
    job_title: Name = "自定义岗位"
    company: Name = ""
    student: Student = Field(default_factory=Student)


def published_posting(db, posting_id):
    posting = jobs.get_job_posting(db, posting_id)
    if not posting or not posting["published"] or posting["status"] != "active":
        raise HTTPException(404, "招聘岗位不存在或已下架。")
    # 固定评分和匹配记录所需的岗位字段，写入时用于识别并发修改。
    return {key: posting.get(key) for key in ("title", "company", "description", "requirements",
                                               "job_category", "skillsText", "skills")}


def save_match(user, body, profile, version):
    resume = resume_analysis_source_text(profile)
    if not resume:
        raise HTTPException(400, "请先完善简历，再进行岗位对比。")
    owner = {"user_id": user["actor_id"], "student_name": body.student.name,
             "student_no": body.student.student_no, "student_college": body.student.college}
    posting_id = body.job_posting_id
    if posting_id:
        with transaction(user["school_id"]) as db:
            posting = published_posting(db, posting_id)
        jd = "\n".join(filter(None, (posting["description"], posting["requirements"])))
    else:
        jd = body.jd_text
        posting = {"title": body.job_title or "自定义岗位", "company": body.company, "requirements": jd}

    # 规则计算和模型调用不占用职业库写锁，期间上传新简历也不会改变本次使用的快照。
    result = score_and_enhance(user["school_id"], resume_text=resume, resume_skills=profile.get("skills") or "",
                               target_role=profile.get("target_role") or "", posting=posting)
    result["profileVersion"] = version
    digest = hashlib.sha256(("direction-ai-v5-catalog-match\n" + resume).encode()).hexdigest()
    with transaction(user["school_id"], write=True) as db:
        if posting_id and published_posting(db, posting_id) != posting:
            raise HTTPException(409, "招聘岗位已更新，请使用最新信息重新对比。")
        record = jobs.create_job_match(
            db, **owner, job_posting_id=posting_id or None, job_title=posting["title"],
            company=posting["company"], source="library" if posting_id else "pasted",
            jd_text=jd, resume_hash=digest, match_score=result["matchScore"],
            result=result, provider=result["provider"], model=result["model"])
        if not posting_id:
            data = {"job_title": posting["title"], "company": posting["company"], "jd_text": jd}
            pending = jobs.find_pending_jd_submission(db, owner["user_id"], posting["title"], posting["company"])
            if pending:
                jobs.update_jd_submission(db, pending["id"], data)
            else:
                jd = jobs.create_jd_submission(db, **owner, **data)
                # 旧方法最多保留 64 个字符，提交岗位描述前须恢复完整的签名主体标识。
                if jd["user_id"] != owner["user_id"]:
                    db.tx.execute("UPDATE job_jd_submissions SET user_id=? WHERE id=?", (owner["user_id"], jd["id"]))
        return {"job_match": record}


@router.post("/v1/job-matches", status_code=201)
async def create_match(body: MatchRequest, user=actor("match.create", ("student",))):
    if not body.job_posting_id and len(body.jd_text) < 20:
        raise HTTPException(400, "岗位描述至少需要 20 字。")
    # 调用方仅提供目标岗位。使用专用于简历服务的新凭据读取本人快照，不回退到旧库。
    try:
        snapshot = await request_json("profile", "GET", "/api/profile/versions/current", actor=user,
                                      scope="profile.snapshot.read")
    except HTTPException as exc:
        if exc.status_code == 404:
            raise HTTPException(400, "请先完善简历，再进行岗位对比。") from None
        raise
    if (not isinstance(snapshot, dict) or snapshot.get("school_id") != user["school_id"]
            or snapshot.get("actor_id") != user["actor_id"] or not isinstance(snapshot.get("profile"), dict)
            or snapshot["profile"].get("user_id") != user["actor_id"] or type(snapshot.get("version")) is not int):
        raise HTTPException(502, "简历快照与请求身份不匹配。")
    return await run_in_threadpool(save_match, user, body, snapshot["profile"], snapshot["version"])


@router.get("/v1/job-matches")
def list_matches(user=read):
    with transaction(user["school_id"]) as db:
        return {"matches": jobs.list_job_matches(db, user_id=user["actor_id"], limit=30)}


@router.get("/v1/job-matches/{match_id}")
def get_match(match_id: str, user=read):
    with transaction(user["school_id"]) as db:
        return {"job_match": found(jobs.find_job_match_for_user(db, match_id, user["actor_id"]))}


StudentID = Annotated[str, StringConstraints(min_length=1, max_length=128)]


class Roster(BaseModel):
    """只有取得管理动作授权的网关可以提交已验证的学生范围。"""
    model_config = ConfigDict(extra="forbid")
    student_ids: list[StudentID] | None = Field(max_length=10000)
    payload: dict | None = None

    def scope(self, user, *, jd=False):
        if self.student_ids is None:
            if user["actor_type"] != "admin":
                raise HTTPException(403, "教师必须限定所管学生。")
            return "1=1", ()
        allowed = tuple(self.student_ids)
        sql = "user_id IN (" + ",".join("?" for _ in allowed) + ")" if allowed else "1=0"
        # 手工录入的岗位描述没有所属学生，归本校管理员维护。
        if jd and user["actor_type"] == "admin":
            sql = "(" + sql + " OR user_id IS NULL)"
        return sql, allowed


def scoped_rows(db, body, user, *, jd=False, keyword="", status="", posting_id="", limit=200, record_id=""):
    clause, allowed = body.scope(user, jd=jd)
    clauses, params = [clause], list(allowed)
    if record_id:
        clauses.append("id = ?")
        params.append(record_id)
    if keyword:
        fields = ["job_title", "company", "student_name", "student_no"] + (["jd_text"] if jd else [])
        clauses.append("(" + " OR ".join(field + " LIKE ?" for field in fields) + ")")
        params.extend([f"%{keyword}%"] * len(fields))
    if status:
        clauses.append("status = ?")
        params.append(status)
    if posting_id:
        clauses.append("job_posting_id = ?")
        params.append(posting_id)
    table = "job_jd_submissions" if jd else "job_matches"
    sql = f"SELECT * FROM {table} WHERE " + " AND ".join(clauses) + " ORDER BY created_at DESC,id DESC LIMIT ?"
    serialize = jobs.serialize_jd_submission if jd else jobs.serialize_job_match
    return [serialize(r) for r in db.tx.all(sql, (*params, limit))]


@router.get("/v1/admin/job-matches")
def admin_matches(body: Roster, keyword: str = "", jobPostingId: str = "", limit: int = Query(200, ge=1, le=1000),
                  user=actor("match.admin.read")):
    with transaction(user["school_id"]) as db:
        rows = scoped_rows(db, body, user, keyword=keyword, posting_id=jobPostingId, limit=limit)
        postings = [{"id": p["id"], "title": p["title"], "company": p.get("company")}
                    for p in jobs.list_job_postings(db, limit=1000)]
        return {"matches": rows, "postings": postings, "scopeNote": "仅显示所管学生的岗位对比记录。"}


@router.get("/v1/admin/job-matches/{match_id}")
def admin_match(match_id: str, body: Roster, user=actor("match.admin.read")):
    with transaction(user["school_id"]) as db:
        rows = scoped_rows(db, body, user, record_id=match_id, limit=1)
        return {"match": found(next(iter(rows), None))}


@router.get("/v1/admin/jd-submissions")
def list_jds(body: Roster, keyword: str = "", status: str = "", limit: int = Query(200, ge=1, le=1000),
             user=actor("jd.read")):
    with transaction(user["school_id"]) as db:
        return {"submissions": scoped_rows(db, body, user, jd=True, keyword=keyword, status=status, limit=limit),
                "scopeNote": "学生粘贴的岗位描述经审核后录入招聘信息库。"}


def checked_jd(db, user, body, submission_id):
    rows = scoped_rows(db, body, user, jd=True, record_id=submission_id, limit=1)
    return found(next(iter(rows), None))


@router.post("/v1/admin/jd-submissions", status_code=201)
def create_jd(body: Roster, user=actor("jd.write", ("admin",))):
    body.scope(user, jd=True)
    payload = body.payload or {}
    title = str(payload.get("job_title") or "").strip()
    if not title:
        raise HTTPException(400, "岗位名称不能为空。")
    with transaction(user["school_id"], write=True) as db:
        return {"ok": True, "submission": jobs.create_jd_submission(
            db, job_title=title, company=payload.get("company"), jd_text=payload.get("jd_text"),
            student_name=payload.get("student_name") or "管理员录入")}


@router.put("/v1/admin/jd-submissions/{submission_id}")
def update_jd(submission_id: str, body: Roster, user=actor("jd.write")):
    payload = body.payload or {}
    with transaction(user["school_id"], write=True) as db:
        current = checked_jd(db, user, body, submission_id)
        if current["status"] == "approved" or str(payload.get("status") or "").strip().lower() == "approved":
            raise HTTPException(409, "已审核岗位请在招聘信息库维护。")
        return {"ok": True, "submission": jobs.update_jd_submission(
            db, submission_id, payload, decided_by=user["actor_id"])}


@router.delete("/v1/admin/jd-submissions/{submission_id}")
def delete_jd(submission_id: str, body: Roster, user=actor("jd.delete")):
    with transaction(user["school_id"], write=True) as db:
        checked_jd(db, user, body, submission_id)
        jobs.delete_jd_submission(db, submission_id)
        return {"ok": True}


@router.post("/v1/admin/jd-submissions/{submission_id}/approve")
def approve_jd(submission_id: str, body: Roster, user=actor("jd.approve")):
    payload = body.payload or {}
    with transaction(user["school_id"], write=True) as db:
        jd = checked_jd(db, user, body, submission_id)
        if jd["status"] == "approved":
            posting = found(jobs.get_job_posting(db, jd["job_posting_id"]))
            return {"ok": True, "submission": jd, "posting": posting, "action": "updated"}
        updates = {key: payload.get(key) or jd[key] for key in ("job_title", "company", "jd_text")}
        jd = jobs.update_jd_submission(db, submission_id, updates, decided_by=user["actor_id"])
        posting, action = jobs.upsert_job_posting_by_source(
            db, {"title": jd["job_title"], "company": jd["company"], "description": jd["jd_text"],
                 "requirements": jd["jd_text"], "status": "active", "published": 1},
            source="student_jd", source_ref=submission_id, created_by=user["actor_id"])
        jd = jobs.mark_jd_submission_approved(db, submission_id, posting["id"], decided_by=user["actor_id"])
        return {"ok": True, "submission": jd, "posting": posting, "action": action}
