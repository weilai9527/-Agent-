"""两个正常工作进程不加载历史应用，不接受无前缀的旧库连接，也不替其他域建表。"""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest


GUARD = """
import sys
class NoLegacy:
    def find_spec(self, name, *args):
        if name in {"backend.src.main", "backend.src.database", "admin_backend.src.main",
                    "admin_backend.src.database"} or name.startswith(("backend.offline", "admin_backend.offline")):
            raise AssertionError("生产进程试图装载旧框架: "+name)
sys.meta_path.insert(0,NoLegacy())
"""


@pytest.mark.parametrize("owner", ["interview", "assessment"])
def test_api_and_worker_need_only_their_own_store(tmp_path, owner):
    root = Path(__file__).resolve().parents[2]
    (tmp_path / "sitecustomize.py").write_text(GUARD)
    env = {key: os.environ[key] for key in ("PATH","TMPDIR","PYTHONPATH") if key in os.environ}
    env.update(APP_ENV="test", SERVICE_ID=owner, LEGACY_SCHOOL_ID="school",
               PYTHONPATH=os.pathsep.join([str(tmp_path),str(root),env.get("PYTHONPATH","")]),
               DB_ENGINE="sqlite", SQLITE_PATH=str(tmp_path/"old.sqlite"))
    command = [sys.executable,"-c",f"from services.{owner}.app import app; assert app.routes"]
    denied = subprocess.run(command,env=env,cwd=root,capture_output=True,text=True,timeout=45)
    assert denied.returncode and (owner.upper()+"_DB_ENGINE") in denied.stderr
    assert not (tmp_path/"old.sqlite").exists()
    env[owner.upper()+"_DB_ENGINE"]="sqlite"
    file=tmp_path/(owner+".sqlite")
    env[owner.upper()+"_SQLITE_PATH"]=str(file)
    subprocess.run(command,env=env,cwd=root,check=True,timeout=45)
    subprocess.run([sys.executable,"-m","services.interview.worker","--once"],env=env,cwd=root,check=True,timeout=45)
    with sqlite3.connect(file) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert not tables & {"users","sessions","resume_profiles","catalog_job_roles","rtc_sessions"}
    assert owner+"_database_owner" in tables
    assert ("interview_reports" in tables) == (owner=="assessment")
    assert not (tmp_path/"old.sqlite").exists()


def test_with_old_environment_cannot_mount_retired_browser_entry(tmp_path):
    env={**os.environ,"APP_ENV":"test","IDENTITY_SESSION_MODE":"legacy","DB_ENGINE":"sqlite",
         "SQLITE_PATH":str(tmp_path/"unopened.sqlite")}
    for module in ("backend.src.main","backend.offline.main"):
        run=subprocess.run([sys.executable,"-c",f"import {module}"],env=env,capture_output=True,text=True,timeout=20)
        assert run.returncode and "RuntimeError" in run.stderr
    assert not (tmp_path/"unopened.sqlite").exists()
