from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


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
