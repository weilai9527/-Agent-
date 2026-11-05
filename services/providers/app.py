"""平台模型配置、推理进程只读投影和受授权的供应商诊断入口。"""
import os
import sqlite3
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.responses import JSONResponse
from pymysql import MySQLError

from shared.env_values import first_env_value
from shared.provider_settings import (
    DDL, RUNTIME_FIELDS, RUNTIME_SCOPE, config_store, public_settings, save_public_settings,
    stored_fields, validate_values,
)
from shared.runtime_mode import require_native_runtime
from shared.service_security import require_service
from .diagnostics import SECRET_FLAGS, diagnose_report_providers


@asynccontextmanager
async def lifespan(_app):
    # 在接触配置库之前拒绝旧身份或共享库模式，以免误部署时写入控制表。
    require_native_runtime()
    config_store().ensure_schema([DDL])
    yield


app = FastAPI(title="模型供应商控制服务", lifespan=lifespan)


@app.exception_handler(sqlite3.Error)
@app.exception_handler(MySQLError)
async def storage_unavailable(_request, _error):
    return JSONResponse(status_code=503, content={"detail": "模型配置库暂不可用"})


def platform_admin(scope):
    def check(actor=Depends(require_service("providers", scope))):
        # 学校管理员仅管理本校；跨学校的模型出站配置只接受部署授权的具名平台管理员。
        operators = os.environ.get("PROVIDER_PLATFORM_ADMIN_IDS", "").split(",")
        if (actor["caller"] in RUNTIME_FIELDS or actor["actor_type"] != "admin" or actor["school_id"] != "platform"
                or actor["actor_id"] not in operators):
            raise HTTPException(403, "需要平台管理员授权")
    return check


def settings_view():
    return {**public_settings(), "providerControlAvailable": True,
            **{name + "ApiKeyConfigured": bool(first_env_value(*keys))
               for name, keys in SECRET_FLAGS.items()}}


@app.get("/internal/runtime-settings")
def runtime_view(response: Response, actor=Depends(require_service("providers", RUNTIME_SCOPE))):
    caller = actor["caller"]
    if (caller not in RUNTIME_FIELDS or actor["actor_type"] != "system"
            or actor["actor_id"] != caller or actor["school_id"] != "platform"):
        raise HTTPException(403, "需要推理服务工作负载授权")
    values = stored_fields(RUNTIME_FIELDS[caller])
    if values:
        try:
            validate_values(values)
        except ValueError:
            raise HTTPException(503, "保存的模型参数未通过出站验证") from None
    response.headers["Cache-Control"] = "no-store"
    return {"consumer": caller, "school_id": "platform", "settings": values}


@app.get("/settings", dependencies=[Depends(platform_admin("providers.read"))])
def read_settings():
    return settings_view()


@app.patch("/settings", dependencies=[Depends(platform_admin("providers.configure"))])
def update_settings(body: dict):
    try:
        save_public_settings(body)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return settings_view()


@app.post("/diagnostics", dependencies=[Depends(platform_admin("providers.diagnose"))])
def probe():
    try:
        results = diagnose_report_providers()
    except ValueError:
        raise HTTPException(503, "模型诊断配置不可用") from None
    if not results:
        raise HTTPException(503, "未配置可执行诊断的供应商")
    return {"providers": results}
