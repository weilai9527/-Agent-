"""验证两个领域服务可在不安装旧后端包的环境中启动，并只访问各自的数据库。"""
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


def run_native_package(tmp_path, module):
    """在仅有原生源码的临时发布目录运行一项业务验收，隔离旧库、部署密钥和网络。"""
    root = Path(__file__).resolve().parents[2]
    package = tmp_path / "native"
    for domain in ("services", "shared"):
        for source in (root / domain).rglob("*.py"):
            relative = source.relative_to(root)
            if source.name.startswith(("test_", "smoke_")) or "tests" in relative.parts:
                continue
            target = package / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    shutil.copyfile(module, package / "_native_case.py")
    # 服务运行时可从已安装的第三方目录加载依赖，但不能借开发机 PYTHONPATH 找回原仓库。
    dependencies = [str(path) for item in os.getenv("PYTHONPATH", "").split(os.pathsep) if item
                    and (path := Path(item).resolve()).is_dir() and not path.is_relative_to(root)
                    and not root.is_relative_to(path)]
    forbidden = package / "forbidden-legacy.sqlite"
    guard = """
import sys
from pathlib import Path

def deny(reason):
    with (stage / ".boundary-violation").open("a") as log:
        log.write(reason + "\\n")
    raise AssertionError(reason)

class NoLegacy:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in {"backend", "admin_backend"}:
            deny("加载了旧包：" + name)

def guard(event, args):
    if event in {"socket.connect", "socket.getaddrinfo"}:
        deny("临时安装包尝试连接网络")
    if event not in {"open", "sqlite3.connect"} or not isinstance(args[0], (str, bytes)):
        return
    import os
    path = Path(os.fsdecode(args[0])).resolve()
    if (path.is_relative_to(repo) and not path.is_relative_to(stage)) or path == legacy:
        deny("访问了仓库或旧数据库")
    if event == "sqlite3.connect" and not path.is_relative_to(stage):
        deny("访问了临时安装目录以外的数据库")

sys.meta_path.insert(0, NoLegacy())
sys.addaudithook(guard)
"""
    # 使用启动钩子捕捉延迟加载。即使业务内部捕获异常并降级，父测试也会发现越界。
    paths = f"from pathlib import Path\nrepo=Path({str(root)!r})\nstage=Path({str(package)!r})\nlegacy=Path({str(forbidden)!r})\n"
    (package / "sitecustomize.py").write_text(paths + guard, encoding="utf-8")
    env = {k: os.environ[k] for k in ("PATH", "LANG", "LC_ALL", "SYSTEMROOT") if k in os.environ}
    env.update(PYTHONPATH=os.pathsep.join([str(package), *dependencies]), PYTHONDONTWRITEBYTECODE="1",
               APP_ENV="test", IDENTITY_SESSION_MODE="native", ASSESSMENT_STORAGE_MODE="isolated",
               DB_ENGINE="sqlite", SQLITE_PATH=str(forbidden), TMPDIR=str(package))
    result = subprocess.run([sys.executable, "-m", "_native_case"], cwd=package, env=env,
                            text=True, capture_output=True, timeout=100)
    assert result.returncode == 0, result.stderr
    assert not (package / ".boundary-violation").exists()
    assert not forbidden.exists()


@pytest.mark.parametrize("owner", ["profile", "career"])
def test_service_starts_without_either_monolith(owner, tmp_path):
    script = """
import importlib
import os
import sys

class NoLegacy:
    def find_spec(self, fullname, path, target=None):
        if fullname.split('.')[0] in {'backend','admin_backend'}:
            raise AssertionError('业务服务尝试加载旧框架：' + fullname)
sys.meta_path.insert(0, NoLegacy())
from fastapi.testclient import TestClient
app = importlib.import_module('services.' + sys.argv[1] + '.app').app
with TestClient(app) as client:
    assert client.get('/ready').status_code == 200
    assert client.get('/api/profile' if sys.argv[1]=='profile' else '/v1/job-postings').status_code == 401
"""
    env = {k: os.environ[k] for k in ("PATH", "PYTHONPATH", "TMPDIR") if k in os.environ}
    wrong = tmp_path / "forbidden-legacy.sqlite"
    env.update(SERVICE_ID=owner, APP_ENV="test", CAREER_SCHOOL_ID="A", DB_ENGINE="sqlite", SQLITE_PATH=str(wrong))
    env[owner.upper()+"_DB_ENGINE"] = "sqlite"
    env[owner.upper()+"_SQLITE_PATH"] = str(tmp_path / (owner+".sqlite"))
    result = subprocess.run([sys.executable,"-c",script,owner], cwd=Path(__file__).resolve().parents[2],
                            env=env, text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert not wrong.exists()


def test_private_model_cannot_read_legacy_or_static_provider_config(monkeypatch):
    from fastapi import HTTPException
    from services.profile.model_policy import select_model

    monkeypatch.setenv("SERVICE_ID", "profile")
    monkeypatch.setenv("PROFILE_MODEL_BY_SCHOOL", '{"A":"custom"}')
    monkeypatch.setenv("AI_API_KEY", "synthetic")
    monkeypatch.setenv("AI_MODEL", "synthetic")
    monkeypatch.setenv("AI_BASE_URL", "https://configured.invalid")
    monkeypatch.setenv("PROVIDER_ALLOWED_CUSTOM_ENDPOINTS", "https://configured.invalid")
    monkeypatch.delenv("PROVIDERS_SERVICE_URL", raising=False)
    assert select_model("B", "profile").provider == "local"
    with pytest.raises(HTTPException) as denied:
        select_model("A", "profile")
    assert denied.value.status_code == 503
