from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap

from cryptography.fernet import Fernet


def test_admin_imports_reveals_exports_and_clears_temporary_passwords(tmp_path):
    project_dir = Path(__file__).resolve().parents[2]
    database_path = tmp_path / "student-accounts.sqlite"
    environment = os.environ.copy()
    environment.update(
        {
            "APP_ENV": "production",
            "DB_ENGINE": "sqlite",
            "SQLITE_PATH": str(database_path),
            "ADMIN_BOOTSTRAP_EMAIL": "root@example.com",
            "ADMIN_BOOTSTRAP_PASSWORD": "RootAdminPassword123!",
            "ADMIN_BOOTSTRAP_ROLE": "super_admin",
            "ADMIN_COOKIE_SECURE": "false",
            "STUDENT_TEMP_PASSWORD_KEY": Fernet.generate_key().decode("ascii"),
        }
    )
    script = textwrap.dedent(
        '''
        from io import BytesIO
        from fastapi.testclient import TestClient
        from openpyxl import Workbook, load_workbook

        import backend.src.database
        import backend.src.main as candidate_main
        import admin_backend.src.main as admin_main

        origin = {"Origin": "http://127.0.0.1:5174"}
        admin = TestClient(admin_main.app)
        login = admin.post(
            "/api/admin/auth/login",
            headers=origin,
            json={"email": "root@example.com", "password": "RootAdminPassword123!"},
        )
        assert login.status_code == 200, login.text

        workbook = Workbook()
        sheet = workbook.active
        counselor = "\\u738b\\u8001\\u5e08"
        sheet.append(["\\u5b66\\u9662", "\\u5b66\\u53f7", "\\u59d3\\u540d", "\\u6027\\u522b", "\\u73ed\\u7ea7", "\\u8f85\\u5bfc\\u5458", "\\u8d26\\u53f7\\u72b6\\u6001", "\\u5b66\\u751f\\u72b6\\u6001", "\\u6ce8\\u518c\\u65f6\\u95f4", "\\u4fee\\u6539\\u65f6\\u95f4"])
        sheet.append(["\\u8ba1\\u7b97\\u673a\\u5b66\\u9662", "20260001", "\\u5f20\\u4e09", "\\u7537", "\\u8f6f\\u4ef6\\u4e00\\u73ed", counselor, "\\u6b63\\u5e38", "\\u5728\\u6821", "2026-09-01", "2026-09-01"])
        sheet.append(["\\u8ba1\\u7b97\\u673a\\u5b66\\u9662", "20260002", "\\u674e\\u56db", "\\u5973", "\\u8f6f\\u4ef6\\u4e00\\u73ed", counselor, "\\u6b63\\u5e38", "\\u5728\\u6821", "2026-09-01", "2026-09-01"])
        content = BytesIO()
        workbook.save(content)

        imported = admin.post(
            "/api/admin/student-accounts/import",
            headers=origin,
            files={"file": ("students.xlsx", content.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        assert imported.status_code == 200, imported.text
        assert imported.json()["result"]["created"] == 2

        students = admin_main.all_rows(
            "SELECT id, student_no, password_hash, temp_password_encrypted FROM users ORDER BY student_no"
        )
        assert len(students) == 2
        assert students[0]["password_hash"] != students[1]["password_hash"]
        assert "20260001" not in students[0]["temp_password_encrypted"]

        revealed = []
        for student in students:
            response = admin.get(f"/api/admin/student-accounts/{student['id']}/temporary-password")
            assert response.status_code == 200, response.text
            revealed.append(response.json()["temporaryPassword"])
        assert revealed[0] != revealed[1]

        exported = admin.get(f"/api/admin/student-accounts/export?counselor={counselor}&class_name=\\u8f6f\\u4ef6\\u4e00\\u73ed&admission_year=2026")
        assert exported.status_code == 200, exported.text
        exported_workbook = load_workbook(BytesIO(exported.content), data_only=True)
        exported_rows = list(exported_workbook.active.iter_rows(values_only=True))
        assert len(exported_rows) == 3
        assert exported_rows[1][1] == "20260001"
        assert exported_rows[1][2] == "2026"
        assert exported_rows[1][7] == revealed[0]

        empty_year = admin.get("/api/admin/student-accounts/export?admission_year=2025")
        assert empty_year.status_code == 200
        empty_workbook = load_workbook(BytesIO(empty_year.content), data_only=True)
        assert empty_workbook.active.max_row == 1

        student_client = TestClient(candidate_main.app)
        student_login = student_client.post(
            "/api/auth/login",
            json={"student_no": "20260001", "password": revealed[0]},
        )
        assert student_login.status_code == 200, student_login.text
        assert student_login.json()["user"]["mustChangePassword"] is True
        changed = student_client.post(
            "/api/auth/change-initial-password",
            json={"password": "StudentPassword123!", "confirm_password": "StudentPassword123!"},
        )
        assert changed.status_code == 200, changed.text

        hidden = admin.get(f"/api/admin/student-accounts/{students[0]['id']}/temporary-password")
        assert hidden.status_code == 409, hidden.text
        cleared = admin_main.one(
            "SELECT temp_password_encrypted, must_change_password FROM users WHERE id = ?",
            (students[0]["id"],),
        )
        assert cleared["temp_password_encrypted"] is None
        assert cleared["must_change_password"] == 0

        remaining_export = admin.get("/api/admin/student-accounts/export")
        remaining_workbook = load_workbook(BytesIO(remaining_export.content), data_only=True)
        assert remaining_workbook.active.max_row == 2
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
