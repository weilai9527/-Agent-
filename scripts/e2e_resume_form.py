"""转到原生简历表单、管理配置和已签名的学校服务契约回归，不打开项目中的任何数据库。"""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
CASES = ("services/profile/test_settings.py::test_real_identity_and_career_endpoints_recheck_staff_and_student",
         "services/profile/test_profile.py::test_profile_revisions_and_private_local_analysis",
         "services/profile/test_candidate_gateway.py::test_native_gateway_upload_and_analysis_forward_only_authorized_data")


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    print("转入原生简历验收：从临时源码副本启动真实 ASGI 路由与独立合成数据库。", flush=True)
    with tempfile.TemporaryDirectory(prefix="profile-form-") as root:
        target = Path(root)
        for tree in ("shared","services"):
            for source in (ROOT/tree).rglob("*.py"):
                if source.is_symlink(): continue
                dest = target/source.relative_to(ROOT)
                dest.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(source,dest)
        # 仅保留依赖安装目录，防止导入工作区的 .env、旧后端或加载生产 DSN。
        paths = [p for p in sys.path if p and Path(p).is_absolute() and not Path(p).resolve().is_relative_to(ROOT)]
        env = {k:os.environ[k] for k in ("PATH","TMPDIR","SYSTEMROOT","LANG") if k in os.environ}
        env.update(APP_ENV="test",PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTHONPATH=os.pathsep.join([str(target), *paths]))
        return subprocess.run([sys.executable,"-m","pytest","-q","--import-mode=importlib",*CASES],
                              env=env,cwd=target).returncode


if __name__ == "__main__":
    sys.exit(main())
