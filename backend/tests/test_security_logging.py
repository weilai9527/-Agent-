from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import textwrap
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from shared import security_logging as security


@pytest.fixture
def harness(monkeypatch):
    emitted, stored = [], []
    monkeypatch.setattr(security, "emit", lambda event, level=logging.INFO: emitted.append(dict(event)))
    store = SimpleNamespace(write=lambda event: stored.append(dict(event)))
    app = FastAPI()
    app.add_middleware(security.RequestLoggingMiddleware, service="test-api", audit_store=store)
    app.add_middleware(CORSMiddleware, allow_origins=["https://client.test"], expose_headers=["X-Request-ID"])
    return app, emitted, stored, store


def test_sensitive_inputs_are_not_logged_and_caller_cannot_forge_id(harness):
    app, emitted, stored, _ = harness

    @app.post("/resource/{resource_id}")
    def denied(resource_id: str, request: Request):
        security.bind_actor(request, {"id": "student-1"}, "student")
        security.audit_context(request, reason="scope_denied")
        raise HTTPException(403, "not allowed")

    response = TestClient(app).post(
        "/resource/record-1?token=secret-query", json={"password": "secret-body"},
        headers={"Authorization": "Bearer secret-auth", "Cookie": "session=secret-cookie",
                 "X-Request-ID": "forged-request-id", "Origin": "https://client.test"},
    )
    assert response.status_code == 403
    event = stored[0]
    assert event["request_id"] == response.headers["x-request-id"] != "forged-request-id"
    assert "X-Request-ID" in response.headers["access-control-expose-headers"]
    assert event["actor_id"] == "student-1"
    assert event["targets"] == {"resource_id": "record-1"}
    assert event["route"] == "/resource/{resource_id}"
    assert event["event_type"] == "security.access_denied"
    assert event["reason"] == "scope_denied"
    assert not event["success"]
    assert "secret-" not in json.dumps(emitted)
    assert len({e["request_id"] for e in emitted}) == 1


def test_unhandled_exception_has_safe_stack_and_cors(harness):
    app, emitted, stored, _ = harness

    @app.get("/explode")
    def explode():
        raise RuntimeError("password=secret-value; raw SQL payload")

    response = TestClient(app).get("/explode", headers={"Origin": "https://client.test"})
    assert response.status_code == 500
    assert response.json()["requestId"] == response.headers["x-request-id"]
    assert response.headers["access-control-allow-origin"] == "https://client.test"
    details = next(e for e in emitted if e["event_type"] == "http.exception")
    assert details["error_type"] == "builtins.RuntimeError"
    assert any(frame["function"] == "explode" for frame in details["frames"])
    assert "secret-value" not in json.dumps(emitted) + response.text
    assert stored[0]["event_type"] == "operation.failed"


def test_audit_database_failure_preserves_response_and_fallback_evidence(harness):
    app, emitted, _, store = harness

    def unavailable(event):
        raise RuntimeError("mysql_password=secret-database-password")

    store.write = unavailable

    @app.post("/api/auth/login")
    def login():
        return {"ok": True}

    response = TestClient(app).post("/api/auth/login")
    assert response.status_code == 200
    event = next(e for e in emitted if e["event_type"] == "student.login")
    fallback = next(e for e in emitted if e["event_type"] == "security.audit_persist_failed")
    assert event["event_id"] == fallback["event_id"]
    assert fallback["request_id"] == response.headers["x-request-id"]
    assert "secret-database-password" not in json.dumps(emitted)


def test_stream_is_not_buffered_and_incomplete_stream_is_reported(harness):
    app, emitted, stored, _ = harness

    @app.get("/stream")
    def stream():
        def chunks():
            yield b"first"
            raise RuntimeError("secret-stream-error")
        return StreamingResponse(chunks())

    sent = []
    async def receive():
        await asyncio.sleep(100)
    async def send(message):
        sent.append(message)
    scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"},
             "http_version": "1.1", "method": "GET", "path": "/stream", "raw_path": b"/stream",
             "query_string": b"", "headers": [], "scheme": "http", "client": ("127.0.0.1", 1),
             "server": ("test", 80)}
    with pytest.raises(RuntimeError):
        asyncio.run(app(scope, receive, send))
    assert any(m.get("body") == b"first" for m in sent)
    assert len([m for m in sent if m["type"] == "http.response.start"]) == 1
    assert stored[0]["status_code"] == 200
    assert stored[0]["response_complete"] is False
    assert stored[0]["success"] is False


def test_concurrent_requests_keep_actor_and_id_separate(harness):
    app, _, stored, _ = harness

    @app.post("/api/auth/login")
    async def login(request: Request):
        data = await request.json()
        security.bind_actor(request, {"id": data["id"]}, "student")
        await asyncio.sleep(0.01)
        return {"ok": True}

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
            return await asyncio.gather(*(client.post("/api/auth/login", json={"id": str(i)}) for i in range(12)))

    responses = asyncio.run(run())
    assert len(stored) == 12
    assert len({e["request_id"] for e in stored}) == 12
    assert {e["actor_id"]: e["request_id"] for e in stored} == {
        str(i): response.headers["x-request-id"] for i, response in enumerate(responses)
    }


@pytest.mark.parametrize("status", [400, 401, 403, 422, 429, 503])
def test_failed_mutations_are_audited(harness, status):
    app, _, stored, _ = harness
    @app.post("/operation")
    def operation():
        raise HTTPException(status)
    assert TestClient(app).post("/operation").status_code == status
    assert stored[0]["status_code"] == status
    assert not stored[0]["success"]


def test_database_store_is_independent_and_schema_is_additive(tmp_path):
    @dataclass
    class Config:
        database: str = "unused"

    path = tmp_path / "audit.sqlite"
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("CREATE TABLE existing_records (value TEXT)")
    db.execute("INSERT INTO existing_records VALUES ('preserve-me')")
    db.commit()
    security.ensure_security_schema(db, "sqlite")
    security.ensure_security_schema(db, "sqlite")
    store = security.SecurityAuditStore(SimpleNamespace(DB_ENGINE="sqlite", SQLITE_PATH=path, config=Config()))
    event = {"event_id": "event-1", "occurred_at": "2026-09-28T00:00:00.000Z", "service": "test",
             "event_type": "student.login", "request_id": "a" * 32, "status_code": 401}
    store.write(event)
    result = security.list_security_events(db, request_id="a" * 32)
    assert result["events"] == [event]
    assert result["total"] == 1
    assert not security.list_security_events(db, request_id="' OR 1=1 --")["events"]
    assert db.execute("SELECT value FROM existing_records").fetchone()[0] == "preserve-me"
    db.execute("INSERT INTO existing_records VALUES ('uncommitted-business-write')")
    with pytest.raises(sqlite3.OperationalError):
        store.write({**event, "event_id": "locked-event"})
    db.rollback()
    assert db.execute("SELECT COUNT(*) FROM existing_records").fetchone()[0] == 1
    assert db.execute("SELECT COUNT(*) FROM security_audit_events").fetchone()[0] == 1
    db.close()


def test_real_student_and_admin_audit_flow(tmp_path):
    project = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env.update({"APP_ENV": "production", "DB_ENGINE": "sqlite", "SQLITE_PATH": str(tmp_path / "flow.sqlite"),
                "PASSWORD_RESET_ENABLED": "false", "COOKIE_SECURE": "false", "ADMIN_COOKIE_SECURE": "false",
                "ADMIN_MASTER_EMAIL": "audit-root@example.com", "ADMIN_MASTER_PASSWORD": "AuditRoot123!"})
    script = textwrap.dedent('''
        import json
        from uuid import uuid4
        from fastapi.testclient import TestClient
        import backend.src.main as main
        import admin_backend.src.main as admin
        uid = str(uuid4())
        with main.db:
            main.db.execute("INSERT INTO users (id,email,student_no,password_hash,name,must_change_password,status) VALUES (?,?,?,?,?,1,'normal')",
                (uid,'20260101@student.local','20260101',main.hash_password('TempSecret123!'),'audit-test')).close()
        student = TestClient(main.app)
        failure = student.post('/api/auth/login',json={'student_no':'20260101','password':'WrongSecret123!'})
        assert failure.status_code == 401
        logged = student.post('/api/auth/login',json={'student_no':'20260101','password':'TempSecret123!'})
        assert logged.status_code == 200
        assert student.get('/api/profile').status_code == 403
        changed = student.post('/api/auth/change-initial-password',json={'password':'NewSecret123!','confirm_password':'NewSecret123!'})
        assert changed.status_code == 200
        assert student.post('/api/auth/logout').status_code == 200
        main.PASSWORD_RESET_ENABLED = True
        main.send_password_reset_email = lambda email,token: False
        mail_failure=student.post('/api/auth/password-reset/request',json={'email':'20260101@student.local'})
        assert mail_failure.status_code==200
        mail_event=json.loads(main.one('SELECT payload_json FROM security_audit_events WHERE request_id=?',(mail_failure.headers['x-request-id'],))['payload_json'])
        assert not mail_event['success'] and mail_event['reason']=='reset_mail_not_configured'
        tokens=[]
        main.send_password_reset_email = lambda email,token: tokens.append(token) or True
        assert student.post('/api/auth/password-reset/request',json={'email':'20260101@student.local'}).status_code==200
        assert student.post('/api/auth/password-reset/verify',json={'token':tokens[0]}).status_code==200
        reset=student.post('/api/auth/password-reset/confirm',json={'token':tokens[0],'password':'ResetSecret123!','confirm_password':'ResetSecret123!'})
        assert reset.status_code==200
        rows = main.all_rows('SELECT payload_json FROM security_audit_events ORDER BY occurred_at,id')
        events = [json.loads(row['payload_json']) for row in rows]
        assert {e['event_type'] for e in events} >= {'student.login','student.logout','student.password_change','security.access_denied'}
        assert any(e.get('actor_id') == uid and e['event_type']=='student.logout' for e in events)
        assert any(e['request_id']==failure.headers['x-request-id'] and not e['success'] for e in events)
        assert 'Secret123!' not in json.dumps(events)
        assert tokens[0] not in json.dumps(events)
        assert any(e.get('actor_id')==uid and e['event_type']=='student.password_reset' for e in events)
        root = TestClient(admin.app)
        assert root.get('/api/admin/security-logs').status_code == 401
        assert root.post('/api/admin/auth/login',headers={'Origin':'http://127.0.0.1:5174'},json={'email':'audit-root@example.com','password':'AuditRoot123!'}).status_code==200
        queried = root.get('/api/admin/security-logs',params={'request_id':failure.headers['x-request-id']})
        assert queried.status_code==200, queried.text
        assert queried.json()['total']==1
        assert queried.json()['events'][0]['attempted_account']=='20260101'
        refreshed = root.get('/api/admin/security-logs', params={'limit':50,'offset':0,'until':'2099-01-01T00:00:00.000Z'})
        assert refreshed.status_code == 200, refreshed.text
        assert refreshed.json()['total'] > 0
        page = root.get('/api/admin/security-logs',params={'limit':1,'event_type':'student.login'}).json()
        assert page['total']==2 and page['hasMore']
        page2 = root.get('/api/admin/security-logs',params={'limit':1,'offset':1,'event_type':'student.login'}).json()
        assert len(page2['events'])==1 and not page2['hasMore']
        assert page2['events'][0]['event_id']!=page['events'][0]['event_id']
        assert root.get('/api/admin/security-logs',params={'since':'2026-09-28T00:00:00'}).status_code==400
        assert root.get('/api/admin/security-logs',params={'limit':201}).status_code==422
        created = root.post('/api/admin/users',headers={'Origin':'http://127.0.0.1:5174'},json={'email':'auditor@example.com','password':'AuditorPassword123!','name':'auditor','role':'reviewer','permissions':[]})
        assert created.status_code==201,created.text
        limited=TestClient(admin.app)
        assert limited.post('/api/admin/auth/login',headers={'Origin':'http://127.0.0.1:5174'},json={'email':'auditor@example.com','password':'AuditorPassword123!'}).status_code==200
        denied=limited.get('/api/admin/security-logs')
        assert denied.status_code==403
        check=root.get('/api/admin/security-logs',params={'request_id':denied.headers['x-request-id']}).json()
        assert check['events'][0]['event_type']=='security.access_denied'
        assert check['events'][0]['actor_type']=='admin'
        assert check['events'][0]['actor_id']
    ''')
    result = subprocess.run([sys.executable, "-c", script], cwd=project, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
