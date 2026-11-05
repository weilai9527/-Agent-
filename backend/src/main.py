"""旧版学生写入口已退出在线部署。正式入口为 services.gateway.student:app。"""

raise RuntimeError("旧版应用已退役，请启动原生学生网关；离线数据夹具必须显式授权。")
