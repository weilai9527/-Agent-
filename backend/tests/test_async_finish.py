from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap


def test_finish_queues_report_without_running_ai_inline(tmp_path):
    project_dir = Path(__file__).resolve().parents[2]
    database_path = tmp_path / "async-finish.sqlite"
    environment = os.environ.copy()
    environment.update({"APP_ENV": "test", "DB_ENGINE": "sqlite", "SQLITE_PATH": str(database_path)})
    script = textwrap.dedent(
        """
        from fastapi import BackgroundTasks
        from fastapi.testclient import TestClient
        import backend.src.main as main

        client = TestClient(main.app)
        registered = client.post(
            "/api/auth/register",
            json={"email": "async-finish@example.com", "password": "Password123!"},
        )
        assert registered.status_code == 201, registered.text
        user = main.one("SELECT * FROM users WHERE email = ?", ("async-finish@example.com",))

        created = client.post("/api/interviews", json={"target_role": "RTC Engineer"})
        assert created.status_code == 201, created.text
        interview_id = created.json()["interview"]["id"]
        answered = client.post(
            f"/api/interviews/{interview_id}/messages",
            json={"sender_type": "candidate", "message_type": "answer", "content": "I used an idempotent queue."},
        )
        assert answered.status_code == 201, answered.text

        def unexpected_inline_generation(*_, **__):
            raise AssertionError("finish must not generate the AI report inline")

        main.generate_ai_report = unexpected_inline_generation
        background_tasks = BackgroundTasks()
        result = main.finish_interview(interview_id, background_tasks, user)

        assert result["interview"]["status"] == "completed"
        assert result["report"]["generation_status"] == "queued"
        assert len(background_tasks.tasks) == 1
        queued = client.get(f"/api/interviews/{interview_id}/report")
        assert queued.status_code == 200, queued.text
        assert queued.json()["report"]["generation_status"] == "queued"

        repeated_tasks = BackgroundTasks()
        repeated = main.finish_interview(interview_id, repeated_tasks, user)
        assert repeated["report"]["id"] == result["report"]["id"]
        assert len(repeated_tasks.tasks) == 0

        main.generate_ai_report = lambda **kwargs: kwargs["fallback_report"]
        main.generate_report_after_finish(interview_id, user)
        completed = client.get(f"/api/interviews/{interview_id}/report")
        assert completed.status_code == 200, completed.text
        assert completed.json()["report"]["generation_status"] != "queued"
        reports = client.get("/api/reports")
        assert reports.status_code == 200, reports.text
        assert any(item["interview_id"] == interview_id for item in reports.json()["reports"])
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
