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
os.environ["ADMIN_MASTER_EMAIL"] = "root-admin@example.com"
os.environ["ADMIN_MASTER_PASSWORD"] = "RootAdminPassword123!"
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

    def test_record_filters_receive_student_fields_and_records_beyond_first_fifty(self):
        self.login_super_admin()
        user_id = f"filters-{uuid4().hex}"
        try:
            admin_main.db.execute(
                "INSERT INTO users (id, email, password_hash, name, student_no, college, class_name) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (user_id, f"{user_id}@example.test", "not-a-login-account", "筛选测试学生", "20260099", "测试学院", "测试班级"),
            )
            for index in range(61):
                interview_id = f"{user_id}-{index}"
                admin_main.db.execute(
                    "INSERT INTO interview_sessions (id, user_id, target_role, status, updated_at) "
                    "VALUES (?, ?, '前端工程师', 'completed', ?)",
                    (interview_id, user_id, f"2026-01-{index % 28 + 1:02d} 23:59:59"),
                )
                admin_main.db.execute(
                    "INSERT INTO interview_reports (id, user_id, interview_id, total_score, grade, "
                    "pass_recommendation, ability_radar, agent_feedback, timeline_review, summary, suggestions) "
                    "VALUES (?, ?, ?, 70, 'C', 'hold', '{}', '[]', '[]', '测试摘要', '测试建议')",
                    (f"report-{interview_id}", user_id, interview_id),
                )
            admin_main.db.commit()
            response = self.client.get('/api/admin/snapshot')
            self.assertEqual(response.status_code, 200, response.text)
            for key in ('interviews', 'reports'):
                records = [row for row in response.json()[key] if user_id in row['id']]
                self.assertEqual(len(records), 61)
                for row in records:
                    self.assertEqual(row['studentNo'], '20260099')
                    self.assertEqual(row['college'], '测试学院')
                    self.assertEqual(row['className'], '测试班级')
        finally:
            admin_main.db.execute('DELETE FROM interview_reports WHERE user_id = ?', (user_id,))
            admin_main.db.execute('DELETE FROM interview_sessions WHERE user_id = ?', (user_id,))
            admin_main.db.execute('DELETE FROM users WHERE id = ?', (user_id,))
            admin_main.db.commit()

    def test_dashboard_roster_scope_and_incomplete_pending_students(self):
        prefix = f"dashboard-{uuid4().hex}"
        db = admin_main.db
        try:
            db.execute("INSERT INTO campus_colleges (id, code, name) VALUES (?, ?, ?)", (prefix, prefix, prefix))
            db.execute("INSERT INTO campus_programs (id, college_id, name) VALUES (?, ?, '专业')", (prefix, prefix))
            for suffix in ('allowed', 'outside'):
                db.execute("INSERT INTO campus_classes (id, program_id, name, invite_code) VALUES (?, ?, ?, ?)",
                           (f'{prefix}-{suffix}', prefix, suffix, f'{prefix}-{suffix}'))
            for suffix, class_name, activated in [('assigned', 'allowed', True), ('unassigned', 'allowed', True),
                                                   ('pending', 'allowed', False), ('outside', 'outside', False)]:
                student_id = f'{prefix}-{suffix}'
                if activated:
                    db.execute("INSERT INTO users (id, email, password_hash, name) VALUES (?, ?, 'not-login', ?)",
                               (student_id, f'{student_id}@example.test', suffix))
                    if suffix == 'assigned':
                        db.execute("INSERT INTO student_enrollments (id, user_id, class_id) VALUES (?, ?, ?)",
                                   (student_id, student_id, f'{prefix}-allowed'))
                db.execute("INSERT INTO student_registrations (id, student_no, name, college, class_name, gender, counselor, user_id) "
                           "VALUES (?, ?, ?, ?, ?, '男', '', ?)",
                           (student_id, student_id, suffix, prefix, class_name, student_id if activated else None))
            db.commit()
            all_rows = [row for row in admin_main.dashboard_roster() if row['id'].startswith(prefix)]
            self.assertEqual(len(all_rows), 4)
            pending = next(row for row in all_rows if row['id'] == f'{prefix}-pending')
            self.assertEqual(pending['missing'], ['辅导员'])
            scoped = admin_main.dashboard_roster([{'college': prefix, 'program': prefix, 'class': f'{prefix}-allowed'}])
            self.assertEqual({row['id'] for row in scoped}, {f'{prefix}-assigned', f'{prefix}-pending'})
            self.assertEqual(admin_main.dashboard_roster([]), [])
            for row in all_rows:
                self.assertNotIn('password_hash', row)
                self.assertNotIn('temp_password_encrypted', row)
        finally:
            for suffix in ('assigned', 'unassigned', 'pending', 'outside'):
                student_id = f'{prefix}-{suffix}'
                db.execute('DELETE FROM student_registrations WHERE id = ?', (student_id,))
                db.execute('DELETE FROM student_enrollments WHERE user_id = ?', (student_id,))
                db.execute('DELETE FROM users WHERE id = ?', (student_id,))
            db.execute('DELETE FROM campus_classes WHERE program_id = ?', (prefix,))
            db.execute('DELETE FROM campus_programs WHERE id = ?', (prefix,))
            db.execute('DELETE FROM campus_colleges WHERE id = ?', (prefix,))
            db.commit()

    def test_admin_creation_disable_and_reenable_revoke_old_sessions(self):
        self.login_super_admin()
        root_id = self.client.get('/api/admin/auth/me').json()['admin']['id']
        payload = {"email": f"lifecycle-{uuid4().hex}@example.com", "name": "生命周期测试管理员", "password": "TestAdminPassword123!", "role": "super_admin", "permissions": ["viewReports"]}
        short = self.client.post('/api/admin/users', headers={"Origin": TRUSTED_ORIGIN}, json={**payload, "password": "short"})
        self.assertEqual(short.status_code, 400)
        created = self.client.post('/api/admin/users', headers={"Origin": TRUSTED_ORIGIN}, json=payload)
        self.assertEqual(created.status_code, 201, created.text)
        account_id = created.json()['admin']['id']
        self.assertEqual(self.client.post('/api/admin/users', headers={"Origin": TRUSTED_ORIGIN}, json=payload).status_code, 409)
        subordinate = TestClient(app)
        login = lambda: subordinate.post('/api/admin/auth/login', headers={"Origin": TRUSTED_ORIGIN}, json={"email": payload['email'], "password": payload['password']})
        self.assertEqual(login().status_code, 200)
        self.assertEqual(subordinate.get('/api/admin/users').status_code, 403, 'A role label cannot grant super-admin access')
        self.assertEqual(subordinate.patch(f'/api/admin/users/{root_id}', headers={"Origin": TRUSTED_ORIGIN}, json={"status": "disabled"}).status_code, 403)
        disabled = self.client.patch(f'/api/admin/users/{account_id}', headers={"Origin": TRUSTED_ORIGIN}, json={"status": "disabled"})
        self.assertEqual(disabled.status_code, 200, disabled.text)
        self.assertEqual(subordinate.get('/api/admin/auth/me').status_code, 401)
        self.assertEqual(login().status_code, 401)
        enabled = self.client.patch(f'/api/admin/users/{account_id}', headers={"Origin": TRUSTED_ORIGIN}, json={"status": "normal"})
        self.assertEqual(enabled.status_code, 200, enabled.text)
        self.assertEqual(subordinate.get('/api/admin/auth/me').status_code, 401, 'Reenabling must not restore revoked sessions')
        self.assertEqual(login().status_code, 200)
        self.assertEqual(subordinate.get('/api/admin/auth/me').json()['admin']['permissions'], ['viewReports'])
        self.assertEqual(self.client.patch(f'/api/admin/users/{root_id}', headers={"Origin": TRUSTED_ORIGIN}, json={"status": "disabled"}).status_code, 400)

    def test_job_sync_requires_auth_and_returns_persisted_results(self):
        with patch.object(admin_main, "fetch_job_feed") as fetch_feed:
            self.assertEqual(self.client.post('/api/admin/job-postings/sync').status_code, 401)
            fetch_feed.assert_not_called()
            self.login_super_admin()
            fetch_feed.return_value = [{"id": uuid4().hex, "title": "同步测试岗位", "company": "测试公司"}, {"title": "缺少编号"}]
            self.assertEqual(self.client.post('/api/admin/job-postings/sync', headers={"Origin": "https://untrusted.test"}).status_code, 403)
            fetch_feed.assert_not_called()
            first = self.client.post('/api/admin/job-postings/sync', headers={"Origin": TRUSTED_ORIGIN})
            self.assertEqual(first.status_code, 200, first.text)
            self.assertEqual((first.json()['created'], first.json()['skipped']), (1, 1))
            second = self.client.post('/api/admin/job-postings/sync', headers={"Origin": TRUSTED_ORIGIN})
            self.assertEqual(second.json()['updated'], 1)
            with patch.dict(os.environ, {"JOB_POSTING_SYNC_ENDPOINT": ""}):
                self.assertFalse(self.client.get('/api/admin/job-postings').json()['syncConfigured'])

    def test_interview_detail_returns_complete_transcript_and_review_target(self):
        self.login_super_admin()
        suffix = uuid4().hex
        user_id = f"review-user-{suffix}"
        interview_id = f"review-interview-{suffix}"
        report_id = f"review-report-{suffix}"
        self.insert_candidate_user(user_id, f"{suffix}@example.com", "Review Student")
        admin_main.db.execute(
            "INSERT INTO interview_sessions (id, user_id, target_role, status) VALUES (?, ?, ?, ?)",
            (interview_id, user_id, "Backend Engineer", "completed"),
        ).close()
        for index in range(91):
            sender = "candidate" if index % 2 else "agent"
            admin_main.db.execute(
                """INSERT INTO interview_messages
                   (id, interview_id, sender_type, message_type, content, order_index)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (f"message-{suffix}-{index}", interview_id, sender,
                 "answer" if sender == "candidate" else "question", f"message {index}", index),
            ).close()
        admin_main.db.execute(
            """INSERT INTO interview_reports
               (id, user_id, interview_id, total_score, grade, pass_recommendation,
                ability_radar, agent_feedback, timeline_review, summary, suggestions)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (report_id, user_id, interview_id, 80, "B", "pass", "{}", "[]", "[]", "summary", "suggestions"),
        ).close()
        admin_main.db.commit()

        response = self.client.get(f"/api/admin/interviews/{interview_id}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()["messages"]), 91)
        self.assertEqual(response.json()["messages"][-1]["content"], "message 90")
        self.assertEqual(response.json()["reviewReport"]["id"], report_id)
        listed = next(item for item in admin_main.list_interviews() if item["id"] == interview_id)
        self.assertEqual(listed["qaCount"], 45)

        review = self.client.patch(
            f"/api/admin/reports/{report_id}/review",
            headers={"Origin": TRUSTED_ORIGIN}, json={"status": "approved"},
        )
        self.assertEqual(review.status_code, 200, review.text)
        self.assertEqual(
            self.client.get(f"/api/admin/interviews/{interview_id}").json()["reviewReport"]["review_status"],
            "approved",
        )

    def insert_candidate_user(self, user_id: str, email: str, name: str) -> None:
        """Keep admin tests independent from candidate-backend import order."""
        columns = {
            row[1]
            for row in admin_main.db.execute("PRAGMA table_info(users)").fetchall()
        }
        if "password_hash" in columns:
            admin_main.db.execute(
                "INSERT INTO users (id, email, password_hash, name, status) VALUES (?, ?, ?, ?, ?)",
                (user_id, email, "test-only-password-hash", name, "normal"),
            ).close()
            return
        admin_main.db.execute(
            "INSERT INTO users (id, email, name, status) VALUES (?, ?, ?, ?)",
            (user_id, email, name, "normal"),
        ).close()

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

    def test_program_job_configuration_priorities_validation_and_permissions(self):
        self.assertEqual(self.client.get('/api/admin/campus/program-jobs').status_code, 401)
        self.login_super_admin()
        _, program_id, _ = self.create_campus_hierarchy()
        options = self.client.get('/api/admin/campus/program-jobs')
        self.assertEqual(options.status_code, 200, options.text)
        self.assertTrue(options.json()['canEdit'])
        self.assertIn(program_id, {program['id'] for program in options.json()['programs']})
        jobs = options.json()['jobs'][:2]
        self.assertEqual(len(jobs), 2)
        self.assertIn('competencies', jobs[0])
        self.assertIn('sourceMajor', jobs[0])
        payload = [{'jobRoleId': jobs[0]['id'], 'priority': 'optional'},
                   {'jobRoleId': jobs[1]['id'], 'priority': 'recommended'}]
        path = f'/api/admin/campus/programs/{program_id}/jobs'
        headers = {'Origin': TRUSTED_ORIGIN}
        saved = self.client.put(path, headers=headers, json={'jobs': payload})
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()['jobs'], payload)
        refreshed = self.client.get('/api/admin/campus/program-jobs').json()
        program = next(row for row in refreshed['programs'] if row['id'] == program_id)
        self.assertEqual({row['job_role_id']: row['priority'] for row in program['jobs']},
                         {item['jobRoleId']: item['priority'] for item in payload})
        for invalid in [payload + [payload[0]], [{'jobRoleId': jobs[0]['id'], 'priority': 'unknown'}],
                        [{'jobRoleId': jobs[0]['id'], 'priority': {}}], [{'jobRoleId': 'missing', 'priority': 'optional'}],
                        payload * 26]:
            response = self.client.put(path, headers=headers, json={'jobs': invalid})
            self.assertEqual(response.status_code, 400, response.text)
        still_saved = admin_main.all_rows('SELECT job_role_id, priority FROM program_job_roles WHERE program_id = ?', (program_id,))
        self.assertEqual(len(still_saved), 2)
        account = {'email': f'catalog-reader-{uuid4().hex}@example.com', 'name': '岗位查看员',
                   'password': 'ReadOnlyCatalog123!', 'permissions': ['manageCatalog'], 'role': 'manager'}
        created = self.client.post('/api/admin/users', headers=headers, json=account)
        self.assertEqual(created.status_code, 201, created.text)
        reader = TestClient(app)
        self.assertEqual(reader.post('/api/admin/auth/login', headers=headers,
                                    json={'email': account['email'], 'password': account['password']}).status_code, 200)
        self.assertFalse(reader.get('/api/admin/campus/program-jobs').json()['canEdit'])
        self.assertEqual(reader.put(path, headers=headers, json={'jobs': []}).status_code, 403)
        cleared = self.client.put(path, headers=headers, json={'jobs': []})
        self.assertEqual(cleared.status_code, 200, cleared.text)
        self.assertEqual(admin_main.all_rows('SELECT id FROM program_job_roles WHERE program_id = ?', (program_id,)), [])
        with patch.object(admin_main, 'catalog_tree', return_value=None):
            empty = self.client.get('/api/admin/campus/program-jobs')
            self.assertEqual(empty.status_code, 200)
            self.assertEqual(empty.json()['jobs'], [])

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
        self.insert_candidate_user(first_id, "campus-student-1@example.com", "Campus Student One")
        self.insert_candidate_user(second_id, "campus-student-2@example.com", "Campus Student Two")
        # The student overview includes only accounts linked to an active registration.
        for user_id, student_no, name in (
            (first_id, "20270001", "Campus Student One"),
            (second_id, "20270002", "Campus Student Two"),
        ):
            admin_main.db.execute(
                "INSERT INTO student_registrations (id, student_no, name, user_id) VALUES (?, ?, ?, ?)",
                (str(uuid4()), student_no, name, user_id),
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
        self.insert_candidate_user(user_id, f"{suffix}@example.com", "Connection Test Student")
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
