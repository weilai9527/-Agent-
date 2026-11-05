"""按身份服务的组织范围维护专业推荐岗位。职业目录和关联关系由本服务持久化。"""
from collections import defaultdict
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from shared.career_catalog import catalog_tree, resolve_version
from shared.service_http import request_json
from .access import actor
from .store import transaction

router = APIRouter()
Identifier = Annotated[str, StringConstraints(min_length=1, max_length=128, pattern=r"^\S+$")]


class Mapping(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    jobRoleId: Identifier
    priority: Literal["recommended", "optional"] = "recommended"


class Replacement(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    jobs: list[Mapping] | None = Field(default=None, max_length=50)
    jobRoleIds: list[Identifier] | None = Field(default=None, max_length=50)
    expectedRevision: int | None = Field(default=None, ge=0, le=2**63 - 1)

    @model_validator(mode="after")
    def valid_selection(self):
        if (self.jobs is None) == (self.jobRoleIds is None):
            raise ValueError("请提交一组岗位关联。")
        if self.jobs is not None and len({item.jobRoleId for item in self.jobs}) != len(self.jobs):
            raise ValueError("岗位不能重复。")
        return self

    def selection(self):
        if self.jobs is not None:
            return [item.model_dump() for item in self.jobs]
        # 旧客户端提交岗位 ID 列表，按首次出现顺序去重，前三项为重点推荐。
        return [{"jobRoleId": item, "priority": "recommended" if i < 3 else "optional"}
                for i, item in enumerate(dict.fromkeys(self.jobRoleIds))]


def _identity_rows(value, program=False):
    if not isinstance(value, list):
        raise ValueError()
    rows = {}
    for item in value:
        keys = ("id", "name", "college_id") if program else ("id", "name")
        if not isinstance(item, dict) or any(not isinstance(item.get(k), str) or not item[k] for k in keys):
            raise ValueError()
        if len(item["id"]) > 128 or item["id"] in rows:
            raise ValueError()
        row = {k: item[k] for k in keys}
        if program and "canEdit" in item:
            if type(item["canEdit"]) is not bool:
                raise ValueError()
            row["canEdit"] = item["canEdit"]
        rows[row["id"]] = row
    return rows


async def authorized_programs(user, *, write=False):
    # 使用本次请求已验证的主体向身份服务单独申请授权，前端不能提供学校或专业范围。
    scope = "program_jobs.write" if write else "program_jobs.read"
    path = "/internal/staff/program-job-options" + ("/write" if write else "")
    reply = await request_json("identity", "GET", path, actor=user, scope=scope)
    try:
        if not isinstance(reply, dict) or any(reply.get(k) != user[k] for k in ("school_id", "actor_id", "actor_type")):
            raise ValueError()
        if type(reply.get("canEdit")) is not bool:
            raise ValueError()
        colleges, programs = _identity_rows(reply["colleges"]), _identity_rows(reply["programs"], program=True)
        can_edit = reply["canEdit"] and user["actor_type"] == "admin"
        for p in programs.values():
            if p["college_id"] not in colleges or (can_edit and "canEdit" not in p):
                raise ValueError()
            p["canEdit"] = can_edit and p.get("canEdit", False)
    except (KeyError, ValueError):
        raise HTTPException(502, "身份服务返回的专业范围无效。") from None
    if write and not can_edit:
        raise HTTPException(403, "当前账号无权配置专业岗位。")
    return colleges, programs, can_edit


def published_jobs(db):
    tree = catalog_tree(db) or {}
    jobs = {}
    # 按同一份已发布目录校验读写，包含停用上级的岗位不会出现在候选项中。
    available_skills = {row["id"] for row in tree.get("competencies", [])}
    for college in tree.get("colleges", []):
        for major in college["majors"]:
            for training in major["training_directions"]:
                for direction in training["employment_directions"]:
                    for job in direction["jobs"]:
                        jobs[job["id"]] = {"id": job["id"], "name": job["name"], "code": job["code"],
                                           "sourceMajor": major["name"], "description": job.get("description") or "",
                                           "competencies": [item for item in job["competencies"] if item["id"] in available_skills]}
    return tree.get("version"), jobs


def program_options(school, colleges, programs, can_edit):
    with transaction(school) as db:
        version, jobs = published_jobs(db)
        ids = list(programs)
        for offset in range(0, len(ids), 200):
            visible = tuple(ids[offset:offset + 200])
            marks = ",".join("?" for _ in visible)
            revisions = {r["program_id"]: r["revision"] for r in db.tx.all(
                f"SELECT program_id,revision FROM career_program_job_state WHERE program_id IN ({marks})", visible)}
            mappings = defaultdict(list)
            for row in db.tx.all(f"SELECT program_id,job_role_id,priority FROM program_job_roles "
                                 f"WHERE program_id IN ({marks}) ORDER BY priority DESC,created_at,id", visible):
                job = jobs.get(row["job_role_id"])
                mappings[row["program_id"]].append({"job_role_id": row["job_role_id"], "priority": row["priority"],
                                                    "job_name": job["name"] if job else None})
            for program_id in visible:
                programs[program_id].update(revision=revisions.get(program_id, 0), jobs=mappings[program_id])
        return {"school_id": school, "colleges": list(colleges.values()), "programs": list(programs.values()),
                "jobs": list(jobs.values()), "publishedVersion": version, "canEdit": can_edit}


@router.get("/v1/admin/campus/program-jobs")
async def list_options(user=actor("program_jobs.read")):
    colleges, programs, can_edit = await authorized_programs(user)
    return await run_in_threadpool(program_options, user["school_id"], colleges, programs, can_edit)


def replace(school, program_id, body):
    selection = body.selection()
    with transaction(school, write=True) as db:
        state = db.tx.one("SELECT revision FROM career_program_job_state WHERE program_id=?", (program_id,))
        revision = state["revision"] if state else 0
        if body.expectedRevision is not None and body.expectedRevision != revision:
            raise HTTPException(409, "此专业的岗位配置已变更，请刷新后重新保存。")
        # 在写锁内再次读取发布状态，任何无效的岗位都会阻止本次整组替换。
        _, jobs = published_jobs(db)
        if any(item["jobRoleId"] not in jobs for item in selection):
            raise HTTPException(400, "包含已停用或未发布的岗位。")
        db.tx.execute("DELETE FROM program_job_roles WHERE program_id=?", (program_id,))
        for item in selection:
            db.tx.execute("INSERT INTO program_job_roles(id, program_id, job_role_id, priority) VALUES (?,?,?,?)",
                          (str(uuid4()), program_id, item["jobRoleId"], item["priority"]))
        if state:
            db.tx.execute("UPDATE career_program_job_state SET revision=? WHERE program_id=?", (revision + 1, program_id))
        else:
            db.tx.execute("INSERT INTO career_program_job_state(program_id,revision) VALUES (?,1)", (program_id,))
        return {"ok": True, "school_id": school, "revision": revision + 1, "jobs": selection,
                "jobRoleIds": [row["jobRoleId"] for row in selection]}


@router.put("/v1/admin/campus/programs/{program_id}/jobs")
async def update_options(program_id: Identifier, body: Replacement, user=actor("program_jobs.write", ("admin",))):
    _, programs, _ = await authorized_programs(user, write=True)
    if program_id not in programs:
        raise HTTPException(404, "专业不存在或不在管理范围内。")
    if not programs[program_id]["canEdit"]:
        raise HTTPException(403, "无权修改此专业。")
    return await run_in_threadpool(replace, user["school_id"], program_id, body)


@router.get("/internal/resume-form/catalog")
def resume_catalog(user=actor("catalog.read", ("student",))):
    if user["caller"] != "profile":
        raise HTTPException(403, "仅允许简历服务读取表单目录。")
    # 简历选项只需要学院与专业名，不传完整职业树或草稿数据。
    with transaction(user["school_id"]) as db:
        version = resolve_version(db)
        colleges = []
        if version:
            colleges = db.tx.all("SELECT id,name FROM catalog_colleges WHERE version_id=? AND enabled=1 "
                                 "ORDER BY sort_order,name,id", (version["id"],))
            majors = defaultdict(list)
            for row in db.tx.all("SELECT college_id,id,name FROM catalog_majors WHERE version_id=? AND enabled=1 "
                                 "ORDER BY sort_order,name,id", (version["id"],)):
                majors[row["college_id"]].append({"id": row["id"], "name": row["name"]})
            for row in colleges:
                row["majors"] = majors[row["id"]]
        return {"school_id": user["school_id"], "colleges": colleges}
