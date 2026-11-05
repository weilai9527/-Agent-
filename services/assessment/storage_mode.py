"""评估默认独占数据库；仅离线夹具可为历史迁移测试生成旧的共享布局。"""
import os
from pathlib import Path


def isolated():
    from shared.offline_fixture import offline_fixture_enabled

    if offline_fixture_enabled() and os.getenv("ASSESSMENT_STORAGE_MODE", "shared") == "shared":
        return False
    if os.getenv("ASSESSMENT_STORAGE_MODE", "isolated") != "isolated":
        raise RuntimeError("正常评估服务必须使用独立存储")
    return True


def assessment_owner():
    return isolated() and os.environ.get("SERVICE_ID") == "assessment"


def emit_projections():
    return isolated() and not assessment_owner()


def setting(name, default=None):
    if not assessment_owner():
        return os.environ.get(name, default)
    key = "ASSESSMENT_" + name
    if name == "SQLITE_PATH" and os.environ.get("ASSESSMENT_DB_ENGINE") != "sqlite":
        return None
    if name.startswith("MYSQL_") and os.environ.get("ASSESSMENT_DB_ENGINE") != "mysql":
        return default
    if name in {"MYSQL_PORT", "MYSQL_CHARSET"}:
        return os.environ.get(key, default)
    value = os.environ.get(key)
    if not value or (name == "DB_ENGINE" and value not in {"sqlite", "mysql"}):
        raise RuntimeError(f"Missing or invalid {key}")
    if name == "SQLITE_PATH" and not Path(value).is_absolute():
        raise RuntimeError("ASSESSMENT_SQLITE_PATH must be absolute")
    return value
