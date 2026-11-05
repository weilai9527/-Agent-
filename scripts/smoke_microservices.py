"""通过回环 HTTP 连接独立服务进程，验收从教学任务到凭证签发的完整流程。

在 macOS 或 Linux 上运行，Python 环境须已安装 deploy/requirements.txt 列出的运行依赖。
源码副本、SQLite 数据、密钥、TLS 信任证书和日志均放在临时目录中，不继承部署环境变量。
本地 HTTPS 测试服务返回固定的模型结果，验收过程不连接真实区块链。
"""
import argparse
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "integration"))
from smoke_school_fixture import ANSWER, MASTER, PASSWORD, SCHOOL, TEACHER_PASSWORD, local_model, permit_fault_proxy

APPS = {
    "media": "services.media.app:app", "usage": "services.usage.app:app",
    "profile": "services.profile.app:app", "career": "services.career.app:app",
    "identity": "services.identity.app:app", "training": "services.training.app:app",
    "interview": "services.interview.app:app", "assessment": "services.assessment.app:app",
    "analytics": "services.analytics.app:app", "credentials": "services.credentials.app:app",
    "public": "services.credentials.app:public_app", "provenance": "services.provenance.app:app",
    "providers": "services.providers.app:app", "operations": "services.operations.app:app",
    "student-gateway": "services.gateway.student:app", "admin-gateway": "services.gateway.admin:app",
}

# 只允许本次部署实际需要的服务间调用。网关无权冒充评估服务发布结果、提交完成事件或将事件上链。
EDGES = {
    "student-gateway": {"identity": {"system": "identity.session.proxy identity.session.resolve"},
                        "training": {"student": "training.read training.start"},
                        "interview": {"student": "interview.training.start interview.question.current interview.turn.submit interview.finish"},
                        "assessment": {"student": "assessment.read"},
                        "credentials": {"student": "credential.apply credential.read"}},
    "admin-gateway": {"identity": {"system": "identity.session.proxy identity.session.resolve",
                                   "admin": "student.import roster.import organization.manage permissions.manage"},
                      "interview": {"admin": "interview.policy.manage interview.records.read", "teacher": "interview.records.read"},
                      "training": {"teacher": "training.read training.assign"},
                      "assessment": {"admin": "assessment.records.read", "teacher": "assessment.records.read assessment.history assessment.review assessment.score assessment.export"},
                      "analytics": {"teacher": "analytics.teaching.read analytics.practice.assign"},
                      "credentials": {"teacher": "credential.approve credential.issue credential.revoke credential.read"}},
    "training": {"identity": {"teacher": "identity.classes.read identity.roster.read"}},
    "interview": {"identity": {"student": "identity.student.read", "admin": "identity.records.scope", "teacher": "identity.records.scope"},
                  "assessment": {"system": "assessment.project"},
                  "training": {"student": "training.verify", "system": "training.complete"}},
    "assessment": {"identity": {"student": "identity.student.read", "admin": "identity.records.scope", "teacher": "identity.student.authorize identity.records.scope"},
                   "interview": {"student": "interview.read"},
                   "training": {"teacher": "training.verify", "student": "training.verify"},
                   "analytics": {"system": "analytics.completion.write"}},
    "analytics": {"training": {"system": "training.verify", "teacher": "training.assign"},
                  "identity": {"teacher": "identity.classes.read identity.roster.read"}},
    "credentials": {"identity": {"teacher": "identity.student.authorize"},
                    "training": {"student": "training.verify", "teacher": "training.verify"},
                    "assessment": {"student": "assessment.credential-evidence", "teacher": "assessment.credential-evidence assessment.credential-authorize"},
                    "provenance": {"system": "provenance.submit provenance.read"}},
    "credentials-verifier": {"provenance": {"system": "provenance.read"}},
}

EDGES["student-gateway"]["interview"]["student"] += " interview.diagnostics.read interview.diagnostics.write"
for role in ("admin","teacher"):
    EDGES["admin-gateway"]["interview"][role] += " interview.templates.read"
EDGES["operations"] = {"identity": {r: "identity.operations.scope" for r in ("teacher", "admin")}}
for gateway in ("admin-gateway", "student-gateway"):
    EDGES[gateway]["operations"] = {"system": "operations.audit.append"}
EDGES["admin-gateway"]["operations"].update(teacher="operations.rtc.read", admin="operations.rtc.read operations.audit.read")
EDGES["interview"]["operations"] = {"student": "operations.rtc.append operations.rtc.self"}


EDGES["interview"]["profile"] = {"student": "profile.snapshot.read"}
EDGES["assessment"]["usage"] = {"student": "usage.reserve usage.dispatch usage.settle"}
EDGES["admin-gateway"]["usage"] = {"admin": "usage.configure usage.read"}
GUARD = '''
import ipaddress
import os
import sys
if os.environ.get("SERVICE_ID") and os.environ.get("IDENTITY_SESSION_MODE", "native") == "native":
    class NoLegacyApps:
        def find_spec(self, fullname, *args):
            if (fullname in {"admin_backend.src.main", "backend.src.main", "admin_backend.src.database", "backend.src.database"}
                    or ".offline" in fullname.split(".src")[0] and fullname.startswith(("backend.", "admin_backend."))):
                raise AssertionError("正式服务尝试加载退役框架：" + fullname)
    sys.meta_path.insert(0, NoLegacyApps())

def _guard(event, args):
    if (event == "sqlite3.connect" and os.environ.get("IDENTITY_SESSION_MODE", "native") == "native"
            and os.environ.get("SERVICE_ID") in {"student-gateway", "admin-gateway"}):
        raise AssertionError("Native browser gateways cannot open SQL databases")
    if event == "socket.getaddrinfo":
        host = args[0]
    elif event == "socket.connect" and isinstance(args[1], tuple):
        host = args[1][0]
    else:
        return
    if host == "localhost":
        return
    try:
        if ipaddress.ip_address(host).is_loopback:
            return
    except ValueError:
        pass
    raise RuntimeError("External connections are forbidden in this smoke deployment")
sys.addaudithook(_guard)
'''


def keypair():
    key = Ed25519PrivateKey.generate()
    return (key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                              serialization.NoEncryption()).decode(),
            key.public_key().public_bytes(serialization.Encoding.PEM,
                                          serialization.PublicFormat.SubjectPublicKeyInfo).decode())


def prepare_sources(temp, *, include_archive=True):
    # 部署验收只打包原生业务；历史迁移测试可显式准备旧夹具。
    components = ["services", "shared"]
    if include_archive:
        components += ["backend/src", "backend/rtc_token_lib", "admin_backend/src", "admin_backend/offline", "backend/offline"]
    for component in components:
        for source in (ROOT / component).rglob("*.py"):
            target = temp / source.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    shutil.copyfile(ROOT / "tests/integration/smoke_school_fixture.py", temp / "fixture.py")
    (temp / "sitecustomize.py").write_text(GUARD, encoding="utf-8")


def until(description, operation, seconds=70):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if value := operation():
            return value
        time.sleep(0.25)
    raise AssertionError(f"Timeout waiting for {description}")


class Deployment:
    def __init__(self, temp, stack, assessment_mode="isolated", crash_issuance=False):
        if assessment_mode != "isolated":
            raise ValueError("日常验收只运行原生网关和独立评估存储")
        self.temp = temp
        self.stack = stack
        self.assessment_mode = assessment_mode
        self.processes = {}
        self.permit_proxy_url = None
        self.permitted_serial = None
        self.keys = {name: keypair() for name in EDGES}
        # 保留已绑定的套接字，直到对应子进程继承它，避免启动前端口被其他进程抢占。
        self.sockets = {}
        self.urls = {}
        for name in APPS:
            sock = stack.enter_context(socket.socket())
            sock.bind(("127.0.0.1", 0))
            self.sockets[name] = sock
            self.urls[name] = f"http://127.0.0.1:{sock.getsockname()[1]}"
        if crash_issuance:
            proxy = permit_fault_proxy(self.urls["assessment"], self.crash_issuer)
            stack.callback(proxy.server_close)
            stack.callback(proxy.shutdown)
            self.permit_proxy_url = f"http://127.0.0.1:{proxy.server_port}"
        model, ca = local_model(temp)
        stack.callback(model.server_close)
        stack.callback(model.shutdown)
        model_url = f"https://127.0.0.1:{model.server_port}/v1"
        private, public = keypair()
        self.school_signing_keys = json.dumps({SCHOOL: {"kid": "smoke-school-key", "private_key": private}})
        self.master_env = {"ADMIN_MASTER_EMAIL": MASTER, "ADMIN_MASTER_PASSWORD": "Synthetic-Only-Master-738!"}
        policy = {caller: {"keys": {"smoke": self.keys[caller][1]}, "schools": [SCHOOL, "other-smoke-school"],
                          "grants": {aud: {role: scopes.split() for role, scopes in roles.items()}
                                     for aud, roles in targets.items()}}
                  for caller, targets in EDGES.items()}
        lib_paths = [str(temp)] + [p for p in sys.path if p and
                                   ("site-packages" in p or (Path(p) / "pytest").is_dir())]
        self.env = {
            "PATH": os.defpath, "TMPDIR": str(temp),
            "PYTHONPATH": os.pathsep.join(dict.fromkeys(lib_paths)), "PYTHONNOUSERSITE": "1",
            "PYTHONUTF8": "1", "APP_ENV": "test", "DB_ENGINE": "sqlite",
            "NO_PROXY": "*", "no_proxy": "*",
            "SQLITE_PATH": str(temp / "legacy.sqlite"),
            "INTERVIEW_DB_ENGINE": "sqlite", "INTERVIEW_SQLITE_PATH": str(temp / "interviews.sqlite"), "LEGACY_SCHOOL_ID": SCHOOL,
            # 故意不设置身份和存储模式，验证默认值就是上线的原生路径。
            "ADMIN_COOKIE_SECURE": "false",
            "FRONTEND_ORIGIN": self.urls["student-gateway"], "ADMIN_FRONTEND_ORIGIN": self.urls["admin-gateway"],
            "SERVICE_TRUST_POLICY": json.dumps(policy), "SERVICE_KEY_ID": "smoke",
            "AI_BASE_URL": model_url, "AI_MODEL": "smoke-model",
            "EVALUATION_PROVIDER_ORDER": "custom", "REPORT_PROVIDER_ORDER": "custom",
            "FOLLOWUP_PROVIDER_ORDER": "custom", "PROVIDER_ALLOWED_CUSTOM_ENDPOINTS": model_url,
            "SSL_CERT_FILE": str(ca), "INTERVIEW_WORKER_POLL_SECONDS": "0.15",
            "CREDENTIALS_PUBLIC_KEYS_JSON": json.dumps({SCHOOL: {"smoke-school-key":public}}),
        }
        for name in ("training", "identity", "analytics", "credentials", "provenance", "operations", "usage", "profile", "career", "media"):
            self.env[name.upper() + "_DB_ENGINE"] = "sqlite"
            self.env[name.upper() + "_SQLITE_PATH"] = str(temp / (name + ".sqlite"))
        for name in ("training", "identity", "interview", "assessment", "analytics", "credentials", "provenance", "operations"):
            self.env[name.upper() + "_SERVICE_URL"] = self.urls[name]
        self.env["CAREER_SCHOOL_ID"] = SCHOOL
        self.env.update(IDENTITY_SOURCE_DB_ENGINE="sqlite", IDENTITY_SOURCE_SQLITE_PATH=self.env["SQLITE_PATH"])
        self.checker = stack.enter_context(httpx.Client(timeout=2, trust_env=False))

    def command(self, args, *, expected_exit=0, stdin_text=None, **extra):
        result = subprocess.run([sys.executable, *args], cwd=self.temp, env={**self.env, **extra},
                                text=True, input=stdin_text, capture_output=True, timeout=120)
        if result.returncode != expected_exit:
            raise RuntimeError(f"Setup failed for {args[0]}: {result.stderr[-1800:]}")
        return result.stdout

    def start(self, name, service_id, args, *, fd=None):
        env = dict(self.env, SERVICE_ID=service_id)
        # 子进程只取得自己持有的数据库，复用宿主环境也不能读到历史源库。
        db_owner = "CREDENTIALS" if service_id == "credentials-verifier" else service_id.upper()
        for key in list(env):
            if key.endswith(("DB_ENGINE", "SQLITE_PATH")) or "MYSQL_" in key:
                if not key.startswith(db_owner + "_") or "_SOURCE_" in key:
                    del env[key]
        if service_id == "assessment":
            env.update(ASSESSMENT_DB_ENGINE="sqlite", ASSESSMENT_SQLITE_PATH=str(self.temp / "assessment.sqlite"))
        if service_id in {"student-gateway", "admin-gateway"}:
            env["OPERATIONS_JOURNAL_DIR"] = str(self.temp / (service_id + "-journal"))
        if name == "score-worker":
            env["AI_API_KEY"] = "synthetic-model-token"
            env["PROVIDERS_SERVICE_URL"] = self.urls["providers"]
        if name == "providers":
            # 模型控制库及其访问凭据只属于控制服务，不传给评分进程或网关。
            env.update(PROVIDERS_DB_ENGINE="sqlite", PROVIDERS_SQLITE_PATH=str(self.temp / "providers.sqlite"),
                       PROVIDER_PLATFORM_ADMIN_IDS="fixture-operator")
            peers = {caller: {"keys": {"smoke": self.keys[caller][1]}, "schools": ["platform"],
                              "grants": {"providers": {role: [scope]}}}
                     for caller, role, scope in (("admin-gateway", "admin", "providers.configure"),
                                                 ("assessment", "system", "providers.runtime.read"))}
            env["SERVICE_TRUST_POLICY"] = json.dumps(peers)
        if name == "credentials":
            env["CREDENTIALS_SIGNING_KEYS_JSON"] = self.school_signing_keys
            if self.permit_proxy_url:
                env["ASSESSMENT_SERVICE_URL"] = self.permit_proxy_url
        if service_id in self.keys:
            env["SERVICE_SIGNING_KEY"] = self.keys[service_id][0]
        log = self.stack.enter_context((self.temp / (name + ".log")).open("w"))
        process = subprocess.Popen([sys.executable, *args], cwd=self.temp, env=env,
                                   stdout=log, stderr=log, pass_fds=() if fd is None else (fd,))
        self.processes[name] = process
        self.stack.callback(self.stop, name)

    def stop(self, name):
        proc = self.processes.get(name)
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()

    def start_app(self, name):
        identity = "credentials-verifier" if name == "public" else name
        fd = self.sockets[name].fileno()
        self.start(name, identity, ["-m", "uvicorn", APPS[name], "--fd", str(fd),
                                    "--log-level", "warning", "--no-access-log"], fd=fd)
        if not (name == "credentials" and self.permit_proxy_url):
            self.sockets[name].close()

    def crash_issuer(self, serial):
        if self.permitted_serial:
            return False
        self.processes["credentials"].kill()
        self.processes["credentials"].wait(timeout=10)
        self.permitted_serial = serial
        return True

    def ready(self, name):
        if self.processes[name].poll() is not None:
            raise RuntimeError(f"{name} exited: {(self.temp / (name+'.log')).read_text()[-1200:]}")
        try:
            return self.checker.get(self.urls[name] + "/__smoke_probe").status_code == 404
        except httpx.TransportError:
            return False

    def launch(self):
        # 专项测试可只启少数下游。完整部署才配置全部服务地址，不能把未监听的预留端口当在线服务。
        for owner in ("profile", "career", "media", "usage"):
            self.env[owner.upper() + "_SERVICE_URL"] = self.urls[owner]
        # 提前确认当前解释器信任本地模型测试服务的 TLS 证书，验证失败即停止。
        self.command(["-c", "import os,httpx; "
                      "r=httpx.post(os.environ['AI_BASE_URL']+'/chat/completions', "
                      "headers={'Authorization':'Bearer synthetic-model-token'},json={'messages':[]}); "
                      "r.raise_for_status()"])
        # 空库开校完全经原生身份域：不复制旧账号，不导入离线夹具。
        self.command(["-m", "services.identity.bootstrap", "--school", SCHOOL, "--email", MASTER,
                      "--name", "验收校管", "--password-stdin"], SERVICE_ID="identity",
                     stdin_text=self.master_env["ADMIN_MASTER_PASSWORD"] + "\n")
        for name in APPS:
            self.start_app(name)
        for name in APPS:
            until(name, lambda: self.ready(name), seconds=120)
        self.seed_teaching_accounts()
        self.start("score-worker", "assessment", ["-m", "services.interview.worker", "--kinds", "score,report,analytics"])
        kinds = "train_complete,project,media_close"
        self.start("completion-worker", "interview", ["-m", "services.interview.worker", "--kinds", kinds])
        self.start("anchor-relay", "credentials", ["-m", "services.credentials.relay"])


    def seed_teaching_accounts(self):
        origin = self.urls["admin-gateway"]
        with httpx.Client(base_url=origin, headers={"Origin": origin}, trust_env=False, timeout=15) as browser:
            call(browser, "POST", "/api/admin/auth/login",
                 {"email": MASTER, "password": self.master_env["ADMIN_MASTER_PASSWORD"]})
            call(browser, "PUT", "/api/admin/usage/quota", {"text":100, "media":10})
            actions = ["interview.records.read", "report.read", "report.review", "report.export", "score.adjust",
                       "training.assign", "training.read", "credential.read", "credential.approve", "credential.issue",
                       "credential.revoke", "analytics.teaching.read", "analytics.practice.assign", "operations.rtc.read"]
            self.teachers = {}
            for name in ("owner", "coworker"):
                user = call(browser, "POST", "/api/admin/identity/v1/staff",
                            {"email": name+"@example.test", "name": name, "password": TEACHER_PASSWORD,
                             "actor_type": "teacher", "permissions": actions})
                self.teachers[name] = user["actor_id"]
            call(browser, "POST", "/api/admin/identity/v1/organization/import",
                 {"colleges":[{"id":"college","name":"Demo"}],
                  "programs":[{"id":"program","name":"Program","college_id":"college"}],
                  "classes":[{"id":"cls","name":"Class","program_id":"program","staff_ids":list(self.teachers.values())}]})
        print("PASS: 空学校从原生身份库开户，经管理网关创建教师并分配班级", flush=True)


def call(client, method, path, body=None, ok=(200, 201)):
    result = client.request(method, path, json=body)
    if result.status_code not in ok:
        raise AssertionError(f"{method} {path}: expected {ok}, got {result.status_code}: {result.text[:480]}")
    return result.json()


def exercise(deployment, stack):
    def browser(name):
        url = deployment.urls[name]
        return stack.enter_context(httpx.Client(base_url=url, headers={"Origin": url}, timeout=15, trust_env=False))
    student = browser("student-gateway")
    manager = browser("admin-gateway")
    teacher = browser("admin-gateway")
    unrelated = browser("admin-gateway")
    verify = browser("public")
    # 在独立评分进程启动后更新模型配置，验证报告中记录的是控制服务新选定的模型。
    now = int(time.time())
    config_token = jwt.encode({"iss": "admin-gateway", "aud": "providers", "school_id": "platform",
                               "actor_type": "admin", "sub": "fixture-operator", "scopes": ["providers.configure"],
                               "iat": now, "exp": now + 30, "jti": "configure-model"},
                              deployment.keys["admin-gateway"][0], algorithm="EdDSA",
                              headers={"kid": "smoke", "typ": "service+jwt"})
    edited = deployment.checker.patch(deployment.urls["providers"] + "/settings",
                                      json={"reportCustomModel": "smoke-control-edit"},
                                      headers={"Authorization": "Bearer " + config_token})
    assert edited.status_code == 200
    call(manager, "POST", "/api/admin/auth/login", {"email": MASTER, "password": deployment.master_env["ADMIN_MASTER_PASSWORD"]})
    initial = "Temporary-7-Campus!"
    imported = call(manager, "POST", "/api/admin/identity/students/import",
                    {"students": [{"name": "New Student", "student_no": "S1001", "temporary_password": initial}]})
    sid = imported["students"][0]["actor_id"]
    call(manager, "POST", "/api/admin/identity/v1/classes/cls/roster/import", {"student_ids": [sid]})
    assert not Path(deployment.env["SQLITE_PATH"]).exists(), "正式链路意外创建了旧库"
    call(student, "POST", "/api/auth/login", {"student_no":"S1001","password":initial})
    call(student, "POST", "/api/auth/change-initial-password", {"password": PASSWORD, "confirm_password": PASSWORD})
    for name, client in (("owner", teacher), ("coworker", unrelated)):
        call(client, "POST", "/api/admin/auth/login", {"email":name+"@example.test","password":TEACHER_PASSWORD})
    assert student.cookies.get("identity_student_session")
    assert teacher.cookies.get("identity_staff_session") and unrelated.cookies.get("identity_staff_session")
    policy_path = "/api/admin/interviewer-policy"
    current = call(manager, "GET", policy_path)
    update = {**current["policy"], "studentCanChoose": not current["policy"]["studentCanChoose"]}
    edited = call(manager, "PUT", policy_path, {"expected_revision": current["revision"], "policy": update})
    assert edited["revision"] != current["revision"] and edited["policy"] == update
    call(manager, "PUT", policy_path, {"expected_revision": current["revision"], "policy": current["policy"]}, ok=(409,))
    call(teacher, "GET", policy_path, ok=(403,))
    assert call(manager, "GET", policy_path)["policy"] == update
    assignment = {"class_ids":["cls"], "title":"Transactions", "job_role":"Engineer",
                  "questions":[{"question_id":"question-1","prompt":"Explain a row lock."}], "max_attempts":1,
                  "deadline":(datetime.now(timezone.utc)+timedelta(hours=2)).isoformat()}
    task = call(teacher, "POST", "/api/admin/training/tasks", assignment)["task_id"]
    assert task in {t["task_id"] for t in call(student, "GET", "/api/training/tasks")["items"]}
    call(unrelated, "GET", f"/api/admin/training/tasks/{task}/roster", ok=(403,404))
    # 发送方可以签发两所学校的令牌。即使教师标识相同，训练服务也必须拒绝访问另一所学校的资源。
    now = int(time.time())
    token = jwt.encode({
        "iss": "admin-gateway", "aud": "training", "sub": deployment.teachers["owner"], "school_id": "other-smoke-school",
        "actor_type": "teacher", "scopes": ["training.read"], "iat": now, "exp": now + 30,
        "jti": "cross-school-test",
    }, deployment.keys["admin-gateway"][0], algorithm="EdDSA", headers={"kid": "smoke", "typ": "service+jwt"})
    cross = deployment.checker.get(deployment.urls["training"] + f"/tasks/{task}/roster",
                                   headers={"Authorization": f"Bearer {token}"})
    assert cross.status_code == 404, "Foreign school could distinguish or read the roster"
    attempt = call(student, "POST", f"/api/training/tasks/{task}/attempts", {"request_id":"claim-1"})
    opened = call(student, "POST", "/api/interviews/training-attempts/"+attempt["attempt_id"], {})
    base = "/api/interviews/"+opened["interview_id"]
    # 使用真实学生会话写 RTC，学校管理端从独立诊断库读取，原始信令与敏感元数据不得出现在结果中。
    call(student, "POST", base+"/webrtc-events", {"event_type":"call_start_requested","session_id":"rtc-secret-canary",
         "message":"rtc-secret-canary","metadata":{"token":"rtc-secret-canary"}})
    rtc = call(manager, "GET", "/api/admin/connection-logs?interview_id="+opened["interview_id"])
    assert rtc["logs"][0]["student_id"] == sid and "rtc-secret-canary" not in json.dumps(rtc)
    templates = call(manager, "GET", "/api/admin/agent-templates")
    assert any(row["usageCount"] > 0 for row in templates["items"])
    call(teacher, "GET", "/api/admin/agent-templates", ok=(403,))

    until("网关审计补投",lambda: call(manager,"GET","/api/admin/security-logs?event_type=admin.login")["events"])
    print("PASS: 原生 RTC 查询与持久安全审计已接通",flush=True)
    question = call(student, "POST", base+"/current-question", {})["question"]
    assert question["content"] == "Explain a row lock."
    submission = {"question_id":question["id"], "submission_id":"synthetic-one", "content":ANSWER}
    assert call(student, "POST", base+"/turns", submission)["action"] == "finish_interview"
    assert call(student, "POST", base+"/turns", submission)["duplicate"] is True
    call(student, "POST", base+"/finish", {})
    print("PASS: cookie logins, frozen roster, scoped assignment, answer replay and finish", flush=True)
    def report_ready():
        report = call(student, "GET", base+"/report")["report"]
        return report if report["generation_status"] == "succeeded" and report["scored_answer_count"] == 1 else None
    report = until("one fully-scored worker report", report_ready)
    assert report["model"] == "smoke-control-edit"
    print("PASS: scorer without provider SQL used the live signed control-plane model edit", flush=True)
    if deployment.assessment_mode == "isolated":
        iid = opened["interview_id"]
        with sqlite3.connect(deployment.temp / "interviews.sqlite") as source:
            names = {r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            assert not names.intersection({"users", "sessions", "interview_reports", "interview_evaluations"})
            assert source.execute("SELECT school_id FROM interview_database_owner").fetchone() == (SCHOOL,)
        with sqlite3.connect(deployment.temp / "assessment.sqlite") as dest:
            assert dest.execute("SELECT id FROM interview_reports WHERE interview_id=?", (iid,)).fetchone()[0] == report["id"]
            assert not dest.execute("SELECT 1 FROM sqlite_master WHERE name IN ('users','sessions')").fetchone()
        print("PASS: isolated assessment owns the report and has no login or source DB", flush=True)
    for owner, record_id in (("interview", opened["interview_id"]), ("assessment", report["id"])):
        records = "/api/admin/" + owner + "/v1/records"
        assert call(manager, "GET", records + "?kind=training&class_id=cls")["items"][0]["id"] == record_id
        assert call(unrelated, "GET", records + "/" + record_id)["student_id"] == sid
    print("PASS: class readers and school administrators see records through both native owners", flush=True)
    report_base = "/api/admin/reports/"+report["id"]
    analytics = "/api/admin/analytics/v1/teaching/"
    observed = until("worker evidence in the teaching view",
                     lambda: call(teacher, "GET", analytics+"weaknesses")["items"])
    assert len(observed) == 1 and observed[0]["original_answer"] == ANSWER
    assert not call(unrelated, "GET", analytics+"weaknesses")["items"]
    practice = {"attempt_id":attempt["attempt_id"], "question_id":observed[0]["question_id"],
                "deadline":assignment["deadline"], "max_attempts":1, "request_id":"practice-1"}
    followup = call(teacher, "POST", analytics+"practice", practice)
    assert followup["source_attempt_id"] == attempt["attempt_id"]
    assert followup["task_id"] in {t["task_id"] for t in call(student, "GET", "/api/training/tasks")["items"]}
    print("PASS: class evidence isolated by teacher, targeted practice reaches the student", flush=True)
    until("training completion", lambda: call(teacher, "GET", f"/api/admin/training/tasks/{task}/roster")["items"][0]["completed_attempts"] == 1)
    version = call(teacher, "GET", report_base+"/history")["report"]["version"]
    reference = "/api/admin/interviews/" + opened["interview_id"] + "/report-reference"
    assert call(teacher, "GET", reference)["report_id"] == report["id"]
    call(unrelated, "GET", reference, ok=(403, 404))
    assert call(teacher, "GET", report_base + "/export")["version"] == version
    call(unrelated, "GET", report_base + "/export", ok=(403, 404))
    change = {"expected_version":version,"total_score":84,"reason":"Reviewed original answer"}
    call(unrelated, "PATCH", report_base+"/score", change, ok=(403,404))
    call(teacher, "PATCH", report_base+"/score", change)
    version = call(teacher, "GET", report_base+"/history")["report"]["version"]
    call(teacher, "PATCH", report_base+"/review", {"expected_version":version,"status":"approved","note":"Checked"})
    print("PASS: background score/report delivery, only the assigned teacher can adjust grade and review", flush=True)
    application = call(student, "POST", "/api/credentials/applications", {"report_id":report["id"]})
    application_base = "/api/admin/credentials/applications/"+application["id"]
    decision = {"decision":"approved","version":version,"digest":application["evidence"]["digest"]}
    call(unrelated, "POST", application_base+"/review", decision, ok=(403,404))
    call(teacher, "POST", application_base+"/issue", {}, ok=(409,))
    call(teacher, "POST", application_base+"/review", decision)
    if deployment.permit_proxy_url:
        call(teacher, "POST", application_base+"/issue", {}, ok=(502, 503))
        until("issuer killed after assessment commit", lambda: deployment.permitted_serial)
        with sqlite3.connect("file:" + deployment.env["CREDENTIALS_SQLITE_PATH"] + "?mode=ro", uri=True) as db:
            assert db.execute("SELECT COUNT(*) FROM teaching_certificates").fetchone() == (0,)
            assert db.execute("SELECT serial FROM credential_issuance_intents").fetchone() == (deployment.permitted_serial,)
        call(teacher, "PATCH", report_base+"/score", {"expected_version": version, "total_score": 85,
                                                     "reason": "Grade change after durable issuance permit"})
        deployment.start_app("credentials")
        until("restarted credentials instance", lambda: deployment.ready("credentials"))
    cert = call(teacher, "POST", application_base+"/issue", {})
    if deployment.permit_proxy_url:
        assert cert["id"] == deployment.permitted_serial
        print("PASS: issuer SIGKILL after permit commit, later grade edit, same serial recovered", flush=True)
    assert call(teacher, "POST", application_base+"/issue", {})["id"] == cert["id"]
    documents = call(student, "GET", "/api/credentials/me/applications")
    serials = [item for row in documents["items"] for item in row["certificates"]]
    proof = next(item["proof"] for item in serials if item["id"] == cert["id"])
    file = deployment.temp / "credential.json"
    file.write_text(json.dumps(proof), encoding="utf-8")
    verifier = ["-m", "services.credentials.verify_file", str(file), "--issuer", SCHOOL,
                "--serial", cert["id"], "--status"]
    verifier_env = {"CREDENTIALS_PUBLIC_SERVICE_URL": deployment.urls["public"]}
    def file_status(code):
        return json.loads(deployment.command(verifier, expected_exit=code, **verifier_env))
    def anchor_received():
        state = call(verify, "GET", cert["verification_url"])
        assert state["status"] == "valid"
        return state["anchor"]["status"] == "pending"
    until("signed issue recorded in the provenance service", anchor_received)
    assert file_status(0)["status"] == "valid"
    deployment.stop("provenance")
    cancel = "/api/admin/credentials/certificates/"+cert["id"]+"/revoke"
    call(unrelated, "POST", cancel, {"reason":"wrong issuer"}, ok=(403,404))
    call(teacher, "POST", cancel, {"reason":"Superseded"})
    revoked = call(verify, "GET", cert["verification_url"])
    assert not revoked["valid"] and revoked["status"] == "revoked"
    assert revoked["anchor"]["status"] != "confirmed"
    assert file_status(1)["status"] == "revoked"
    deployment.stop("public")
    offline = file_status(2)
    assert offline["signature"] == "verified" and offline["status"] == "unknown"
    print("PASS: teacher approval, idempotent signed issue, public verification and revocation during chain outage", flush=True)
    return dict(school=SCHOOL, teacher=deployment.teachers["owner"], student=sid, task=task, attempt=attempt["attempt_id"],
                interview=opened["interview_id"], report=report["id"], serial=cert["id"],
                signature=proof["signature"], application=application["id"], answer=ANSWER,
                review_version=version, latest_score=85 if deployment.permit_proxy_url else 84)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assessment-mode", choices=("isolated",), default="isolated")
    parser.add_argument("--crash-issuance", action="store_true",
                        help="Kill the synthetic credentials process after assessment commits a permit")
    parser.add_argument("--restore-drill", action="store_true",
                        help="Freeze and restore all seven synthetic isolated-school SQLite domains")
    args = parser.parse_args()
    if args.restore_drill and args.assessment_mode != "isolated":
        parser.error("--restore-drill requires the isolated assessment database")
    with tempfile.TemporaryDirectory(prefix="interview-smoke-") as folder, ExitStack() as stack:
        temp = Path(folder)
        prepare_sources(temp, include_archive=False)
        assert not (temp / "backend").exists() and not (temp / "admin_backend").exists()
        deployment = Deployment(temp, stack, args.assessment_mode, args.crash_issuance)
        deployment.launch()
        expected = exercise(deployment, stack)
        if args.restore_drill:
            from smoke_restore import exercise_restore
            exercise_restore(deployment, expected)


if __name__ == "__main__":
    main()
