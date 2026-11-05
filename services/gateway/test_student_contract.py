"""已登录学生的路由契约。所有 HTTP 传输都在进程内替换，测试不连接数据库或网络。"""
from unittest.mock import patch

from fastapi.testclient import TestClient
import httpx

from services.gateway import native_student


def test_student_routes_are_remote_even_without_an_owner(monkeypatch):
    monkeypatch.setenv("IDENTITY_SESSION_MODE", "native")
    monkeypatch.setenv("FRONTEND_ORIGIN", "https://school.example.test")
    monkeypatch.delenv("ASSESSMENT_SERVICE_URL", raising=False)
    monkeypatch.delenv("TRAINING_SERVICE_URL", raising=False)
    seen = []

    def student(request, scope, role):
        seen.append((request.url.path, scope, role))
        return {"actor_id": "s", "actor_type": "student", "school_id": "school", "scopes": [scope]}

    monkeypatch.setattr(native_student, "resolve_native", student)
    client = TestClient(native_student.create_app(), base_url="https://school.example.test")
    for path, scope in (("/api/reports", "assessment.read"), ("/api/training/tasks", "training.read")):
        result = client.get(path)
        assert result.status_code == 503 and result.headers["cache-control"] == "no-store"
        assert seen[-1] == (path, scope, "student")
    count = len(seen)
    rejected = client.post("/api/training/tasks/one/attempts", headers={"Origin": "https://untrusted.test"}, json={})
    assert rejected.status_code == 403 and len(seen) == count
    for path in ("/api/admin/reports", "/internal/interviews/guess/media-context"):
        assert client.get(path).status_code == 404 and len(seen) == count

    monkeypatch.setenv("ASSESSMENT_SERVICE_URL", "https://assessment.example.test")
    with patch("shared.service_http.service_headers", return_value={"Authorization": "Bearer synthetic"}):
        async def response(_transport, request):
            assert request.url.path == "/api/reports/missing"
            assert request.headers["Authorization"] == "Bearer synthetic" and "cookie" not in request.headers
            return httpx.Response(404, request=request, json={"detail": "报告不存在。"})

        with patch.object(httpx.AsyncHTTPTransport, "handle_async_request", response):
            missing = client.get("/api/reports/missing")
        assert missing.status_code == 404 and missing.json()["error"] == "报告不存在。"


def test_invalid_auth_body_does_not_echo_credentials(monkeypatch):
    monkeypatch.setenv("IDENTITY_SESSION_MODE", "native")
    with TestClient(native_student.create_app()) as client:
        invalid = client.post("/api/auth/login", json=["合成密码-不应回显"])
        assert invalid.status_code == 422 and "合成密码" not in invalid.text
        assert invalid.headers["cache-control"] == "no-store"
