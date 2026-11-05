"""验证注册、训练和报告的数据范围边界。

每个场景使用独立进程和新建的 SQLite 数据库，不依赖业务库、真实账号、模型服务或持久化环境配置文件。
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
from shared.offline_fixture import enable_offline_fixture
enable_offline_fixture()
from admin_backend.offline import main

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
    "review_legacy_permission_requests": '''
root()
db.execute("INSERT INTO admin_users (id,email,name,password_hash,role,permissions) VALUES ('staff','staff@example.test','Staff','synthetic','manager','[]')")
db.execute("INSERT INTO admin_permission_requests (id,admin_user_id,requester_email,permissions,student_scope) VALUES ('req','staff','staff@example.test',?,?)",
           (json.dumps(["report.review"]), json.dumps([{"college": "c1", "class_id": "a"}])))
db.commit()
def approve():
    return request("PATCH", "permission-requests/req", json={"action": "approve"})
assert approve().status_code == 400
assert main.one("SELECT status FROM admin_permission_requests WHERE id='req'")["status"] == "pending"
assert main.one("SELECT permissions FROM admin_users WHERE id='staff'")["permissions"] == "[]"
db.execute("UPDATE admin_permission_requests SET student_scope=? WHERE id='req'",
           (json.dumps([{"college":"c1","class":"a"}]),))
db.commit()
original_audit = main.record_audit
def unavailable(*args, **kwargs):
    raise main.error(503, "Synthetic audit outage")
main.record_audit = unavailable
assert approve().status_code == 503
assert main.one("SELECT status FROM admin_permission_requests WHERE id='req'")["status"] == "pending"
assert main.one("SELECT permissions FROM admin_users WHERE id='staff'")["permissions"] == "[]"
main.record_audit = original_audit
assert approve().status_code == 200
account = main.one("SELECT student_scope,permissions FROM admin_users WHERE id='staff'")
assert json.loads(account["permissions"]) == ["report.review"]
assert json.loads(account["student_scope"]) == [{"college": "c1", "program": "p1", "class": "a"}]
assert request("PATCH", "permission-requests/req", json={"action": "reject"}).status_code == 400
assert main.one("SELECT status FROM admin_permission_requests WHERE id='req'")["status"] == "approved"
''',
    "report_score_coverage": """
def snapshot_report():
    return request("GET", "snapshot").json()["reports"][0]
assert snapshot_report()["scored_answer_count"] is None
assert snapshot_report()["score"] is None
db.execute("INSERT INTO interview_messages (id, interview_id, sender_type, message_type, content, order_index) VALUES ('msg', 'allowed', 'candidate', 'answer', 'answer text', 1)")
for status, scored, count, fallback, total, displayed, averaged in [
    ("succeeded", None, None, 0, 70, 70, 70), ("degraded", None, None, 1, 60, 60, None),
    ("pending_retry", 0, 1, 1, 0, None, None), ("insufficient_evidence", 0, 1, 0, 0, None, None),
    ("degraded", 1, 1, 1, 0, 0, 0), ("succeeded", 1, 2, 0, 55, 55, None),
]:
    db.execute("UPDATE interview_reports SET generation_status=?, scored_answer_count=?, answer_count=?, fallback=?, total_score=? WHERE id='allowed'", (status, scored, count, fallback, total))
    db.commit()
    row = snapshot_report()
    assert row["score"] == displayed and row["scored_answer_count"] == scored, row
    assert row["stat_eligible"] == (averaged is not None), row
    assert request("GET", "reports/allowed").json()["report"]["total_score"] == displayed
    assert next(r for r in main.list_candidates() if r["id"] == "allowed")["averageScore"] == averaged
    assert next(r for r in main.list_campus_students() if r["id"] == "allowed")["readiness"] == averaged
# 仅有名册权限时，汇总字段也不能泄露个人分数。
db.execute("UPDATE interview_reports SET generation_status='succeeded', fallback=0, scored_answer_count=1, answer_count=1, total_score=93 WHERE id='allowed'")
db.commit()
actor["permissions"] = ["manageStudents"]
assert request("GET", "campus/overview").json()["students"][0]["readiness"] is None
assert request("GET", "snapshot").json()["candidates"][0]["averageScore"] is None
actor["permissions"].append("report.read")
assert request("GET", "campus/overview").json()["students"][0]["readiness"] == 93
assert request("GET", "snapshot").json()["candidates"][0]["averageScore"] == 93
""",
    "training_and_reports": '''
snapshot = request("GET", "snapshot").json()
for collection in ("interviews", "reports", "candidates"):
    assert {row["id"] for row in snapshot[collection]} == {"allowed"}, collection
assert snapshot["metrics"][0]["value"] == "1", snapshot["metrics"]
# 旧报告只读账号必须显式获授复核权限才能复核。
assert snapshot["permissions"]["canViewReports"] and not snapshot["permissions"]["canReviewReports"]
assert request("PATCH", "reports/allowed/review", json={"status": "approved"}).status_code == 403
actor["permissions"].append("report.review")
for uid in ("outside", "other", "unassigned"):
    for collection in ("interviews", "reports"):
        assert request("GET", collection + "/" + uid).status_code == 403
    assert request("PATCH", "reports/" + uid + "/review", json={"status": "approved"}).status_code == 403
    assert main.one("SELECT review_status FROM interview_reports WHERE id = ?", (uid,))["review_status"] != "approved"
assert request("GET", "interviews/allowed").status_code == 200
assert request("GET", "reports/allowed").status_code == 200
# 即使账号持有显式授权，旧路由也不能直接写入报告。
assert request("PATCH", "reports/allowed/review", json={"status": "approved"}).status_code == 403
actor["permissions"] = ["report.review"]
assert request("GET", "reports/allowed").status_code == 403
actor["actor_type"] = "teacher"
assert request("PATCH", "reports/allowed/review", json={"status": "pending"}).status_code == 503
actor["actor_type"] = "admin"
actor["permissions"] = ["report.read"]
assert request("GET", "reports/allowed").status_code == 200
assert request("PATCH", "reports/allowed/review", json={"status": "approved"}).status_code == 403
assert request("GET", "reports/allowed/export").status_code == 403
actor["permissions"] = ["report.export"]
assert request("GET", "reports/allowed").status_code == 403
assert request("PATCH", "reports/allowed/review", json={"status": "approved"}).status_code == 403
assert request("GET", "reports/outside/export").status_code == 403
exported = request("GET", "reports/allowed/export")
assert exported.status_code == 200 and exported.headers["content-disposition"].startswith("attachment;")
assert exported.headers["cache-control"] == "no-store" and exported.json()["report"]["id"] == "allowed"
actor["permissions"] = ["report.read"]
# 学院或专业授权涵盖其下多个班级，其他学院仍不可见。
for scope in ([{"college": "c1", "program": "p1"}], [{"college": "c1"}]):
    actor["student_scope"] = scope
    assert {r["id"] for r in request("GET", "snapshot").json()["reports"]} == {"allowed", "outside"}
actor["student_scope"] = [{"college": "c1", "class": "a"}, {"college": "c2"}]
assert {r["id"] for r in request("GET", "snapshot").json()["reports"]} == {"allowed", "other"}
for scope in ([], [{}], [None], [{"class": "a"}], [{"college": "c1", "class_id": "a"}],
              [{"college": "c1", "class": False}]):
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
# 模拟报告与面试归属不一致的旧记录：报告标为授权范围内的学生，原始面试却属于另一人。
actor["email"] = "limited@example.test"
actor["permissions"] = ["report.read", "report.review", "report.export"]
actor["student_scope"] = [{"college": "c1", "program": "p1", "class": "a"}]
db.execute("UPDATE interview_reports SET user_id='allowed' WHERE id='outside'")
db.commit()
assert "outside" not in {r["id"] for r in request("GET", "snapshot").json()["reports"]}
assert request("GET", "reports/outside").status_code == 404
assert request("GET", "reports/outside/export").status_code == 404
assert request("PATCH", "reports/outside/review", json={"status": "approved"}).status_code == 403
assert main.one("SELECT review_status FROM interview_reports WHERE id='outside'")["review_status"] != "approved"
''',
    "logs_and_organization": '''
actor["permissions"] = ["viewConnectionLogs", "manageOrganization", "manageStudents"]
for event_id, iid, uid, level in (("e1", "allowed", "allowed", "warning"),
                                  ("e2", "outside", "outside", "error"),
                                  ("unassigned", "unassigned", "unassigned", "info"),
                                  ("corrupt", "outside", "allowed", "error")):
    db.execute("INSERT INTO webrtc_diagnostic_events (id, interview_id, user_id, session_id, event_type, level, metadata_json) VALUES (?, ?, ?, ?, 'state', ?, ?)",
               (event_id, iid, uid, event_id, level, json.dumps({"event": event_id})))
db.commit()
logs = request("GET", "connection-logs").json()
assert [(r["id"], r["candidate"], r["metadata"]) for r in logs["logs"]] == [
    ("e1", "allowed", {"event": "e1"})], logs
assert {k: logs["summary"][k] for k in ("total", "sessions", "warnings", "errors")} == {
    "total": 1, "sessions": 1, "warnings": 1, "errors": 0}
assert request("GET", "connection-logs?query=outside").json()["logs"] == []
for scope in ([], [{}], [{"class": "a"}]):
    actor["student_scope"] = scope
    hidden = request("GET", "connection-logs").json()
    assert hidden["logs"] == [] and hidden["summary"]["total"] == 0 and hidden["summary"]["latestAt"] == "-"
actor["student_scope"] = [{"college": "c1", "program": "p1", "class": "a"}]
structure = request("GET", "organization/structure").json()
assert [r["id"] for r in structure["classes"]] == ["a"], structure
# 缺少 user_id 的旧记录仍可能通过学号关联到已有账号，改动班级标签不能泄露该学生。
db.execute("UPDATE student_registrations SET user_id=NULL, class_name='Allowed' WHERE id='outside'")
db.commit()
assert "outside" not in {r["id"] for r in request("GET", "snapshot").json()["dashboardRoster"]}
assert "outside" not in {r["id"] for r in request("GET", "campus/overview").json()["pendingStudents"]}
assert request("DELETE", "campus/classes/b").status_code == 403
assert request("DELETE", "campus/programs/p1").status_code == 403
assert request("DELETE", "campus/colleges/c1").status_code == 403
assert request("POST", "campus/classes", json={"programId": "p1", "name": "new"}).status_code == 403
actor["student_scope"] = [{"college": "c1", "program": "p1"}]
body = b"college,major,class\\nc1,p1,NewClass\\nc2,p2,Denied\\n"
assert request("POST", "campus/structure/import", files={"file": ("org.csv", body, "text/csv")}).status_code == 403
assert not main.one("SELECT id FROM campus_classes WHERE name IN ('NewClass', 'Denied')")
assert request("POST", "campus/classes", json={"programId": "p1", "name": "NewClass"}).status_code == 201
body = b"email,student_no\\nallowed@example.test,changed\\nother@example.test,denied\\n"
assert request("POST", "campus/students/import?class_id=b", files={"file": ("move.csv", body, "text/csv")}).status_code == 403
assert main.one("SELECT class_id, student_no FROM student_enrollments WHERE user_id = 'allowed'") == {"class_id": "a", "student_no": "allowed"}
root()
assert request("GET", "connection-logs").json()["summary"]["total"] == 3
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
# 导入文件中含有无效行时，须回滚此前写入的账号和记录。
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
# 伪造班级显示名称不能让范围外的账号变为可访问。
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
