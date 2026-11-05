"""微服务进程注册表。启动前校验身份、数据库归属和秘密的投放边界。"""

import argparse
import os
import sys
from pathlib import Path

from shared.runtime_mode import require_native_runtime


APIS = {
    "student-gateway": ("services.gateway.student:app", 3001),
    "admin-gateway": ("services.gateway.admin:app", 3002),
    "identity": ("services.identity.app:app", 8101),
    "profile": ("services.profile.app:app", 8102),
    "career": ("services.career.app:app", 8103),
    "training": ("services.training.app:app", 8104),
    "interview": ("services.interview.app:app", 8105),
    "media": ("services.media.app:app", 8106),
    "assessment": ("services.assessment.app:app", 8107),
    "analytics": ("services.analytics.app:app", 8108),
    "credentials": ("services.credentials.app:app", 8109),
    "usage": ("services.usage.app:app", 8110),
    "provenance": ("services.provenance.app:app", 8111),
    "providers": ("services.providers.app:app", 8112),
    "operations": ("services.operations.app:app", 8114),
    "credentials-verifier": ("services.credentials.app:public_app", 8113),
}

WORKERS = {
    "interview-events": ("interview", "services.interview.worker", "--kinds", "train_complete,project,media_close"),
    "assessment-jobs": ("assessment", "services.interview.worker", "--kinds", "score,report,analytics"),
    "credential-relay": ("credentials", "services.credentials.relay"),
    "chain-worker": ("provenance", "services.provenance.worker"),
}


def check_config(name, actor, env):
    if env.get("SERVICE_ID") != actor:
        raise ValueError(f"This process requires SERVICE_ID={actor}")
    require_native_runtime(env)
    # 签发密钥仅交给签发进程。转发器、验真器和链提交进程各用自己的身份。
    for setting, owner in (("CREDENTIALS_SIGNING_KEYS_JSON", "credentials"),
                           ("PROVENANCE_SUBMIT_TOKEN", "chain-worker")):
        if env.get(setting) and name != owner:
            raise ValueError(f"Only {owner} may receive {setting}")
    production = env.get("APP_ENV", "").strip().lower() == "production"
    if production and name != "providers" and any(
        value and (key in {"PROVIDERS_DB_ENGINE", "PROVIDERS_SQLITE_PATH"} or key.startswith("PROVIDERS_MYSQL_"))
        for key, value in env.items()
    ):
        raise ValueError("Only the providers process may receive the model control database configuration")
    if production and name in {"student-gateway", "admin-gateway"}:
        if any(value and key.endswith(("MYSQL_PASSWORD", "SQLITE_PATH")) for key, value in env.items()):
            raise ValueError("Native gateways may not receive business database credentials or paths")
    if name not in {"interview", "assessment", "assessment-jobs", "interview-events"}:
        return
    if not env.get("LEGACY_SCHOOL_ID"):
        raise ValueError("A bound school is required for the interview and assessment stores")
    if production and actor == "assessment" and not env.get("USAGE_SERVICE_URL"):
        raise ValueError("Configure USAGE_SERVICE_URL for the isolated production assessment owner")
    prefix = "ASSESSMENT_" if actor == "assessment" else "INTERVIEW_"
    engine = env.get(prefix + "DB_ENGINE")
    if engine == "sqlite":
        path = env.get(prefix + "SQLITE_PATH", "")
        if not Path(path).is_absolute():
            raise ValueError(f"Set an absolute {prefix}SQLITE_PATH")
    elif engine == "mysql":
        for field in ("MYSQL_HOST", "MYSQL_DATABASE", "MYSQL_USER", "MYSQL_PASSWORD"):
            if not env.get(prefix + field):
                raise ValueError(f"Explicitly configure {prefix}{field}")
        if env[prefix + "MYSQL_USER"].casefold() == "root":
            raise ValueError("Use a dedicated service database account")
    else:
        raise ValueError(f"Set {prefix}DB_ENGINE to mysql or sqlite")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name", choices=[*APIS, *WORKERS, "list"])
    parser.add_argument("--check", action="store_true", help="check process identity and configuration without starting")
    parser.add_argument("--reload", action="store_true", help="本地 HTTP 开发进程重新加载代码")
    args = parser.parse_args()
    if args.reload and (args.name not in APIS or os.getenv("APP_ENV", "").lower() == "production"):
        parser.error("仅本地 HTTP 开发进程支持 --reload")
    if args.name == "list":
        for name, (app, port) in APIS.items():
            print(f"{name:24} {port:5}  {app}")
        for name, (actor, module, *options) in WORKERS.items():
            print(f"{name:24} worker  {module} {' '.join(options)} [{actor}]")
        return
    if args.name in APIS:
        actor = args.name
        app, port = APIS[args.name]
        command = ["uvicorn", app, "--host", "127.0.0.1", "--port", str(port), "--no-access-log"]
        if args.reload:
            command.append("--reload")
    else:
        actor, *command = WORKERS[args.name]
    try:
        check_config(args.name, actor, os.environ)
    except ValueError as error:
        parser.error(str(error))
    if args.check:
        print(f"{args.name}: process boundary checks passed")
        return
    # 替换当前进程，让监管器的终止信号直接送达服务或 Worker，避免遗留任务租约。
    os.execv(sys.executable, [sys.executable, "-m", *command])


if __name__ == "__main__":
    main()
