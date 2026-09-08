from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap


def test_webrtc_diagnostics_are_sanitized_and_expire(tmp_path):
    project_dir = Path(__file__).resolve().parents[2]
    database_path = tmp_path / "webrtc-diagnostics.sqlite"
    environment = os.environ.copy()
    environment.update(
        {
            "APP_ENV": "test",
            "DB_ENGINE": "sqlite",
            "SQLITE_PATH": str(database_path),
            "WEBRTC_DIAGNOSTIC_RETENTION_DAYS": "7",
            "WEBRTC_DIAGNOSTIC_CLEANUP_INTERVAL_SECONDS": "60",
        }
    )
    script = textwrap.dedent(
        """
        from fastapi.testclient import TestClient
        import backend.src.main as main

        client = TestClient(main.app)
        registered = client.post(
            "/api/auth/register",
            json={"email": "webrtc-log@example.com", "password": "Password123!"},
        )
        assert registered.status_code == 201, registered.text

        created = client.post(
            "/api/interviews",
            json={"target_role": "后端开发工程师"},
        )
        assert created.status_code == 201, created.text
        interview_id = created.json()["interview"]["id"]

        logged = client.post(
            f"/api/interviews/{interview_id}/webrtc-events",
            json={
                "session_id": "session-test",
                "event_type": "connection_state_changed",
                "level": "warning",
                "connection_state": "disconnected",
                "ice_connection_state": "disconnected",
                "message": "temporary disconnect",
                "metadata": {
                    "phase": "ice",
                    "elapsed_ms": 321,
                    "sdp": "must-not-be-stored",
                    "api_key": "must-not-be-stored",
                },
                "client_created_at": "2026-07-28T06:00:00.000Z",
            },
        )
        assert logged.status_code == 201, logged.text
        assert logged.json()["event"]["retentionDays"] == 7

        listed = client.get(f"/api/interviews/{interview_id}/webrtc-events")
        assert listed.status_code == 200, listed.text
        events = listed.json()["events"]
        assert len(events) == 1
        assert events[0]["event_type"] == "connection_state_changed"
        assert events[0]["metadata"] == {"phase": "ice", "elapsed_ms": 321}

        cursor = main.db.execute(
            "UPDATE webrtc_diagnostic_events SET created_at = datetime('now', '-30 days') WHERE id = ?",
            (events[0]["id"],),
        )
        cursor.close()
        main.db.commit()
        deleted = main.cleanup_webrtc_diagnostic_events(force=True)
        assert deleted == 1

        listed_after_cleanup = client.get(f"/api/interviews/{interview_id}/webrtc-events")
        assert listed_after_cleanup.status_code == 200
        assert listed_after_cleanup.json()["events"] == []
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
