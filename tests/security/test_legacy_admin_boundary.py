"""用真实历史会话 Cookie 验证迁移前接口的对象级权限。"""
import json
import os
from importlib.util import find_spec
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


@pytest.mark.parametrize("scenario", [
    "view_cannot_review", "diagnostics_respect_enrollment", "job_matches_respect_enrollment",
    "agent_templates_respect_enrollment",
])
def test_legacy_entry_point(tmp_path, scenario):
    root = Path(__file__).resolve().parents[2]
    # 仅复制源码并显式启用临时数据库，避免历史夹具意外读取学校部署文件。
    for component in ("backend/src", "admin_backend/src", "admin_backend/offline", "backend/offline", "shared", "services"):
        for source in (root / component).rglob("*.py"):
            target = tmp_path / source.relative_to(root)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    runner = tmp_path / "scenario.py"
    shutil.copyfile(__file__, runner)
    env = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "TMPDIR") if key in os.environ}
    # 兼容通过 pip --target 安装在临时目录的测试依赖。
    package_dirs = {str(Path(find_spec(name).origin).parent.parent)
                    for name in ("pytest", "openpyxl", "fastapi", "cryptography", "jwt")}
    env.update({
        "APP_ENV": "test", "DB_ENGINE": "sqlite", "SQLITE_PATH": str(tmp_path / "test.sqlite"),
        "ADMIN_MASTER_EMAIL": "master@example.test", "ADMIN_MASTER_PASSWORD": "SyntheticMasterOnly-942!",
        "ADMIN_COOKIE_SECURE": "true", "PYTHONUTF8": "1",
        "PYTHONPATH": os.pathsep.join(sorted(package_dirs)),
    })
    result = subprocess.run([sys.executable, str(runner), scenario], cwd=tmp_path, env=env,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def verify(scenario):
    from fastapi.testclient import TestClient
    from shared.offline_fixture import enable_offline_fixture
    enable_offline_fixture()
    from admin_backend.offline import main
    from shared.recruitment import create_job_match

    db = main.db
    teacher_email = "review-reader@example.test"
    password = "Synthetic-Member-219!"
    permissions = ["viewReports", "viewConnectionLogs", "manageCatalog", "manageModelConfig"]
    scope = [{"college": "campus", "program": "program", "class": "class-a"}]
    db.execute(
        "INSERT INTO admin_users(id,email,password_hash,name,permissions,student_scope) "
        "VALUES (?,?,?,?,?,?)",
        ("reader", teacher_email, main.hash_password(password), "Reader",
         json.dumps(permissions), json.dumps(scope)),
    )
    db.execute("INSERT INTO campus_colleges(id,code,name) VALUES ('campus','C','Test Campus')")
    db.execute("INSERT INTO campus_programs(id,college_id,name) VALUES ('program','campus','Test Program')")
    matches = {}
    for label in ("a", "b"):
        group = f"class-{label}"
        db.execute("INSERT INTO campus_classes(id,program_id,name,graduation_year,invite_code) "
                   "VALUES (?,'program',?,2027,?)", (group, group, group))
        db.execute("INSERT INTO users(id,email,password_hash,name,student_no) VALUES (?,?,?,?,?)",
                   (label, f"{label}@example.test", "no-login", label, label))
        main.upsert_student_enrollment(label, class_id=group, student_no=label)
        db.execute("INSERT INTO interview_sessions(id,user_id,target_role,status) "
                   "VALUES (?,?,'role','completed')", (label, label))
        db.execute(
            "INSERT INTO interview_reports(id,user_id,interview_id,total_score,grade,pass_recommendation,"
            "ability_radar,agent_feedback,timeline_review,summary,suggestions) "
            "VALUES (?,?,?,70,'C','hold','{}','[]','[]','test','test')", (label, label, label),
        )
        db.execute("INSERT INTO webrtc_diagnostic_events(id,interview_id,user_id,event_type) "
                   "VALUES (?,?,?,'connected')", (label, label, label))
        for name in ("shared-agent", f"agent-{label}"):
            db.execute(
                "INSERT INTO interview_agents(id,interview_id,agent_name,agent_type,agent_role) "
                "VALUES (?,?,?,'technical','technical')", (f"{label}-{name}", label, name),
            )
        matches[label] = create_job_match(
            db, user_id=label, student_name=label, student_no=label, job_posting_id=None,
            job_title="test", company="test", source="library", jd_text="Synthetic",
            resume_hash="test", match_score=72, result={"summary": "Synthetic"},
        )["id"]
    db.commit()
    with TestClient(main.app, base_url="https://school.test") as client:
        login = client.post("/api/admin/auth/login", json={"email": teacher_email, "password": password})
        assert login.status_code == 200, login.text
        assert client.get("/api/admin/reports/a").status_code == 200
        assert client.get("/api/admin/reports/b").status_code in (403, 404)
        if scenario == "view_cannot_review":
            review = client.patch("/api/admin/reports/a/review", json={"status": "approved"})
            status = main.one("SELECT review_status FROM interview_reports WHERE id='a'")["review_status"]
            assert status != "approved", "viewReports alone approved an in-scope report"
            assert review.status_code == 403
        elif scenario == "diagnostics_respect_enrollment":
            diagnostic = client.get("/api/admin/connection-logs")
            assert diagnostic.status_code == 200
            data = diagnostic.json()
            assert {entry["interviewId"] for entry in data["logs"]} == {"a"}
            assert data["summary"]["total"] == 1
        elif scenario == "job_matches_respect_enrollment":
            listing = client.get("/api/admin/job-matches")
            assert listing.status_code == 200
            assert {row["id"] for row in listing.json()["matches"]} == {matches["a"]}
            assert client.get(f"/api/admin/job-matches/{matches['a']}").status_code == 200
            assert client.get(f"/api/admin/job-matches/{matches['b']}").status_code in (403, 404)
        elif scenario == "agent_templates_respect_enrollment":
            snapshot = client.get("/api/admin/snapshot")
            assert snapshot.status_code == 200
            usage = {row["name"]: row["usageCount"] for row in snapshot.json()["agents"]}
            assert usage == {"shared-agent": 1, "agent-a": 1}
            assert client.get("/api/admin/agents/agent-b").status_code in (403, 404)
            detail = client.get("/api/admin/agents/shared-agent")
            assert detail.status_code == 200
            assert detail.json()["recentUsage"] == []
            db.execute("UPDATE admin_users SET permissions=? WHERE id='reader'",
                       (json.dumps([*permissions, "viewInterviews"]),))
            db.commit()
            result = client.get("/api/admin/agents/shared-agent")
            assert result.status_code == 200
            assert {row["interview_id"] for row in result.json()["recentUsage"]} == {"a"}
        else:
            raise AssertionError(f"Unknown security scenario {scenario}")


if __name__ == "__main__":
    def deny_network(event, _args):
        if event == "socket.connect":
            raise RuntimeError("External sockets are forbidden in the security fixture")

    sys.addaudithook(deny_network)
    verify(sys.argv[1])
