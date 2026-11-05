"""使用 uvicorn services.career.app:app 启动，部署时需明确绑定各学校数据库。"""
from contextlib import asynccontextmanager

from shared.runtime_mode import require_native_runtime
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from . import catalog, matches, postings, program_jobs
from .limits import BodyLimit
from .store import ensure_school, school_databases


@asynccontextmanager
async def lifespan(_):
    require_native_runtime()
    for school in school_databases():
        ensure_school(school, seed=True)
    yield


app = FastAPI(title="Career service", lifespan=lifespan)
app.add_middleware(BodyLimit)
app.include_router(catalog.router)
app.include_router(postings.router)
app.include_router(matches.router)
app.include_router(program_jobs.router)


@app.exception_handler(ValueError)
async def invalid_value(_, exc):
    return JSONResponse({"detail": str(exc)[:300]}, 400)


@app.exception_handler(ValidationError)
@app.exception_handler(RequestValidationError)
async def invalid_fields(_, exc):
    # 避免 FastAPI 的默认验证错误将私有岗位描述原样返回。
    return JSONResponse({"detail": "请求字段无效。"}, 422)


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/ready")
def ready():
    if not all(store.ping() for store in school_databases().values()):
        raise HTTPException(503, "Career database unavailable")
    return {"ok": True}
