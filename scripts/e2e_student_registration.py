"""转到原生学校管理的真实浏览器验收。只操作其临时服务和合成学校，不使用已有业务数据或服务器。"""
import argparse
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--admin-build",type=Path,default=ROOT/"admin/dist",help="已构建的原生管理端目录，只读。")
    args = parser.parse_args()
    build = args.admin_build.resolve()
    if not (build/"index.html").is_file():
        parser.error("请先构建管理端，再通过 --admin-build 传入构建目录。")
    print("转入原生学校验收：隔离身份库、真实网关、注册与发放、撤销及隔校权限。", flush=True)
    return subprocess.run([sys.executable, str(ROOT/"admin/tests/nativeSchoolConsole.browser.py"), str(build)]).returncode


if __name__ == "__main__":
    sys.exit(main())
