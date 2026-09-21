from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap


def test_student_number_login_requires_initial_password_change(tmp_path):
    project_dir = Path(__file__).resolve().parents[2]
    database_path = tmp_path / "student-auth.sqlite"
    environment = os.environ.copy()
    environment.update({"APP_ENV": "production", "DB_ENGINE": "sqlite", "SQLITE_PATH": str(database_path)})
    script = textwrap.dedent(
        '''
        from uuid import uuid4
        from fastapi.testclient import TestClient
        import backend.src.main as main

        user_id = str(uuid4())
        with main.db:
            main.db.execute(
                """
                INSERT INTO users (
                  id, email, student_no, password_hash, name, must_change_password,
                  temp_password_encrypted, status
                ) VALUES (?, ?, ?, ?, ?, 1, ?, 'normal')
                """,
                (user_id, "20260001@student.local", "20260001", main.hash_password("TempPass234"), "测试学生", "encrypted-placeholder"),
            ).close()
            main.db.execute(
                "INSERT INTO profiles (id, user_id, nickname) VALUES (?, ?, ?)",
                (str(uuid4()), user_id, "测试学生"),
            ).close()

        client = TestClient(main.app)
        closed = client.post(
            "/api/auth/register",
            json={"email": "new@example.com", "password": "Password123!"},
        )
        assert closed.status_code == 403, closed.text

        logged_in = client.post(
            "/api/auth/login",
            json={"student_no": "20260001", "password": "TempPass234"},
        )
        assert logged_in.status_code == 200, logged_in.text
        assert logged_in.json()["user"]["studentNo"] == "20260001"
        assert logged_in.json()["user"]["mustChangePassword"] is True

        blocked = client.get("/api/profile")
        assert blocked.status_code == 403, blocked.text

        changed = client.post(
            "/api/auth/change-initial-password",
            json={"password": "NewPassword456!", "confirm_password": "NewPassword456!"},
        )
        assert changed.status_code == 200, changed.text
        assert changed.json()["user"]["mustChangePassword"] is False

        row = main.one(
            "SELECT must_change_password, temp_password_encrypted, temp_password_created_at FROM users WHERE id = ?",
            (user_id,),
        )
        assert row["must_change_password"] == 0
        assert row["temp_password_encrypted"] is None
        assert row["temp_password_created_at"] is None
        assert client.get("/api/profile").status_code == 200

        client.post("/api/auth/logout")
        old_password = client.post(
            "/api/auth/login",
            json={"student_no": "20260001", "password": "TempPass234"},
        )
        assert old_password.status_code == 401
        new_password = client.post(
            "/api/auth/login",
            json={"student_no": "20260001", "password": "NewPassword456!"},
        )
        assert new_password.status_code == 200, new_password.text
        '''
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=project_dir,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
