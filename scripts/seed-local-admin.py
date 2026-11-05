"""旧演示库写入入口已关闭。创建校级主管理员应使用原生身份服务的交互式初始化命令。"""
import sys


if __name__ == "__main__":
    print("旧库演示数据写入已关闭。新学校请使用 python -m services.identity.bootstrap --help；"
          "合成学校验收使用 python scripts/smoke_microservices.py --help。", file=sys.stderr)
    sys.exit(2)
