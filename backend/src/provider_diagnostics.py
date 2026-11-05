"""旧诊断模块只向显式离线夹具提供兼容导入；部署入口见 services.providers.app。"""
import argparse
import json

from shared.offline_fixture import require_offline_fixture


def __getattr__(name):
    if name == "app":
        # 普通进程即使尝试按旧模块名启动，也不能据此进入管理或付费诊断入口。
        require_offline_fixture()
        from services.providers.app import app
        return app
    raise AttributeError(name)


def diagnose_report_providers(*, make_request=False):
    require_offline_fixture()
    if make_request:
        raise RuntimeError("旧诊断入口只支持离线配置检查；连通性检测须经平台授权")
    from services.providers.diagnostics import diagnose_report_providers as inspect
    return inspect(make_request=False)


def main():
    parser = argparse.ArgumentParser(description="离线夹具的配置检查。在线管理请使用 providers 服务。")
    parser.add_argument("--config-only", action="store_true", required=True)
    parser.parse_args()
    results = diagnose_report_providers()
    print(json.dumps({"providers": results}, ensure_ascii=False))
    return 0 if results else 2


if __name__ == "__main__":
    raise SystemExit(main())
