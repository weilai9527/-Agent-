"""旧管理端已退役。直接使用旧 ASGI 路径必须在导入任何数据库前停止。"""

raise RuntimeError(
    "请使用 services.gateway.admin:app；查询冻结的历史快照请运行 python -m deploy.emergency"
)
