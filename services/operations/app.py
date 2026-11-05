"""运行诊断和安全审计的唯一在线存储；离线导入工具另行持有历史库只读权限。"""

import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import Body, Depends, FastAPI, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from shared.runtime_mode import require_native_runtime
from shared.service_db import ServiceDatabase
from shared.service_http import request_json
from shared.service_security import require_service
from .events import GATEWAYS, audit_data, rtc_data, timestamp
from .store import insert, page, prepare


@asynccontextmanager
async def lifespan(app):
    require_native_runtime()
    app.state.store = ServiceDatabase.from_env("operations")
    if not 0 <= retain_days() <= 36500:
        raise ValueError("诊断保留天数必须为 0 到 36500")
    prepare(app.state.store)
    yield


app = FastAPI(title="学校运行诊断与安全审计", lifespan=lifespan)


@app.middleware("http")
async def no_cache(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(RequestValidationError)
async def invalid(_request, _error):
    return JSONResponse({"detail": "日志查询或投递参数无效"}, status_code=422)


@app.get("/health")
def health():
    return {"ready": app.state.store.ping()}


def caller(actor, services, roles):
    if actor["caller"] not in services or actor["actor_type"] not in roles:
        raise HTTPException(403, "此来源或角色不能执行操作")


def retain_days():
    return int(os.environ.get("OPERATIONS_RTC_RETENTION_DAYS", "0"))


def cutoff():
    return timestamp(datetime.now(timezone.utc) - timedelta(days=retain_days())) if retain_days() else ""


@app.post("/internal/security-events")
def ingest(event: dict = Body(...), actor=Depends(require_service("operations", "operations.audit.append"))):
    caller(actor, GATEWAYS, {"system"})
    if actor["actor_id"] != actor["caller"]:
        raise HTTPException(403, "只接受网关进程本身的审计")
    try:
        data = audit_data(event, actor["caller"])
    except (ValueError, KeyError, TypeError, OverflowError):
        raise HTTPException(422, "审计事件格式无效") from None
    with app.state.store.transaction(write=True) as tx:
        insert(
            tx,
            app.state.store.engine,
            actor["school_id"],
            "audit",
            data["event_id"],
            data["actor_id"],
            "",
            data["occurred_at"],
            data,
        )
    return {"id": data["event_id"]}


@app.post("/internal/rtc/{interview_id}", status_code=201)
def rtc_write(
    interview_id: str,
    data: dict = Body(...),
    actor=Depends(require_service("operations", "operations.rtc.append")),
):
    # 面试服务已核对路径中的面试与当前学生，浏览器不能直接签发此动作。
    caller(actor, {"interview"}, {"student"})
    if not 0 < len(interview_id) <= 64:
        raise HTTPException(422, "面试编号无效")
    try:
        safe = rtc_data(data, from_trusted_bridge=True)
    except (TypeError, ValueError):
        raise HTTPException(422, "诊断级别无效") from None
    event_id, now = str(uuid4()), timestamp(datetime.now(timezone.utc))
    db = app.state.store
    with db.transaction(write=True) as tx:
        insert(tx, db.engine, actor["school_id"], "rtc", event_id, actor["actor_id"], interview_id, now, safe)
        if retain_days():
            tx.execute(
                "DELETE FROM ops_events WHERE school_id=? AND category='rtc' AND occurred_at<?",
                (actor["school_id"], cutoff()),
            )
    return {"event": {"id": event_id, "eventType": safe["event_type"], "retentionDays": retain_days()}}


@app.get("/internal/rtc/{interview_id}")
def rtc_self(
    interview_id: str,
    limit: int = Query(200, ge=1, le=500),
    actor=Depends(require_service("operations", "operations.rtc.self")),
):
    caller(actor, {"interview"}, {"student"})
    rows, _ = page(
        app.state.store,
        "school_id=? AND category='rtc' AND actor_id=? AND interview_id=? AND occurred_at>=?",
        [actor["school_id"], actor["actor_id"], interview_id, cutoff()],
        limit,
        0,
    )
    return {
        "events": [
            dict(json.loads(r["payload"]), id=r["event_id"], created_at=r["occurred_at"]) for r in rows
        ],
        "retentionDays": retain_days(),
    }


async def permitted(actor, action, q="", after=""):
    caller(actor, {"admin-gateway"}, {"admin", "teacher"})
    scope = await request_json(
        "identity",
        "POST",
        "/internal/operations/scope",
        actor=actor,
        scope="identity.operations.scope",
        body={"action": action, "student_q": q, "after_student": after},
    )
    if (
        not isinstance(scope, dict)
        or scope.get("action") != action
        or any(scope.get(k) != actor[k] for k in ("school_id", "actor_id", "actor_type"))
        or type(scope.get("all")) is not bool
        or not isinstance(scope.get("students"), list)
        or len(scope["students"]) > 100
        or not isinstance(scope.get("next"), str)
        or any(
            not isinstance(r, dict)
            or not isinstance(r.get("actor_id"), str)
            or not isinstance(r.get("name"), str)
            for r in scope["students"]
        )
    ):
        raise HTTPException(502, "身份服务返回的范围不匹配")
    return scope


@app.get("/v1/connection-logs")
async def rtc_list(
    student_q: str = Query("", max_length=128),
    after_student: str = Query("", max_length=128),
    interview_id: str = Query("", max_length=64),
    event_type: str = Query("", max_length=80),
    level: str = Query("", pattern="^(info|warning|error)?$"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0, le=1000000),
    actor=Depends(require_service("operations", "operations.rtc.read")),
):
    scope = await permitted(actor, "operations.rtc.read", student_q, after_student)
    names = {r["actor_id"]: r["name"] for r in scope["students"]}
    where = ["school_id=?", "category='rtc'", "occurred_at>=?"]
    args = [actor["school_id"], cutoff()]
    # 游标只决定从哪一段名册继续，每次翻页重新授权，不信任浏览器缓存的班级或学生列表。
    if not scope["all"]:
        where.append("actor_id IN (" + ",".join("?" for _ in names) + ")" if names else "1=0")
        args.extend(names)
    for column, value in (("interview_id", interview_id), ("event_type", event_type), ("level", level)):
        if value:
            where.append(column + "=?")
            args.append(value)
    rows, total = await run_in_threadpool(page, app.state.store, " AND ".join(where), args, limit, offset)
    logs = [
        dict(
            json.loads(r["payload"]),
            id=r["event_id"],
            interview_id=r["interview_id"],
            student_id=r["actor_id"],
            candidate=names.get(r["actor_id"], r["actor_id"]),
            created_at=r["occurred_at"],
        )
        for r in rows
    ]
    return {
        "logs": logs,
        "hasMore": offset + len(rows) < total,
        "nextStudents": scope["next"],
        "retentionDays": retain_days(),
    }


@app.get("/v1/security-logs")
async def audit_list(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=1000000),
    request_id: str = Query("", max_length=32),
    actor_id: str = Query("", max_length=128),
    event_type: str = Query("", max_length=80),
    school_id: str = Query("", max_length=128),
    since: datetime | None = None,
    until: datetime | None = None,
    actor=Depends(require_service("operations", "operations.audit.read")),
):
    scope = await permitted(actor, "operations.audit.read")
    if actor["actor_type"] != "admin" or not scope["all"]:
        raise HTTPException(403, "需要全校审计授权")
    platform = actor["school_id"] == "platform" and actor["actor_id"] in os.environ.get(
        "OPERATIONS_PLATFORM_ADMIN_IDS", ""
    ).split(",")
    if school_id and school_id != actor["school_id"] and not platform:
        raise HTTPException(403, "不能跨学校查阅审计")
    school = school_id if platform else actor["school_id"]
    if (since and not since.tzinfo) or (until and not until.tzinfo) or (since and until and since > until):
        raise HTTPException(422, "日期筛选需包含时区且起止有序")
    where, args = ["category='audit'"], []
    for column, op, value in (
        ("school_id", "=", school),
        ("request_id", "=", request_id),
        ("actor_id", "=", actor_id),
        ("event_type", "=", event_type),
        ("occurred_at", ">=", timestamp(since) if since else ""),
        ("occurred_at", "<=", timestamp(until) if until else ""),
    ):
        if value:
            where.append(column + op + "?")
            args.append(value)
    rows, total = await run_in_threadpool(page, app.state.store, " AND ".join(where), args, limit, offset)
    return {
        "events": [dict(json.loads(r["payload"]), school_id=r["school_id"]) for r in rows],
        "total": total,
        "offset": offset,
        "limit": limit,
        "hasMore": offset + len(rows) < total,
    }
