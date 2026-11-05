"""管理招聘库、同步学校配置的数据源，并兼容既有 Excel 格式。"""
import os
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from .feed import fetch_job_feed, import_job_feed
from shared import recruitment as jobs
from .access import actor, found
from .store import transaction
from .uploads import read_workbook
from .workbooks import build_job_posting_workbook, evaluate_job_posting_import, published_job_roles

router = APIRouter()
read = actor("posting.admin.read")
write = actor("posting.write")
PUBLIC_FIELDS = ("id", "title", "company", "job_category", "city", "graduation_year", "employment_type",
                 "salary", "education_requirement", "experience_requirement", "deadline", "skillList",
                 "catalog_job_name", "requirements", "description")


def sync_configured(school_id):
    # 私有数据源只能绑定一所学校，其他学校需单独配置数据源或部署服务。
    binding = os.environ.get("JOB_POSTING_SYNC_SCHOOL_ID") or os.environ.get("CAREER_SCHOOL_ID")
    return binding == school_id and bool(os.environ.get("JOB_POSTING_SYNC_ENDPOINT", "").strip())


@router.get("/v1/job-postings")
def postings(keyword: str = "", user=actor("posting.read", ("student",))):
    with transaction(user["school_id"]) as db:
        rows = jobs.list_job_postings(db, keyword=keyword, published_only=True, limit=200)
        return {"postings": [{k: row.get(k) for k in PUBLIC_FIELDS} for row in rows]}


@router.get("/v1/admin/job-postings")
def admin_postings(keyword: str = "", status: str = "", user=read):
    with transaction(user["school_id"]) as db:
        return {"postings": jobs.list_job_postings(db, keyword=keyword, status=status),
                "jobRoles": list(published_job_roles(db).values()),
                "syncConfigured": sync_configured(user["school_id"]),
                "scopeNote": "招聘信息库包含手动录入、Excel 导入和数据源同步的岗位。"}


def linked_payload(db, body):
    result = {**body}
    if "status" in result and result["status"] not in ("active", "disabled"):
        raise ValueError("status 只能为 active 或 disabled。")
    if "published" in result and str(result["published"]).lower() not in {"0", "1", "true", "false"}:
        raise ValueError("published 必须为布尔值或 0 / 1。")
    if "catalog_job_name" in body:
        matched = published_job_roles(db).get(str(body["catalog_job_name"]).strip())
        result["catalog_job_role_id"] = matched["id"] if matched else None
    elif body.get("catalog_job_role_id"):
        roles = published_job_roles(db).values()
        role = next((r for r in roles if r["id"] == body["catalog_job_role_id"]), None)
        if not role:
            raise ValueError("标准岗位不存在。")
        result["catalog_job_name"] = role["name"]
    # 根据操作类型记录岗位来源，忽略手工编辑传入的来源字段。
    result.pop("source", None)
    return result


@router.post("/v1/admin/job-postings", status_code=201)
def create_posting(body: dict, user=write):
    with transaction(user["school_id"], write=True) as db:
        return {"ok": True, "posting": jobs.create_job_posting(db, linked_payload(db, body), user["actor_id"])}


@router.put("/v1/admin/job-postings/{posting_id}")
def update_posting(posting_id: str, body: dict, user=write):
    with transaction(user["school_id"], write=True) as db:
        return {"ok": True, "posting": found(jobs.update_job_posting(db, posting_id, linked_payload(db, body)))}


@router.delete("/v1/admin/job-postings/{posting_id}")
def delete_posting(posting_id: str, user=actor("posting.delete")):
    with transaction(user["school_id"], write=True) as db:
        found(jobs.delete_job_posting(db, posting_id))
        return {"ok": True}


def download(rows, filename, template=False):
    return StreamingResponse(build_job_posting_workbook(rows, template=template),
                             media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/v1/admin/job-postings/template")
def template(user=read):
    with transaction(user["school_id"]):
        return download([], "job-posting-import-template.xlsx", True)


@router.get("/v1/admin/job-postings/export")
def export(keyword: str = "", status: str = "", user=read):
    with transaction(user["school_id"]) as db:
        return download(jobs.list_job_postings(db, keyword=keyword, status=status), "job-postings.xlsx")


@router.post("/v1/admin/job-postings/import")
def import_postings(file: UploadFile = File(...), user=actor("posting.import")):
    content = read_workbook(file, 5 * 1024 * 1024)
    with transaction(user["school_id"], write=True) as db:
        return {"ok": True, **evaluate_job_posting_import(db, content)}


@router.post("/v1/admin/job-postings/sync")
def sync(body: dict | None = None, user=actor("posting.sync")):
    if body:
        raise HTTPException(400, "同步仅允许使用运维配置的数据源。")
    if not sync_configured(user["school_id"]):
        raise HTTPException(400, "尚未为当前学校配置同步数据源。")
    rows = fetch_job_feed()
    with transaction(user["school_id"], write=True) as db:
        return import_job_feed(db, rows, created_by=user["actor_id"])
