"""Administrator bootstrap must use explicit configuration, never default credentials."""
import os
from pathlib import Path
import subprocess
import sys

from cryptography.fernet import Fernet
import pytest


@pytest.mark.parametrize("mode", ["missing", "missing_email", "missing_password", "short_password", "master", "legacy"])
def test_admin_bootstrap_requires_explicit_credentials(tmp_path, mode):
    email = "bootstrap-test@example.test"
    password = "SyntheticBootstrapPassword123!"
    env = {
        **os.environ,
        "DB_ENGINE": "sqlite",
        "SQLITE_PATH": str(tmp_path / "bootstrap.sqlite"),
        "APP_ENV": "production",
        "PYTHONUTF8": "1",
        "ADMIN_COOKIE_SECURE": "false",
        "STUDENT_TEMP_PASSWORD_KEY": Fernet.generate_key().decode("ascii"),
        # Empty values also prevent ignored local .env files from filling these in.
        "ADMIN_MASTER_EMAIL": "",
        "ADMIN_MASTER_PASSWORD": "",
        "ADMIN_BOOTSTRAP_EMAIL": "",
        "ADMIN_BOOTSTRAP_PASSWORD": "",
    }
    if mode != "missing":
        prefix = "ADMIN_BOOTSTRAP" if mode == "legacy" else "ADMIN_MASTER"
        env[f"{prefix}_EMAIL"] = "" if mode == "missing_email" else email
        env[f"{prefix}_PASSWORD"] = "" if mode == "missing_password" else "short" if mode == "short_password" else password
    if mode == "master":
        env["ADMIN_BOOTSTRAP_EMAIL"] = "ignored-legacy@example.test"
        env["ADMIN_BOOTSTRAP_PASSWORD"] = "IgnoredLegacyPassword123!"

    success = mode in {"master", "legacy"}
    script = "from admin_backend.src import main\n"
    if success:
        script += (
            "from fastapi.testclient import TestClient\n"
            "client = TestClient(main.app)\n"
            f"assert main.MASTER_ADMIN_EMAIL == {email!r}\n"
            "response = client.post('/api/admin/auth/login', "
            "headers={'Origin': 'http://127.0.0.1:5174'}, "
            f"json={{'email': {email!r}, 'password': {password!r}}})\n"
            "assert response.status_code == 200, response.text\n"
        )
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=Path(__file__).resolve().parents[2],
        env=env, capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    if success:
        assert result.returncode == 0, result.stdout + result.stderr
    else:
        assert result.returncode != 0
        assert "主管理员配置无效" in result.stderr
