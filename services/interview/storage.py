"""按进程身份绑定面试或评估专库；网关和其他服务不能借用此连接。"""
from contextlib import closing
import os
import sqlite3
import threading

from shared.service_db import ServiceDatabase, _MYSQL_SQL_TOKENS
from shared.offline_fixture import offline_fixture_enabled


class DomainConnection:
    """一个工作线程独占一个连接；嵌套调用沿用外层事务。"""

    def __init__(self, store):
        self.store = store
        self.local = threading.local()

    def connect(self):
        conn = getattr(self.local, "conn", None)
        if conn is None or (self.store.engine == "mysql" and not conn.open):
            conn = self.store._connect()
            if self.store.engine == "sqlite":
                conn.row_factory = sqlite3.Row
                conn.isolation_level = ""
                conn.execute("PRAGMA foreign_keys=ON").close()
                conn.execute("PRAGMA journal_mode=WAL").close()
                conn.execute("PRAGMA busy_timeout=5000").close()
            else:
                conn.autocommit(True)
            self.local.conn = conn
        return conn

    def execute(self, sql, params=()):
        cursor = self.connect().cursor()
        try:
            if params and self.store.engine == "mysql":
                sql = _MYSQL_SQL_TOKENS.sub(lambda token: "%s" if token[0] == "?" else token[0], sql.replace("%", "%%"))
            if params:
                cursor.execute(sql, params)
            else:
                cursor.execute(sql)
        except BaseException:
            cursor.close()
            raise
        return cursor

    def commit(self):
        self.connect().commit()

    def rollback(self):
        self.connect().rollback()

    def __enter__(self):
        depth = getattr(self.local, "depth", 0)
        conn = self.connect()
        if depth == 0 and self.store.engine == "mysql":
            conn.begin()
        self.local.depth = depth + 1
        return self

    def __exit__(self, exc_type, _error, _trace):
        self.local.depth -= 1
        if self.local.depth == 0:
            if exc_type:
                self.rollback()
            else:
                self.commit()


if offline_fixture_enabled() and os.environ.get("SERVICE_ID") not in {"interview", "assessment"}:
    # 仅历史回归夹具使用旧表，正式进程始终按身份选取带前缀的专库配置。
    from .offline_binding import get
    db = get()
    DB_ENGINE = db.engine
else:
    owner = os.environ.get("SERVICE_ID")
    if owner not in {"interview", "assessment"}:
        raise RuntimeError("此数据库只能由面试或评估进程使用。")
    store = ServiceDatabase.from_env(owner)
    DB_ENGINE = store.engine
    db = DomainConnection(store)


def one(sql, params=()):
    with closing(db.execute(sql, params)) as cursor:
        row = cursor.fetchone()
        return dict(row) if row is not None else None


def all_rows(sql, params=()):
    with closing(db.execute(sql, params)) as cursor:
        return [dict(row) for row in cursor.fetchall()]
