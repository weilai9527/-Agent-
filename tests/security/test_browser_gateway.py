import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.gateway import routes
from shared import security_logging
from shared.service_http import service_origin
from fastapi import HTTPException
import pytest


def test_gateway_routes_delegate_one_action_and_never_expose_system_commands(monkeypatch):
    actor = {"actor_id": "t1", "actor_type": "teacher", "school_id": "school-a"}
    calls = []

    def session(request, scope):
        if request.cookies.get("test_session") != "valid":
            raise HTTPException(401)
        return actor

    async def transport(service, method, path, **kwargs):
        calls.append((service, method, path, kwargs["actor"], kwargs["scope"], kwargs["body"]))
        return httpx.Response(201, json={"task_id": "created"})

    monkeypatch.setattr(routes, "admin_gateway_context", session)
    monkeypatch.setattr(routes, "service_request", transport)
    app = FastAPI()
    events = []
    monkeypatch.setattr(security_logging, "emit", lambda event, *args: events.append(event))
    app.add_middleware(security_logging.RequestLoggingMiddleware, service="admin-gateway")
    routes.mount_business_routes(app, staff=True, origins=["https://staff.example.test"])
    client = TestClient(app)
    headers = {"Origin": "https://staff.example.test", "X-School-ID": "other", "X-Actor-Type": "admin"}
    url = "/api/admin/training/tasks"
    assert client.post(url, json={}, headers=headers).status_code == 401
    client.cookies.set("test_session", "valid")
    for bad_origin in ({}, {"Origin": "https://evil.example.test"}):
        assert client.post(url, json={}, headers=bad_origin).status_code == 403
    assert client.post(url, content="{}", headers=headers).status_code == 415
    assert client.post("/api/admin/training/attempts/id/complete", headers=headers, json={}).status_code == 404
    reply = client.post(url, json={"title": "T"}, headers=headers)
    assert reply.status_code == 201 and reply.headers["cache-control"] == "no-store"
    assert calls == [("training", "POST", "/tasks", actor, "training.assign", {"title": "T"})]
    audit = next(e for e in events if e["event_type"] == "training.assign" and e["success"])
    assert (audit["actor_id"], audit["school_id"], audit["actor_type"]) == ("t1", "school-a", "teacher")
    assert "title" not in str(events) and "test_session" not in str(events)


@pytest.mark.parametrize("origin", [
    "http://public.example.test", "https://user:pass@example.test", "https://example.test/private",
    "https://example.test?key=bad", "https://example.test#fragment", "",
])
def test_gateway_rejects_unsafe_service_origins(monkeypatch, origin):
    monkeypatch.setenv("TRAINING_SERVICE_URL", origin)
    with pytest.raises(HTTPException) as denied:
        service_origin("training")
    assert denied.value.status_code == 503
