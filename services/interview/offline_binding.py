"""历史回归由离线夹具显式注入数据库；运行服务不能借此选择连接。"""
from shared.offline_fixture import require_offline_fixture


_fixture_store = None


def bind(store):
    global _fixture_store
    require_offline_fixture()
    _fixture_store = store


def get():
    require_offline_fixture()
    if _fixture_store is None:
        raise RuntimeError("请先在临时解释器内初始化历史数据夹具")
    return _fixture_store
