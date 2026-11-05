"""日常进程的启动契约。旧库救援由独立命令启动，不通过环境开关切换网关。"""
import os


def require_native_runtime(env=None):
    """网关和进程启动器必须在加载业务应用、数据库或学校密钥之前调用。"""
    if env is None:
        from .offline_fixture import offline_fixture_enabled
        if offline_fixture_enabled():
            raise ValueError("已启用离线夹具的进程不能启动在线服务")
    env = os.environ if env is None else env
    for setting, expected, label in (("IDENTITY_SESSION_MODE", "native", "原生身份"),
                                     ("ASSESSMENT_STORAGE_MODE", "isolated", "独立存储")):
        if env.get(setting, expected) != expected:
            raise ValueError(f"正常服务只支持{label}（{setting}={expected}）。旧快照请使用 python -m deploy.emergency")
