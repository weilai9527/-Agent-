"""在没有业务数据库的网关上建立真实会话，使用独立进程作为下游。"""
from contextlib import ExitStack
import json
import sqlite3
from unittest.mock import patch

import httpx

from shared.account_security import hash_password
from scripts.smoke_microservices import Deployment, PASSWORD, SCHOOL, call, prepare_sources, until


GATEWAY_GUARD = """
import os
if os.environ.get("SERVICE_ID") == "student-gateway":
    class NoOwnerImports:
        def find_spec(self, fullname, *args):
            if fullname in {"backend.src.main", "backend.src.database", "admin_backend.src.database",
                            "admin_backend.src.main", "services.assessment.app", "services.interview.app"}:
                raise AssertionError("Student gateway imported a database owner: " + fullname)
    sys.meta_path.insert(0, NoOwnerImports())
    def no_gateway_database(event, args):
        if event == "sqlite3.connect" or (event == "socket.connect" and isinstance(args[1], tuple)
                                          and args[1][1] == 1):
            raise AssertionError("Student gateway attempted SQL access")
    sys.addaudithook(no_gateway_database)
"""


def test_native_gateway_survives_owner_outage_without_sql(tmp_path):
    prepare_sources(tmp_path)
    with (tmp_path / "sitecustomize.py").open("a") as guard:
        guard.write(GATEWAY_GUARD)

    with ExitStack() as stack:
        deployment = Deployment(tmp_path, stack, "isolated")
        policy = json.loads(deployment.env["SERVICE_TRUST_POLICY"])
        policy["student-gateway"]["grants"]["interview"]["student"] += ["interview.read", "interview.create"]
        deployment.env["SERVICE_TRUST_POLICY"] = json.dumps(policy)
        for peer in ("identity", "interview", "assessment", "training"):
            deployment.start_app(peer)
        for peer in ("identity", "interview", "assessment", "training"):
            until(peer, lambda: deployment.ready(peer))

        with sqlite3.connect(tmp_path / "identity.sqlite") as identity:
            identity.execute("""INSERT INTO identity_student_credentials
                           (school_id,actor_id,student_no,name,password_hash,status,must_change_password)
                           VALUES (?,'student','N1001','Native student',?,'normal',0)""",
                             (SCHOOL, hash_password(PASSWORD)))

        # SQLite 路径只发给持有数据的服务；网关尝试直接连接源库时必须失败。
        gateway_env = {k: v for k, v in deployment.env.items()
                       if not any(word in k for word in ("DB_ENGINE", "SQLITE", "MYSQL"))}
        gateway_env.update(DB_ENGINE="mysql", MYSQL_HOST="127.0.0.1", MYSQL_PORT="1",
                           ASSESSMENT_DB_ENGINE="mysql", ASSESSMENT_MYSQL_HOST="127.0.0.1", ASSESSMENT_MYSQL_PORT="1")
        with patch.object(deployment, "env", gateway_env):
            deployment.start_app("student-gateway")
        until("student-gateway", lambda: deployment.ready("student-gateway"))
        origin = deployment.urls["student-gateway"]
        browser = stack.enter_context(httpx.Client(base_url=origin, headers={"Origin": origin},
                                                   trust_env=False, timeout=12))
        assert call(browser, "GET", "/api/health")["ok"]
        assert browser.get("/api/interviews").status_code == 401
        call(browser, "POST", "/api/auth/login", {"student_no": "N1001", "password": PASSWORD})
        assert browser.cookies.get("identity_student_session")
        report_history = call(browser, "GET", "/api/reports")
        assert report_history["reports"] == []
        # 停掉之前在线的服务，同时检查未配置服务，两者都不能转向历史数据库。
        deployment.stop("assessment")
        assert browser.get("/api/reports").status_code == 503
        assert browser.get("/api/job-postings").status_code == 503
        assert call(browser, "GET", "/api/training/tasks")["items"] == []
        created = call(browser, "POST", "/api/interviews", {"target_role": "QA", "user_id": "someone-else"})
        interview = created["interview"]
        assert interview["user_id"] == "student"
        assert call(browser, "GET", "/api/interviews/" + interview["id"])["interview"]["id"] == interview["id"]
        assert "policy" in call(browser, "GET", "/api/interviewer-policy")
        assert call(browser, "GET", "/api/auth/me")["user"]["name"] == "Native student"
        call(browser, "POST", "/api/auth/logout")
        assert browser.get("/api/interviews").status_code == 401
