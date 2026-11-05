"""学校身份服务入口。导入模块不会打开数据库连接。"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from . import operations_scope, organization_workbook, staff_maintenance
from shared.runtime_mode import require_native_runtime
from shared.service_db import ServiceDatabase
from .academic_options import router as academic_options_router
from . import browser, candidate, organization, permission_requests, record_scope, registrations, staff
from .account_summary import router as account_summary_router


def initialize(store):
    statements = [*browser.SCHEMA, *registrations.SCHEMA, *staff.SCHEMA, *staff_maintenance.SCHEMA, *candidate.SCHEMA, *organization.SCHEMA, *permission_requests.SCHEMA,
                  """CREATE TABLE IF NOT EXISTS identity_cutover (
                     school_id VARCHAR(128) PRIMARY KEY, migrated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"""]
    if store.engine == "mysql":
        # 两种数据库都须按原始标识精确区分学校与主体。
        statements = [sql + " ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin" for sql in statements]
    store.ensure_schema(statements)
    store.require_exact_keys("identity")


@asynccontextmanager
async def lifespan(application):
    require_native_runtime()
    store = ServiceDatabase.from_env("identity")
    initialize(store)
    application.state.store = store
    yield


app = FastAPI(title="School identity", lifespan=lifespan)
app.include_router(staff_maintenance.router)
app.include_router(registrations.router)
app.include_router(staff.router)
app.include_router(permission_requests.router)
app.include_router(candidate.router)
app.include_router(organization.router)
app.include_router(organization_workbook.router)
app.include_router(record_scope.router)

app.include_router(academic_options_router)
app.include_router(operations_scope.router)
app.include_router(account_summary_router)


@app.middleware("http")
async def no_cache(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(RequestValidationError)
async def invalid_request(_request, _error):
    # 校验错误不得回显初始密码、整批导入字段或内部会话令牌。
    return JSONResponse(status_code=422, content={"detail": "Invalid identity request"})


@app.get("/health")
def health():
    return {"ready": app.state.store.ping()}
