"""按服务专属配置访问数据库，导入模块不会连接。SQLite 使用绝对路径；MySQL 使用预建专库及最小权限账号，通过系统信任库或服务专用 CA 验证 TLS。"""

from __future__ import annotations

import os
import re
import sqlite3
import ssl
from collections.abc import Iterable, Iterator, Mapping
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from pathlib import Path


# 只转换占位符。引号、SQL 注释和列名里的问号均是原文的一部分。
_MYSQL_SQL_TOKENS = re.compile(
    r"""'(?:''|\\.|[^'\\])*'|"(?:""|\\.|[^"\\])*"|`(?:``|[^`])*`"""
    r"""|/\*.*?\*/|\#[^\n]*|--(?=\s|$)[^\n]*|\?""",
    re.DOTALL,
)


class Transaction:
    """两种驱动统一使用问号参数；事务结束后不能继续持有这个对象。"""

    def __init__(self, cursor, engine: str):
        self._cursor = cursor
        self._engine = engine

    def execute(self, sql: str, params: tuple = ()) -> int:
        if self._engine == "mysql" and params:
            # PyMySQL 绑定参数时使用百分号格式，LIKE 中的字面百分号也需要转义。
            sql = _MYSQL_SQL_TOKENS.sub(
                lambda m: "%s" if m[0] == "?" else m[0], sql.replace("%", "%%")
            )
        if params:
            self._cursor.execute(sql, params)
        else:
            self._cursor.execute(sql)
        return self._cursor.rowcount

    def one(self, sql: str, params: tuple = ()) -> dict | None:
        self.execute(sql, params)
        row = self._cursor.fetchone()
        return dict(row) if row is not None else None

    def all(self, sql: str, params: tuple = ()) -> list[dict]:
        self.execute(sql, params)
        return [dict(row) for row in self._cursor.fetchall()]


@dataclass(frozen=True)
class ServiceDatabase:
    engine: str
    _path: Path | None = None
    _mysql_options: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_env(
        cls, service: str, env: Mapping[str, str] | None = None
    ) -> ServiceDatabase:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", service):
            raise ValueError("Expected a lowercase service identifier")
        env = os.environ if env is None else env
        prefix = service.upper() + "_"

        def required(key: str) -> str:
            value = env.get(prefix + key)
            if not value:
                raise ValueError(f"Missing {prefix}{key}")
            return value

        engine = required("DB_ENGINE").lower()
        if engine == "sqlite":
            path = Path(required("SQLITE_PATH"))
            # 每个事务单独连接，进程私有的内存库无法跨连接保存数据，因此要求绝对文件路径。
            if not path.is_absolute():
                raise ValueError(f"{prefix}SQLITE_PATH must be an absolute file path")
            return cls(engine, _path=path)
        if engine != "mysql":
            raise ValueError(f"{prefix}DB_ENGINE must be sqlite or mysql")

        port = int(env.get(prefix + "MYSQL_PORT", "3306"))
        if not 1 <= port <= 65535:
            raise ValueError(f"Invalid {prefix}MYSQL_PORT")
        options = {
            "host": required("MYSQL_HOST"),
            "port": port,
            "user": required("MYSQL_USER"),
            "password": required("MYSQL_PASSWORD"),
            "database": required("MYSQL_DATABASE"),
            "ssl": ssl.create_default_context(cafile=env.get(prefix + "MYSQL_SSL_CA") or None),
        }
        return cls(engine, _mysql_options=options)

    def _connect(self):
        if self.engine == "mysql":
            import pymysql

            return pymysql.connect(
                **self._mysql_options, charset="utf8mb4", autocommit=False,
                cursorclass=pymysql.cursors.DictCursor,
                connect_timeout=5, read_timeout=15, write_timeout=15,
            )
        if self.engine != "sqlite" or self._path is None:
            raise ValueError("Invalid service database configuration")
        self._path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        # 只为新库文件设置私有权限；不要更改共享临时目录或运维已配置文件的权限。
        try:
            fd = os.open(self._path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(fd)
        return sqlite3.connect(self._path, isolation_level=None, timeout=5)

    @contextmanager
    def transaction(self, *, write: bool = False) -> Iterator[Transaction]:
        """创建独立事务；嵌套操作必须传入同一个 tx，异常时整体回滚。"""
        with closing(self._connect()) as connection:
            if self.engine == "sqlite":
                connection.row_factory = sqlite3.Row
            with closing(connection.cursor()) as cursor:
                if self.engine == "sqlite":
                    cursor.execute("PRAGMA foreign_keys = ON")
                    if not write:
                        cursor.execute("PRAGMA query_only = ON")
                    # 先取得 SQLite 写锁再读取。同一项任务不能被两个请求同时认领。
                    cursor.execute("BEGIN IMMEDIATE" if write else "BEGIN")
                else:
                    cursor.execute("START TRANSACTION READ WRITE" if write else "START TRANSACTION READ ONLY")
                try:
                    yield Transaction(cursor, self.engine)
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise

    def ensure_schema(self, statements: Iterable[str]) -> None:
        """只执行本服务持有的可重复建表语句。MySQL 的 DDL 可能隐式提交。"""
        with self.transaction(write=True) as tx:
            for statement in statements:
                tx.execute(statement)

    def require_exact_keys(self, domain: str) -> None:
        if self.engine == "mysql":
            from .mysql_keys import require_exact_columns
            with self.transaction() as tx:
                require_exact_columns(tx.all, domain)

    def ping(self) -> bool:
        """就绪检查实际连接数据库，驱动错误交给调用方处理。"""
        with self.transaction() as tx:
            return tx.one("SELECT 1 AS healthy") == {"healthy": 1}
