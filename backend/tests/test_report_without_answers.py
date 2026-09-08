from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap


def test_report_without_candidate_answers_is_not_scored_or_sent_to_ai(tmp_path):
    project_dir = Path(__file__).resolve().parents[2]
    database_path = tmp_path / "report-without-answers.sqlite"
    environment = os.environ.copy()
    environment.update({"APP_ENV": "test", "DB_ENGINE": "sqlite", "SQLITE_PATH": str(database_path)})
    script = textwrap.dedent(
        """
        from fastapi.testclient import TestClient
        import backend.src.main as main

        client = TestClient(main.app)
        registered = client.post(
            "/api/auth/register",
            json={"email": "no-answers@example.com", "password": "Password123!"},
        )
        assert registered.status_code == 201, registered.text

        created = client.post(
            "/api/interviews",
            json={"target_role": "前端工程师", "focus_areas": "项目深挖"},
        )
        assert created.status_code == 201, created.text
        interview_id = created.json()["interview"]["id"]
        finished = client.post(f"/api/interviews/{interview_id}/finish")
        assert finished.status_code == 200, finished.text

        def unexpected_ai_call(**_):
            raise AssertionError("没有候选人回答时不应调用 AI 生成报告")

        main.generate_ai_report = unexpected_ai_call
        generated = client.post(f"/api/interviews/{interview_id}/report")
        assert generated.status_code == 201, generated.text
        report = generated.json()["report"]
        assert report["generation_status"] == "insufficient_evidence"
        assert report["pass_recommendation"] == "insufficient_evidence"
        assert report["total_score"] == 0
        assert report["grade"] == "-"
        assert report["provider"] == "local"
        assert report["model"] == "evidence-check-v1"
        assert report["ability_radar"] == "{}"
        assert report["timeline_review"] == "[]"
        assert "未记录到候选人回答" in report["summary"]

        stats = client.get("/api/stats/me")
        assert stats.status_code == 200, stats.text
        assert stats.json()["stats"]["average_total_score"] == 0
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
