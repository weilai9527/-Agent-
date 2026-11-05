"""启动测试只使用临时配置库；验证导入图、应急边界和测试夹具许可。"""
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from services.providers.app import app


def test_native_entry_works_without_legacy_sources(tmp_path):
    env = {"PATH": os.defpath, "SERVICE_ID": "providers", "PROVIDERS_DB_ENGINE": "sqlite",
           "PROVIDERS_SQLITE_PATH": str(tmp_path / "providers.sqlite")}
    code = """
import importlib.abc
import sys
class NoLegacy(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname.partition('.')[0] in {'backend', 'admin_backend'}:
            raise AssertionError(fullname)
sys.meta_path.insert(0, NoLegacy())
from fastapi.testclient import TestClient
from services.providers.app import app
with TestClient(app) as client:
    assert client.get('/settings').status_code == 401
"""
    subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[2],
                   env=env, check=True, timeout=25)


def test_missing_owner_database_refuses_startup():
    with patch.dict(os.environ, {"SERVICE_ID": "providers", "PROVIDERS_SERVICE_URL": "https://other.test"}, clear=True):
        with pytest.raises(HTTPException) as unavailable, TestClient(app):
            pass
        assert unavailable.value.status_code == 503


@pytest.mark.parametrize(("name", "value"), [("IDENTITY_SESSION_MODE", "legacy"), ("ASSESSMENT_STORAGE_MODE", "shared")])
def test_wrong_runtime_fails_before_opening_database(tmp_path, name, value):
    path = tmp_path / "must-not-exist.sqlite"
    env = {"SERVICE_ID": "providers", "PROVIDERS_DB_ENGINE": "sqlite", "PROVIDERS_SQLITE_PATH": str(path),
           name: value}
    with patch.dict(os.environ, env, clear=True), pytest.raises(ValueError), TestClient(app):
        pass
    assert not path.exists()
