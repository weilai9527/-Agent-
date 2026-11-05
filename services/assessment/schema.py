"""评分和报告由评估服务维护。本库的面试记录来自面试服务的输入快照。"""
from contextlib import closing
import os

from services.interview.input_schema import INPUT_TABLES


# 保留现有评分和查询所需的表结构；账号凭据、登录会话、RTC 房间
# 及其他业务服务的数据表均不复制到评估库。
TABLES = (*INPUT_TABLES,
    """CREATE TABLE IF NOT EXISTS interview_evaluations (
    id CHAR(36) PRIMARY KEY,
    interview_id CHAR(36) NOT NULL,
    message_id CHAR(36) NOT NULL,
    agent_id CHAR(36),
    score INT NOT NULL,
    strengths MEDIUMTEXT NOT NULL,
    issues MEDIUMTEXT NOT NULL,
    suggestions MEDIUMTEXT NOT NULL,
    dimension_scores TEXT NOT NULL,
    dimension_evidence TEXT,
    provider VARCHAR(80) NOT NULL DEFAULT 'local',
    model VARCHAR(160) NOT NULL DEFAULT 'rules-v1',
    prompt_version VARCHAR(80) NOT NULL DEFAULT 'legacy-local-v1',
    generation_status VARCHAR(40) NOT NULL DEFAULT 'succeeded',
    generation_error TEXT,
    fallback TINYINT(1) NOT NULL DEFAULT 1,
    generated_at DATETIME NULL,
    review_status VARCHAR(40) NOT NULL DEFAULT 'pending',
    reviewed_by CHAR(36) NULL,
    reviewed_at DATETIME NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(interview_id, message_id),
    FOREIGN KEY (interview_id) REFERENCES interview_sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (message_id) REFERENCES interview_messages(id) ON DELETE CASCADE,
    FOREIGN KEY (agent_id) REFERENCES interview_agents(id) ON DELETE SET NULL
)""",
    """CREATE TABLE IF NOT EXISTS interview_reports (
    id CHAR(36) PRIMARY KEY,
    user_id CHAR(36) NOT NULL,
    interview_id CHAR(36) NOT NULL UNIQUE,
    total_score INT NOT NULL,
    scored_answer_count INT,
    answer_count INT,
    grade VARCHAR(20) NOT NULL,
    pass_recommendation VARCHAR(40) NOT NULL,
    ability_radar TEXT NOT NULL,
    agent_feedback MEDIUMTEXT NOT NULL,
    timeline_review MEDIUMTEXT NOT NULL,
    summary MEDIUMTEXT NOT NULL,
    suggestions MEDIUMTEXT NOT NULL,
    provider VARCHAR(80) NOT NULL DEFAULT 'local',
    model VARCHAR(160) NOT NULL DEFAULT 'rules-v1',
    prompt_version VARCHAR(80) NOT NULL DEFAULT 'legacy-local-v1',
    generation_status VARCHAR(40) NOT NULL DEFAULT 'succeeded',
    generation_error TEXT,
    fallback TINYINT(1) NOT NULL DEFAULT 1,
    generated_at DATETIME NULL,
    review_status VARCHAR(40) NOT NULL DEFAULT 'pending',
    reviewed_by CHAR(36) NULL,
    reviewed_at DATETIME NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (interview_id) REFERENCES interview_sessions(id) ON DELETE CASCADE
)""",
    """CREATE TABLE IF NOT EXISTS user_skill_stats (
    id CHAR(36) PRIMARY KEY,
    user_id CHAR(36) NOT NULL UNIQUE,
    total_interviews INT NOT NULL DEFAULT 0,
    completed_interviews INT NOT NULL DEFAULT 0,
    average_total_score INT NOT NULL DEFAULT 0,
    technical_depth_avg INT NOT NULL DEFAULT 0,
    expression_clarity_avg INT NOT NULL DEFAULT 0,
    business_understanding_avg INT NOT NULL DEFAULT 0,
    dimension_trends TEXT NOT NULL,
    weak_points TEXT NOT NULL,
    recent_training_focus VARCHAR(160),
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
)""",
    """CREATE TABLE IF NOT EXISTS assessment_projection_inbox (
    interview_id CHAR(36) NOT NULL, sequence_no BIGINT NOT NULL, school_id VARCHAR(128) NOT NULL,
    student_id CHAR(36) NOT NULL, digest CHAR(64) NOT NULL, PRIMARY KEY(interview_id,sequence_no)
)""",
)


def initialize(db, engine):
    # 通过归属标记核对学校与数据库用途。即便其他业务库的表名完全不同，
    # 误连到非空的其他库或其他学校的评估库也会拒绝启动。
    school = os.environ.get("LEGACY_SCHOOL_ID")
    if not school or len(school) > 128:
        raise RuntimeError("Assessment requires its bound school")
    inspect = ("SHOW TABLES" if engine == "mysql" else
               "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    with closing(db.execute(inspect)) as rows:
        names = {next(iter(dict(row).values())) for row in rows.fetchall()}
    if names and ("assessment_database_owner" not in names or "users" in names):
        raise RuntimeError("Assessment requires an empty database or a marked assessment store")
    suffix = " ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci" if engine == "mysql" else ""
    exact = " COLLATE utf8mb4_bin" if engine == "mysql" else ""
    conflict = "ON DUPLICATE KEY UPDATE slot=slot" if engine == "mysql" else "ON CONFLICT(slot) DO NOTHING"
    with db:
        db.execute(f"""CREATE TABLE IF NOT EXISTS assessment_database_owner
                      (slot INT PRIMARY KEY, school_id VARCHAR(128){exact} NOT NULL)""" + suffix).close()
        db.execute(f"INSERT INTO assessment_database_owner VALUES (1,?) {conflict}", (school,)).close()
        with closing(db.execute("SELECT school_id FROM assessment_database_owner WHERE slot=1")) as rows:
            if dict(rows.fetchone())["school_id"] != school:
                raise RuntimeError("Assessment database belongs to another school")
        for ddl in TABLES:
            if engine == "mysql":
                # 学生身份标识符必须精确匹配，按大小写区分查询，
                # 避免读取到另一位原生账号学生的记录。
                ddl = ddl.replace("school_id VARCHAR(128)", "school_id VARCHAR(128) COLLATE utf8mb4_bin")
                for column in ("user_id", "student_id"):
                    ddl = ddl.replace(column + " CHAR(36)", column + " CHAR(36) COLLATE utf8mb4_bin")
            db.execute(ddl + suffix).close()
        # 学校名录提供每页已获准访问的学生标识。
        # 按学生和报告编号建立索引，避免档案增长后扫描其他学生的记录。
        name = "idx_assessment_reports_subject"
        if engine == "sqlite":
            db.execute(f"CREATE INDEX IF NOT EXISTS {name} ON interview_reports(user_id,id)").close()
        else:
            with closing(db.execute("SHOW INDEX FROM interview_reports WHERE Key_name=?", (name,))) as indexes:
                present = indexes.fetchone() is not None
            if not present:
                import pymysql
                try:
                    db.execute(f"CREATE INDEX {name} ON interview_reports(user_id,id)").close()
                except pymysql.MySQLError as error:
                    # 接口进程和后台任务进程可能在同一旧库上同时启动并创建索引。
                    if error.args[0] != 1061:
                        raise
    if engine == "mysql":
        from shared.mysql_keys import check_legacy_adapter
        check_legacy_adapter(db, "assessment")
