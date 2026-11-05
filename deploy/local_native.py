"""单校本地原生实例的初始化、开户、配置核验与进程监管。仅生成本机演练用密钥。"""

import argparse
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .local_grants import GRANTS
from .run_service import APIS, WORKERS, check_config


ROOT = Path(__file__).resolve().parents[1]
# 没有托管链交易凭据时保留待存证事件。不能用本地假回执冒充已上链。
LOCAL_WORKERS = tuple(name for name in WORKERS if name != "chain-worker")
PROCESSES = (*APIS, *LOCAL_WORKERS)
STUDENT_WEB = "http://127.0.0.1:5173"
STAFF_WEB = "http://127.0.0.1:5174"


def service_id(name):
    return WORKERS[name][0] if name in WORKERS else name


def db_owner(name):
    if name in {"student-gateway", "admin-gateway"}:
        return None
    return "credentials" if name == "credentials-verifier" else service_id(name)


def private_key(file):
    key = Ed25519PrivateKey.generate()
    with file.open("x") as stream:
        os.chmod(file, 0o600)
        stream.write(
            key.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
            ).decode()
        )
    return (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )


def state_path(value):
    state = Path(value).expanduser().resolve()
    if state == ROOT or ROOT in state.parents or state == Path.home() or state == state.parent:
        raise ValueError("请选择代码库外单独的本地实例目录")
    return state


def initialize(state, school):
    if school == "platform" or not 1 <= len(school) <= 128 or any(c.isspace() or ord(c) < 32 for c in school):
        raise ValueError("请指定非平台学校的有效编号")
    if state.exists():
        raise ValueError("实例目录已存在，不能覆盖现有学校及其密钥")
    state.parent.mkdir(parents=True, exist_ok=True)
    # 在兄弟临时目录生成全部文件，再原子发布，避免半套学校密钥被误当成已初始化实例。
    with tempfile.TemporaryDirectory(dir=state.parent, prefix=".native-init-") as temp:
        work = Path(temp)
        for sub in ("keys", "stores", "logs", "journals"):
            (work / sub).mkdir(mode=0o700)
        public = {name: private_key(work / "keys" / (name + ".pem")) for name in GRANTS}
        cert_public = private_key(work / "keys" / "school-issuer.pem")
        manifest = {
            "version": 1,
            "school": school,
            "process_public": public,
            "certificate_public": cert_public,
        }
        (work / "instance.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        # mkdir 独占目的地，防止并发 init 静默替换另一实例的目录。
        state.mkdir(mode=0o700)
        try:
            os.replace(work, state)
        except BaseException:
            state.rmdir()
            raise
    print(f"本机原生实例已初始化：{state}；学校 {school}")


def trust_for(receiver, manifest):
    trust = {}
    for sender, targets in GRANTS.items():
        if receiver not in targets:
            continue
        issuer = service_id(sender)
        school = "platform" if receiver == "providers" else manifest["school"]
        peer = trust.setdefault(
            issuer, {"keys": {}, "schools": [school], "grants": {receiver: {}}, "key_grants": {}}
        )
        # Worker 与 API 的领域身份相同，但使用不同 kid/私钥。每个接收方仅信任确需调用它的进程公钥。
        peer["keys"][sender] = manifest["process_public"][sender]
        peer["key_grants"][sender] = {
            receiver: {role: actions.split() for role, actions in targets[receiver].items()}
        }
        grants = peer["grants"][receiver]
        for role, actions in targets[receiver].items():
            grants[role] = sorted(set(grants.get(role, [])) | set(actions.split()))
    return trust


def environment(name, state, manifest):
    owner = db_owner(name)
    actor = service_id(name)
    school = manifest["school"]
    env = {k: os.environ[k] for k in ("PATH", "SYSTEMROOT", "LANG", "TMPDIR") if k in os.environ}
    # 不继承调用 shell 的 SQL、供应商、签发、应急、代理和 PYTHONPATH 设置。
    env.update(
        APP_ENV="local",
        SERVICE_ID=actor,
        PYTHONUTF8="1",
        PYTHONNOUSERSITE="1",
        IDENTITY_SESSION_MODE="native",
        ASSESSMENT_STORAGE_MODE="isolated",
        LEGACY_SCHOOL_ID=school,
        SERVICE_TRUST_POLICY=json.dumps(trust_for(name, manifest) if name in APIS else {}),
    )
    if name in GRANTS:
        env.update(SERVICE_KEY_ID=name, SERVICE_SIGNING_KEY=(state / "keys" / (name + ".pem")).read_text())
    if owner:
        env[owner.upper() + "_DB_ENGINE"] = "sqlite"
        env[owner.upper() + "_SQLITE_PATH"] = str(state / "stores" / (owner + ".sqlite"))
    for target in GRANTS.get(name, {}):
        env[target.upper() + "_SERVICE_URL"] = f"http://127.0.0.1:{APIS[target][1]}"
    if name == "interview":
        # HTTP 进程仅检查是否部署了媒体域，以便登记收尾任务；实际媒体调用仅授权给事件 Worker。
        env["MEDIA_SERVICE_URL"] = f"http://127.0.0.1:{APIS['media'][1]}"
    if name == "career":
        env["CAREER_SCHOOL_ID"] = school
    if name in {"identity", "student-gateway", "admin-gateway"}:
        env.update(FRONTEND_ORIGIN=STUDENT_WEB, ADMIN_FRONTEND_ORIGIN=STAFF_WEB)
    if name in {"student-gateway", "admin-gateway"}:
        env["OPERATIONS_JOURNAL_DIR"] = str(state / "journals" / name)
    if name in {"credentials", "credentials-verifier"}:
        env["CREDENTIALS_PUBLIC_KEYS_JSON"] = json.dumps(
            {school: {"local-issuer": manifest["certificate_public"]}}
        )
    if name == "credentials":
        env["CREDENTIALS_SIGNING_KEYS_JSON"] = json.dumps(
            {
                school: {
                    "kid": "local-issuer",
                    "private_key": (state / "keys" / "school-issuer.pem").read_text(),
                }
            }
        )
        env["CREDENTIALS_PUBLIC_SERVICE_URL"] = f"http://127.0.0.1:{APIS['credentials-verifier'][1]}"
    check_config(name, actor, env)
    return env


def boot(state, manifest, email, name, password_stdin):
    args = [
        sys.executable,
        "-m",
        "services.identity.bootstrap",
        "--school",
        manifest["school"],
        "--email",
        email,
        "--name",
        name,
    ]
    if password_stdin:
        args.append("--password-stdin")
    subprocess.run(args, cwd=ROOT, env=environment("identity", state, manifest), check=True)


def serve(state, manifest):
    # 首先检查端口冲突，不能把外部正在运行的进程误认为本实例的就绪服务。
    for name, (_, port) in APIS.items():
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError as exc:
                raise RuntimeError(f"{name} 的本机端口 {port} 不可用") from exc
    clients = {}
    log_files = []
    stopped = False

    def shutdown(_signum, _frame):
        nonlocal stopped
        stopped = True

    def start(name):
        out = (state / "logs" / (name + ".log")).open("a", encoding="utf-8")
        log_files.append(out)
        clients[name] = subprocess.Popen(
            [sys.executable, "-m", "deploy.run_service", name],
            cwd=ROOT,
            env=environment(name, state, manifest),
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=out,
        )

    def assert_running():
        for name, child in clients.items():
            if child.poll() is not None:
                raise RuntimeError(f"{name} 提前退出，请查看 {state / 'logs' / (name + '.log')}")

    class LocalProbe(HTTPRedirectHandler):
        # 就绪探测只能触达指定的回环端口，异常响应不允许把探测引到外部站点。
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    opener = build_opener(ProxyHandler({}), LocalProbe())

    def wait_ready(names):
        # 非业务探测不创建学校数据。仅当全部子进程存活且各自 ASGI 已开始响应后再放行下一组。
        pending = set(names)
        deadline = time.monotonic() + 90
        while pending and not stopped:
            assert_running()
            for name in list(pending):
                try:
                    with opener.open(
                        f"http://127.0.0.1:{APIS[name][1]}/__native_ready__", timeout=0.5
                    ) as reply:
                        if reply.status == 200:
                            pending.remove(name)
                except HTTPError as exc:
                    if exc.code == 404:
                        pending.remove(name)
                except (URLError, TimeoutError, OSError):
                    pass
            if pending and time.monotonic() > deadline:
                raise RuntimeError("以下服务启动超时：" + "、".join(sorted(pending)))
            time.sleep(0.15)

    old_handlers = {sig: signal.signal(sig, shutdown) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        domains = [
            name for name in APIS if name not in {"student-gateway", "admin-gateway", "credentials-verifier"}
        ]
        for name in domains:
            start(name)
        wait_ready(domains)
        if stopped:
            return
        # 公开验真进程只查证书库，需等签发域完成自己的建表，再以独立身份启动。
        for name in ("credentials-verifier", "student-gateway", "admin-gateway"):
            start(name)
        wait_ready(("credentials-verifier", "student-gateway", "admin-gateway"))
        if stopped:
            return
        for name in LOCAL_WORKERS:
            start(name)
        print(
            "本机原生服务已启动。学生网关 3001，管理网关 3002；前端启动命令见 deploy/NATIVE-LOCAL.md。",
            flush=True,
        )
        while not stopped:
            assert_running()
            time.sleep(0.5)
    finally:
        # 只终止此监管器自己的子进程，不查杀其他学校或其他正在工作的端口。
        for child in reversed(list(clients.values())):
            if child.poll() is None:
                child.terminate()
        for child in clients.values():
            try:
                child.wait(timeout=8)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        for out in log_files:
            out.close()
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--state", required=True, help="代码库外本地演练实例专用目录")
    sub = cli.add_subparsers(dest="cmd", required=True)
    init = sub.add_parser("init", help="为新学校创建本机演练密钥和实例目录")
    init.add_argument("--school", required=True)
    admin = sub.add_parser("bootstrap", help="在空身份库创建第一位学校管理员")
    admin.add_argument("--email", required=True)
    admin.add_argument("--name", required=True)
    admin.add_argument(
        "--password-stdin", action="store_true", help="从标准输入读取本地初始口令，默认交互输入"
    )
    sub.add_parser("up", help="以独立环境运行所有本地原生服务，Ctrl+C 停止")
    sub.add_parser("check", help="逐个校验本机进程环境，不显示秘密值")
    policy = sub.add_parser("policy", help="输出某个接收方的公开信任配置，供人工审查")
    policy.add_argument("receiver", choices=APIS)
    args = cli.parse_args()
    try:
        state = state_path(args.state)
        if args.cmd == "init":
            initialize(state, args.school)
            return
        manifest = json.loads((state / "instance.json").read_text(encoding="utf-8"))
        if manifest.get("version") != 1:
            raise ValueError("不支持的本机实例配置版本")
        if args.cmd == "policy":
            print(json.dumps(trust_for(args.receiver, manifest), ensure_ascii=False, indent=2))
        elif args.cmd == "bootstrap":
            boot(state, manifest, args.email, args.name, args.password_stdin)
        elif args.cmd == "check":
            for name in PROCESSES:
                environment(name, state, manifest)
            print(f"{len(PROCESSES)} 个本机进程的配置检查通过")
        else:
            serve(state, manifest)
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.CalledProcessError) as exc:
        cli.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
