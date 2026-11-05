"""每所学校使用独立职业库，学校标识不参与拼接 SQL 表名或列名。"""
import json
import os
from contextlib import contextmanager
from pathlib import Path

from fastapi import HTTPException
from shared import career_catalog, recruitment
from shared.service_db import ServiceDatabase


# 职业库的表可以随版本逐步创建；迁移回执只在导入旧数据后存在。
# 旧管理库也有部分同名业务表，仅凭表名不能代替学校绑定。
_OWNED_TABLES = frozenset({
    "career_owner", "career_suggestion_events", "career_program_job_state", "career_legacy_copy",
    "program_job_roles", "job_postings", "job_matches", "job_jd_submissions",
    "catalog_versions", "catalog_colleges", "catalog_majors", "catalog_training_directions",
    "catalog_employment_directions", "catalog_job_roles", "catalog_competencies",
    "catalog_job_competencies", "catalog_role_permissions", "catalog_job_aliases",
    "catalog_job_suggestions", "catalog_job_suggestion_drafts", "catalog_import_jobs",
})


def school_databases():
    mapping = os.environ.get("CAREER_SCHOOL_DATABASES")
    engine = os.environ.get("CAREER_DB_ENGINE")
    if engine not in ("mysql", "sqlite"):
        raise ValueError("Configure CAREER_DB_ENGINE")
    key = "CAREER_SQLITE_PATH" if engine == "sqlite" else "CAREER_MYSQL_DATABASE"
    if mapping is None:
        school = os.environ.get("CAREER_SCHOOL_ID")
        if not school:
            raise ValueError("Configure a career school binding")
        mapping = {school: os.environ.get(key)}
    else:
        mapping = json.loads(mapping)
    if not isinstance(mapping, dict) or not mapping:
        raise ValueError("Invalid career school bindings")
    seen = set()
    result = {}
    for school, location in mapping.items():
        if not school or not isinstance(location, str) or not location:
            raise ValueError("Missing school database")
        canonical = str(Path(location).resolve()) if engine == "sqlite" else location.casefold()
        if canonical in seen:
            raise ValueError("Schools cannot share a career database")
        seen.add(canonical)
        result[school] = ServiceDatabase.from_env("career", {**os.environ, key: location})
    return result


def school_store(school_id):
    db = school_databases().get(school_id)
    if db is None:
        raise HTTPException(403, "School has no career database binding")
    return db


class Result:
    """为旧数据访问函数提供兼容的单次查询结果。"""
    def __init__(self, rows=None, rowcount=0):
        self.rows = rows or []
        self.rowcount = rowcount

    def close(self):
        pass

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return next(iter(self.rows), None)


class Repository:
    def __init__(self, tx, engine):
        self.tx = tx
        self.engine = engine

    def execute(self, sql, params=()):
        if sql.lstrip().upper().startswith(("SELECT", "PRAGMA", "SHOW")):
            return Result(rows=self.tx.all(sql, params))
        return Result(rowcount=self.tx.execute(sql, params))

    # 旧数据函数内部可能重复提交或回滚，统一由外层事务提交；导入等异常由外层回滚。
    def commit(self):
        pass

    def rollback(self):
        pass


def _check_destination(tx, engine, school_id):
    if engine == "sqlite":
        # GLOB 中的下划线是字面字符，不会把 sqliteX 等业务表误判成内部表。
        objects = tx.all("""SELECT name, type AS kind FROM sqlite_master
                            WHERE type IN ('table','view') AND name NOT GLOB 'sqlite_*'""")
        table_kind = "table"
    else:
        objects = tx.all("""SELECT TABLE_NAME AS name, TABLE_TYPE AS kind FROM information_schema.TABLES
                            WHERE BINARY TABLE_SCHEMA=BINARY DATABASE()""")
        table_kind = "BASE TABLE"
    if any(row["kind"] != table_kind or row["name"] not in _OWNED_TABLES for row in objects):
        raise ValueError("Career database contains a foreign table or view")
    if not objects:
        return
    tables = {row["name"] for row in objects}
    if "career_owner" not in tables:
        raise ValueError("Career requires an empty or explicitly bound service database")
    binding = tx.all("SELECT id,school_id FROM career_owner LIMIT 2")
    if not binding and tables == {"career_owner"}:
        # MySQL 创建标记表后可能在首次写入学校前退出，只有空标记表时可续建。
        return
    if binding != [{"id": 1, "school_id": school_id}]:
        raise ValueError("Career database is not exclusively bound to the requested school")


def ensure_school(school_id, seed=False):
    store = school_store(school_id)
    school_type = "VARCHAR(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin" if store.engine == "mysql" else "TEXT"
    with store.transaction(write=True) as tx:
        # 先检查所有对象及绑定，再执行首条 DDL；SQLite 写锁也保护检查与初始化之间的窗口。
        _check_destination(tx, store.engine, school_id)
        tx.execute(f"CREATE TABLE IF NOT EXISTS career_owner (id INTEGER PRIMARY KEY, school_id {school_type} NOT NULL)")
        insert = "INSERT IGNORE" if store.engine == "mysql" else "INSERT OR IGNORE"
        tx.execute(f"{insert} INTO career_owner (id,school_id) VALUES (1,?)", (school_id,))
        if tx.one("SELECT school_id FROM career_owner WHERE id=1")["school_id"] != school_id:
            raise ValueError("Career database already bound to another school")
        tx.execute("CREATE TABLE IF NOT EXISTS career_suggestion_events (digest VARCHAR(64) PRIMARY KEY)")
        # 专业 ID 来自身份服务；保留停用岗位的旧映射，供界面提示并移除。
        key = school_type
        timestamp = "DATETIME" if store.engine == "mysql" else "TEXT"
        tx.execute(f"""CREATE TABLE IF NOT EXISTS program_job_roles (
            id {key} PRIMARY KEY, program_id {key} NOT NULL, job_role_id {key} NOT NULL,
            priority VARCHAR(24) NOT NULL, created_at {timestamp} DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(program_id, job_role_id))""")
        tx.execute(f"""CREATE TABLE IF NOT EXISTS career_program_job_state (
            program_id {key} PRIMARY KEY, revision BIGINT NOT NULL)""")
        db = Repository(tx, store.engine)
        career_catalog.ensure_catalog_schema(db, store.engine)
        recruitment.ensure_recruitment_schema(db, store.engine)
        if store.engine == "mysql":
            # 旧 UUID 列可能忽略大小写。签名主体区分大小写，最长可达 128 个字符。
            for table, nullable in (("job_matches", "NOT NULL"), ("job_jd_submissions", "NULL")):
                row = tx.one("SELECT COLLATION_NAME AS collation_name, CHARACTER_MAXIMUM_LENGTH AS max_len "
                             "FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() "
                             "AND TABLE_NAME=? AND COLUMN_NAME='user_id'", (table,))
                if row["collation_name"] != "utf8mb4_bin" or row["max_len"] < 128:
                    tx.execute(f"ALTER TABLE {table} MODIFY user_id VARCHAR(128) "
                               f"CHARACTER SET utf8mb4 COLLATE utf8mb4_bin {nullable}")
    store.require_exact_keys("career")
    if seed:
        with transaction(school_id, write=True) as db:
            if not db.tx.one("SELECT id FROM catalog_versions LIMIT 1"):
                career_catalog.seed_computer_pilot(db)


@contextmanager
def transaction(school_id, *, write=False):
    store = school_store(school_id)
    with store.transaction(write=write) as tx:
        # 多个进程必须按顺序完成审核发布、导入更新等读写操作。SQLite 已获取立即写锁。
        lock = " FOR UPDATE" if write and store.engine == "mysql" else ""
        row = tx.one("SELECT school_id FROM career_owner WHERE id=1" + lock)
        if not row or row["school_id"] != school_id:
            raise HTTPException(403, "Career database belongs to another school")
        yield Repository(tx, store.engine)
