from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import sqlite3
import threading

from . import env  # noqa: F401


ADMIN_BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = ADMIN_BACKEND_DIR.parent
DB_ENGINE = os.environ.get("DB_ENGINE", "mysql").strip().lower()
SQLITE_PATH = Path(os.environ.get("SQLITE_PATH") or PROJECT_DIR / "backend" / "data" / "dev.sqlite")


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
        raise RuntimeError("缺少 MySQL 驱动，请先执行：python3 -m pip install -r admin_backend/requirements.txt") from exc


def _normalize_sql(sql: str) -> str:
    return sql.replace("?", "%s")


class MySQLDatabase:
    def __init__(self, cfg: MySQLConfig):
        self.cfg = cfg
        self._local = threading.local()

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
        conn = getattr(self._local, "conn", None)
        if conn and getattr(conn, "open", False):
            return conn
        self._ensure_database()
        pymysql = _load_pymysql()
        conn = pymysql.connect(
            host=self.cfg.host,
            port=self.cfg.port,
            user=self.cfg.user,
            password=self.cfg.password,
            database=self.cfg.database,
            charset=self.cfg.charset,
            autocommit=True,
            cursorclass=pymysql.cursors.DictCursor,
        )
        self._local.conn = conn
        return conn

    def execute(self, sql: str, params: tuple = ()):
        conn = self.connect()
        cursor = conn.cursor()
        try:
            cursor.execute(_normalize_sql(sql), params)
            return cursor
        except Exception:
            cursor.close()
            if not getattr(conn, "open", False):
                self._local.conn = None
            raise

    def commit(self) -> None:
        self.connect().commit()

    def rollback(self) -> None:
        self.connect().rollback()

    def begin(self) -> None:
        self.connect().begin()


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
        return self._conn

    def execute(self, sql: str, params: tuple = ()):
        return self.connect().execute(sql, params)

    def commit(self) -> None:
        self.connect().commit()

    def rollback(self) -> None:
        self.connect().rollback()

    def begin(self) -> None:
        self.connect().execute("BEGIN")


db = SQLiteDatabase(SQLITE_PATH) if DB_ENGINE == "sqlite" else MySQLDatabase(config)


def row_to_dict(row):
    if row is None:
        return None
    return dict(row)


def all_rows(sql: str, params: tuple = ()) -> list[dict]:
    return [row_to_dict(row) for row in db.execute(sql, params).fetchall()]


def one(sql: str, params: tuple = ()) -> dict | None:
    return row_to_dict(db.execute(sql, params).fetchone())


def get_database_path() -> str:
    if DB_ENGINE == "sqlite":
        return f"sqlite:///{SQLITE_PATH}"
    return f"mysql://{config.user}@{config.host}:{config.port}/{config.database}"


def ensure_admin_schema() -> None:
    if DB_ENGINE == "sqlite":
        statements = [
            """
            CREATE TABLE IF NOT EXISTS admin_users (
              id TEXT PRIMARY KEY,
              email TEXT NOT NULL UNIQUE,
              password_hash TEXT NOT NULL,
              name TEXT NOT NULL,
              role TEXT NOT NULL DEFAULT '管理员',
              status TEXT NOT NULL DEFAULT 'normal',
              permissions TEXT NOT NULL DEFAULT '[]',
              student_scope TEXT,
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              last_login_at TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS admin_sessions (
              id TEXT PRIMARY KEY,
              admin_user_id TEXT NOT NULL,
              token_hash TEXT NOT NULL UNIQUE,
              expires_at TIMESTAMP NOT NULL,
              user_agent TEXT,
              ip_address TEXT,
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              FOREIGN KEY (admin_user_id) REFERENCES admin_users(id) ON DELETE CASCADE
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS admin_audit_logs (
              id TEXT PRIMARY KEY,
              admin_user_id TEXT,
              actor_email TEXT,
              action TEXT NOT NULL,
              target_type TEXT,
              target_id TEXT,
              summary TEXT,
              ip_address TEXT,
              user_agent TEXT,
              success INTEGER NOT NULL DEFAULT 1,
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              FOREIGN KEY (admin_user_id) REFERENCES admin_users(id) ON DELETE SET NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS admin_permission_requests (
              id TEXT PRIMARY KEY,
              admin_user_id TEXT NOT NULL,
              requester_email TEXT NOT NULL,
              requester_name TEXT,
              permissions TEXT NOT NULL DEFAULT '[]',
              student_scope TEXT,
              reason TEXT,
              status TEXT NOT NULL DEFAULT 'pending',
              reviewed_by TEXT,
              reviewed_at TIMESTAMP,
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              FOREIGN KEY (admin_user_id) REFERENCES admin_users(id) ON DELETE CASCADE
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS student_registrations (
              id TEXT PRIMARY KEY,
              student_no TEXT NOT NULL UNIQUE,
              name TEXT NOT NULL,
              user_id TEXT,
              imported_by TEXT,
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS campus_colleges (
              id TEXT PRIMARY KEY,
              code TEXT NOT NULL UNIQUE,
              name TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'active',
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS campus_programs (
              id TEXT PRIMARY KEY,
              college_id TEXT NOT NULL,
              standard_major_code TEXT,
              name TEXT NOT NULL,
              direction TEXT,
              coordinator TEXT,
              status TEXT NOT NULL DEFAULT 'active',
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              FOREIGN KEY (college_id) REFERENCES campus_colleges(id) ON DELETE CASCADE
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS campus_classes (
              id TEXT PRIMARY KEY,
              program_id TEXT NOT NULL,
              name TEXT NOT NULL,
              graduation_year INTEGER,
              advisor TEXT,
              invite_code TEXT NOT NULL UNIQUE,
              status TEXT NOT NULL DEFAULT 'active',
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              FOREIGN KEY (program_id) REFERENCES campus_programs(id) ON DELETE CASCADE
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS student_enrollments (
              id TEXT PRIMARY KEY,
              user_id TEXT NOT NULL UNIQUE,
              class_id TEXT,
              student_no TEXT,
              status TEXT NOT NULL DEFAULT 'active',
              focus_flag INTEGER NOT NULL DEFAULT 0,
              note TEXT,
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              FOREIGN KEY (class_id) REFERENCES campus_classes(id) ON DELETE SET NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS program_job_roles (
              id TEXT PRIMARY KEY,
              program_id TEXT NOT NULL,
              job_role_id TEXT NOT NULL,
              priority TEXT NOT NULL DEFAULT 'recommended',
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              UNIQUE(program_id, job_role_id),
              FOREIGN KEY (program_id) REFERENCES campus_programs(id) ON DELETE CASCADE
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_admin_sessions_user_id ON admin_sessions(admin_user_id)",
            "CREATE INDEX IF NOT EXISTS idx_admin_sessions_expires_at ON admin_sessions(expires_at)",
            "CREATE INDEX IF NOT EXISTS idx_admin_audit_created_at ON admin_audit_logs(created_at)",
            "CREATE INDEX IF NOT EXISTS idx_campus_programs_college ON campus_programs(college_id)",
            "CREATE INDEX IF NOT EXISTS idx_campus_classes_program ON campus_classes(program_id)",
            "CREATE INDEX IF NOT EXISTS idx_student_enrollments_class ON student_enrollments(class_id)",
            """
            CREATE TABLE IF NOT EXISTS resume_form_settings (
              id TEXT PRIMARY KEY,
              colleges TEXT NOT NULL,
              updated_by TEXT,
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """,
        ]
    else:
        statements = [
            """
            CREATE TABLE IF NOT EXISTS admin_users (
              id VARCHAR(36) PRIMARY KEY,
              email VARCHAR(255) NOT NULL UNIQUE,
              password_hash VARCHAR(255) NOT NULL,
              name VARCHAR(80) NOT NULL,
              role VARCHAR(80) NOT NULL DEFAULT '管理员',
              status VARCHAR(32) NOT NULL DEFAULT 'normal',
              permissions TEXT NULL,
              student_scope TEXT NULL,
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
              last_login_at TIMESTAMP NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            """
            CREATE TABLE IF NOT EXISTS admin_sessions (
              id VARCHAR(36) PRIMARY KEY,
              admin_user_id VARCHAR(36) NOT NULL,
              token_hash VARCHAR(64) NOT NULL UNIQUE,
              expires_at TIMESTAMP NOT NULL,
              user_agent VARCHAR(500),
              ip_address VARCHAR(80),
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              INDEX idx_admin_sessions_user_id (admin_user_id),
              INDEX idx_admin_sessions_expires_at (expires_at),
              CONSTRAINT fk_admin_sessions_user FOREIGN KEY (admin_user_id) REFERENCES admin_users(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            """
            CREATE TABLE IF NOT EXISTS admin_audit_logs (
              id VARCHAR(36) PRIMARY KEY,
              admin_user_id VARCHAR(36),
              actor_email VARCHAR(255),
              action VARCHAR(100) NOT NULL,
              target_type VARCHAR(80),
              target_id VARCHAR(255),
              summary VARCHAR(1000),
              ip_address VARCHAR(80),
              user_agent VARCHAR(500),
              success TINYINT(1) NOT NULL DEFAULT 1,
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              INDEX idx_admin_audit_created_at (created_at),
              CONSTRAINT fk_admin_audit_user FOREIGN KEY (admin_user_id) REFERENCES admin_users(id) ON DELETE SET NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            """
            CREATE TABLE IF NOT EXISTS admin_permission_requests (
              id VARCHAR(36) PRIMARY KEY,
              admin_user_id VARCHAR(36) NOT NULL,
              requester_email VARCHAR(255) NOT NULL,
              requester_name VARCHAR(80),
              permissions TEXT NOT NULL,
              student_scope TEXT,
              reason VARCHAR(1000),
              status VARCHAR(24) NOT NULL DEFAULT 'pending',
              reviewed_by VARCHAR(255),
              reviewed_at TIMESTAMP NULL,
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              INDEX idx_admin_perm_requests_user (admin_user_id),
              CONSTRAINT fk_admin_perm_request_user FOREIGN KEY (admin_user_id) REFERENCES admin_users(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            """
            CREATE TABLE IF NOT EXISTS campus_colleges (
              id VARCHAR(36) PRIMARY KEY,
              code VARCHAR(64) NOT NULL UNIQUE,
              name VARCHAR(160) NOT NULL,
              status VARCHAR(24) NOT NULL DEFAULT 'active',
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            """
            CREATE TABLE IF NOT EXISTS campus_programs (
              id VARCHAR(36) PRIMARY KEY,
              college_id VARCHAR(36) NOT NULL,
              standard_major_code VARCHAR(64),
              name VARCHAR(160) NOT NULL,
              direction VARCHAR(160),
              coordinator VARCHAR(120),
              status VARCHAR(24) NOT NULL DEFAULT 'active',
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
              INDEX idx_campus_programs_college (college_id),
              CONSTRAINT fk_campus_program_college FOREIGN KEY (college_id) REFERENCES campus_colleges(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            """
            CREATE TABLE IF NOT EXISTS campus_classes (
              id VARCHAR(36) PRIMARY KEY,
              program_id VARCHAR(36) NOT NULL,
              name VARCHAR(160) NOT NULL,
              graduation_year INT,
              advisor VARCHAR(120),
              invite_code VARCHAR(40) NOT NULL UNIQUE,
              status VARCHAR(24) NOT NULL DEFAULT 'active',
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
              INDEX idx_campus_classes_program (program_id),
              CONSTRAINT fk_campus_class_program FOREIGN KEY (program_id) REFERENCES campus_programs(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            """
            CREATE TABLE IF NOT EXISTS student_enrollments (
              id VARCHAR(36) PRIMARY KEY,
              user_id VARCHAR(36) NOT NULL UNIQUE,
              class_id VARCHAR(36),
              student_no VARCHAR(80),
              status VARCHAR(24) NOT NULL DEFAULT 'active',
              focus_flag TINYINT(1) NOT NULL DEFAULT 0,
              note VARCHAR(1000),
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
              INDEX idx_student_enrollments_class (class_id),
              CONSTRAINT fk_student_enrollment_class FOREIGN KEY (class_id) REFERENCES campus_classes(id) ON DELETE SET NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            """
            CREATE TABLE IF NOT EXISTS program_job_roles (
              id VARCHAR(36) PRIMARY KEY,
              program_id VARCHAR(36) NOT NULL,
              job_role_id VARCHAR(36) NOT NULL,
              priority VARCHAR(24) NOT NULL DEFAULT 'recommended',
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              UNIQUE KEY uq_program_job_role (program_id, job_role_id),
              INDEX idx_program_job_roles_program (program_id),
              CONSTRAINT fk_program_job_role_program FOREIGN KEY (program_id) REFERENCES campus_programs(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            """
            CREATE TABLE IF NOT EXISTS resume_form_settings (
              id VARCHAR(36) PRIMARY KEY,
              colleges TEXT NOT NULL,
              updated_by VARCHAR(255),
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
        ]

    for statement in statements:
        cursor = db.execute(statement)
        cursor.close()
    db.commit()

    _migrate_admin_users()

    from shared.career_catalog import ensure_catalog_schema, seed_computer_pilot

    ensure_catalog_schema(db, DB_ENGINE)
    seed_computer_pilot(db)


def _migrate_admin_users() -> None:
    """兼容升级：为 admin_users 补充权限列；仅在首次迁移时清空旧的角色制管理员账号。

    新权限模型下，历史角色（reviewer / operations）不再参与权限判断，
    管理端启动后只会保留代码中定义的主管理员，其余账号由主管理员重新创建。
    """
    if DB_ENGINE == "sqlite":
        columns = {row["name"] for row in db.execute("PRAGMA table_info(admin_users)").fetchall()}
        if "permissions" not in columns:
            db.execute("ALTER TABLE admin_users ADD COLUMN permissions TEXT NOT NULL DEFAULT '[]'")
        if "student_scope" not in columns:
            db.execute("ALTER TABLE admin_users ADD COLUMN student_scope TEXT")
        missing = [column for column in ("permissions", "student_scope") if column not in columns]
    else:
        rows = all_rows(
            """
            SELECT COLUMN_NAME FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'admin_users'
            """
        )
        existing = {str(row.get("COLUMN_NAME") or "") for row in rows}
        missing = [column for column in ("permissions", "student_scope") if column not in existing]
        for column in missing:
            db.execute(f"ALTER TABLE admin_users ADD COLUMN {column} TEXT NULL")
    if missing:
        db.execute("DELETE FROM admin_users")
        db.commit()
