"""Regression coverage for registration, training and report scope boundaries.

Each scenario runs in its own process with a fresh SQLite database. No business
database, real accounts, model services or persistent environment files are used.
"""
import os
from pathlib import Path
import subprocess
import sys
import textwrap

from cryptography.fernet import Fernet
import pytest


SETUP = '''
import json
from fastapi.testclient import TestClient
from admin_backend.src import main

actor = {"id": "test-limited", "email": "limited@example.test", "name": "Limited",
         "role": "manager", "permissions": ["manageStudents", "viewInterviews", "viewReports"],
         "student_scope": [{"college": "c1", "program": "p1", "class": "a"}]}
main.app.dependency_overrides[main.require_admin] = lambda: actor
main.record_audit = lambda *args, **kwargs: None
db = main.db
for cid in ("c1", "c2"):
    db.execute("INSERT INTO campus_colleges (id, code, name) VALUES (?, ?, ?)", (cid, cid, cid))
for pid, cid in (("p1", "c1"), ("p2", "c2"), ("p3", "c1")):
    db.execute("INSERT INTO campus_programs (id, college_id, name) VALUES (?, ?, ?)", (pid, cid, pid))
for class_id, pid, name in (("a", "p1", "Allowed"), ("b", "p1", "Outside"),
                           ("c", "p2", "Other"), ("d", "p1", "Ambiguous"), ("e", "p3", "Ambiguous")):
    db.execute("INSERT INTO campus_classes (id, program_id, name, graduation_year, invite_code) VALUES (?, ?, ?, 2027, ?)",
               (class_id, pid, name, "test-" + class_id))
for uid, class_id, college, name in (("allowed", "a", "c1", "Allowed"), ("outside", "b", "c1", "Outside"),
                                   ("other", "c", "c2", "Other"), ("unassigned", None, "c1", "Allowed")):
    db.execute("INSERT INTO users (id, email, password_hash, name, student_no) VALUES (?, ?, ?, ?, ?)",
               (uid, uid + "@example.test", "synthetic-hash", uid, uid))
    if class_id:
        main.upsert_student_enrollment(uid, class_id=class_id, student_no=uid)
    db.execute("INSERT INTO student_registrations (id, student_no, name, college, class_name, gender, counselor, user_id) VALUES (?, ?, ?, ?, ?, 'X', 'Test', ?)",
               (uid, uid, uid, college, name, uid))
    db.execute("INSERT INTO interview_sessions (id, user_id, target_role, status) VALUES (?, ?, 'Test role', 'completed')", (uid, uid))
    db.execute("INSERT INTO interview_reports (id, user_id, interview_id, total_score, grade, pass_recommendation, ability_radar, agent_feedback, timeline_review, summary, suggestions) VALUES (?, ?, ?, 70, 'C', 'hold', '{}', '[]', '[]', 'Test', 'Test')", (uid, uid, uid))
for rid, college, name in (("pending", "c1", "Allowed"), ("pending-out", "c1", "Outside"), ("ambiguous", "c1", "Ambiguous")):
    db.execute("INSERT INTO student_registrations (id, student_no, name, college, class_name, gender, counselor) VALUES (?, ?, ?, ?, ?, 'X', 'Test')", (rid, rid, rid, college, name))
db.commit()
client = TestClient(main.app)
origin = {"Origin": "http://127.0.0.1:5174"}
def request(method, path, **kwargs):
    return client.request(method, "/api/admin/" + path, headers=origin, **kwargs)
def create(student_no, college="c1", class_name="Allowed"):
    return request("POST", "student-registrations", json={"studentNo": student_no, "name": "Test", "college": college, "className": class_name, "gender": "X", "counselor": "Test"})
def root():
    actor["email"] = main.MASTER_ADMIN_EMAIL
    actor["role"] = "super_admin"
'''


SCENARIOS = {
    "training_and_reports": '''
snapshot = request("GET", "snapshot").json()
for collection in ("interviews", "reports", "candidates"):
    assert {row["id"] for row in snapshot[collection]} == {"allowed"}, collection
assert snapshot["metrics"][0]["value"] == "1", snapshot["metrics"]
for uid in ("outside", "other", "unassigned"):
    for collection in ("interviews", "reports"):
        assert request("GET", collection + "/" + uid).status_code == 403
    assert request("PATCH", "reports/" + uid + "/review", json={"status": "approved"}).status_code == 403
    assert main.one("SELECT review_status FROM interview_reports WHERE id = ?", (uid,))["review_status"] != "approved"
assert request("GET", "interviews/allowed").status_code == 200
assert request("GET", "reports/allowed").status_code == 200
assert request("PATCH", "reports/allowed/review", json={"status": "approved"}).status_code == 200
# College and program scopes include sibling classes, but not other colleges.
for scope in ([{"college": "c1", "program": "p1"}], [{"college": "c1"}]):
    actor["student_scope"] = scope
    assert {r["id"] for r in request("GET", "snapshot").json()["reports"]} == {"allowed", "outside"}
actor["student_scope"] = [{"college": "c1", "class": "a"}, {"college": "c2"}]
assert {r["id"] for r in request("GET", "snapshot").json()["reports"]} == {"allowed", "other"}
for scope in ([], [{}], [None], [{"class": "a"}]):
    actor["student_scope"] = scope
    data = request("GET", "snapshot").json()
    assert data["interviews"] == data["reports"] == []
    assert request("GET", "reports/allowed").status_code == 403
actor["permissions"] = ["manageOrganization"]
data = request("GET", "snapshot").json()
assert data["permissions"]["canViewProgramJobs"] is True
assert data["permissions"]["canViewCatalog"] is False
assert data["metrics"] == []
assert request("GET", "reports/allowed").status_code == 403
root()
assert len(request("GET", "snapshot").json()["reports"]) == 4
assert request("GET", "reports/unassigned").status_code == 200
''',
    "registration_single_and_import": '''
assert {r["id"] for r in request("GET", "student-registrations").json()["registrations"]} == {"allowed", "pending"}
for rid in ("outside", "other", "unassigned", "pending-out", "ambiguous"):
    assert request("DELETE", "student-registrations/" + rid).status_code == 403
    assert request("DELETE", "student-registrations/" + rid + "/account").status_code == 403
    assert main.one("SELECT deleted_at FROM student_registrations WHERE id = ?", (rid,))["deleted_at"] is None
for number, college, name in (("outside", "c1", "Allowed"), ("pending-out", "c1", "Allowed"),
                              ("unassigned", "c1", "Allowed"), ("new-out", "c1", "Outside"),
                              ("new-ambiguous", "c1", "Ambiguous"), ("allowed", "c2", "Other")):
    assert create(number, college, name).status_code == 403
# Mixed valid/invalid files must roll back earlier inserted accounts and rows.
csv = b"student_no,name,college,class_name,gender,counselor\\nnew-valid,Test,c1,Allowed,X,Test\\noutside,Test,c1,Allowed,X,Test\\n"
result = request("POST", "student-registrations/import", files={"file": ("scope.csv", csv, "text/csv")})
assert result.status_code == 403, result.text
assert main.one("SELECT id FROM users WHERE student_no = 'new-valid'") is None
assert main.one("SELECT id FROM student_registrations WHERE student_no = 'new-valid'") is None
assert main.one("SELECT name FROM users WHERE id = 'outside'")["name"] == "outside"
assert create("new-valid").status_code == 200
csv = b"student_no,name,college,class_name,gender,counselor\\nimport-valid,Test,c1,Allowed,X,Test\\n"
result = request("POST", "student-registrations/import", files={"file": ("scope.csv", csv, "text/csv")})
assert result.status_code == 200, result.text
uid = main.one("SELECT id FROM users WHERE student_no = 'import-valid'")["id"]
assert main.one("SELECT class_id FROM student_enrollments WHERE user_id = ?", (uid,))["class_id"] == "a"
assert request("DELETE", "student-registrations/pending").status_code == 200
assert request("DELETE", "student-registrations/allowed/account").status_code == 200
assert main.one("SELECT id FROM users WHERE id = 'allowed'") is None
assert main.one("SELECT id FROM users WHERE id = 'outside'") is not None
''',
    "registration_bulk": '''
actor["student_scope"] = []
assert request("GET", "student-registrations").json()["registrations"] == []
assert create("denied").status_code == 403
assert request("POST", "student-registrations/activate").status_code == 200
assert request("DELETE", "student-registrations/accounts").json()["revoked"] == 0
assert request("DELETE", "student-registrations").status_code == 200
assert all(r["deleted_at"] is None for r in main.all_rows("SELECT deleted_at FROM student_registrations"))
actor["student_scope"] = [{"college": "c1", "program": "p1", "class": "a"}]
# Forged display labels cannot bring an outside account into the scope.
db.execute("UPDATE student_registrations SET class_name = 'Allowed' WHERE id = 'outside'")
db.commit()
result = request("POST", "student-registrations/activate")
assert result.status_code == 200, result.text
assert main.one("SELECT user_id FROM student_registrations WHERE id = 'pending'")["user_id"]
assert main.one("SELECT user_id FROM student_registrations WHERE id = 'pending-out'")["user_id"] is None
assert main.one("SELECT name FROM users WHERE id = 'outside'")["name"] == "outside"
result = request("DELETE", "student-registrations/accounts")
assert result.status_code == 200 and result.json()["revoked"] == 2, result.text
assert main.one("SELECT id FROM users WHERE id = 'outside'") is not None
result = request("DELETE", "student-registrations")
assert result.status_code == 200, result.text
assert main.one("SELECT deleted_at FROM student_registrations WHERE id = 'outside'")["deleted_at"] is None
assert main.one("SELECT deleted_at FROM student_registrations WHERE id = 'pending'")["deleted_at"] is not None
root()
assert request("DELETE", "student-registrations/outside/account").status_code == 200
assert main.one("SELECT id FROM users WHERE id = 'outside'") is None
''',
}


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_student_data_scope_regressions(tmp_path, scenario):
    env = {**os.environ, "DB_ENGINE": "sqlite", "SQLITE_PATH": str(tmp_path / "scope.sqlite"),
           "APP_ENV": "production", "ADMIN_MASTER_EMAIL": "root@example.test",
           "ADMIN_MASTER_PASSWORD": "SyntheticRootPassword123!", "ADMIN_COOKIE_SECURE": "false",
           "STUDENT_TEMP_PASSWORD_KEY": Fernet.generate_key().decode("ascii"), "PYTHONUTF8": "1"}
    result = subprocess.run([sys.executable, "-c", textwrap.dedent(SETUP) + textwrap.dedent(SCENARIOS[scenario])],
                            cwd=Path(__file__).resolve().parents[2], env=env, capture_output=True, text=True, encoding="utf-8", timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
