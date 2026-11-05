"""在空的原生学校身份库创建首位管理员。此运维命令不提供 HTTP 接口，也不能重置已有账户。"""
import argparse
import getpass
import json
import os
import re
import sys
from uuid import uuid4

from shared.account_security import hash_staff_password as hash_password, is_valid_email, normalize_email
from shared.service_db import ServiceDatabase
from .app import initialize
from .organization import audit, lock_school
from .permissions import NATIVE_EXPLICIT_GRANTS, STAFF_ACTIONS, TEACHER_ONLY


def provision(store, school, email, name, password):
    if not isinstance(school, str) or not re.fullmatch(r"[\w.-]{1,128}", school):
        raise ValueError("无效的学校标识")
    email = normalize_email(email)
    if not is_valid_email(email) or not 1 <= len(name.strip()) <= 160 or not 12 <= len(password) <= 128:
        raise ValueError("请输入有效邮箱、姓名和 12 至 128 字符的口令")
    # 该账号用于学校初始管理。负责教师专有动作永远不作为管理员初始权限。
    grants = set(STAFF_ACTIONS) - TEACHER_ONLY - NATIVE_EXPLICIT_GRANTS
    if school != "platform":
        grants -= {"model.config.read", "model.config.write"}
    actor_id = uuid4().hex
    password_hash = hash_password(password)
    initialize(store)
    with store.transaction(write=True) as tx:
        lock_school(tx, store, school)
        if tx.one("SELECT actor_id FROM identity_staff WHERE school_id=? LIMIT 1", (school,)):
            raise ValueError("本校已有职员，初始化命令不能覆盖身份或提升权限")
        tx.execute("""INSERT INTO identity_staff
            (school_id,actor_id,email,password_hash,name,actor_type,status,permissions,school_wide)
            VALUES (?,?,?,?,?,'admin','normal',?,1)""",
                   (school, actor_id, email, password_hash, name.strip(), json.dumps(sorted(grants))))
        audit(tx, {"school_id": school, "actor_id": "school-bootstrap"}, "staff.bootstrap", actor_id)
    return actor_id


def main():
    from shared.runtime_mode import require_native_runtime
    require_native_runtime()
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--school", required=True)
    cli.add_argument("--email", required=True)
    cli.add_argument("--name", required=True)
    cli.add_argument("--password-stdin", action="store_true", help="从受保护的标准输入读取单行口令")
    args = cli.parse_args()
    if os.environ.get("SERVICE_ID") != "identity" or os.environ.get("LEGACY_SCHOOL_ID") != args.school:
        cli.error("请核对 SERVICE_ID=identity 和当前部署绑定的学校")
    password = sys.stdin.readline(132).rstrip("\r\n") if args.password_stdin else getpass.getpass("设置主管理员口令：")
    try:
        actor = provision(ServiceDatabase.from_env("identity"), args.school, args.email, args.name, password)
    except ValueError as exc:
        cli.error(str(exc))
    print(f"原生身份库已初始化，学校={args.school} 管理员编号={actor}")


if __name__ == "__main__":
    main()
