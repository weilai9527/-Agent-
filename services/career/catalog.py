"""同一学校的发布目录和可编辑草稿共用其独立职业库。"""
import hashlib
import json
from typing import Annotated
from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from shared import career_catalog as catalog
from .access import actor, found
from .store import transaction
from .uploads import read_workbook

router = APIRouter()
published = actor("catalog.read", ("student", "system"))
admin_read = actor("catalog.admin.read")
write = actor("catalog.write")
review = actor("catalog.review")


@router.get("/v1/catalog/versions")
def versions(user=published):
    with transaction(user["school_id"]) as db:
        return {"versions": catalog.list_versions(db)}


@router.get("/v1/catalog/tree")
def tree(version: str | None = None, user=published):
    with transaction(user["school_id"]) as db:
        return found(catalog.catalog_tree(db, version_code=version))


Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]


class Directions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    names: list[Name] = Field(max_length=20)
    record: bool = False
    event_id: str | None = Field(default=None, min_length=1, max_length=128)


@router.post("/v1/catalog/directions")
def directions(body: Directions, user=actor("catalog.enrich", ("student",))):
    items = [{"name": name} for name in body.names]
    if body.record:
        raise HTTPException(400, "使用审核建议接口记录方向。")
    with transaction(user["school_id"]) as db:
        return {"directions": catalog.refresh_resume_direction_matches(db, items)}


@router.post("/v1/catalog/suggestions")
def record_directions(body: Directions, user=actor("catalog.suggest", ("student",))):
    if not body.record:
        raise HTTPException(400, "须显式请求记录方向。")
    with transaction(user["school_id"], write=True) as db:
        result = []
        for name in body.names:
            item = {"name": name, **catalog.match_catalog_job(db, name)}
            if item["catalog_status"] == "external":
                normalized = catalog.normalize_job_name(name)
                key = json.dumps([user["actor_id"], body.event_id, normalized], ensure_ascii=False)
                digest = hashlib.sha256(key.encode()).hexdigest()
                if not db.tx.one("SELECT digest FROM career_suggestion_events WHERE digest=?", (digest,)):
                    suggestion = catalog.record_job_suggestion(db, name, item, "profile")
                    db.tx.execute("INSERT INTO career_suggestion_events (digest) VALUES (?)", (digest,))
                else:
                    suggestion = db.tx.one(
                        "SELECT id,review_status FROM catalog_job_suggestions WHERE normalized_name=?", (normalized,))
                if suggestion:
                    item.update(suggestion_id=suggestion["id"], suggestion_status=suggestion["review_status"])
            result.append(item)
        return {"directions": result}


@router.get("/v1/admin/catalog/versions")
def admin_versions(user=admin_read):
    with transaction(user["school_id"]) as db:
        return {"versions": catalog.list_versions(db, include_drafts=True)}


@router.post("/v1/admin/catalog/versions", status_code=201)
def create_version(body: dict, user=write):
    with transaction(user["school_id"], write=True) as db:
        return {"version": catalog.create_version(db, body, user["actor_id"])}


@router.get("/v1/admin/catalog/tree")
def admin_tree(version: str | None = None, user=admin_read):
    with transaction(user["school_id"]) as db:
        return found(catalog.catalog_tree(db, version_code=version, include_disabled=True, include_drafts=True))


@router.post("/v1/admin/catalog/versions/{version_id}/entities/{entity_type}", status_code=201)
def create_entity(version_id: str, entity_type: str, body: dict, user=write):
    with transaction(user["school_id"], write=True) as db:
        return {"item": catalog.create_catalog_entity(db, version_id, entity_type, body)}


@router.patch("/v1/admin/catalog/versions/{version_id}/entities/{entity_type}/{entity_id}")
def update_entity(version_id: str, entity_type: str, entity_id: str, body: dict, user=write):
    with transaction(user["school_id"], write=True) as db:
        return {"item": found(catalog.update_catalog_entity(db, version_id, entity_type, entity_id, body))}


@router.delete("/v1/admin/catalog/versions/{version_id}/entities/{entity_type}/{entity_id}")
def delete_entity(version_id: str, entity_type: str, entity_id: str, user=write):
    with transaction(user["school_id"], write=True) as db:
        found(catalog.delete_catalog_entity(db, version_id, entity_type, entity_id))
        return {"ok": True}


class Matrix(BaseModel):
    competencies: list[dict] = Field(max_length=1000)


@router.put("/v1/admin/catalog/versions/{version_id}/jobs/{job_role_id}/competencies")
def replace_competencies(version_id: str, job_role_id: str, body: Matrix, user=write):
    with transaction(user["school_id"], write=True) as db:
        return {"competencies": catalog.replace_job_competencies(db, version_id, job_role_id, body.competencies)}


@router.post("/v1/admin/catalog/versions/{version_id}/publish")
def publish(version_id: str, user=actor("catalog.publish")):
    with transaction(user["school_id"], write=True) as db:
        return {"version": found(catalog.publish_version(db, version_id, user["actor_id"]))}


@router.post("/v1/admin/catalog/versions/{version_id}/imports", status_code=201)
def import_catalog(version_id: str, file: UploadFile = File(...), mode: str = "merge", user=actor("catalog.import")):
    content = read_workbook(file, 10 * 1024 * 1024)
    with transaction(user["school_id"], write=True) as db:
        return {"import_job": catalog.import_catalog_excel(db, version_id, file.filename, content, mode, user["actor_id"])}


@router.get("/v1/admin/catalog/job-suggestions")
def suggestions(status: str | None = None, user=admin_read):
    if status and status not in {"pending", "approved", "rejected", "merged"}:
        raise HTTPException(400, "岗位建议状态不正确。")
    with transaction(user["school_id"]) as db:
        return {"suggestions": catalog.list_job_suggestions(db, status)}


@router.post("/v1/admin/catalog/job-suggestions/{suggestion_id}/review")
def review_suggestion(suggestion_id: str, body: dict, user=review):
    with transaction(user["school_id"], write=True) as db:
        return {"suggestion": found(catalog.review_job_suggestion(
            db, suggestion_id, str(body.get("status") or ""), user["actor_id"], body.get("note")))}


@router.post("/v1/admin/catalog/job-suggestions/{suggestion_id}/merge")
def merge_suggestion(suggestion_id: str, body: dict, user=review):
    with transaction(user["school_id"], write=True) as db:
        return {"suggestion": found(catalog.merge_job_suggestion(
            db, suggestion_id, str(body.get("job_role_id") or ""), user["actor_id"]))}


@router.post("/v1/admin/catalog/job-suggestions/{suggestion_id}/approve-to-draft", status_code=201)
def approve_to_draft(suggestion_id: str, body: dict, user=review):
    Matrix.model_validate(body)
    with transaction(user["school_id"], write=True) as db:
        return found(catalog.approve_job_suggestion_to_draft(
            db, suggestion_id, str(body.get("version_id") or ""), body, user["actor_id"]))
