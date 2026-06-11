from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import sqlite3

from . import env  # noqa: F401


BACKEND_DIR = Path(__file__).resolve().parents[1]
DB_ENGINE = os.environ.get("DB_ENGINE", "mysql").strip().lower()
SQLITE_PATH = Path(os.environ.get("SQLITE_PATH") or BACKEND_DIR / "data" / "dev.sqlite")


@dataclass(frozen=True)
class MySQLConfig:
    host: str = os.environ.get("MYSQL_HOST", "127.0.0.1")
    port: int = int(os.environ.get("MYSQL_PORT", "3306"))
    user: str = os.environ.get("MYSQL_USER", "root")
    password: str = os.environ.get("MYSQL_PASSWORD", "")
    database: str = os.environ.get("MYSQL_DATABASE", "multi_agent_interview")
    charset: str = os.environ.get("MYSQL_CHARSET", "utf8mb4")


config = MySQLConfig()


def _safe_identifier(value: str, label: str) -> str:
    if not re.match(r"^[A-Za-z0-9_]+$", value):
        raise RuntimeError(f"{label} 只能包含字母、数字和下划线。")
    return value


def _load_pymysql():
    try:
        import pymysql
        import pymysql.cursors

        return pymysql
    except ImportError as exc:
        raise RuntimeError("缺少 MySQL 驱动，请先执行：python3 -m pip install -r backend/requirements.txt") from exc


def _normalize_sql(sql: str) -> str:
    sql = sql.replace("?", "%s")
    sql = sql.replace("datetime('now')", "CURRENT_TIMESTAMP")
    sql = re.sub(r"datetime\(([^)]+)\)", r"\1", sql)
    return sql


class MySQLDatabase:
    def __init__(self, cfg: MySQLConfig):
        self.cfg = cfg
        self._conn = None

    def _ensure_database(self) -> None:
        pymysql = _load_pymysql()
        database = _safe_identifier(self.cfg.database, "MYSQL_DATABASE")
        charset = _safe_identifier(self.cfg.charset, "MYSQL_CHARSET")
        conn = pymysql.connect(
            host=self.cfg.host,
            port=self.cfg.port,
            user=self.cfg.user,
            password=self.cfg.password,
            charset=self.cfg.charset,
            autocommit=True,
        )
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"CREATE DATABASE IF NOT EXISTS `{database}` "
                    f"CHARACTER SET {charset} COLLATE {charset}_unicode_ci"
                )
        finally:
            conn.close()

    def connect(self):
        if self._conn:
            return self._conn

        self._ensure_database()
        pymysql = _load_pymysql()
        self._conn = pymysql.connect(
            host=self.cfg.host,
            port=self.cfg.port,
            user=self.cfg.user,
            password=self.cfg.password,
            database=self.cfg.database,
            charset=self.cfg.charset,
            autocommit=False,
            cursorclass=pymysql.cursors.DictCursor,
        )
        return self._conn

    def execute(self, sql: str, params: tuple = ()):
        conn = self.connect()
        cursor = conn.cursor()
        cursor.execute(_normalize_sql(sql), params)
        return cursor

    def commit(self) -> None:
        self.connect().commit()

    def rollback(self) -> None:
        self.connect().rollback()

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, _exc, _tb):
        if exc_type:
            self.rollback()
        else:
            self.commit()
        return False


class SQLiteDatabase:
    def __init__(self, path: Path):
        self.path = path
        self._conn = None

    def connect(self):
        if self._conn:
            return self._conn

        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA foreign_keys = ON")
        return self._conn

    def execute(self, sql: str, params: tuple = ()):
        return self.connect().execute(sql, params)

    def executescript(self, sql: str) -> None:
        self.connect().executescript(sql)

    def commit(self) -> None:
        self.connect().commit()

    def rollback(self) -> None:
        self.connect().rollback()

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, _exc, _tb):
        if exc_type:
            self.rollback()
        else:
            self.commit()
        return False


db = SQLiteDatabase(SQLITE_PATH) if DB_ENGINE == "sqlite" else MySQLDatabase(config)


def row_to_dict(row: dict | None) -> dict | None:
    return dict(row) if row else None


def rows_to_dicts(rows: list[dict]) -> list[dict]:
    return [dict(row) for row in rows]


def one(sql: str, params: tuple = ()) -> dict | None:
    cursor = db.execute(sql, params)
    try:
        return row_to_dict(cursor.fetchone())
    finally:
        cursor.close()


def all_rows(sql: str, params: tuple = ()) -> list[dict]:
    cursor = db.execute(sql, params)
    try:
        return rows_to_dicts(cursor.fetchall())
    finally:
        cursor.close()


def run(sql: str, params: tuple = ()) -> None:
    with db:
        cursor = db.execute(sql, params)
        cursor.close()


def _execute_schema(sql: str) -> None:
    cursor = db.execute(sql)
    cursor.close()


def _column_exists(table_name: str, column_name: str) -> bool:
    row = one(
        """
        SELECT COUNT(*) AS count
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = ?
          AND COLUMN_NAME = ?
        """,
        (table_name, column_name),
    )
    return bool(row and row["count"])


def _index_exists(table_name: str, index_name: str) -> bool:
    row = one(
        """
        SELECT COUNT(*) AS count
        FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = ?
          AND INDEX_NAME = ?
        """,
        (table_name, index_name),
    )
    return bool(row and row["count"])


def _ensure_index(table_name: str, index_name: str, columns: str) -> None:
    if _index_exists(table_name, index_name):
        return
    _execute_schema(f"CREATE INDEX {index_name} ON {table_name} ({columns})")


def _init_sqlite_db() -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
          id TEXT PRIMARY KEY,
          email TEXT NOT NULL UNIQUE,
          password_hash TEXT NOT NULL,
          name TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'normal',
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          last_login_at TEXT
        );

        CREATE TABLE IF NOT EXISTS profiles (
          id TEXT PRIMARY KEY,
          user_id TEXT NOT NULL UNIQUE,
          nickname TEXT,
          target_role TEXT,
          experience_level TEXT,
          resume_text TEXT,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS sessions (
          id TEXT PRIMARY KEY,
          user_id TEXT NOT NULL,
          token_hash TEXT NOT NULL UNIQUE,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          expires_at TEXT NOT NULL,
          user_agent TEXT,
          FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS password_reset_tokens (
          id TEXT PRIMARY KEY,
          user_id TEXT NOT NULL,
          token_hash TEXT NOT NULL UNIQUE,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          expires_at TEXT NOT NULL,
          used_at TEXT,
          FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS interview_sessions (
          id TEXT PRIMARY KEY,
          user_id TEXT NOT NULL,
          target_role TEXT NOT NULL,
          experience_level TEXT,
          interview_type TEXT,
          company_context TEXT,
          focus_areas TEXT,
          difficulty TEXT,
          interviewer_style TEXT,
          status TEXT NOT NULL DEFAULT 'draft',
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          started_at TEXT,
          completed_at TEXT,
          FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS interview_agents (
          id TEXT PRIMARY KEY,
          interview_id TEXT NOT NULL,
          agent_name TEXT NOT NULL,
          agent_type TEXT NOT NULL,
          agent_role TEXT NOT NULL,
          strategy TEXT,
          order_index INTEGER NOT NULL DEFAULT 0,
          status TEXT NOT NULL DEFAULT 'pending',
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY (interview_id) REFERENCES interview_sessions(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS interview_messages (
          id TEXT PRIMARY KEY,
          interview_id TEXT NOT NULL,
          agent_id TEXT,
          sender_type TEXT NOT NULL,
          message_type TEXT NOT NULL,
          content TEXT NOT NULL,
          transcript_text TEXT,
          order_index INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY (interview_id) REFERENCES interview_sessions(id) ON DELETE CASCADE,
          FOREIGN KEY (agent_id) REFERENCES interview_agents(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS interview_evaluations (
          id TEXT PRIMARY KEY,
          interview_id TEXT NOT NULL,
          message_id TEXT NOT NULL,
          agent_id TEXT,
          score INTEGER NOT NULL,
          strengths TEXT NOT NULL,
          issues TEXT NOT NULL,
          suggestions TEXT NOT NULL,
          dimension_scores TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(interview_id, message_id),
          FOREIGN KEY (interview_id) REFERENCES interview_sessions(id) ON DELETE CASCADE,
          FOREIGN KEY (message_id) REFERENCES interview_messages(id) ON DELETE CASCADE,
          FOREIGN KEY (agent_id) REFERENCES interview_agents(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS interview_reports (
          id TEXT PRIMARY KEY,
          user_id TEXT NOT NULL,
          interview_id TEXT NOT NULL UNIQUE,
          total_score INTEGER NOT NULL,
          grade TEXT NOT NULL,
          pass_recommendation TEXT NOT NULL,
          ability_radar TEXT NOT NULL,
          agent_feedback TEXT NOT NULL,
          timeline_review TEXT NOT NULL,
          summary TEXT NOT NULL,
          suggestions TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
          FOREIGN KEY (interview_id) REFERENCES interview_sessions(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS user_skill_stats (
          id TEXT PRIMARY KEY,
          user_id TEXT NOT NULL UNIQUE,
          total_interviews INTEGER NOT NULL DEFAULT 0,
          completed_interviews INTEGER NOT NULL DEFAULT 0,
          average_total_score INTEGER NOT NULL DEFAULT 0,
          technical_depth_avg INTEGER NOT NULL DEFAULT 0,
          expression_clarity_avg INTEGER NOT NULL DEFAULT 0,
          business_understanding_avg INTEGER NOT NULL DEFAULT 0,
          dimension_trends TEXT NOT NULL,
          weak_points TEXT NOT NULL,
          recent_training_focus TEXT,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_sessions_token_hash ON sessions(token_hash);
        CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
        CREATE INDEX IF NOT EXISTS idx_password_reset_token_hash ON password_reset_tokens(token_hash);
        CREATE INDEX IF NOT EXISTS idx_interview_sessions_user_id ON interview_sessions(user_id);
        CREATE INDEX IF NOT EXISTS idx_interview_sessions_status ON interview_sessions(status);
        CREATE INDEX IF NOT EXISTS idx_interview_agents_interview_id ON interview_agents(interview_id);
        CREATE INDEX IF NOT EXISTS idx_interview_messages_interview_id ON interview_messages(interview_id);
        CREATE INDEX IF NOT EXISTS idx_interview_messages_agent_id ON interview_messages(agent_id);
        CREATE INDEX IF NOT EXISTS idx_interview_evaluations_interview_id ON interview_evaluations(interview_id);
        CREATE INDEX IF NOT EXISTS idx_interview_evaluations_message_id ON interview_evaluations(message_id);
        CREATE INDEX IF NOT EXISTS idx_interview_reports_user_id ON interview_reports(user_id);
        CREATE INDEX IF NOT EXISTS idx_interview_reports_interview_id ON interview_reports(interview_id);
        CREATE INDEX IF NOT EXISTS idx_user_skill_stats_user_id ON user_skill_stats(user_id);
        """
    )

    profile_columns = [
        ("avatar_url", "TEXT"),
        ("company_type", "TEXT"),
        ("target_city", "TEXT"),
        ("expected_salary", "TEXT"),
        ("years_of_experience", "TEXT"),
        ("education_level", "TEXT"),
        ("skills", "TEXT"),
        ("project_keywords", "TEXT"),
        ("project_experience", "TEXT"),
        ("portfolio_links", "TEXT"),
        ("preferred_interview_type", "TEXT"),
        ("preferred_difficulty", "TEXT"),
        ("preferred_interviewer_style", "TEXT"),
    ]
    existing = {row["name"] for row in db.execute("PRAGMA table_info(profiles)").fetchall()}
    for name, column_type in profile_columns:
        if name not in existing:
            db.execute(f"ALTER TABLE profiles ADD COLUMN {name} {column_type}")
    db.commit()


def init_db() -> None:
    if DB_ENGINE == "sqlite":
        _init_sqlite_db()
        return

    schema_statements = [
        """
        CREATE TABLE IF NOT EXISTS users (
          id CHAR(36) PRIMARY KEY,
          email VARCHAR(255) NOT NULL UNIQUE,
          password_hash VARCHAR(255) NOT NULL,
          name VARCHAR(120) NOT NULL,
          status VARCHAR(40) NOT NULL DEFAULT 'normal',
          created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          last_login_at DATETIME NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """,
        """
        CREATE TABLE IF NOT EXISTS profiles (
          id CHAR(36) PRIMARY KEY,
          user_id CHAR(36) NOT NULL UNIQUE,
          nickname VARCHAR(120),
          target_role VARCHAR(160),
          experience_level VARCHAR(80),
          resume_text MEDIUMTEXT,
          created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """,
        """
        CREATE TABLE IF NOT EXISTS sessions (
          id CHAR(36) PRIMARY KEY,
          user_id CHAR(36) NOT NULL,
          token_hash VARCHAR(128) NOT NULL UNIQUE,
          created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          expires_at DATETIME NOT NULL,
          user_agent VARCHAR(500),
          FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """,
        """
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
          id CHAR(36) PRIMARY KEY,
          user_id CHAR(36) NOT NULL,
          token_hash VARCHAR(128) NOT NULL UNIQUE,
          created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          expires_at DATETIME NOT NULL,
          used_at DATETIME NULL,
          FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """,
        """
        CREATE TABLE IF NOT EXISTS interview_sessions (
          id CHAR(36) PRIMARY KEY,
          user_id CHAR(36) NOT NULL,
          target_role VARCHAR(160) NOT NULL,
          experience_level VARCHAR(80),
          interview_type VARCHAR(120),
          company_context VARCHAR(240),
          focus_areas TEXT,
          difficulty VARCHAR(80),
          interviewer_style VARCHAR(120),
          status VARCHAR(40) NOT NULL DEFAULT 'draft',
          created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          started_at DATETIME NULL,
          completed_at DATETIME NULL,
          FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """,
        """
        CREATE TABLE IF NOT EXISTS interview_agents (
          id CHAR(36) PRIMARY KEY,
          interview_id CHAR(36) NOT NULL,
          agent_name VARCHAR(160) NOT NULL,
          agent_type VARCHAR(80) NOT NULL,
          agent_role TEXT NOT NULL,
          strategy TEXT,
          order_index INT NOT NULL DEFAULT 0,
          status VARCHAR(40) NOT NULL DEFAULT 'pending',
          created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY (interview_id) REFERENCES interview_sessions(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """,
        """
        CREATE TABLE IF NOT EXISTS interview_messages (
          id CHAR(36) PRIMARY KEY,
          interview_id CHAR(36) NOT NULL,
          agent_id CHAR(36),
          sender_type VARCHAR(40) NOT NULL,
          message_type VARCHAR(40) NOT NULL,
          content MEDIUMTEXT NOT NULL,
          transcript_text MEDIUMTEXT,
          order_index INT NOT NULL DEFAULT 0,
          created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY (interview_id) REFERENCES interview_sessions(id) ON DELETE CASCADE,
          FOREIGN KEY (agent_id) REFERENCES interview_agents(id) ON DELETE SET NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """,
        """
        CREATE TABLE IF NOT EXISTS interview_evaluations (
          id CHAR(36) PRIMARY KEY,
          interview_id CHAR(36) NOT NULL,
          message_id CHAR(36) NOT NULL,
          agent_id CHAR(36),
          score INT NOT NULL,
          strengths MEDIUMTEXT NOT NULL,
          issues MEDIUMTEXT NOT NULL,
          suggestions MEDIUMTEXT NOT NULL,
          dimension_scores TEXT NOT NULL,
          created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(interview_id, message_id),
          FOREIGN KEY (interview_id) REFERENCES interview_sessions(id) ON DELETE CASCADE,
          FOREIGN KEY (message_id) REFERENCES interview_messages(id) ON DELETE CASCADE,
          FOREIGN KEY (agent_id) REFERENCES interview_agents(id) ON DELETE SET NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """,
        """
        CREATE TABLE IF NOT EXISTS interview_reports (
          id CHAR(36) PRIMARY KEY,
          user_id CHAR(36) NOT NULL,
          interview_id CHAR(36) NOT NULL UNIQUE,
          total_score INT NOT NULL,
          grade VARCHAR(20) NOT NULL,
          pass_recommendation VARCHAR(40) NOT NULL,
          ability_radar TEXT NOT NULL,
          agent_feedback MEDIUMTEXT NOT NULL,
          timeline_review MEDIUMTEXT NOT NULL,
          summary MEDIUMTEXT NOT NULL,
          suggestions MEDIUMTEXT NOT NULL,
          created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
          FOREIGN KEY (interview_id) REFERENCES interview_sessions(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """,
        """
        CREATE TABLE IF NOT EXISTS user_skill_stats (
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
          updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """,
    ]

    for statement in schema_statements:
        _execute_schema(statement)

    profile_columns = [
        ("avatar_url", "VARCHAR(500)"),
        ("company_type", "VARCHAR(160)"),
        ("target_city", "VARCHAR(160)"),
        ("expected_salary", "VARCHAR(160)"),
        ("years_of_experience", "VARCHAR(80)"),
        ("education_level", "VARCHAR(120)"),
        ("skills", "TEXT"),
        ("project_keywords", "TEXT"),
        ("project_experience", "MEDIUMTEXT"),
        ("portfolio_links", "TEXT"),
        ("preferred_interview_type", "VARCHAR(120)"),
        ("preferred_difficulty", "VARCHAR(80)"),
        ("preferred_interviewer_style", "VARCHAR(120)"),
    ]
    for name, column_type in profile_columns:
        if not _column_exists("profiles", name):
            _execute_schema(f"ALTER TABLE profiles ADD COLUMN {name} {column_type}")

    _ensure_index("sessions", "idx_sessions_token_hash", "token_hash")
    _ensure_index("sessions", "idx_sessions_user_id", "user_id")
    _ensure_index("password_reset_tokens", "idx_password_reset_token_hash", "token_hash")
    _ensure_index("interview_sessions", "idx_interview_sessions_user_id", "user_id")
    _ensure_index("interview_sessions", "idx_interview_sessions_status", "status")
    _ensure_index("interview_agents", "idx_interview_agents_interview_id", "interview_id")
    _ensure_index("interview_messages", "idx_interview_messages_interview_id", "interview_id")
    _ensure_index("interview_messages", "idx_interview_messages_agent_id", "agent_id")
    _ensure_index("interview_evaluations", "idx_interview_evaluations_interview_id", "interview_id")
    _ensure_index("interview_evaluations", "idx_interview_evaluations_message_id", "message_id")
    _ensure_index("interview_reports", "idx_interview_reports_user_id", "user_id")
    _ensure_index("interview_reports", "idx_interview_reports_interview_id", "interview_id")
    _ensure_index("user_skill_stats", "idx_user_skill_stats_user_id", "user_id")
    db.commit()


def get_database_path() -> str:
    if DB_ENGINE == "sqlite":
        return f"sqlite:///{SQLITE_PATH}"
    return f"mysql://{config.user}@{config.host}:{config.port}/{config.database}"


init_db()
