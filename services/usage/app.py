"""学校预算和预留的内部接口。租户与操作人来自签名凭据，管理和派发分别授权。"""
import os
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from shared.runtime_mode import require_native_runtime
from shared.service_db import ServiceDatabase
from shared.service_security import require_service
from .ledger import UsageLedger


@asynccontextmanager
async def lifespan(app):
    require_native_runtime()
    if os.environ.get("SERVICE_ID") != "usage":
        raise RuntimeError("用量服务必须以 SERVICE_ID=usage 启动")
    ledger = UsageLedger(ServiceDatabase.from_env("usage"))
    ledger.initialize()
    app.state.ledger = ledger
    yield


app = FastAPI(title="School usage", lifespan=lifespan)
Limit = Annotated[int, Field(strict=True, ge=0, le=10**12)]


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Quota(Payload):
    text: Limit
    media: Limit


class Reservation(Payload):
    request_id: Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:/-]+$")]
    resource: Literal["text", "media"]
    units: Annotated[int, Field(strict=True, ge=1, le=10**12)]
    ttl_seconds: Annotated[int, Field(strict=True, ge=1, le=3600)] = 120


class Settlement(Payload):
    actual_units: Limit


def manager(ctx):
    if ctx["actor_type"] not in ("admin", "system"):
        raise HTTPException(403, "School quota management requires an administrator")


@app.get("/internal/usage/quota")
def quota(request: Request, ctx=Depends(require_service("usage", "usage.read"))):
    manager(ctx)
    return request.app.state.ledger.quota(ctx["school_id"])


@app.put("/internal/usage/quota")
def configure(body: Quota, request: Request, ctx=Depends(require_service("usage", "usage.configure"))):
    manager(ctx)
    return request.app.state.ledger.configure(ctx["school_id"], body.text, body.media)


@app.post("/internal/usage/reservations")
def reserve(body: Reservation, request: Request, ctx=Depends(require_service("usage", "usage.reserve"))):
    return request.app.state.ledger.reserve(ctx, body)


@app.post("/internal/usage/reservations/{reservation_id}/begin")
def begin(reservation_id: str, request: Request, ctx=Depends(require_service("usage", "usage.dispatch"))):
    return request.app.state.ledger.begin(ctx, reservation_id)


@app.post("/internal/usage/reservations/{reservation_id}/settle")
def settle(reservation_id: str, body: Settlement, request: Request,
           ctx=Depends(require_service("usage", "usage.settle"))):
    return request.app.state.ledger.settle(ctx, reservation_id, body.actual_units)
