from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4


TEST_DB_PATH = Path(tempfile.gettempdir()) / "multi_agent_interview_admin_auth_test.sqlite"
if TEST_DB_PATH.exists():
    TEST_DB_PATH.unlink()

os.environ["DB_ENGINE"] = "sqlite"
os.environ["SQLITE_PATH"] = str(TEST_DB_PATH)
os.environ["ADMIN_BOOTSTRAP_EMAIL"] = "root-admin@example.com"
os.environ["ADMIN_BOOTSTRAP_PASSWORD"] = "RootAdminPassword123!"
os.environ["ADMIN_BOOTSTRAP_NAME"] = "测试超级管理员"
os.environ["ADMIN_BOOTSTRAP_ROLE"] = "super_admin"
os.environ["ADMIN_COOKIE_SECURE"] = "false"

from fastapi.testclient import TestClient

from admin_backend.src import main as admin_main
from admin_backend.src.main import app


TRUSTED_ORIGIN = "http://127.0.0.1:5174"


class AdminAuthTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def login_super_admin(self) -> None:
        response = self.client.post(
            "/api/admin/auth/login",
            headers={"Origin": TRUSTED_ORIGIN},
            json={"email": "root-admin@example.com", "password": "RootAdminPassword123!"},
        )
        self.assertEqual(response.status_code, 200, response.text)

    def create_campus_hierarchy(self) -> tuple[str, str, str]:
        suffix = uuid4().hex[:8]
        college = self.client.post(
            "/api/admin/campus/colleges",
            headers={"Origin": TRUSTED_ORIGIN},
            json={"code": f"EDU-{suffix}", "name": f"Campus college {suffix}"},
        )
        self.assertEqual(college.status_code, 201, college.text)
        college_id = college.json()["college"]["id"]
        program = self.client.post(
            "/api/admin/campus/programs",
            headers={"Origin": TRUSTED_ORIGIN},
            json={
                "collegeId": college_id,
                "name": f"Software engineering {suffix}",
                "direction": "Backend development",
                "coordinator": "Program owner",
            },
        )
        self.assertEqual(program.status_code, 201, program.text)
        program_id = program.json()["program"]["id"]
        class_response = self.client.post(
            "/api/admin/campus/classes",
            headers={"Origin": TRUSTED_ORIGIN},
            json={
                "programId": program_id,
                "name": f"Class {suffix}",
                "graduationYear": 2027,
                "advisor": "Advisor",
                "inviteCode": f"TEST-{suffix}",
            },
        )
        self.assertEqual(class_response.status_code, 201, class_response.text)
        return college_id, program_id, class_response.json()["class"]["id"]

    def test_protected_endpoint_requires_login(self):
        response = self.client.get("/api/admin/snapshot")
        self.assertEqual(response.status_code, 401)

    def test_bootstrap_admin_can_login_and_read_session(self):
        self.login_super_admin()
        response = self.client.get("/api/admin/auth/me")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["admin"]["role"], "super_admin")

    def test_catalog_endpoints_use_data_permissions(self):
        self.login_super_admin()
        versions = self.client.get("/api/admin/catalog/versions")
        self.assertEqual(versions.status_code, 200, versions.text)
        self.assertIn("computer-pilot-v1", {item["code"] for item in versions.json()["versions"]})
        created = self.client.post(
            "/api/admin/catalog/versions",
            headers={"Origin": TRUSTED_ORIGIN},
            json={"code": "catalog-auth-test", "name": "权限测试草稿"},
        )
        self.assertEqual(created.status_code, 201, created.text)

        account = self.client.post(
            "/api/admin/users",
            headers={"Origin": TRUSTED_ORIGIN},
            json={
                "email": "catalog-reviewer@example.com",
                "password": "ReviewerPassword123!",
                "name": "目录只读审核员",
                "role": "reviewer",
            },
        )
        self.assertIn(account.status_code, {201, 409}, account.text)
        reviewer = TestClient(app)
        login = reviewer.post(
            "/api/admin/auth/login",
            headers={"Origin": TRUSTED_ORIGIN},
            json={"email": "catalog-reviewer@example.com", "password": "ReviewerPassword123!"},
        )
        self.assertEqual(login.status_code, 200, login.text)
        self.assertEqual(reviewer.get("/api/admin/catalog/versions").status_code, 200)
        denied = reviewer.post(
            "/api/admin/catalog/versions",
            headers={"Origin": TRUSTED_ORIGIN},
            json={"code": "denied", "name": "不应创建"},
        )
        self.assertEqual(denied.status_code, 403)

    def test_catalog_draft_entity_crud_endpoints(self):
        self.login_super_admin()
        created_version = self.client.post(
            "/api/admin/catalog/versions",
            headers={"Origin": TRUSTED_ORIGIN},
            json={"code": "catalog-crud-test", "name": "目录编辑接口测试"},
        )
        self.assertEqual(created_version.status_code, 201, created_version.text)
        version_id = created_version.json()["version"]["id"]

        created = self.client.post(
            f"/api/admin/catalog/versions/{version_id}/entities/colleges",
            headers={"Origin": TRUSTED_ORIGIN},
            json={"code": "MED", "name": "医学院", "sort_order": 10},
        )
        self.assertEqual(created.status_code, 201, created.text)
        college_id = created.json()["item"]["id"]

        updated = self.client.patch(
            f"/api/admin/catalog/versions/{version_id}/entities/colleges/{college_id}",
            headers={"Origin": TRUSTED_ORIGIN},
            json={"name": "医学与健康学院", "enabled": False},
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["item"]["enabled"], 0)

        deleted = self.client.delete(
            f"/api/admin/catalog/versions/{version_id}/entities/colleges/{college_id}",
            headers={"Origin": TRUSTED_ORIGIN},
        )
        self.assertEqual(deleted.status_code, 200, deleted.text)

        published_version = self.client.get("/api/admin/catalog/versions").json()["versions"]
        published_id = next(item["id"] for item in published_version if item["status"] == "published")
        rejected = self.client.post(
            f"/api/admin/catalog/versions/{published_id}/entities/colleges",
            headers={"Origin": TRUSTED_ORIGIN},
            json={"code": "LOCKED", "name": "禁止写入"},
        )
        self.assertEqual(rejected.status_code, 400, rejected.text)
        self.assertIn("草稿", rejected.text)

    def test_campus_hierarchy_and_job_mapping(self):
        self.login_super_admin()
        college_id, program_id, class_id = self.create_campus_hierarchy()

        overview = self.client.get("/api/admin/campus/overview")
        self.assertEqual(overview.status_code, 200, overview.text)
        body = overview.json()
        self.assertIn(college_id, {item["id"] for item in body["colleges"]})
        self.assertIn(program_id, {item["id"] for item in body["programs"]})
        self.assertIn(class_id, {item["id"] for item in body["classes"]})
        self.assertTrue(body["jobRoles"])

        job_id = body["jobRoles"][0]["id"]
        mapped = self.client.put(
            f"/api/admin/campus/programs/{program_id}/jobs",
            headers={"Origin": TRUSTED_ORIGIN},
            json={"jobRoleIds": [job_id]},
        )
        self.assertEqual(mapped.status_code, 200, mapped.text)
        refreshed = self.client.get("/api/admin/campus/overview").json()
        program = next(item for item in refreshed["programs"] if item["id"] == program_id)
        self.assertEqual([item["job_role_id"] for item in program["jobs"]], [job_id])

    def test_campus_student_assignment_and_csv_import(self):
        self.login_super_admin()
        _, _, class_id = self.create_campus_hierarchy()
        for statement in (
            """
            CREATE TABLE IF NOT EXISTS users (
              id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, name TEXT, status TEXT,
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              last_login_at TIMESTAMP
            )
            """,
            "CREATE TABLE IF NOT EXISTS profiles (user_id TEXT PRIMARY KEY, target_role TEXT)",
            "CREATE TABLE IF NOT EXISTS interview_sessions (id TEXT PRIMARY KEY, user_id TEXT)",
            "CREATE TABLE IF NOT EXISTS interview_reports (id TEXT PRIMARY KEY, user_id TEXT, total_score REAL)",
        ):
            admin_main.db.execute(statement).close()
        first_id = str(uuid4())
        second_id = str(uuid4())
        admin_main.db.execute(
            "INSERT INTO users (id, email, name, status) VALUES (?, ?, ?, ?)",
            (first_id, "campus-student-1@example.com", "Campus Student One", "normal"),
        ).close()
        admin_main.db.execute(
            "INSERT INTO users (id, email, name, status) VALUES (?, ?, ?, ?)",
            (second_id, "campus-student-2@example.com", "Campus Student Two", "normal"),
        ).close()
        admin_main.db.commit()

        assigned = self.client.patch(
            f"/api/admin/campus/students/{first_id}",
            headers={"Origin": TRUSTED_ORIGIN},
            json={"classId": class_id, "studentNo": "20270001", "focus": True},
        )
        self.assertEqual(assigned.status_code, 200, assigned.text)

        imported = self.client.post(
            f"/api/admin/campus/students/import?class_id={class_id}",
            headers={"Origin": TRUSTED_ORIGIN},
            files={
                "file": (
                    "students.csv",
                    b"email,student_no\ncampus-student-2@example.com,20270002\nmissing@example.com,20279999\n",
                    "text/csv",
                )
            },
        )
        self.assertEqual(imported.status_code, 200, imported.text)
        self.assertEqual(imported.json()["matched"], 1)
        self.assertEqual(len(imported.json()["unmatched"]), 1)

        overview = self.client.get("/api/admin/campus/overview")
        self.assertEqual(overview.status_code, 200, overview.text)
        students = {item["id"]: item for item in overview.json()["students"]}
        self.assertEqual(students[first_id]["classId"], class_id)
        self.assertTrue(students[first_id]["focus"])
        self.assertEqual(students[second_id]["classId"], class_id)

    def test_login_rejects_untrusted_origin(self):
        response = self.client.post(
            "/api/admin/auth/login",
            headers={"Origin": "https://untrusted.example"},
            json={"email": "root-admin@example.com", "password": "RootAdminPassword123!"},
        )
        self.assertEqual(response.status_code, 403)

    def test_reviewer_cannot_read_candidate_details(self):
        self.login_super_admin()
        create_response = self.client.post(
            "/api/admin/users",
            headers={"Origin": TRUSTED_ORIGIN},
            json={
                "email": "reviewer@example.com",
                "password": "ReviewerPassword123!",
                "name": "测试审核员",
                "role": "reviewer",
            },
        )
        self.assertIn(create_response.status_code, {201, 409}, create_response.text)

        reviewer_client = TestClient(app)
        login_response = reviewer_client.post(
            "/api/admin/auth/login",
            headers={"Origin": TRUSTED_ORIGIN},
            json={"email": "reviewer@example.com", "password": "ReviewerPassword123!"},
        )
        self.assertEqual(login_response.status_code, 200, login_response.text)
        response = reviewer_client.get("/api/admin/candidates/not-allowed")
        self.assertEqual(response.status_code, 403)

    def test_logout_revokes_session(self):
        self.login_super_admin()
        response = self.client.post("/api/admin/auth/logout", headers={"Origin": TRUSTED_ORIGIN})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get("/api/admin/auth/me").status_code, 401)

    def test_connection_logs_are_available_in_admin(self):
        self.login_super_admin()
        for statement in (
            """
            CREATE TABLE IF NOT EXISTS users (
              id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, name TEXT, status TEXT,
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            "CREATE TABLE IF NOT EXISTS interview_sessions (id TEXT PRIMARY KEY, user_id TEXT, target_role TEXT)",
            """
            CREATE TABLE IF NOT EXISTS webrtc_diagnostic_events (
              id TEXT PRIMARY KEY,
              interview_id TEXT NOT NULL,
              user_id TEXT NOT NULL,
              session_id TEXT,
              provider TEXT,
              event_type TEXT NOT NULL,
              level TEXT NOT NULL,
              connection_state TEXT,
              ice_connection_state TEXT,
              ice_gathering_state TEXT,
              signaling_state TEXT,
              data_channel_state TEXT,
              message TEXT,
              metadata_json TEXT,
              client_created_at TEXT,
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
        ):
            admin_main.db.execute(statement).close()
        try:
            admin_main.db.execute("ALTER TABLE interview_sessions ADD COLUMN target_role TEXT").close()
        except Exception:
            pass

        suffix = uuid4().hex
        user_id = f"connection-user-{suffix}"
        interview_id = f"connection-interview-{suffix}"
        event_id = f"connection-event-{suffix}"
        admin_main.db.execute(
            "INSERT INTO users (id, email, name, status) VALUES (?, ?, ?, ?)",
            (user_id, f"{suffix}@example.com", "Connection Test Student", "normal"),
        ).close()
        admin_main.db.execute(
            "INSERT INTO interview_sessions (id, user_id, target_role) VALUES (?, ?, ?)",
            (interview_id, user_id, "WebRTC Engineer"),
        ).close()
        admin_main.db.execute(
            """
            INSERT INTO webrtc_diagnostic_events (
              id, interview_id, user_id, session_id, provider, event_type, level,
              connection_state, ice_connection_state, ice_gathering_state,
              signaling_state, data_channel_state, message, metadata_json,
              client_created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                interview_id,
                user_id,
                "qwen-session-test",
                "qwen-realtime",
                "ice_connection_state_changed",
                "warning",
                "connecting",
                "checking",
                "complete",
                "stable",
                "connecting",
                "ICE is still checking",
                '{"candidateType":"relay"}',
                "2026-07-28T08:00:00Z",
            ),
        ).close()
        admin_main.db.commit()

        response = self.client.get(
            "/api/admin/connection-logs",
            params={"level": "warning", "query": "Connection Test Student"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["retentionDays"], 14)
        event = next(item for item in body["logs"] if item["id"] == event_id)
        self.assertEqual(event["candidate"], "Connection Test Student")
        self.assertEqual(event["eventType"], "ice_connection_state_changed")
        self.assertEqual(event["iceConnectionState"], "checking")
        self.assertEqual(event["metadata"]["candidateType"], "relay")
        self.assertGreaterEqual(body["summary"]["warnings"], 1)

    def test_super_admin_can_save_masked_report_provider_settings(self):
        self.login_super_admin()
        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            with patch.object(admin_main, "USER_BACKEND_ENV_PATH", env_path), patch.dict(os.environ, {}, clear=False):
                response = self.client.patch(
                    "/api/admin/settings",
                    headers={"Origin": TRUSTED_ORIGIN},
                    json={
                        "reportOpenaiApiKey": "sk-test-openai-report-secret",
                        "reportOpenaiModel": "gpt-4o-mini",
                        "reportQwenApiKey": "sk-test-qwen-report-secret",
                        "reportQwenModel": "qwen-plus",
                        "reportProviderOrder": "openai,qwen",
                        "reportTimeout": 60,
                        "reportRetries": 1,
                    },
                )

                self.assertEqual(response.status_code, 200, response.text)
                serialized = response.text
                self.assertNotIn("sk-test-openai-report-secret", serialized)
                self.assertNotIn("sk-test-qwen-report-secret", serialized)
                settings = response.json()["settings"]
                self.assertTrue(settings["reportOpenaiApiKeyConfigured"])
                self.assertTrue(settings["reportQwenApiKeyConfigured"])
                self.assertEqual(settings["reportProviderOrder"], "openai,qwen")
                saved = env_path.read_text(encoding="utf-8")
                self.assertIn("OPENAI_API_KEY=sk-test-openai-report-secret", saved)
                self.assertIn("QWEN_API_KEY=sk-test-qwen-report-secret", saved)

    def test_report_provider_settings_reject_env_line_injection(self):
        self.login_super_admin()
        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            with patch.object(admin_main, "USER_BACKEND_ENV_PATH", env_path):
                response = self.client.patch(
                    "/api/admin/settings",
                    headers={"Origin": TRUSTED_ORIGIN},
                    json={"reportOpenaiApiKey": "valid-looking-key\nINJECTED=true"},
                )
                self.assertEqual(response.status_code, 400, response.text)
                self.assertFalse(env_path.exists())

    def test_super_admin_can_run_sanitized_report_provider_diagnostics(self):
        self.login_super_admin()
        result = [
            {
                "provider": "openai",
                "model": "gpt-4o-mini",
                "base_url": "https://api.openai.com/v1",
                "credential_source": "OPENAI_API_KEY",
                "configured": True,
                "status": "ok",
                "latency_ms": 321,
            }
        ]
        with patch("backend.src.provider_diagnostics.diagnose_report_providers", return_value=result):
            response = self.client.post(
                "/api/admin/settings/report-providers/test",
                headers={"Origin": TRUSTED_ORIGIN},
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["ok"])
        self.assertEqual(response.json()["providers"][0]["status"], "ok")


if __name__ == "__main__":
    unittest.main()
