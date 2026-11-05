"""仅供迁移回归构造合成旧数据，不能用这个模块启动学校的在线业务。"""
import os
from pathlib import Path
import stat
import sys


_enabled = False
_connection_settings = ()
_sqlite_fd = None
_sqlite_id = None


def _settings():
    return tuple(os.environ.get(key) for key in ("DB_ENGINE", "SQLITE_PATH", "MYSQL_HOST",
                 "MYSQL_PORT", "MYSQL_DATABASE", "MYSQL_USER", "MYSQL_PASSWORD", "MYSQL_SSL_CA"))


def _private_test_path(path):
    """只信任系统固定的临时目录；TMPDIR 由调用者提供，不能作为放行依据。"""
    if not path.is_absolute():
        return False
    resolved = path.resolve()
    roots = ([Path.home() / "AppData" / "Local" / "Temp"] if os.name == "nt" else
             [Path("/tmp").resolve(), Path("/var/tmp").resolve()])
    if sys.platform == "darwin":
        for parent in resolved.parents:
            if (parent.name == "T" and parent.parent.parent.parent == Path("/private/var/folders")
                    and parent.stat().st_uid == os.getuid()):
                roots.append(parent)
                break
    root = next((r for r in roots if resolved.is_relative_to(r) and resolved != r), None)
    if root is None:
        return False
    if os.name != "nt":
        parent = resolved.parent
        # 共享的 /tmp 仅作为上级锚点；数据库须在当前用户私有目录中，旁人不能替换祖先路径。
        while True:
            if parent == root and parent != resolved.parent:
                break
            if parent.exists():
                info = parent.stat()
                if info.st_uid != os.getuid() or info.st_mode & 0o022:
                    return False
            if parent == root:
                break
            parent = parent.parent
    # SQLite 会打开旁路 WAL、共享内存和回滚日志，也需要防止硬链接或符号链接指向实际库。
    for suffix in ("", "-wal", "-shm", "-journal"):
        file = Path(str(path) + suffix)
        try:
            info = file.lstat()
        except FileNotFoundError:
            continue
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or (hasattr(os,"getuid") and info.st_uid != os.getuid()):
            return False
    return True


def _check_database():
    """仅接受临时文件或验收脚本创建的本机 MySQL 账号；拒绝源码库及业务进程身份。"""
    if os.environ.get("SERVICE_ID") not in (None, "", "legacy_admin", "offline-fixture"):
        raise RuntimeError("业务服务不能启用旧版写入夹具")
    if os.environ.get("DB_ENGINE") == "sqlite":
        raw = os.environ.get("SQLITE_PATH", "")
        if raw == ":memory:":
            return
        path = Path(raw)
        if path.suffix in {".sqlite", ".sqlite3", ".db"} and _private_test_path(path):
            return
    elif (os.environ.get("DB_ENGINE") == "mysql" and os.environ.get("MYSQL_HOST") == "127.0.0.1"
          and os.environ.get("MYSQL_DATABASE") == "verify_legacy_admin"
          and os.environ.get("MYSQL_USER") == "legacy_admin"
          and os.environ.get("MYSQL_PORT", "").isdigit()
          and int(os.environ["MYSQL_PORT"]) not in {0, 3306}
          and _private_test_path(Path(os.environ.get("MYSQL_SSL_CA", "")))):
        return
    raise RuntimeError("旧版写入夹具仅可使用临时合成 SQLite 或本地验收专库")


def enable_offline_fixture():
    """测试须在自己的解释器显式调用，再导入离线夹具；设置环境变量本身不授权。"""
    global _enabled, _connection_settings, _sqlite_fd, _sqlite_id
    if _enabled:
        require_offline_fixture()
        return
    _check_database()
    if os.environ["DB_ENGINE"] == "sqlite" and os.environ["SQLITE_PATH"] != ":memory:":
        path = Path(os.environ["SQLITE_PATH"])
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # 在允许导入前固定真实文件，防止换路径、删后重建或复用 inode。描述符随进程关闭。
        fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            ident = os.fstat(fd)
            if not _private_test_path(path) or not os.path.samestat(ident, path.stat()):
                raise RuntimeError("离线目标文件已替换")
            _sqlite_id = ident
            _sqlite_fd = fd
        except BaseException:
            os.close(fd)
            raise
    _connection_settings = _settings()
    _enabled = True


def offline_fixture_enabled():
    return _enabled


def require_offline_fixture():
    if not _enabled:
        raise RuntimeError("旧版写入应用已退出部署；请使用原生网关或只读应急命令")
    _check_database()
    if _connection_settings != _settings():
        raise RuntimeError("离线数据库配置在授权后被修改")
    if _sqlite_fd is not None and not os.path.samestat(_sqlite_id, Path(os.environ["SQLITE_PATH"]).stat()):
        raise RuntimeError("离线数据库文件在授权后被替换")


def connect_offline_sqlite(path, **options):
    """在 SQLite 首次打开与执行任何写入型 PRAGMA 之间复核文件及旁路日志。"""
    import sqlite3
    require_offline_fixture()
    if str(path) != os.environ["SQLITE_PATH"]:
        raise RuntimeError("SQLite 连接指向未授权的旧库")
    connection = sqlite3.connect(path, **options)
    try:
        require_offline_fixture()
        return connection
    except BaseException:
        connection.close()
        raise


class OfflineClientOnly:
    """保留进程内 HTTP 合同测试；即使误用 Uvicorn 启动夹具也不能提供旧版网络业务。"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        kind = scope["type"]
        if kind == "lifespan" and "asgi" in scope:
            # 在旧 startup 钩子之前结束网络服务器启动，避免后台恢复任务先运行再拒绝网络流量。
            await receive()
            await send({"type": "lifespan.startup.failed", "message": "旧夹具不能作为网络服务启动"})
            return
        if kind == "http" or kind == "websocket":
            # 测试扩展由 ASGI 驱动传入，HTTP 请求头和浏览器 Cookie 不能伪造它。
            peer = scope.get("client") or ("", 0)
            is_memory = ("asgi" not in scope and peer[0] == "testclient"
                         and (kind == "websocket" or "http.response.debug" in scope.get("extensions", {})))
            if not is_memory:
                if kind == "websocket":
                    await send({"type": "websocket.close", "code": 1008})
                else:
                    await send({"type": "http.response.start", "status": 410, "headers": [(b"cache-control", b"no-store")]})
                    await send({"type": "http.response.body", "body": b""})
                return
        await self.app(scope, receive, send)
