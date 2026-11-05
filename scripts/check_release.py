"""在源码的临时副本中运行 Python 验收测试，不加载部署凭据。"""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
DIRECTORIES = ("backend", "admin_backend", "services", "shared", "scripts", "tests", "deploy")
SOURCE_SUFFIXES = {".py", ".js", ".jsx", ".md", ".txt"}


def copy_sources(target):
    for name in DIRECTORIES:
        for folder, dirs, files in os.walk(ROOT / name):
            dirs[:] = [d for d in dirs if d not in {"data", "node_modules", "__pycache__", "dist", "logs"}
                       and not d.startswith(".")]
            for filename in files:
                path = Path(folder, filename)
                if path.suffix in SOURCE_SUFFIXES and not path.is_symlink() and not filename.startswith("."):
                    dest = target / path.relative_to(ROOT)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(path, dest)


def run_suite(target, env, label, paths):
    print(f"\n--- {label} ---", flush=True)
    return subprocess.run(
        [sys.executable, "-m", "pytest", "--import-mode=importlib", "-q", *paths],
        cwd=target, env=dict(env, SQLITE_PATH=str(target / (label + ".sqlite"))),
    ).returncode


def main():
    with tempfile.TemporaryDirectory(prefix="interview-release-") as temp:
        target = Path(temp)
        copy_sources(target)
        # 保留 pip --target 安装的依赖目录，隔离部署环境的凭据、端点、数据库路径和环境配置文件。
        env = {k: os.environ[k] for k in ("PATH", "TMPDIR", "SYSTEMROOT", "LANG") if k in os.environ}
        dependencies = [p for p in sys.path if p and Path(p).is_absolute() and
                        not Path(p).resolve().is_relative_to(ROOT)]
        env.update(APP_ENV="test", DB_ENGINE="sqlite", PYTHONUTF8="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
                   PYTHONPATH=os.pathsep.join([str(target), *dependencies]),
                   ADMIN_MASTER_EMAIL="test-admin@example.test", ADMIN_MASTER_PASSWORD="SyntheticTestOnly027!")
        failures = []
        if run_suite(target, env, "core", ["tests", "services"]):
            failures.append("core")
        # 历史夹具的进程许可不能留在原生服务的测试进程里。
        if run_suite(target, env, "student", ["backend/tests"]):
            failures.append("student")
        # 旧管理模块在导入时就绑定 SQLite 文件。各测试套件应分进程运行，避免误用其他模块的不完整测试库。
        for test in sorted((target / "admin_backend/tests").glob("test_*.py")):
            if run_suite(target, env, test.stem, [str(test.relative_to(target))]):
                failures.append(test.stem)
        if failures:
            print("Failed suites:", ", ".join(failures), file=sys.stderr)
        return bool(failures)


if __name__ == "__main__":
    sys.exit(main())
