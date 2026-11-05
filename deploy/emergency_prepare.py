"""离线制备应急状态快照和签名工单；两个子命令由备份管理员和审批人分开执行。"""
import argparse
import hashlib
import os
import re
import secrets
import sqlite3
import tempfile
import time
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from deploy.emergency import AUDIENCE, FORMAT, ISSUER, MAX_SECONDS, pinned_snapshot, read_db, snapshot_meta
from shared.service_db import ServiceDatabase, Transaction


def checksum(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


@contextmanager
def report_source(args):
    """始终从恢复副本取数。旧单校数据库没有学校列，必须另外核对其冻结文件的摘要。"""
    if args.sqlite:
        path = args.sqlite.resolve(strict=True)
        with tempfile.TemporaryDirectory(prefix="rescue-source-") as folder:
            if args.legacy_sha256:
                if any(Path(str(path) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
                    raise ValueError("旧版来源须为已合并事务日志的冻结文件")
                # 在私有副本上校验摘要后再查询，避免源路径中途替换导致学校错绑。
                import shutil
                local = Path(folder) / "source.sqlite"
                shutil.copyfile(path, local)
                if checksum(local) != args.legacy_sha256:
                    raise ValueError("旧版冻结文件摘要不匹配")
                path = local
            with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn, closing(conn.cursor()) as cur:
                cur.row_factory = sqlite3.Row
                cur.execute("PRAGMA query_only=ON")
                cur.execute("PRAGMA trusted_schema=OFF")
                cur.execute("BEGIN")
                yield Transaction(cur, "sqlite")
        return
    if args.legacy_sha256:
        raise ValueError("无学校绑定的 MySQL 旧库需先离线迁移，或转换为经核对的冻结 SQLite 副本")
    store = ServiceDatabase.from_env("emergency_source")
    if store.engine != "mysql":
        raise ValueError("请选择 SQLite 文件或配置 EMERGENCY_SOURCE_MYSQL_* 恢复专库")
    # 此进程使用恢复专库的 SELECT 账号。一个只读事务固定水位，分页时不能换连接。
    with closing(store._connect()) as conn, closing(conn.cursor()) as cursor:
        # 即使恢复账号默认 READ COMMITTED，来源校验、报告计数和所有页也必须看到同一水位。
        cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        cursor.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY")
        try:
            yield Transaction(cursor, "mysql")
        finally:
            conn.rollback()


def verify_source(tx, school, *, mysql, legacy_hash):
    """摘要只证明来源字节；即便是旧库，只要有学校字段就必须核实归属。"""
    if mysql:
        objects = tx.all("""SELECT TABLE_NAME AS name,TABLE_TYPE AS kind FROM INFORMATION_SCHEMA.TABLES
                            WHERE TABLE_SCHEMA=DATABASE()""")
        tables = {r["name"] for r in objects if r["kind"] == "BASE TABLE"}
        marked = {r["name"] for r in tx.all("""SELECT TABLE_NAME AS name FROM INFORMATION_SCHEMA.COLUMNS
                         WHERE TABLE_SCHEMA=DATABASE() AND LOWER(COLUMN_NAME)='school_id'""") if r["name"] in tables}
    else:
        objects = tx.all("SELECT name,type,sql FROM sqlite_schema WHERE type IN ('table','view')")
        tables = {r["name"] for r in objects if r["type"] == "table" and "VIRTUAL TABLE" not in r["sql"].upper()}
        marked = {name for name in tables if tx.one(
            "SELECT 1 AS has_school FROM pragma_table_info(?) WHERE lower(name)='school_id' LIMIT 1", (name,))}
    if "interview_reports" not in tables:
        raise ValueError("报告来源必须是恢复副本的实际数据表")
    owner = "assessment_database_owner"
    if owner in {r["name"] for r in objects}:
        if owner not in tables or tx.all("SELECT slot,school_id FROM assessment_database_owner LIMIT 2") != [
                {"slot":1, "school_id":school}]:
            raise ValueError("备份与请求的学校不一致")
    elif not legacy_hash:
        raise ValueError("来源缺少学校标记，须提供经核实的旧版 SQLite 摘要")
    for table in sorted(marked):
        # 表名来自系统目录；拒绝异常标识，避免以来源库中的名称拼接任意 SQL。
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table):
            raise ValueError("学校标记表名无效")
        mismatch = "BINARY school_id <> BINARY ?" if mysql else "school_id COLLATE BINARY <> ?"
        if tx.one(f"SELECT 1 AS mismatch FROM `{table}` WHERE school_id IS NULL OR {mismatch} LIMIT 1", (school,)):
            raise ValueError("备份与请求的学校不一致")


def snapshot(args):
    stamp = datetime.fromisoformat(args.as_of.replace("Z", "+00:00"))
    if stamp.tzinfo is None or stamp > datetime.now(timezone.utc):
        raise ValueError("必须提供带时区且不在未来的备份水位时间")
    output = args.output.absolute()
    with tempfile.TemporaryDirectory(dir=output.parent) as folder:
        staging = Path(folder) / "snapshot.sqlite"
        with report_source(args) as tx, closing(sqlite3.connect(staging)) as dest:
            verify_source(tx,args.school,mysql=not args.sqlite,legacy_hash=args.legacy_sha256)
            total = tx.one("SELECT COUNT(*) AS n FROM interview_reports")["n"]
            id_order = "id COLLATE BINARY" if args.sqlite else "BINARY id"
            dest.execute("CREATE TABLE snapshot_meta(format TEXT,school TEXT,as_of TEXT,report_count INTEGER)")
            dest.execute("CREATE TABLE report_status(id TEXT PRIMARY KEY,generation_status TEXT,review_status TEXT)")
            cursor = ""
            count = 0
            # 发布文件只保存状态；不读取姓名、简历、作答、分数、评语或密码。
            while True:
                batch = tx.all(f"SELECT id,generation_status,review_status FROM interview_reports WHERE {id_order}>? ORDER BY {id_order} LIMIT 512",
                               (cursor,))
                if not batch:
                    break
                dest.executemany("INSERT INTO report_status VALUES (?,?,?)",
                                 [(r["id"], r["generation_status"], r["review_status"]) for r in batch])
                cursor = batch[-1]["id"]
                count += len(batch)
            if count != total:
                raise ValueError("报告标识为空或重复，未能完整导出报告状态")
            dest.execute("INSERT INTO snapshot_meta VALUES (?,?,?,?)", (FORMAT, args.school, stamp.isoformat(), count))
            snapshot_meta(dest, args.school)
            dest.commit()
        staging.chmod(0o400)
        os.link(staging, output)
    print(f"学校={args.school} 报告数={count} SHA256={checksum(output)}")


def issue(args):
    """签名绑定学校、操作者、冻结摘要与独立口令。服务端永远拿不到审批私钥。"""
    if not all(re.fullmatch(r"[\w.@-]{1,128}", x) for x in (args.incident, args.school, args.operator)):
        raise ValueError("请提供有效的工单号、学校和操作者")
    if not 1 <= args.minutes <= MAX_SECONDS // 60:
        raise ValueError("每张工单的有效期须在 1 至 60 分钟之间")
    key = serialization.load_pem_private_key(args.key.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("审批私钥须为 Ed25519")
    src = args.snapshot.resolve(strict=True)
    with pinned_snapshot(src) as (frozen, digest), closing(read_db(frozen)) as db:
        snapshot_meta(db, args.school)
    now = int(time.time())
    bearer = secrets.token_urlsafe(32)
    ticket = jwt.encode({"iss": ISSUER, "aud": AUDIENCE, "iat": now, "nbf": now, "exp": now + 60 * args.minutes,
                         "jti": args.incident, "sub": args.operator, "school": args.school,
                         "scope": "emergency.report-status.read", "snapshot_sha256": digest,
                         "bearer_sha256": hashlib.sha256(bearer.encode()).hexdigest()},
                        key, algorithm="EdDSA", headers={"typ": "emergency+jwt"})
    # 不复用旧目录，失败时最多留下未发给运维的口令，不会出现半签发的有效工单。
    args.output.mkdir(mode=0o700)
    for name, value in (("bearer", bearer), ("permit.jwt", ticket)):
        with os.fdopen(os.open(args.output / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as stream:
            stream.write(value + "\n")
    print(f"已签发工单 {args.incident}，有效期 {args.minutes} 分钟；工单和口令须分开交付。")


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    sub = cli.add_subparsers(dest="action", required=True)
    make = sub.add_parser("snapshot", help="从恢复专库导出最小状态快照")
    sources = make.add_mutually_exclusive_group(required=True)
    sources.add_argument("--sqlite", type=Path)
    sources.add_argument("--mysql", action="store_true")
    make.add_argument("--legacy-sha256", help="校方为无学校列的旧版冻结 SQLite 文件核实的 SHA256")
    make.add_argument("--as-of", required=True, help="源备份对应的真实时间水位，必须带时区")
    sign = sub.add_parser("issue", help="在隔离审批机上签发限时工单")
    sign.add_argument("--snapshot", required=True, type=Path)
    sign.add_argument("--key", required=True, type=Path)
    sign.add_argument("--operator", required=True)
    sign.add_argument("--incident", required=True)
    sign.add_argument("--minutes", type=int, required=True)
    for command in (make, sign):
        command.add_argument("--school", required=True)
        command.add_argument("--output", required=True, type=Path)
    args = cli.parse_args()
    (snapshot if args.action == "snapshot" else issue)(args)


if __name__ == "__main__":
    main()
