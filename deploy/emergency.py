"""持签名工单查询冻结的学校快照。独立回环端口只开放两个只读诊断接口。"""
import hashlib
import hmac
import logging
import os
import re
import sqlite3
import stat
import tempfile
import time
from contextlib import asynccontextmanager, closing, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import jwt
import uvicorn
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.datastructures import MutableHeaders

LOG = logging.getLogger("uvicorn.error")
ISSUER = "school-emergency-approver"
AUDIENCE = "legacy-readonly-rescue"
MAX_SECONDS = 3600
FORMAT = "school-report-status-v1"
HEX = re.compile(r"[0-9a-f]{64}")
REPORT_ID = re.compile(r"[\w-]{1,128}")


@contextmanager
def open_regular(path):
    """先打开再检查文件描述符；工单被换成管道或符号链接时立即拒绝。"""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    with os.fdopen(os.open(path, flags), "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("应急输入必须为普通文件")
        yield stream


def fingerprint(stream):
    info = os.fstat(stream.fileno())
    return info.st_dev, info.st_ino, info.st_ctime_ns, info.st_mtime_ns, info.st_size


def read_small(path, size):
    with open_regular(path) as stream:
        stamp = fingerprint(stream)
        data = stream.read(size + 1)
        if stamp != fingerprint(stream) or not data or len(data) > size:
            raise ValueError("授权文件已变化、为空或超过大小限制")
        return data, stamp


@dataclass(frozen=True)
class Settings:
    school: str
    snapshot: Path
    ticket: Path
    public_key: Path

    @classmethod
    def from_env(cls):
        paths = [Path(os.environ[key]) for key in ("EMERGENCY_SNAPSHOT", "EMERGENCY_TICKET_FILE",
                                                   "EMERGENCY_APPROVER_PUBLIC_KEY_FILE")]
        if not all(p.is_absolute() and p.is_file() and not p.is_symlink() for p in paths):
            raise ValueError("应急文件须为绝对路径的普通文件")
        return cls(os.environ["EMERGENCY_SCHOOL_ID"], *paths)


def read_permit(settings):
    key = serialization.load_pem_public_key(read_small(settings.public_key, 4096)[0])
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("工单审批必须使用 Ed25519 公钥")
    raw, ticket_identity = read_small(settings.ticket, 8192)
    raw = raw.strip()
    if jwt.get_unverified_header(raw).get("typ") != "emergency+jwt":
        raise ValueError("工单类型错误")
    required = ["iss", "aud", "iat", "nbf", "exp", "sub", "jti", "school", "scope", "snapshot_sha256", "bearer_sha256"]
    claims = jwt.decode(raw, key, algorithms=["EdDSA"], issuer=ISSUER, audience=AUDIENCE,
                        options={"require": required, "strict_aud": True})
    if (claims["school"] != settings.school or claims["scope"] != "emergency.report-status.read"
            or not all(isinstance(claims[k], str) and re.fullmatch(r"[\w.@-]{1,128}", claims[k])
                       for k in ("sub", "jti", "school"))
            or not all(type(claims[k]) is int for k in ("iat", "nbf", "exp"))
            or not claims["iat"] <= claims["nbf"] < claims["exp"] <= claims["iat"] + MAX_SECONDS
            or not all(isinstance(claims[k], str) and HEX.fullmatch(claims[k]) for k in ("snapshot_sha256", "bearer_sha256"))):
        raise ValueError("应急工单超出校区、时限或操作范围")
    return raw, claims, ticket_identity


def read_db(path):
    # 仅打开已经验过签名摘要的私有副本。immutable 模式要求生成快照前完成 WAL 合并。
    conn = sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True, timeout=1)
    try:
        conn.execute("PRAGMA query_only=ON")
        conn.execute("PRAGMA trusted_schema=OFF")
    except Exception:
        conn.close()
        raise
    return conn


def snapshot_meta(db, school):
    """签名证明谁批准了文件，结构和状态白名单另行验证，防止将错列的个人信息返回给运维。"""
    schemas = db.execute("SELECT name,type,tbl_name,sql FROM sqlite_schema").fetchall()
    expected = {"snapshot_meta": (("format","TEXT",0),("school","TEXT",0),("as_of","TEXT",0),("report_count","INTEGER",0)),
                "report_status": (("id","TEXT",1),("generation_status","TEXT",0),("review_status","TEXT",0))}
    # 允许报告主键的 SQLite 自动索引。视图、触发器、额外索引和生成列均不能混入签发包。
    tables = {}
    for name, kind, owner, sql in schemas:
        if kind == "index" and name == "sqlite_autoindex_report_status_1" and owner == "report_status" and sql is None:
            continue
        if kind != "table" or name not in expected or not isinstance(sql,str) or "VIRTUAL" in sql.upper():
            raise ValueError("应急数据表结构错误")
        tables[name] = sql
    if tables.keys() != expected.keys():
        raise ValueError("应急数据表结构错误")
    for table, columns in expected.items():
        rows = db.execute(f"PRAGMA table_xinfo({table})").fetchall()
        if (tuple((r[1],r[2].upper(),r[5]) for r in rows) != columns
                or any(r[4] is not None or r[6] != 0 for r in rows)):
            raise ValueError("应急数据表结构错误")
    meta = db.execute("SELECT format,school,as_of,report_count FROM snapshot_meta LIMIT 2").fetchall()
    if len(meta) != 1 or meta[0][:2] != (FORMAT, school):
        raise ValueError("快照格式或学校绑定错误")
    _, _, as_of, count = meta[0]
    if not isinstance(as_of, str) or not re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})", as_of):
        raise ValueError("无效的快照时间")
    if datetime.fromisoformat(as_of.replace("Z", "+00:00")) > datetime.now(timezone.utc):
        raise ValueError("快照时间不能在未来")
    if type(count) != int or count != db.execute("SELECT COUNT(*) FROM report_status").fetchone()[0]:
        raise ValueError("报告条数校验失败")
    if any(not isinstance(r[0],str) or not REPORT_ID.fullmatch(r[0])
           for r in db.execute("SELECT id FROM report_status")):
        raise ValueError("快照含无效的报告编号")
    bad = db.execute("""SELECT 1 FROM report_status WHERE typeof(generation_status)<>'text'
        OR generation_status COLLATE BINARY NOT IN ('pending','queued','running','pending_retry','degraded','failed','succeeded')
        OR typeof(review_status)<>'text'
        OR review_status COLLATE BINARY NOT IN ('pending','approved','rejected') LIMIT 1""").fetchone()
    if bad:
        raise ValueError("应急快照包含未知状态")
    return meta[0]


@contextmanager
def pinned_snapshot(source):
    """在可信临时目录固定一次文件内容，使审批、摘要和读取均对应同一份字节。"""
    with tempfile.TemporaryDirectory(prefix="school-rescue-") as folder:
        private = Path(folder) / "status.sqlite"
        digest = hashlib.sha256()
        with open_regular(source) as src, private.open("xb") as dst:
            stamp = fingerprint(src)
            remaining = stamp[-1]
            while remaining:
                chunk = src.read(min(remaining, 1024 * 1024))
                if not chunk:
                    raise ValueError("快照复制中源文件被截断")
                digest.update(chunk)
                dst.write(chunk)
                remaining -= len(chunk)
            if stamp != fingerprint(src):
                raise ValueError("快照复制中源文件发生变化")
        private.chmod(0o400)
        yield private, digest.hexdigest()


class EmergencyBoundary:
    """只允许本机运维 HTTP，在向客户端发送响应头之前最后一次校验工单。"""

    def __init__(self, app, state, permit_active):
        self.app = app
        self.state = state
        self.permit_active = permit_active

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        denied = None

        async def checked_send(message):
            nonlocal denied
            if message["type"] == "http.response.start":
                if scope.get("state", {}).get("emergency_authorized") and not self.permit_active():
                    # 查询或线程池等待期间可能撤回；替换状态码、头和整个正文，避免泄露存在性。
                    denied = JSONResponse({"detail": "工单已撤回或过期"}, status_code=403)
                    message = {"type":"http.response.start", "status":403, "headers":list(denied.raw_headers)}
                headers = MutableHeaders(scope=message)
                headers["Cache-Control"] = "no-store"
                headers["X-Content-Type-Options"] = "nosniff"
                route = scope.get("route")
                LOG.warning("应急查询 工单=%s 操作者=%s 路由=%s 结果=%s", self.state.permit["jti"],
                            self.state.permit["sub"], getattr(route, "path", "未授权路径"), message["status"])
            elif message["type"] == "http.response.body" and denied is not None:
                # 正常端点均为单一 JSON 响应。即使下游意外改用流式响应，也只发拒绝正文一次。
                if message.get("more_body", False):
                    return
                message = {"type":"http.response.body", "body":denied.body}
            await send(message)

        if (not request.client or request.client.host not in {"127.0.0.1", "::1"}
                or any(h in request.headers for h in ("origin","cookie","forwarded","x-forwarded-for"))
                or request.url.query):
            await JSONResponse({"detail":"仅允许本机运维客户端"},status_code=403)(scope, receive, checked_send)
        else:
            await self.app(scope, receive, checked_send)


def create_app(settings):
    @asynccontextmanager
    async def lifespan(app):
        raw, permit, ticket_identity = read_permit(settings)
        with pinned_snapshot(settings.snapshot) as (copy, digest):
            if not hmac.compare_digest(digest, permit["snapshot_sha256"]):
                raise ValueError("应急快照摘要不匹配")
            with closing(read_db(copy)) as db:
                meta = snapshot_meta(db, settings.school)
            app.state.snapshot, app.state.meta = copy, meta
            app.state.ticket, app.state.permit = raw, permit
            app.state.revoked = False
            app.state.ticket_identity = ticket_identity
            LOG.warning("应急入口启动 学校=%s 工单=%s 操作者=%s 到期=%s", settings.school, permit["jti"],
                        permit["sub"], permit["exp"])
            try:
                yield
            finally:
                LOG.warning("应急入口关闭 工单=%s", permit["jti"])

    app = FastAPI(title="应急只读查询", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    def authorized(request: Request):
        current = app.state.permit
        values = request.headers.getlist("authorization")
        token = values[0].removeprefix("Bearer ") if len(values) == 1 and values[0].startswith("Bearer ") else ""
        if (not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", token) or
                not hmac.compare_digest(hashlib.sha256(token.encode()).hexdigest(), current["bearer_sha256"])):
            raise HTTPException(401, "需要本工单绑定的凭据")
        if not permit_active():
            raise HTTPException(403, "工单已撤回或过期")
        request.state.emergency_authorized = True

    def permit_active():
        current = app.state.permit
        try:
            data, stamp = read_small(settings.ticket, 8192)
            same_ticket = hmac.compare_digest(data.strip(), app.state.ticket) and stamp == app.state.ticket_identity
        except (OSError, ValueError):
            same_ticket = False
        if not same_ticket or not current["nbf"] <= time.time() < current["exp"]:
            # 已观察到撤回或过期后，本进程不可因文件被还原或时钟回拨而重新授权。
            app.state.revoked = True
        return not app.state.revoked

    app.add_middleware(EmergencyBoundary, state=app.state, permit_active=permit_active)

    @app.get("/emergency/summary", dependencies=[Depends(authorized)])
    def summary():
        _, school, as_of, count = app.state.meta
        return {"school": school, "snapshot_at": as_of, "reports": count, "read_only": True}

    @app.get("/emergency/reports/{report_id}/status", dependencies=[Depends(authorized)])
    def status(report_id: str):
        if not REPORT_ID.fullmatch(report_id):
            raise HTTPException(404, "快照中无此报告")
        with closing(read_db(app.state.snapshot)) as db:
            row = db.execute("SELECT generation_status,review_status FROM report_status WHERE id COLLATE BINARY=?", (report_id,)).fetchone()
        if not row:
            raise HTTPException(404, "快照中无此报告")
        return {"school": settings.school, "snapshot_at": app.state.meta[2],
                "generation_status": row[0], "review_status": row[1]}

    return app


if __name__ == "__main__":
    uvicorn.run(create_app(Settings.from_env()), host="127.0.0.1", port=3010,
                proxy_headers=False, access_log=False)
