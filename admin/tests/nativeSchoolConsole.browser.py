"""以真实网关、独立身份库与已构建管理页面验收学校管理。参数为管理端 Vite 构建目录。"""
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from contextlib import ExitStack

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from smoke_microservices import keypair, prepare_sources


def run(build):
    if not (build / "index.html").is_file():
        raise ValueError("Supply the directory of the built admin console")
    with tempfile.TemporaryDirectory(prefix="native-console-") as root, ExitStack() as stack:
        temp = Path(root)
        # 只处理本次新建的临时目录；即使两个旧后端目录完全不存在也要覆盖所有管理操作。
        prepare_sources(temp)
        for component in ("backend", "admin_backend"):
            source = temp / component
            if source.is_dir():
                shutil.rmtree(source)
        listeners = {}
        for service in ("admin-gateway", "identity"):
            sock = stack.enter_context(socket.socket())
            sock.bind(("127.0.0.1", 0))
            listeners[service] = sock
        urls = {key: f"http://127.0.0.1:{sock.getsockname()[1]}" for key, sock in listeners.items()}
        private, public = keypair()
        actions = ["organization.read", "organization.manage", "roster.import", "student.import",
                   "student.read", "permissions.manage", "audit.read", "registration.read", "registration.import",
                   "registration.issue", "registration.status", "registration.reissue", "staff.profile.write", "staff.password.reset"]
        trust = {"admin-gateway": {"keys": {"test": public}, "schools": ["synthetic-school"],
                 "grants": {"identity": {"admin": actions, "teacher": ["organization.read", "student.read"],
                                            "system": ["identity.session.proxy", "identity.session.resolve"]}}}}
        paths = [str(temp), *(p for p in sys.path if "site-packages" in p or (p and (Path(p) / "pytest").is_dir()))]
        env = {"PATH": os.defpath, "PYTHONPATH": os.pathsep.join(paths), "PYTHONNOUSERSITE": "1",
               "APP_ENV": "test", "IDENTITY_SESSION_MODE": "native", "LEGACY_SCHOOL_ID": "synthetic-school",
               "IDENTITY_DB_ENGINE": "sqlite", "IDENTITY_SQLITE_PATH": str(temp / "identity.sqlite"),
               "IDENTITY_SERVICE_URL": urls["identity"], "ADMIN_FRONTEND_ORIGIN": urls["admin-gateway"],
               "COOKIE_SECURE": "false", "ADMIN_STATIC_BUILD": str(build),
               "SERVICE_TRUST_POLICY": json.dumps(trust), "SERVICE_KEY_ID": "test"}
        (temp / "console_host.py").write_text(
            "import os\nfrom services.gateway.admin import app\nfrom starlette.staticfiles import StaticFiles\n"
            "app.mount('/admin', StaticFiles(directory=os.environ['ADMIN_STATIC_BUILD'], html=True))\n"
        )
        with httpx.Client(trust_env=False, timeout=2) as client:
            for service, app, ready in (("identity", "services.identity.app:app", "/health"),
                                        ("admin-gateway", "console_host:app", "/admin/")):
                sock = listeners[service]
                log = stack.enter_context((temp / (service + ".log")).open("w+"))
                process_env = {**env, "SERVICE_ID": service}
                if service == "admin-gateway":
                    # 业务网关仅持有签名身份，不能得到身份库的文件路径或 SQL 凭据。
                    process_env.pop("IDENTITY_SQLITE_PATH")
                    process_env.pop("IDENTITY_DB_ENGINE")
                    process_env["SERVICE_SIGNING_KEY"] = private
                proc = subprocess.Popen([sys.executable, "-m", "uvicorn", app, "--fd", str(sock.fileno()),
                                         "--no-access-log"], cwd=temp, env=process_env, pass_fds=(sock.fileno(),),
                                        stdout=log, stderr=subprocess.STDOUT)
                stack.callback(lambda child=proc: stop(child))
                deadline = time.monotonic() + 70
                while time.monotonic() < deadline:
                    if proc.poll() is not None:
                        log.seek(0)
                        raise RuntimeError(log.read()[-2500:])
                    try:
                        if client.get(urls[service] + ready).status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(.1)
                else:
                    raise RuntimeError(service + " startup timeout")
        password = secrets.token_urlsafe(24)
        encoded = subprocess.check_output(
            [sys.executable, "-c", "from shared.account_security import hash_staff_password as hash_password; import sys; print(hash_password(sys.stdin.read()))"],
            cwd=temp, env=env, input=password, text=True).strip()
        with sqlite3.connect(env["IDENTITY_SQLITE_PATH"]) as db:
            db.execute("INSERT INTO identity_staff VALUES(?,?,?,?,?,'admin','normal',?,1)",
                       ("synthetic-school", "admin-qa", "qa@unit.test", encoded, "验收教务员", json.dumps(actions)))
            db.execute("INSERT INTO org_colleges VALUES('synthetic-school','college','合成学院','active')")
            db.execute("INSERT INTO org_programs VALUES('synthetic-school','program','college','合成专业','active')")
            db.execute("INSERT INTO org_classes VALUES('synthetic-school','class-one','program','验收一班','active')")
        node_env = {**os.environ, "QA_BASE": urls["admin-gateway"], "QA_PASSWORD": password}
        subprocess.run([shutil.which("node"), str(Path(__file__).with_suffix(".cjs"))], env=node_env, check=True, timeout=155)
        with sqlite3.connect(env["IDENTITY_SQLITE_PATH"]) as db:
            seen = {row[0] for row in db.execute("SELECT action FROM identity_audit WHERE school_id='synthetic-school'")}
            required = {"staff.create", "student.import", "roster.import", "staff.login", "registration.issue", "registration.revoke"}
            assert required <= seen, seen
            assert db.execute("SELECT COUNT(*) FROM org_enrollments WHERE school_id='synthetic-school' AND class_id='class-one'").fetchone()[0] == 1
            assert db.execute("SELECT COUNT(*) FROM org_staff_classes WHERE school_id='synthetic-school' AND class_id='class-one'").fetchone()[0] == 1
            print("Verified native audit and school-scoped student/teacher membership in independent SQLite.")


def stop(proc):
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


if __name__ == "__main__":
    run(Path(sys.argv[1]).resolve())
