"""Request diagnostics and durable security events, without request/response bodies."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import re
import sqlite3
import sys
import time
import traceback
from typing import Any
from uuid import uuid4

from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse


logger = logging.getLogger("interview.operations")


def configure_logging() -> None:
    # Own handler: uvicorn's default logging config does not configure application INFO logs.
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def clean(value: Any, limit: int = 160) -> str:
    return re.sub(r"[\x00-\x1f\x7f]", "", str(value or ""))[:limit]


def emit(event: dict, level: int = logging.INFO) -> None:
    logger.log(level, json.dumps(event, ensure_ascii=False, separators=(",", ":")))


def bind_actor(request, actor: dict | None, actor_type: str) -> None:
    if actor:
        request.state.security_actor = {
            "actor_id": clean(actor.get("id"), 80), "actor_type": actor_type,
        }


def audit_context(request, **fields: Any) -> None:
    allowed = {"action", "reason", "attempted_account", "target_type", "target_id", "outcome"}
    current = getattr(request.state, "security_context", {})
    current.update({k: clean(v) for k, v in fields.items() if k in allowed})
    request.state.security_context = current


def exception_details(exc: Exception) -> dict:
    # Exception messages, source lines and locals can contain SQL values, API keys or tokens.
    # Preserve the type and call locations without copying those potentially sensitive values.
    return {
        "error_type": clean(type(exc).__module__ + "." + type(exc).__name__),
        "frames": [
            {"file": Path(f.filename).name, "line": f.lineno, "function": clean(f.name)}
            for f in traceback.extract_tb(exc.__traceback__)[-40:]
        ],
    }


def ensure_security_schema(db, engine: str) -> None:
    columns = """
        id VARCHAR(36) PRIMARY KEY,
        occurred_at VARCHAR(32) NOT NULL,
        service VARCHAR(48) NOT NULL,
        event_type VARCHAR(80) NOT NULL,
        request_id VARCHAR(32) NOT NULL,
        actor_id VARCHAR(80),
        status_code INTEGER NOT NULL,
        payload_json TEXT NOT NULL
    """
    if engine == "mysql":
        sql = f"""CREATE TABLE IF NOT EXISTS security_audit_events (
            {columns},
            INDEX idx_security_time (occurred_at, id),
            INDEX idx_security_request (request_id),
            INDEX idx_security_actor (actor_id, occurred_at),
            INDEX idx_security_type (event_type, occurred_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""
        db.execute(sql).close()
    else:
        db.execute(f"CREATE TABLE IF NOT EXISTS security_audit_events ({columns})").close()
        for name, fields in [
            ("time", "occurred_at, id"), ("request", "request_id"),
            ("actor", "actor_id, occurred_at"), ("type", "event_type, occurred_at"),
        ]:
            db.execute(f"CREATE INDEX IF NOT EXISTS idx_security_{name} ON security_audit_events ({fields})").close()
    db.commit()


class SecurityAuditStore:
    """Separate bounded connections; never commit or roll back a business transaction."""

    def __init__(self, database_module):
        self.engine = database_module.DB_ENGINE
        self.sqlite_path = str(database_module.SQLITE_PATH)
        self.mysql = asdict(database_module.config)

    def write(self, event: dict) -> None:
        if self.engine == "sqlite":
            conn = sqlite3.connect(self.sqlite_path, timeout=1)
            placeholder = "?"
        else:
            import pymysql
            conn = pymysql.connect(
                **self.mysql, connect_timeout=2, read_timeout=2, write_timeout=2,
                autocommit=False,
            )
            placeholder = "%s"
        try:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "INSERT INTO security_audit_events "
                    "(id, occurred_at, service, event_type, request_id, actor_id, status_code, payload_json) "
                    f"VALUES ({', '.join([placeholder] * 8)})",
                    (event["event_id"], event["occurred_at"], event["service"], event["event_type"],
                     event["request_id"], event.get("actor_id"), event["status_code"],
                     json.dumps(event, ensure_ascii=False, separators=(",", ":"))),
                )
                conn.commit()
            finally:
                cursor.close()
        finally:
            conn.close()


AUTH_ACTIONS = {
    "/api/auth/login": "student.login",
    "/api/auth/logout": "student.logout",
    "/api/auth/change-initial-password": "student.password_change",
    "/api/auth/password-reset/request": "student.password_reset_request",
    "/api/auth/password-reset/verify": "student.password_reset_verify",
    "/api/auth/password-reset/confirm": "student.password_reset",
    "/api/admin/auth/login": "admin.login",
    "/api/admin/auth/logout": "admin.logout",
}


class RequestLoggingMiddleware:
    """Pure ASGI middleware: preserve streaming and isolate concurrent request contexts."""

    def __init__(self, app, service: str, audit_store: SecurityAuditStore):
        self.app = app
        self.service = service
        self.audit_store = audit_store
        configure_logging()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        state = scope.setdefault("state", {})
        # Never accept an arbitrary caller's ID as trusted correlation information.
        request_id = uuid4().hex
        state["request_id"] = request_id
        started = time.perf_counter()
        status = 500
        response_started = False
        response_complete = False
        response_ms = None
        failure = None

        async def observed_send(message):
            nonlocal status, response_started, response_complete, response_ms
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"x-request-id"]
                message = {**message, "headers": headers + [(b"x-request-id", request_id.encode())]}
                response_started = True
            await send(message)
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                response_complete = True
                response_ms = round((time.perf_counter() - started) * 1000, 3)

        try:
            await self.app(scope, receive, observed_send)
        except Exception as exc:
            failure = exception_details(exc)
            if not response_started:
                await JSONResponse(
                    {"error": "服务暂时不可用，请稍后重试。", "requestId": request_id}, status_code=500,
                )(scope, receive, observed_send)
            else:
                # A partially sent stream cannot be replaced with a JSON response.
                raise
        finally:
            route = getattr(scope.get("route"), "path", "<unmatched>")
            context = state.get("security_context", {})
            actor = state.get("security_actor", {})
            event = {
                "occurred_at": timestamp(), "service": self.service,
                "event_type": "http.request", "request_id": request_id,
                "method": clean(scope.get("method"), 12), "route": clean(route, 255),
                "status_code": status, "response_complete": response_complete,
                "success": status < 400 and failure is None and response_complete,
                "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                "response_ms": response_ms,
                "client_ip": clean((scope.get("client") or ("unknown",))[0], 64),
                **actor,
            }
            if failure:
                emit({**event, "event_type": "http.exception", **failure}, logging.ERROR)
            emit(event, logging.ERROR if status >= 500 else logging.INFO)
            action = context.get("action") or AUTH_ACTIONS.get(route)
            failed = not event["success"]
            if not action and (status in {401, 403, 429} or status >= 500 or failure or not response_complete):
                action = {401: "security.unauthenticated", 403: "security.access_denied",
                          429: "security.rate_limited"}.get(status, "operation.failed")
            if not action and failed and (scope.get("method") in {"POST", "PUT", "PATCH", "DELETE"} or route.startswith("/api/admin/")):
                action = "operation.failed"
            if action:
                targets = {
                    k: clean(v, 80) for k, v in scope.get("path_params", {}).items()
                    if k.endswith("_id") and re.fullmatch(r"[A-Za-z0-9_-]{1,80}", str(v))
                }
                audit = {
                    **event, "event_id": str(uuid4()), "event_type": clean(action, 80),
                    "success": event["success"] and context.get("outcome") != "failed",
                    "reason": context.get("reason") or (
                        "unhandled_exception" if failure else "response_incomplete" if not response_complete else f"http_{status}"),
                    "targets": targets,
                    **{k: v for k, v in context.items() if k in {"attempted_account", "target_type", "target_id"}},
                }
                if failure:
                    audit["error_type"] = failure["error_type"]
                # First emit the full bounded security event into the existing journal sink.
                emit(audit, logging.WARNING if not audit["success"] else logging.INFO)
                try:
                    await run_in_threadpool(self.audit_store.write, audit)
                except Exception as exc:
                    emit({
                        "occurred_at": timestamp(), "service": self.service,
                        "event_type": "security.audit_persist_failed", "event_id": audit["event_id"],
                        "request_id": request_id, "error_type": type(exc).__name__,
                        "fallback": "structured_runtime_log",
                    }, logging.ERROR)


def list_security_events(db, *, limit: int = 50, offset: int = 0, request_id: str = "",
                         actor_id: str = "", event_type: str = "", since: str = "", until: str = "") -> dict:
    """Super-admin API uses bounded, parameterized filters; timestamps are normalized UTC."""
    clauses, params = [], []
    for column, value in [("request_id", request_id), ("actor_id", actor_id), ("event_type", event_type)]:
        if value:
            clauses.append(f"{column} = ?")
            params.append(value)
    for operator, value in [(">=", since), ("<=", until)]:
        if value:
            clauses.append(f"occurred_at {operator} ?")
            params.append(value)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    cursor = db.execute("SELECT COUNT(*) AS total FROM security_audit_events" + where, tuple(params))
    try:
        total = dict(cursor.fetchone())["total"]
    finally:
        cursor.close()
    cursor = db.execute(
        "SELECT payload_json FROM security_audit_events" + where + " ORDER BY occurred_at DESC, id DESC LIMIT ? OFFSET ?",
        tuple(params) + (limit, offset),
    )
    try:
        events = [json.loads(dict(row)["payload_json"]) for row in cursor.fetchall()]
    finally:
        cursor.close()
    return {"events": events, "total": total, "limit": limit, "offset": offset,
            "hasMore": offset + len(events) < total}
