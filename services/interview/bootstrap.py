"""只初始化当前进程所属的数据库，拒绝在未标记的历史库上就地建表。"""
from contextlib import closing
import os

from shared.interviewer_policy import ensure_interviewer_policy_schema
from . import assessment_events, profile_context, training_rounds
from .input_schema import INPUT_TABLES
from .job_store import interview_jobs
from .storage import DB_ENGINE, db, one


def _index(name, table, columns, *, unique=False):
    """固定名称和列来自模块内的清单，重复启动时只补缺失的索引。"""
    kind = "UNIQUE " if unique else ""
    if DB_ENGINE == "sqlite":
        db.execute(f"CREATE {kind}INDEX IF NOT EXISTS {name} ON {table}({columns})").close()
        return
    if one("SELECT 1 AS present FROM information_schema.STATISTICS "
           "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=? AND INDEX_NAME=? LIMIT 1",(table,name)):
        return
    import pymysql
    try:
        db.execute(f"CREATE {kind}INDEX {name} ON {table}({columns})").close()
    except pymysql.MySQLError as exc:
        # 接口和投递进程可以同时启动。只忽略另一进程已经完成同名建索引的情况。
        if exc.args[0] != 1061:
            raise


def initialize_interview():
    if os.environ.get("SERVICE_ID") != "interview":
        raise RuntimeError("面试运行时只能使用面试服务身份")
    school = os.environ.get("LEGACY_SCHOOL_ID")
    if not school or len(school) > 128:
        raise RuntimeError("启动面试服务前必须绑定学校。")
    mysql = DB_ENGINE == "mysql"
    inspect = "SHOW TABLES" if mysql else "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    with closing(db.execute(inspect)) as cursor:
        names = {next(iter(dict(row).values())) for row in cursor.fetchall()}
    if names and ("interview_database_owner" not in names or names & {"users", "interview_reports", "assessment_database_owner"}):
        raise RuntimeError("面试专库必须为空库或属于同一学校的已标记专库。")
    suffix = " ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci" if mysql else ""
    exact = " COLLATE utf8mb4_bin" if mysql else ""
    conflict = "ON DUPLICATE KEY UPDATE slot=slot" if mysql else "ON CONFLICT(slot) DO NOTHING"
    with db:
        db.execute(f"""CREATE TABLE IF NOT EXISTS interview_database_owner (
                   slot INT PRIMARY KEY, school_id VARCHAR(128){exact} NOT NULL){suffix}""").close()
        db.execute("INSERT INTO interview_database_owner VALUES (1,?) "+conflict, (school,)).close()
        if one("SELECT school_id FROM interview_database_owner WHERE slot=1")["school_id"] != school:
            raise RuntimeError("面试专库绑定的学校不匹配。")
        for ddl in INPUT_TABLES:
            ddl = ddl.replace("user_id CHAR(36)", "user_id CHAR(36)"+exact)
            ddl = ddl.replace("source_ref VARCHAR(128)", "source_ref VARCHAR(128)"+exact)
            db.execute(ddl+suffix).close()
        db.execute("""CREATE TABLE IF NOT EXISTS interview_progress (
                   interview_id CHAR(36) PRIMARY KEY, question_id CHAR(36), agent_id CHAR(36),
                   last_submission_id VARCHAR(128), FOREIGN KEY(interview_id) REFERENCES interview_sessions(id)
                   ON DELETE CASCADE)"""+suffix).close()
    # 并发 RTC 字幕重发由物理唯一键兜底；重复来源不能产生第二次回答和评分。
    _index("uq_interview_messages_source_ref","interview_messages","interview_id,source,source_ref",unique=True)
    _index("idx_interview_subject","interview_sessions","user_id,id")
    _index("idx_interview_message_order","interview_messages","interview_id,order_index")
    _index("idx_interview_agent_order","interview_agents","interview_id,order_index")
    ensure_interviewer_policy_schema(db, DB_ENGINE)
    training_rounds.migrate()
    profile_context.initialize()
    interview_jobs.migrate()
    assessment_events.initialize(db, mysql)


def initialize_assessment():
    if os.environ.get("SERVICE_ID") != "assessment":
        raise RuntimeError("评估运行时只能使用评估服务身份")
    from services.assessment import evidence, schema, versions
    from services.usage import worker as text_usage

    schema.initialize(db, DB_ENGINE)
    training_rounds.migrate()
    profile_context.initialize()
    evidence.init_schema(db, DB_ENGINE)
    versions.init_schema()
    interview_jobs.migrate()
    text_usage.initialize(interview_jobs)
