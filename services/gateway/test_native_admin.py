"""在不提供任何业务 SQL 的情况下，用真实身份与职业服务验收原生管理网关。"""
import io
import json
import sqlite3
from contextlib import ExitStack
from unittest.mock import patch

import httpx
from openpyxl import Workbook, load_workbook

from shared.account_security import hash_password
from scripts.smoke_microservices import APPS, Deployment, PASSWORD, SCHOOL, call, prepare_sources, until


GUARD = """
import os
if os.environ.get("SERVICE_ID") == "admin-gateway":
    class NoOwnerImports:
        def find_spec(self, fullname, *args):
            if fullname in {"admin_backend.src.main", "admin_backend.src.database", "backend.src.main",
                            "backend.src.database", "pymysql", "services.identity.app", "services.career.app",
                            "services.assessment.app"}:
                raise AssertionError("Staff gateway imported database owner: " + fullname)
    sys.meta_path.insert(0, NoOwnerImports())
    def no_sql(event, args):
        if event == "sqlite3.connect":
            raise AssertionError("Staff gateway attempted SQL access")
    sys.addaudithook(no_sql)
"""


def test_native_staff_gateway_without_database(tmp_path):
    prepare_sources(tmp_path)
    with (tmp_path / "sitecustomize.py").open("a") as guard:
        guard.write(GUARD)
    with ExitStack() as stack:
        stack.enter_context(patch.dict(APPS, career="services.career.app:app"))
        deployment = Deployment(tmp_path, stack, "isolated")
        policy = json.loads(deployment.env["SERVICE_TRUST_POLICY"])
        grants = policy["admin-gateway"]["grants"]
        grants["identity"]["admin"] += ["identity.classes.read", "identity.roster.read", "organization.read"]
        grants["career"] = {"admin": ["posting.admin.read", "match.admin.read", "posting.import", "catalog.admin.read"]}
        deployment.env.update(SERVICE_TRUST_POLICY=json.dumps(policy), CAREER_SCHOOL_ID=SCHOOL,
                              CAREER_DB_ENGINE="sqlite", CAREER_SQLITE_PATH=str(tmp_path / "career.sqlite"),
                              CAREER_SERVICE_URL=deployment.urls["career"], PROVIDER_PLATFORM_ADMIN_IDS="operator")
        for service in ("identity", "career"):
            deployment.start_app(service)
            until(service, lambda: deployment.ready(service))

        encoded = hash_password(PASSWORD)
        with sqlite3.connect(tmp_path / "identity.sqlite") as identity:
            actions = json.dumps(["posting.admin.read", "posting.import", "match.admin.read", "catalog.admin.read",
                                  "organization.read", "model.config.write"])
            identity.execute("INSERT INTO identity_staff VALUES (?,?,?,?,?,?,'normal',?,0)",
                             (SCHOOL, "operator", "staff@example.test", encoded, "Staff", "admin", actions))
            identity.execute("INSERT INTO org_colleges VALUES (?,'c','College','active')", (SCHOOL,))
            identity.execute("INSERT INTO org_programs VALUES (?,'p','c','Program','active')", (SCHOOL,))
            for group in ("mine", "outside"):
                identity.execute("INSERT INTO org_classes VALUES (?,?,'p',?,'active')", (SCHOOL, group, group))
                identity.execute("""INSERT INTO identity_student_credentials
                    (school_id,actor_id,student_no,name,password_hash,status,must_change_password)
                    VALUES (?,?,?,?,?,'normal',0)""", (SCHOOL, group, group, group, encoded))
                identity.execute("INSERT INTO org_enrollments VALUES (?,?,?,'active')", (SCHOOL, group, group))
            identity.execute("INSERT INTO org_staff_classes VALUES (?,'operator','mine')", (SCHOOL,))
        with sqlite3.connect(tmp_path / "career.sqlite") as career:
            for student in ("mine", "outside"):
                career.execute("INSERT INTO job_matches (id,user_id,job_title) VALUES (?,?,?)", (student, student, student))

        clean = {key: val for key, val in deployment.env.items() if not any(w in key for w in ("MYSQL", "SQLITE", "DB_ENGINE"))}
        with patch.object(deployment, "env", clean):
            deployment.start_app("admin-gateway")
        until("staff gateway", lambda: deployment.ready("admin-gateway"))
        base = deployment.urls["admin-gateway"]
        browser = stack.enter_context(httpx.Client(base_url=base, headers={"Origin": base}, trust_env=False))
        assert call(browser, "GET", "/api/admin/health")["ok"]
        assert browser.get("/api/admin/job-postings").status_code == 401
        call(browser, "POST", "/api/admin/auth/login", {"email": "staff@example.test", "password": PASSWORD})
        snapshot = call(browser, "GET", "/api/admin/snapshot")
        assert snapshot["identityMode"] == "native" and snapshot["assessmentVersioned"]
        assert snapshot["permissions"]["canViewCatalog"] and not snapshot["permissions"].get("canManageSettings")
        # 学校用户即便与平台管理员同名并具有模型动作，也不能通过伪造请求头切换到平台域。
        assert browser.patch("/api/admin/settings", json={"reportRetries": 0},
                             headers={"X-School-ID": "platform"}).status_code == 403
        groups = call(browser, "GET", "/api/admin/identity/v1/organization")["classes"]
        assert [g["class_id"] for g in groups] == ["mine"]
        forged = browser.request("GET", "/api/admin/job-matches?student_ids=outside",
                                 headers={"X-Actor-ID": "other", "X-School-ID": "foreign"}, json={"student_ids": None})
        assert [m["id"] for m in forged.json()["matches"]] == ["mine"], forged.text
        assert browser.get("/api/admin/job-matches/outside").status_code == 404
        assert browser.patch("/api/admin/reports/r/score", json={}).status_code == 403
        assert browser.post("/api/admin/job-postings/import", headers={"Origin":"https://outside.test"}).status_code == 403
        assert call(browser, "GET", "/api/admin/catalog/versions")["versions"]
        assert browser.post("/api/admin/catalog/versions", json={}).status_code == 403

        template = browser.get("/api/admin/job-postings/template")
        assert template.status_code == 200 and "attachment" in template.headers["content-disposition"]
        sheet = Workbook()
        sheet.active.append(["岗位名称", "公司", "岗位描述", "状态"])
        sheet.active.append(["Network engineer", "Example", "Test description", "active"])
        content = io.BytesIO()
        sheet.save(content)
        result = browser.post("/api/admin/job-postings/import", files={"file": ("jobs.xlsx", content.getvalue())})
        assert result.status_code == 200, result.text
        exported = browser.get("/api/admin/job-postings/export")
        assert exported.status_code == 200
        assert any("Network engineer" in row for row in
                   load_workbook(io.BytesIO(exported.content), read_only=True).active.values)
        deployment.stop("career")
        assert browser.get("/api/admin/job-postings").status_code == 503
        assert call(browser, "GET", "/api/admin/auth/me")["admin"]["id"] == "operator"
        call(browser, "POST", "/api/admin/auth/logout")
        assert browser.get("/api/admin/catalog/versions").status_code == 401
