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
            autocommit=False,
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
