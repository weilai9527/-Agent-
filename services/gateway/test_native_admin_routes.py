"""验证原生管理入口的路由白名单、进程隔离及平台权限。"""
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import AsyncMock

from fastapi import HTTPException
from fastapi.testclient import TestClient

from services.gateway import native_admin


def test_clean_process_never_imports_a_database_owner(tmp_path):
    script = r"""
import sys
def guard(event, args):
    if event == 'sqlite3.connect':
        raise RuntimeError('native gateway opened SQLite')
    if event == 'import' and args[0] in {'pymysql', 'admin_backend.src.main', 'admin_backend.src.database',
                                         'backend.src.main', 'backend.src.database'}:
        raise RuntimeError('native gateway imported '+args[0])
sys.addaudithook(guard)
from services.gateway.admin import app
from fastapi.testclient import TestClient
with TestClient(app) as client:
    assert client.get('/api/admin/health').json()['service'] == 'admin-gateway'
    # /snapshot proxies /me. Missing service credentials must fail closed.
    assert client.get('/api/admin/snapshot').status_code == 503
    for path in ('/identity/v1/organization','/training/tasks','/analytics/v1/teaching/summary',
                 '/reports/r/history','/reports/r/export','/interview/v1/records','/assessment/v1/records/r',
                 '/credentials/students/s/applications',
                 '/usage/quota','/catalog/tree','/job-postings/export','/job-matches','/jd-submissions','/settings'):
        response = client.get('/api/admin' + path)
        assert response.status_code == 401, (path, response.status_code, response.text)
    assert client.get('/internal/sessions/staff/resolve').status_code == 404
    assert client.post('/api/admin/identity/internal/staff/record-students',json={}).status_code == 404
    assert client.patch('/api/admin/settings',json={},headers={'Origin':'https://other.test'}).status_code == 403
assert not ({'backend.src.main','backend.src.database','admin_backend.src.main','admin_backend.src.database'} & sys.modules.keys())
"""
    env = {k: v for k, v in os.environ.items() if k in {"PATH", "PYTHONPATH"}}
    env.update(IDENTITY_SESSION_MODE="native", LEGACY_SCHOOL_ID="school", IDENTITY_SERVICE_URL="https://identity.test",
               PYTHONDONTWRITEBYTECODE="1")
    source = Path(__file__).resolve().parents[2]
    run = subprocess.run([sys.executable, "-c", script], cwd=source, env=env,
                         capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stderr


def test_model_control_delegates_platform_only(monkeypatch):
    monkeypatch.setenv("IDENTITY_SESSION_MODE", "native")
    monkeypatch.setenv("ADMIN_FRONTEND_ORIGIN", "https://admin.test")
    monkeypatch.setenv("PROVIDER_PLATFORM_ADMIN_IDS", "operator")
    actor = {"actor_id": "operator", "actor_type": "admin", "school_id": "school"}
    grants = {"model.config.read", "model.config.write"}

    def resolve(request, scope):
        if scope not in grants:
            raise HTTPException(403, "Revoked")
        return {**actor, "scopes": [scope]}

    monkeypatch.setattr(native_admin, "admin_gateway_context", resolve)
    peer = AsyncMock(return_value={"reportTimeout": 25})
    monkeypatch.setattr(native_admin, "request_json", peer)
    with TestClient(native_admin.create_app(), headers={"Origin":"https://admin.test"}) as client:
        path = "/api/admin/settings"
        assert client.get(path, headers={"X-School-ID":"platform"}).status_code == 403
        peer.assert_not_called()
        actor["school_id"] = "platform"
        actor["actor_id"] = "another"
        assert client.get(path).status_code == 403
        actor["actor_id"] = "operator"
        assert client.get(path).json() == {"reportTimeout":25}
        assert peer.await_args.kwargs["scope"] == "providers.read"
        assert client.patch(path, json={"reportOpenaiApiKey":"fake"}).status_code == 400
        assert client.patch(path, json={"reportTimeout":25}).status_code == 200
        assert peer.await_args.kwargs["scope"] == "providers.configure"
        grants.remove("model.config.write")
        assert client.patch(path, json={"reportTimeout":10}).status_code == 403
        assert client.post(path + "/report-providers/test").status_code == 403
        assert peer.await_count == 2
