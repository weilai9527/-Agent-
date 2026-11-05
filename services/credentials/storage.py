"""证书专库的表结构。签发记录及其待存证事件由同一事务写入。"""

from shared.service_db import ServiceDatabase


def database():
    return ServiceDatabase.from_env("credentials")


def initialize(db):
    # 学校、操作人和密钥编号均区分大小写；初始化后再核对现有表，防止历史排序规则混淆对象。
    suffix = " ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin" if db.engine == "mysql" else ""
    db.ensure_schema(sql + suffix for sql in [
        """CREATE TABLE IF NOT EXISTS credential_applications (
            id CHAR(64) PRIMARY KEY, school_id VARCHAR(128) NOT NULL, student_id VARCHAR(128) NOT NULL,
            evidence TEXT NOT NULL, salt CHAR(64) NOT NULL, created_at VARCHAR(32) NOT NULL,
            decision VARCHAR(16) NOT NULL, reviewed_by VARCHAR(128), reviewed_at VARCHAR(32),
            review_note TEXT, first_serial CHAR(32))""",
        """CREATE TABLE IF NOT EXISTS teaching_certificates (
            serial CHAR(32) PRIMARY KEY, application_id CHAR(64) NOT NULL,
            generation INT NOT NULL, previous_serial CHAR(32), issued_at VARCHAR(32) NOT NULL,
            issued_by VARCHAR(128) NOT NULL, kid VARCHAR(128) NOT NULL, signature VARCHAR(86) NOT NULL,
            revoked_at VARCHAR(32), revoked_by VARCHAR(128), reason TEXT, successor CHAR(32),
            issue_event CHAR(32) NOT NULL, revocation_event CHAR(32),
            UNIQUE(application_id,generation),
            FOREIGN KEY(application_id) REFERENCES credential_applications(id))""",
        """CREATE TABLE IF NOT EXISTS credential_issuance_intents (
            application_id CHAR(64) NOT NULL, generation INT NOT NULL, serial CHAR(32) NOT NULL UNIQUE,
            previous_serial CHAR(32), issued_at VARCHAR(32) NOT NULL, issued_by VARCHAR(128) NOT NULL,
            kid VARCHAR(128) NOT NULL, signature VARCHAR(86) NOT NULL,
            PRIMARY KEY(application_id,generation),
            FOREIGN KEY(application_id) REFERENCES credential_applications(id))""",
        """CREATE TABLE IF NOT EXISTS credential_outbox (
            event_id CHAR(32) PRIMARY KEY, school_id VARCHAR(128) NOT NULL, digest CHAR(64) NOT NULL,
            delivered INT NOT NULL DEFAULT 0, next_try BIGINT NOT NULL DEFAULT 0,
            tries INT NOT NULL DEFAULT 0)""",
    ])
    db.require_exact_keys("credentials")
