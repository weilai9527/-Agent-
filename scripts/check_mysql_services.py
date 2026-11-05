"""启动仅监听回环地址的临时 MySQL 8 实例，验证各服务能否初始化数据库，无需连接外部数据库。"""
import argparse
import importlib
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOMAINS = ("identity", "profile", "career", "training", "analytics", "usage", "media",
           "credentials", "provenance", "providers", "operations", "interview", "assessment")


def exercise(domain):
    from fastapi.testclient import TestClient
    sys.path.insert(0, str(ROOT))
    if domain == "public_verifier":
        from services.credentials.app import public_app
        from services.credentials.storage import database
        import pymysql
        with TestClient(public_app) as client:
            assert client.get("/verify/" + "0" * 32).status_code == 404
        try:
            with database().transaction(write=True) as tx:
                tx.execute("DELETE FROM teaching_certificates WHERE 1=0")
        except pymysql.MySQLError as exc:
            assert exc.args[0] in {1044, 1142}
        else:
            raise AssertionError("Public verifier obtained write permission")
        return
    if domain == "legacy_admin":
        import unittest
        from admin_backend.tests.test_mysql_collations import MySQLCollationIntegrationTests
        result = unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromTestCase(MySQLCollationIntegrationTests))
        if not result.wasSuccessful() or result.testsRun != 2 or result.skipped:
            raise RuntimeError("Legacy cross-table collation checks failed or did not run")
        return
    module = f"services.{domain}.app"
    app = importlib.import_module(module).app
    # 连续启动两次，检查 MySQL 隐式提交的 DDL 是否留下部分建好的表，导致后续进程启动失败。
    for _ in range(2):
        with TestClient(app):
            pass
    if domain == "identity":
        from check_mysql_school_office import exercise_school_office
        exercise_school_office()
        from check_mysql_staff_requests import exercise_staff_requests
        exercise_staff_requests()
        from check_mysql_key_isolation import exercise_identity
        exercise_identity()
    if domain in {"interview", "assessment"}:
        from check_mysql_projection import exercise_projection
        exercise_projection(domain)
    if domain == "career":
        from services.career.store import transaction
        from shared.career_catalog import record_job_suggestion
        with transaction("mysql-test", write=True) as db:
            first = record_job_suggestion(db, "Synthetic role", {}, "first")
            second = record_job_suggestion(db, "Synthetic role", {}, "second")
            assert first["id"] == second["id"] and second["occurrence_count"] == 2
            assert (second["first_provider"], second["last_provider"]) == ("first", "second")
    if domain == "usage":
        from check_mysql_key_isolation import exercise_usage
        exercise_usage()
        from services.usage.app import Reservation
        from services.usage.ledger import UsageLedger
        from shared.service_db import ServiceDatabase
        ledger = UsageLedger(ServiceDatabase.from_env("usage"))
        actor = {"school_id": "mysql-test", "caller": "media", "actor_type": "student", "actor_id": "one"}
        ledger.configure("mysql-test", 2, 4)
        request = Reservation(request_id="mysql-test-action", resource="media", units=1)
        first = ledger.reserve(actor, request)
        assert ledger.reserve(actor, request)["reservation_id"] == first["reservation_id"]


def run(binary, tmp):
    import pymysql
    root_secret = secrets.token_hex(24)
    data = tmp / "db"
    data.mkdir()
    common = [str(binary), "--no-defaults", f"--basedir={binary.parent.parent}", f"--datadir={data}"]
    subprocess.run([*common, "--initialize-insecure"], stdout=subprocess.DEVNULL,
                   stderr=subprocess.PIPE, check=True, timeout=90)
    pem = tmp / "tls.pem"
    key = tmp / "tls.key"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                    "-subj", "/CN=localhost", "-addext", "subjectAltName=IP:127.0.0.1,DNS:localhost",
                    "-keyout", str(key), "-out", str(pem)], check=True, capture_output=True)
    init = tmp / "root.sql"
    init.write_text(f"ALTER USER 'root'@'localhost' IDENTIFIED BY '{root_secret}';\n")
    init.chmod(0o600)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    local_socket = str(tmp / "mysql.sock")
    process = subprocess.Popen([*common, "--mysqlx=OFF", "--skip-log-bin", "--skip-name-resolve", "--bind-address=127.0.0.1",
                                f"--port={port}", f"--socket={local_socket}", f"--init-file={init}",
                                f"--ssl-cert={pem}", f"--ssl-key={key}", f"--ssl-ca={pem}",
                                f"--log-error={tmp / 'server.log'}"])
    try:
        for _ in range(120):
            if process.poll() is not None:
                raise RuntimeError("Disposable MySQL exited on startup")
            try:
                conn = pymysql.connect(unix_socket=local_socket, user="root", password=root_secret, connect_timeout=1)
                break
            except pymysql.OperationalError:
                time.sleep(0.25)
        else:
            raise RuntimeError("Disposable MySQL did not start")
        failed = []
        with conn, conn.cursor() as cursor:
            for domain in (*DOMAINS, "legacy_admin", "public_verifier"):
                readonly = domain == "public_verifier"
                owner = "credentials" if readonly else domain
                schema = f"verify_{owner}"
                secret = secrets.token_hex(22)
                if not readonly:
                    cursor.execute(f"CREATE DATABASE `{schema}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
                cursor.execute("CREATE USER %s@'127.0.0.1' IDENTIFIED BY %s", (domain, secret))
                privilege = ("SELECT" if readonly else "ALL" if domain == "legacy_admin" else
                             "SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, REFERENCES, INDEX")
                cursor.execute(f"GRANT {privilege} ON `{schema}`.* TO %s@'127.0.0.1'", (domain,))
                conn.commit()
                # 每个业务域使用独立账号，只能在自己的库中创建或读取表。
                env = {k: os.environ[k] for k in ("PATH", "PYTHONPATH", "TMPDIR", "LANG") if k in os.environ}
                settings = {"DB_ENGINE": "mysql", "MYSQL_HOST": "127.0.0.1", "MYSQL_PORT": str(port),
                            "MYSQL_DATABASE": schema, "MYSQL_USER": domain, "MYSQL_PASSWORD": secret,
                            "MYSQL_SSL_CA": str(pem)}
                env.update({owner.upper() + "_" + k: v for k, v in settings.items()})
                env.update(APP_ENV="test", SERVICE_ID=domain, LEGACY_SCHOOL_ID="mysql-test",
                           CAREER_SCHOOL_ID="mysql-test", ASSESSMENT_STORAGE_MODE="isolated", TEST_PROJECTION_WIRE=str(tmp / "project.json"))
                if domain == "legacy_admin":
                    env.update(settings)
                if readonly:
                    env["SERVICE_ID"] = "credentials-verifier"
                if domain == "assessment":
                    # 验证计量工作进程使用的外键和回执表结构。测试模型返回固定结果，无需发出 HTTP 请求。
                    env["USAGE_SERVICE_URL"] = "http://127.0.0.1:1"
                if domain == "legacy_admin":
                    env.update(IDENTITY_SESSION_MODE="legacy", ASSESSMENT_STORAGE_MODE="shared", RUN_MYSQL_INTEGRATION_TESTS="1",
                               ADMIN_MASTER_EMAIL="mysql@example.test", ADMIN_MASTER_PASSWORD=secrets.token_urlsafe(30))
                result = subprocess.run([sys.executable, __file__, "--exercise", domain], cwd=ROOT,
                                        env=env, capture_output=True, text=True, timeout=120)
                print(domain, "FAIL" if result.returncode else "PASS", flush=True)
                if result.returncode:
                    print(result.stderr[-2800:].replace(secret, "[redacted]"), flush=True)
                    failed.append(domain)
        return 1 if failed else 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    group = cli.add_mutually_exclusive_group(required=True)
    group.add_argument("--mysqld", type=Path)
    group.add_argument("--exercise", choices=[*DOMAINS, "legacy_admin", "public_verifier"], help=argparse.SUPPRESS)
    args = cli.parse_args()
    if args.exercise:
        exercise(args.exercise)
    else:
        with tempfile.TemporaryDirectory(prefix="interview-db-", dir="/tmp") as folder:
            sys.exit(run(args.mysqld.resolve(strict=True), Path(folder)))
