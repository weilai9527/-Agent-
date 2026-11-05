"""从已停写的单校快照导入面试和待投递证据；源库只读，目标库事务提交。"""
import argparse
from contextlib import closing, contextmanager
import hashlib
import os
from pathlib import Path
import sqlite3

from services.assessment.migration import HISTORY, PERMITS, PERMIT_COLUMNS
from services.interview.assessment_events import INPUTS, capture, encoded
from shared.service_db import ServiceDatabase


class Snapshot:
    def __init__(self, conn, mysql):
        self.conn, self.mysql = conn, mysql
        self.tables = {next(iter(row.values())) for row in self.query(
            "SHOW TABLES" if mysql else "SELECT name FROM sqlite_master WHERE type='table'")}

    def query(self, sql, params=()):
        with closing(self.conn.cursor()) as cursor:
            cursor.execute(sql.replace("?", "%s") if self.mysql else sql, params)
            return [dict(row) for row in cursor.fetchall()]

    def rows(self, table, columns, *, where="", params=(), order=""):
        if table not in self.tables:
            return []
        return self.query(f"SELECT {','.join(columns.split())} FROM {table}" + where + order, params)


@contextmanager
def open_snapshot(path):
    if path is None:
        source = ServiceDatabase.from_env("interview_source")
        if source.engine != "mysql":
            raise ValueError("SQLite 快照须明确指定 --source-sqlite")
        conn = source._connect()
    else:
        if not path.is_absolute() or not path.is_file() or path.is_symlink():
            raise ValueError("仅接受已存在的绝对快照文件路径")
        target = Path(os.environ["INTERVIEW_SQLITE_PATH"]) if os.environ.get("INTERVIEW_SQLITE_PATH") else None
        if target is not None and target.exists() and path.samefile(target):
            raise ValueError("源快照不能与面试目标库相同")
        conn = sqlite3.connect(path.resolve().as_uri()+"?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
    with closing(conn):
        with closing(conn.cursor()) as cursor:
            if path is None:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                cursor.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY")
            else:
                cursor.execute("PRAGMA query_only=ON")
                cursor.execute("BEGIN")
        yield Snapshot(conn, path is None)


EXTRA = {
    "interview_progress": "interview_id question_id agent_id last_submission_id",
    "interview_report_ids": "interview_id report_id",
    "interview_assessment_streams": "interview_id sequence_no digest",
    "interview_assessment_imports": "interview_id digest",
}
JOB = "id kind interview_id subject_id version state attempts ready_at lease_token last_error created_at"
DELIVERY = "job_id interview_id school_id student_id prerequisite body"


def history(source, iid):
    reports = source.rows("interview_reports", HISTORY["interview_reports"],
                          where=" WHERE interview_id=?", params=(iid,))
    rid = reports[0]["id"] if reports else None
    data = {}
    for name, columns in HISTORY.items():
        key = "report_id" if name in {"assessment_report_versions", "assessment_report_reviews"} else "interview_id"
        order = {"assessment_report_versions": "version", "assessment_report_reviews": "version,sequence_no",
                 "interview_evaluations": "id"}.get(name,key)
        data[name] = source.rows(name, columns, where=f" WHERE {key}=?", params=(rid if key=="report_id" else iid,),
                                 order=" ORDER BY "+order)
    permits = source.rows(PERMITS, " ".join(PERMIT_COLUMNS), where=" WHERE report_id=?", params=(rid,),
                          order=" ORDER BY application_id,generation")
    if permits:
        data[PERMITS] = permits
    return data


def export_session(source, iid):
    rows = {}
    for table, fields in {**INPUTS, **EXTRA}.items():
        key = "id" if table=="interview_sessions" else "interview_id"
        # 消息存在回指外键；先插入原题，再恢复对应回答。
        order = {"interview_messages": "order_index,id", "interview_training_questions": "position",
                 "interview_turns": "submission_id", "interview_agents": "id"}.get(table, key)
        rows[table] = source.rows(table,fields,where=f" WHERE {key}=?",params=(iid,),order=" ORDER BY "+order)
    rows["interview_jobs"] = source.rows("interview_jobs", JOB, where=" WHERE interview_id=? AND kind IN ('project','train_complete','media_close')",
                                          params=(iid,), order=" ORDER BY id")
    deliveries = source.rows("interview_delivery_events", DELIVERY, where=" WHERE interview_id=?", params=(iid,),order=" ORDER BY job_id")
    keys = {job["id"] for job in rows["interview_jobs"]}
    rows["interview_delivery_events"] = [e for e in deliveries if e["job_id"] in keys]
    return rows, history(source, iid)


def insert_rows(db, table, rows):
    for row in rows:
        db.execute(f"INSERT INTO {table} ({','.join(row)}) VALUES ({','.join('?' for _ in row)})",
                   tuple(row.values())).close()


def migrate(source, school):
    from . import runtime as owner
    from .storage import DB_ENGINE, db, one
    if "interview_sessions" not in source.tables or "users" not in source.tables:
        raise ValueError("源快照缺少历史面试或所属账号表")
    with db:
        db.execute("CREATE TABLE IF NOT EXISTS interview_cutover (slot INT PRIMARY KEY,digest CHAR(64) NOT NULL)").close()
    # 作答投递和媒体关闭可在新库重试。旧评分或计量如果尚未结算，直接切换会重发模型请求。
    if "interview_jobs" in source.tables and source.query(
            "SELECT 1 FROM interview_jobs WHERE kind IN ('score','report','analytics') AND state<>'done' LIMIT 1"):
        raise ValueError("旧评分、报告或分析作业未清空；请停写并核对投递和模型结算，再重新制作快照")
    if "worker_model_attempts" in source.tables and source.query(
            "SELECT 1 FROM worker_model_attempts WHERE state NOT IN ('settled','published') LIMIT 1"):
        raise ValueError("存在未核清的模型请求；请先核对使用账本")
    fingerprint = hashlib.sha256()
    records = source.query("SELECT id FROM interview_sessions ORDER BY id")
    with db:
        if DB_ENGINE == "sqlite":
            db.execute("BEGIN IMMEDIATE").close()
        # 锁定数据库所属学校；迁移脚本与业务进程不得同时接收生产写入。
        lock = " FOR UPDATE" if DB_ENGINE=="mysql" else ""
        if one("SELECT school_id FROM interview_database_owner WHERE slot=1"+lock)["school_id"] != school:
            raise ValueError("面试库所属学校不符")
        saved = one("SELECT digest FROM interview_cutover WHERE slot=1")
        if not saved and (one("SELECT id FROM interview_sessions LIMIT 1") or one("SELECT id FROM interviewer_policy LIMIT 1")):
            raise ValueError("首次切换只能导入空业务库")
        for table, fields in (("interviewer_policy","id config"), ("interview_policy_changes","id school_id actor_id old_digest new_digest changed_at")):
            data = source.rows(table,fields,order=" ORDER BY id")
            if any(r.get("school_id",school) != school for r in data):
                raise ValueError("策略变更记录所属学校不符")
            fingerprint.update(encoded(data).encode())
            if not saved:
                insert_rows(db,table,data)
        for item in records:
            iid = item["id"]
            rows, evidence = export_session(source,iid)
            if any(r["school_id"] != school or r["student_id"] != rows["interview_sessions"][0]["user_id"]
                   for r in rows["interview_training_attempts"]+rows["interview_delivery_events"]):
                raise ValueError("历史面试的教学归属不一致")
            fingerprint.update(encoded([rows,evidence]).encode())
            if saved:
                continue
            for table, data in rows.items():
                insert_rows(db,table,data)
            streams = rows["interview_assessment_streams"]
            if not streams or rows["interview_assessment_imports"]:
                capture(owner.interview_jobs,iid,history=evidence if any(evidence.values()) else None)
            elif evidence["interview_reports"] and not rows["interview_report_ids"]:
                insert_rows(db,"interview_report_ids",[{"interview_id":iid,"report_id":evidence["interview_reports"][0]["id"]}])
        seal = fingerprint.hexdigest()
        if saved and saved["digest"] != seal:
            raise ValueError("快照内容与上次导入不同；拒绝覆盖已迁移数据")
        if not saved:
            db.execute("INSERT INTO interview_cutover VALUES (1,?)",(seal,)).close()
    return len(records)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--school",required=True)
    cli.add_argument("--source-sqlite",type=Path)
    args = cli.parse_args()
    if os.environ.get("SERVICE_ID") != "interview" or args.school != os.environ.get("LEGACY_SCHOOL_ID"):
        cli.error("必须使用指定学校的面试进程身份")
    with open_snapshot(args.source_sqlite) as snapshot:
        print(f"已核对并导入 {migrate(snapshot,args.school)} 个面试场次；开放写入前请核对事件收件进度。")


if __name__=="__main__":
    main()
