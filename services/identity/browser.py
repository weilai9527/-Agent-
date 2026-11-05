"""教职工与学生登录共用的浏览器来源校验、会话和限流保护。"""
import hashlib
import os
import time
from urllib.parse import urlsplit

from fastapi import HTTPException

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS identity_login_limits (
       bucket CHAR(64) PRIMARY KEY, expires_at BIGINT NOT NULL, attempts INTEGER NOT NULL
    )""",
)
WINDOW = 15 * 60


def gateway_origins(kind):
    production = os.getenv("APP_ENV", "").strip().lower() == "production"
    if kind == "student":
        default = "" if production else "http://127.0.0.1:5173"
        configured = os.getenv("FRONTEND_ORIGIN", default)
    elif kind == "staff":
        default = "" if production else ",".join(f"http://{host}:{port}"
            for host in ("127.0.0.1", "localhost") for port in (5174, 5175, 5176))
        configured = os.getenv("ADMIN_FRONTEND_ORIGIN", default)
    else:
        raise ValueError("Unknown browser kind")
    return {origin.strip() for origin in configured.split(",") if origin.strip()}


def check_origin(request, *, extra_origins=()):
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    # 浏览器提交来源或同站信息，非浏览器调用仍须验证实际密码或不透明会话凭据。
    origin = request.headers.get("origin")
    if not origin and request.headers.get("referer"):
        ref = urlsplit(request.headers["referer"])
        origin = f"{ref.scheme}://{ref.netloc}"
    trusted = {v.strip() for v in os.getenv("IDENTITY_BROWSER_ORIGINS", "").split(",") if v.strip()}
    trusted.update(extra_origins)
    trusted.add(f"{request.url.scheme}://{request.url.netloc}")
    if (origin and origin not in trusted) or (
        not origin and request.headers.get("sec-fetch-site") in {"cross-site", "same-site"}
    ):
        raise HTTPException(403, "Browser origin denied")


def reserve_login(store, kind, school, login, ip):
    """先占用账号和来源地址两个计数，再验证密码。标识以摘要存储，遭拒的预留在事务中回滚。"""
    now = int(time.time())
    counters = ((f"ip\0{ip}", 240), (f"{kind}\0{school}\0{login}", 8))
    with store.transaction(write=True) as tx:
        for value, limit in counters:
            bucket = hashlib.sha256(value.encode()).hexdigest()
            insert = "INSERT INTO identity_login_limits (bucket,expires_at,attempts) VALUES (?,?,0)"
            if store.engine == "mysql":
                insert += " ON DUPLICATE KEY UPDATE bucket = VALUES(bucket)"
            else:
                insert += " ON CONFLICT (bucket) DO NOTHING"
            tx.execute(insert, (bucket, now + WINDOW))
            updated = tx.execute("""
                UPDATE identity_login_limits
                SET attempts=CASE WHEN expires_at<=? THEN 1 ELSE attempts+1 END,
                    expires_at=CASE WHEN expires_at<=? THEN ? ELSE expires_at END
                WHERE bucket=? AND (expires_at<=? OR attempts<?)
            """, (now, now, now + WINDOW, bucket, now, limit))
            if not updated:
                raise HTTPException(429, "Too many login attempts", headers={"Retry-After": str(WINDOW)})
    # 低频清理过期计数，避免每次登录都在全表持有范围锁。
    if os.urandom(1) == b"\x00":
        with store.transaction(write=True) as tx:
            tx.execute("DELETE FROM identity_login_limits WHERE expires_at<=?", (now,))
