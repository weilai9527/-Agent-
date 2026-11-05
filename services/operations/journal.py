"""把原生网关的安全事件先写到持久卷；诊断库停机后由同一网关自动补投。"""

import asyncio
from contextlib import asynccontextmanager, suppress
import json
import os
from pathlib import Path
import tempfile

from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool

from shared.security_logging import RequestLoggingMiddleware, emit
from shared.service_http import request_json
from services.identity.permissions import legacy_school_id
from .events import audit_data, GATEWAYS


class GatewayJournal:
    def __init__(self, directory, source, school):
        if not Path(directory).is_absolute() or source not in GATEWAYS:
            raise ValueError("诊断缓冲目录必须为已配置的绝对路径")
        import hashlib

        # 学校编号不直接用于文件路径。共享卷上的不同学校、不同入口各自持有独立的待发目录。
        self.directory = Path(directory) / hashlib.sha256(school.encode()).hexdigest() / source
        self.school = school
        self.source = source
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)

    def write(self, event):
        if event.get("school_id", self.school) != self.school:
            raise ValueError("网关事件学校与部署学校不符")
        payload = audit_data(event, self.source)
        path = self.directory / (payload["event_id"] + ".json")
        temp = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", dir=self.directory, delete=False, prefix=".pending-"
            ) as stream:
                temp = Path(stream.name)
                json.dump(payload, stream, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            # 写完后才发布，避免 relay 看见半个 JSON 文件。文件系统断电也要保留目录项。
            os.replace(temp, path)
            if os.name == "posix":
                fd = os.open(self.directory, os.O_RDONLY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
        finally:
            if temp:
                temp.unlink(missing_ok=True)

    async def drain(self):
        actor = {"school_id": self.school, "actor_type": "system", "actor_id": self.source}
        # 多个网关副本同时投递同一文件时，接收端用事件主键去重。只在收到匹配回执后删除。
        with os.scandir(self.directory) as files:
            for entry in files:
                if not entry.name.endswith(".json") or not entry.is_file(follow_symlinks=False):
                    continue
                path = Path(entry.path)
                try:
                    data = json.loads(await run_in_threadpool(path.read_bytes))
                    reply = await request_json(
                        "operations",
                        "POST",
                        "/internal/security-events",
                        actor=actor,
                        scope="operations.audit.append",
                        body=data,
                    )
                    if reply != {"id": data["event_id"]}:
                        raise RuntimeError("诊断服务回执不符")
                    path.unlink(missing_ok=True)
                except FileNotFoundError:
                    continue
                except (ValueError, KeyError):
                    # 隔离破损文件并报告，不阻塞后续正常事件，也不输出原始内容。
                    if path.exists():
                        path.rename(path.with_suffix(".invalid"))
                    emit({"event_type": "operations.journal.invalid", "service": self.source}, 40)
                except HTTPException as exc:
                    if exc.status_code not in {409, 422}:
                        raise
                    if path.exists():
                        path.rename(path.with_suffix(".rejected"))
                    emit({"event_type": "operations.journal.rejected", "service": self.source}, 40)

    async def relay(self):
        delay = 1
        while True:
            try:
                await self.drain()
                delay = 1
            except (OSError, RuntimeError, HTTPException):
                # 失败后保留已落盘文件；网关仍可处理其他业务，不回退旧库。
                emit({"event_type": "operations.journal.deferred", "service": self.source}, 30)
                delay = min(delay * 2, 30)
            await asyncio.sleep(delay)


def mount_journal(app, source):
    directory = os.environ.get("OPERATIONS_JOURNAL_DIR")
    enabled = (
        directory is not None
        or bool(os.getenv("OPERATIONS_SERVICE_URL"))
        or os.getenv("APP_ENV") == "production"
    )
    if not enabled:
        # 未启动诊断服务的本地开发仍输出结构化日志，生产环境必须显式注入持久卷。
        app.add_middleware(RequestLoggingMiddleware, service=source)
        return
    if not directory or not os.getenv("OPERATIONS_SERVICE_URL"):
        raise RuntimeError("请同时配置 OPERATIONS_JOURNAL_DIR 持久卷及 OPERATIONS_SERVICE_URL")
    journal = GatewayJournal(directory, source, legacy_school_id())
    original = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(instance):
        async with original(instance) as state:
            worker = asyncio.create_task(journal.relay())
            try:
                yield state
            finally:
                worker.cancel()
                with suppress(asyncio.CancelledError):
                    await worker

    app.router.lifespan_context = lifespan
    app.add_middleware(RequestLoggingMiddleware, service=source, audit_store=journal)
