from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap


def test_uploaded_resume_filename_is_persisted_and_profile_updates_do_not_clear_it(tmp_path):
    project_dir = Path(__file__).resolve().parents[2]
    database_path = tmp_path / "resume-upload.sqlite"
    environment = os.environ.copy()
    environment.update(
        {
            "APP_ENV": "test",
            "DB_ENGINE": "sqlite",
            "SQLITE_PATH": str(database_path),
        }
    )
    script = textwrap.dedent(
        """
        from fastapi.testclient import TestClient
        from backend.src.main import app

        client = TestClient(app)
        registered = client.post(
            "/api/auth/register",
            json={"email": "resume-upload@example.com", "password": "Password123!"},
        )
        assert registered.status_code == 201, registered.text

        uploaded = client.post(
            "/api/profile/resume-upload",
            files={"file": ("candidate-resume.txt", "Python 后端项目与系统设计经验", "text/plain")},
        )
        assert uploaded.status_code == 200, uploaded.text
        payload = uploaded.json()
        assert payload["filename"] == "candidate-resume.txt"
        assert payload["profile"]["resume_filename"] == "candidate-resume.txt"

        saved = client.put("/api/profile", json=payload["profile"])
        assert saved.status_code == 200, saved.text
        assert saved.json()["profile"]["resume_filename"] == "candidate-resume.txt"

        reloaded = client.get("/api/profile")
        assert reloaded.status_code == 200, reloaded.text
        assert reloaded.json()["profile"]["resume_filename"] == "candidate-resume.txt"
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=project_dir,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
