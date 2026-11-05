"""学生个人资料、不可变简历版本与学校授权的模型分析接口。"""

from contextlib import asynccontextmanager

from shared.runtime_mode import require_native_runtime
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from starlette.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from .limits import BodyLimit

from shared.service_db import ServiceDatabase
from shared.service_security import require_service
from . import settings, settings_store, store, teaching_view
from .fields import form_fields, project_form
from .parser import MAX_FILE, extract


@asynccontextmanager
async def lifespan(application):
    require_native_runtime()
    application.state.db = ServiceDatabase.from_env("profile")
    store.ensure_schema(application.state.db)
    settings_store.ensure_schema(application.state.db)
    yield


app = FastAPI(title="Candidate profile service", lifespan=lifespan)


app.add_middleware(BodyLimit)
app.include_router(settings.router)
app.include_router(teaching_view.router)


def student(scope):
    def owner(actor=Depends(require_service("profile", scope))):
        if actor["actor_type"] != "student":
            raise HTTPException(403, "仅限学生本人。")
        return actor["school_id"], actor["actor_id"]
    return owner


def database(request: Request):
    return request.app.state.db


read = student("profile.read")
write = student("profile.write")
version_read = student("profile.versions.read")


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/ready")
def ready(db=Depends(database)):
    try:
        if db.ping():
            return {"ok": True}
    except Exception:
        pass
    raise HTTPException(503, "Profile database unavailable")


@app.exception_handler(RequestValidationError)
async def invalid_request(_, exc):
    # FastAPI 的默认校验错误可能包含私人简历正文。
    return JSONResponse({"detail": "请求字段无效。"}, 422)


@app.get("/api/profile")
def get_profile(owner=Depends(read), db=Depends(database)):
    with db.transaction() as tx:
        current = store.snapshot(tx, owner)
        return {"profile": current["profile"] if current else store.blank(owner)}


@app.put("/api/profile")
def put_profile(body: dict, owner=Depends(write), db=Depends(database)):
    return store.save(db, owner, "profile", body)


@app.get("/api/resume-form")
def get_form(owner=Depends(read), db=Depends(database)):
    with db.transaction() as tx:
        current = store.snapshot(tx, owner)
        return {"form": current["form"] if current else {}}


@app.put("/api/resume-form")
def put_form(body: dict, owner=Depends(write), db=Depends(database)):
    form = form_fields(body)
    projection = project_form(form)
    saved = store.save(db, owner, "form", projection, form)
    return {"ok": True, "form": form, "resume_text": projection["resume_text"], **saved}


@app.post("/api/profile/resume-upload")
async def upload(request: Request, owner=Depends(student("profile.upload")), db=Depends(database)):
    # 通过鉴权后才解析私有文件的 multipart 内容。
    async with request.form(max_files=1, max_fields=0) as parts:
        file = parts.get("file")
        if not isinstance(file, UploadFile):
            raise HTTPException(422, "缺少 file 上传字段。")
        content = await file.read(MAX_FILE + 1)
        name, text, count = await run_in_threadpool(extract, file.filename or "", content)
    saved = await run_in_threadpool(store.save, db, owner, "upload", {"resume_text": text, "resume_filename": name})
    return {"filename": name, "text": text, "char_count": len(text), "original_char_count": count,
            "truncated": count > len(text), **saved}


@app.get("/api/profile/resume-analysis")
def get_analysis(owner=Depends(read), db=Depends(database)):
    return store.analysis_state(db, owner)


@app.post("/api/profile/resume-analysis")
def generate_analysis(body: dict | None = None, owner=Depends(student("profile.analyze")), db=Depends(database)):
    payload = body or {}
    if set(payload) - {"force"}:
        raise HTTPException(400, "请求仅支持 force 参数。")
    force = payload.get("force", False)
    if type(force) is not bool:
        raise HTTPException(400, "force 必须为布尔值。")
    return {"resume_analysis": store.analyze(db, owner, force)}


@app.get("/api/profile/versions")
def versions(limit: int = 50, before: int | None = None, owner=Depends(version_read), db=Depends(database)):
    if not 1 <= limit <= 100 or (before is not None and not 1 <= before <= 2**63 - 1):
        raise HTTPException(400, "无效的分页范围。")
    query = f"SELECT version, source, created_at FROM profile_versions WHERE {store.OWNER}"
    if before is not None:
        query += " AND version<?"
    args = (*owner, before, limit) if before is not None else (*owner, limit)
    with db.transaction() as tx:
        return {"versions": tx.all(query + " ORDER BY version DESC LIMIT ?", args)}


def find_snapshot(db, owner, version=None):
    with db.transaction() as tx:
        current = store.snapshot(tx, owner, version)
        if not current:
            raise HTTPException(404, "简历版本不存在。")
        return {**current, "school_id": owner[0], "actor_id": owner[1]}


@app.get("/api/profile/versions/current")
def current_snapshot(owner=Depends(student("profile.snapshot.read")), db=Depends(database)):
    return find_snapshot(db, owner)


@app.get("/api/profile/versions/{version}")
def version_snapshot(version: int, owner=Depends(version_read), db=Depends(database)):
    if not 1 <= version <= 2**63 - 1:
        raise HTTPException(404, "简历版本不存在。")
    return find_snapshot(db, owner, version)


@app.get("/internal/interview-context")
def interview_context(owner=Depends(student("profile.snapshot.read")), db=Depends(database)):
    # 在同一事务快照读取资料和分析，只返回面试提示词需要的分析字段。
    import json
    with db.transaction() as tx:
        current = store.snapshot(tx, owner)
        cached = tx.one(f"SELECT analysis FROM profile_owners WHERE {store.OWNER}", owner)
    analysis = {}
    if current and store.resume_analysis_source_text(current["profile"]):
        data = json.loads(cached["analysis"]) if cached and cached["analysis"] else {}
        if store.current_for_snapshot(data, current) and isinstance(data.get("analysis"), dict):
            analysis = data["analysis"]
        else:
            analysis = store.build_local_resume_analysis(current["profile"])
    allowed = ("candidate_summary", "core_skills", "projects", "risk_points", "recommended_directions")
    return {"school_id": owner[0], "actor_id": owner[1], "version": current["version"] if current else 0,
            "analysis": {key: analysis[key] for key in allowed if key in analysis}}
