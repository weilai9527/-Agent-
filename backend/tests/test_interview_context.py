from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap


def test_resume_context_is_separate_from_short_focus_area(tmp_path):
    project_dir = Path(__file__).resolve().parents[2]
    database_path = tmp_path / "interview-context.sqlite"
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
            json={"email": "context-test@example.com", "password": "Password123!"},
        )
        assert registered.status_code == 201, registered.text

        long_context = "项目背景与技术亮点。" * 400
        created = client.post(
            "/api/interviews",
            json={
                "target_role": "后端开发工程师",
                "focus_areas": "项目深挖",
                "resume_context": long_context,
            },
        )
        assert created.status_code == 201, created.text
        interview = created.json()["interview"]
        assert interview["focus_areas"] == "项目深挖"
        assert interview["resume_context"] == long_context

        exact_focus_limit = client.post(
            "/api/interviews",
            json={
                "target_role": "后端开发工程师",
                "focus_areas": "重" * 500,
                "resume_context": long_context,
            },
        )
        assert exact_focus_limit.status_code == 201, exact_focus_limit.text

        over_focus_limit = client.post(
            "/api/interviews",
            json={
                "target_role": "后端开发工程师",
                "focus_areas": "重" * 501,
                "resume_context": long_context,
            },
        )
        assert over_focus_limit.status_code == 400, over_focus_limit.text
        assert "500" in over_focus_limit.text

        too_long = client.post(
            "/api/interviews",
            json={
                "target_role": "后端开发工程师",
                "focus_areas": "项目深挖",
                "resume_context": "字" * 12001,
            },
        )
        assert too_long.status_code == 400, too_long.text
        assert "12,000" in too_long.text or "12000" in too_long.text
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
