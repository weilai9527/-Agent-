"""教学分析服务，入口为 uvicorn services.analytics.app:app。"""
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request

from shared.runtime_mode import require_native_runtime
from shared.service_db import ServiceDatabase
from shared.service_security import require_service
from . import peers, storage
from .models import Completion, Identifier, Label, Practice


@asynccontextmanager
async def lifespan(app):
    require_native_runtime()
    db = ServiceDatabase.from_env("analytics")
    storage.initialize(db)
    app.state.db = db
    yield


app = FastAPI(title="Teaching Analytics", lifespan=lifespan)
write_scores = require_service("analytics", "analytics.completion.write")
teaching = require_service("analytics", "analytics.teaching.read")
self_read = require_service("analytics", "analytics.self.read")
assign = require_service("analytics", "analytics.practice.assign")


def role(ctx, *allowed):
    if ctx["actor_type"] not in allowed:
        raise HTTPException(403, "Actor cannot perform this action")


def filters(task_id: Identifier | None = None, class_id: Identifier | None = None,
            job_role: Label | None = None, dimension: Label | None = None):
    return {"task_id": task_id, "class_id": class_id, "job_role": job_role, "dimension": dimension}


def visible_rows(db, ctx, selection, *, weaknesses=False):
    role(ctx, "teacher", "admin")
    roster = peers.current_roster(ctx, selection.get("class_id"))
    return storage.read(db, ctx, roster, **selection, weaknesses=weaknesses)


def weakest_first(rows):
    return sorted(rows, key=lambda r: (r["score"], r["attempt_id"], r["question_id"], r["dimension"]))


@app.get("/health")
def health(request: Request):
    return {"service": "analytics", "ok": request.app.state.db.ping()}


@app.post("/v1/completions")
def complete(body: Completion, request: Request, ctx=Depends(write_scores)):
    role(ctx, "system")
    if ctx["caller"] != "assessment":
        raise HTTPException(403, "Only the assessment publisher can deliver scores")
    attempt = peers.completed_attempt(ctx, body.attempt_id)
    return storage.publish(request.app.state.db, body, attempt)


@app.get("/v1/teaching/summary")
def teaching_summary(request: Request, selection=Depends(filters), ctx=Depends(teaching)):
    rows = visible_rows(request.app.state.db, ctx, {**selection, "dimension": None})
    return storage.summary(rows, selection["dimension"])


@app.get("/v1/teaching/weaknesses")
def teaching_weaknesses(request: Request, selection=Depends(filters), ctx=Depends(teaching)):
    rows = visible_rows(request.app.state.db, ctx, selection, weaknesses=True)
    return {"items": weakest_first(rows)}


@app.get("/v1/me/weaknesses")
def own_weaknesses(request: Request, selection=Depends(filters), ctx=Depends(self_read)):
    role(ctx, "student")
    rows = storage.read(request.app.state.db, ctx, None, **selection, weaknesses=True)
    return {"items": weakest_first(rows)}


@app.post("/v1/teaching/practice")
def practice(body: Practice, request: Request, ctx=Depends(assign)):
    role(ctx, "teacher")
    selection = {"attempt_id": body.attempt_id, "question_id": body.question_id}
    rows = visible_rows(request.app.state.db, ctx, selection, weaknesses=True)
    if not rows:
        raise HTTPException(404, "Weak question unavailable")
    # 训练服务在创建单人任务时再次核验当前师生关系，负责请求去重、截止时间和次数限制。
    return peers.assign(ctx, body, rows[0])
