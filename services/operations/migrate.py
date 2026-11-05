"""从运维已核对归属的单校只读快照导入诊断与审计；运行中的服务不持有源库连接信息。"""

import argparse
from contextlib import closing, contextmanager
import json
import os
import sqlite3
from uuid import UUID

from shared.service_db import ServiceDatabase, Transaction
from .events import audit_data, rtc_data, timestamp
from .store import insert, prepare


@contextmanager
def snapshot(source, target):
    if source.engine == "sqlite":
        if not source._path.is_file() or (
            target.engine == "sqlite" and target._path.exists() and source._path.samefile(target._path)
        ):
            raise ValueError("源库须为现存独立快照")
        with closing(sqlite3.connect(source._path.as_uri() + "?mode=ro", uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA query_only=ON")
            conn.execute("BEGIN")
            with closing(conn.cursor()) as cursor:
                yield Transaction(cursor, "sqlite")
    else:
        if target.engine == "mysql" and all(
            source._mysql_options[k] == target._mysql_options[k] for k in ("host", "port", "database")
        ):
            raise ValueError("源和目标不可使用同一数据库")
        # MySQL 源账号仅授 SELECT；transaction() 另外设置 READ ONLY。
        with source.transaction() as tx:
            yield tx


def batches(tx, sql):
    last = ""
    while True:
        batch = tx.all(sql, (last, 250))
        if not batch:
            return
        yield from batch
        last = batch[-1]["id"]


def migrate(source, target, school, category):
    if not school or school != os.environ.get("OPERATIONS_ARCHIVE_SCHOOL"):
        raise ValueError("请先核对只读档案并配置 OPERATIONS_ARCHIVE_SCHOOL")
    count = 0
    with snapshot(source, target) as original:
        prepare(target)
        with target.transaction(write=True) as tx:
            if category in ("rtc", "both"):
                # 不允许旧数据中伪造学生编号的日志通过班级查询泄露另一人的记录。
                query = """SELECT e.id,e.interview_id,e.user_id,e.created_at,e.event_type,e.level,e.provider,
                     e.session_id,e.connection_state,e.ice_connection_state,e.ice_gathering_state,e.signaling_state,
                     e.data_channel_state,i.user_id AS owner_id,i.id AS owned_interview
                     FROM webrtc_diagnostic_events e LEFT JOIN interview_sessions i ON i.id=e.interview_id
                     WHERE e.id>? ORDER BY e.id LIMIT ?"""
                for row in batches(original, query):
                    if row["user_id"] != row["owner_id"] or row["interview_id"] != row["owned_interview"]:
                        raise ValueError("历史 RTC 日志的面试或学生归属冲突，请离线核对")
                    insert(
                        tx,
                        target.engine,
                        school,
                        "rtc",
                        str(UUID(row["id"])),
                        row["user_id"],
                        row["interview_id"],
                        timestamp(row["created_at"]),
                        rtc_data(row),
                    )
                    count += 1
            if category in ("audit", "both"):
                query = """SELECT id,occurred_at,service,event_type,request_id,actor_id,status_code,payload_json
                         FROM security_audit_events WHERE id>? ORDER BY id LIMIT ?"""
                for row in batches(original, query):
                    event = json.loads(row["payload_json"])
                    if not isinstance(event, dict) or event.get("school_id", school) != school:
                        raise ValueError("审计记录的学校与快照声明不符")
                    source_name = row["service"]
                    if source_name not in ("candidate-api", "admin-api", "student-gateway", "admin-gateway"):
                        raise ValueError("未识别的历史审计来源")
                    event.update(
                        event_id=row["id"],
                        occurred_at=row["occurred_at"],
                        event_type=row["event_type"],
                        request_id=row["request_id"],
                        actor_id=row["actor_id"],
                        status_code=row["status_code"],
                    )
                    data = audit_data(event, source_name)
                    insert(
                        tx,
                        target.engine,
                        school,
                        "audit",
                        data["event_id"],
                        data["actor_id"],
                        "",
                        data["occurred_at"],
                        data,
                    )
                    count += 1
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--school", required=True, help="运维已核对源快照的学校编号")
    parser.add_argument(
        "--category", choices=("rtc", "audit", "both"), default="both", help="选择此快照包含的日志表"
    )
    args = parser.parse_args()
    count = migrate(
        ServiceDatabase.from_env("operations_source"),
        ServiceDatabase.from_env("operations"),
        args.school,
        args.category,
    )
    print(f"已核对并导入 {count} 条脱敏日志，重复执行不会覆盖已有记录。")


if __name__ == "__main__":
    main()
