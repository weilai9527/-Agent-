"""媒体服务入口，使用独立数据库保存轮次快照和 RTC 任务。"""
import asyncio
import os
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool

from shared.runtime_mode import require_native_runtime
from . import access, omni_socket, providers, rtc, voice


@asynccontextmanager
async def lifespan(app):
    # 恢复循环能操作供应商侧任务，必须在打开数据库前确认运行模式和服务身份。
    require_native_runtime()
    if os.environ.get("SERVICE_ID") != "media":
        raise RuntimeError("媒体服务要求 SERVICE_ID=media")
    await run_in_threadpool(access.initialize)
    await run_in_threadpool(rtc.initialize)
    recovery = asyncio.create_task(rtc.rtc_recovery_loop())
    try:
        yield
    finally:
        recovery.cancel()
        with suppress(asyncio.CancelledError):
            await recovery


app = FastAPI(title="面试媒体服务", lifespan=lifespan)
for module in (access, rtc, providers, voice, omni_socket):
    app.include_router(module.router)
