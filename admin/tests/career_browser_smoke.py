"""用构建后的管理前端、三个真实回环服务及临时学校数据库验收职业管理。可用 ADMIN_TEST_DIST 指定构建目录，PLAYWRIGHT_MODULE_ROOT 和 TEST_CHROME_PATH 可指向本机浏览器依赖。"""
import contextlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

import httpx
from openpyxl import Workbook

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.smoke_microservices import keypair, prepare_sources
from shared.account_security import hash_staff_password as hash_password
from backend.tests.test_career_catalog import build_workbook
import sqlite3


def run(work, stack):
    prepare_sources(work)
    dist = Path(os.getenv("ADMIN_TEST_DIST", ROOT / "admin/dist")).resolve()
    if not (dist / "index.html").is_file():
        raise ValueError("Build the management UI before running this smoke")
    # 仅在临时源码副本挂载静态页面；网关和前端共用临时端口以复验同源部署。
    (work / "site_app.py").write_text("from services.gateway.admin import app\n"
        "from starlette.staticfiles import StaticFiles\n"
        f"app.mount('/admin',StaticFiles(directory={str(dist)!r},html=True))\n")
    apps = {"career": "services.career.app:app", "identity": "services.identity.app:app", "admin-gateway": "site_app:app"}
    sockets = {name: stack.enter_context(socket.socket()) for name in apps}
    for sock in sockets.values():
        sock.bind(("127.0.0.1", 0))
    urls = {name: f"http://127.0.0.1:{sock.getsockname()[1]}" for name, sock in sockets.items()}
    scope = ["posting.admin.read", "posting.import", "catalog.admin.read", "catalog.review", "catalog.import", "jd.read", "jd.write", "jd.approve"]
    key, public = keypair()
    policy = {"admin-gateway": {"schools": ["test-school"], "keys": {"test": public}, "grants": {
        "identity": {"system": ["identity.session.proxy", "identity.session.resolve"], "admin": ["identity.classes.read", "identity.roster.read"]},
        "career": {"admin": scope}}}}
    libs = [str(work)] + [p for p in sys.path if p and ("site-packages" in p or (Path(p) / "pytest").is_dir())]
    env = {"PATH": os.defpath, "PYTHONPATH":os.pathsep.join(libs),"PYTHONNOUSERSITE":"1","TMPDIR":str(work),
           "APP_ENV":"test","IDENTITY_SESSION_MODE":"native","LEGACY_SCHOOL_ID":"test-school",
           "DB_ENGINE":"sqlite","SQLITE_PATH":str(work/"audit.db"),"SERVICE_KEY_ID":"test",
           "IDENTITY_DB_ENGINE":"sqlite","IDENTITY_SQLITE_PATH":str(work/"identity.db"),
           "CAREER_DB_ENGINE":"sqlite","CAREER_SQLITE_PATH":str(work/"career.db"),"CAREER_SCHOOL_ID":"test-school",
           "ADMIN_FRONTEND_ORIGIN":urls["admin-gateway"],"IDENTITY_SERVICE_URL":urls["identity"],
           "CAREER_SERVICE_URL":urls["career"],"SERVICE_TRUST_POLICY":json.dumps(policy)}
    for name, target in apps.items():
        log = stack.enter_context((work / (name + ".log")).open("w+"))
        fd = sockets[name].fileno()
        proc = subprocess.Popen([sys.executable, "-m", "uvicorn", target, "--fd", str(fd), "--no-access-log"],
                                cwd=work, stdout=log, stderr=log, pass_fds=(fd,),
                                env={**env, "SERVICE_ID":name, **({"SERVICE_SIGNING_KEY":key} if name=="admin-gateway" else {})})
        stack.callback(proc.wait, 20)
        stack.callback(proc.terminate)
        sockets[name].close()
        with httpx.Client(trust_env=False, timeout=2) as client:
            for _ in range(240):
                if proc.poll() is not None:
                    log.seek(0)
                    raise RuntimeError(log.read()[-2000:])
                try:
                    if client.get(urls[name]+"/openapi.json").is_success:
                        break
                except httpx.RequestError:
                    pass
                time.sleep(.25)
            else:
                raise TimeoutError(name)
    accounts = {"importer":["posting.import"], "reader":["posting.admin.read"],
                "catalog":["catalog.admin.read","catalog.review"], "reviewer":["jd.read","jd.approve"],
                "catalog-importer":["catalog.import"], "jd-author":["jd.write"]}
    digest = hash_password("Synthetic-Career-Password-123!")
    with sqlite3.connect(work/"identity.db") as conn:
        for user, grants in accounts.items():
            conn.execute("INSERT INTO identity_staff VALUES ('test-school',?,?,?,?,'admin','normal',?,1)",
                         (user,user+"@school.test",digest,user,json.dumps(grants)))
    with sqlite3.connect(work/"career.db") as conn:
        conn.execute("INSERT INTO catalog_versions(id,code,name,status) VALUES ('ui-draft','ui-draft','UI import test','draft')")
        conn.execute("INSERT INTO catalog_job_suggestions(id,suggested_name,normalized_name) VALUES ('test','Synthetic role','synthetic')")
        conn.execute("INSERT INTO job_jd_submissions(id,job_title,jd_text) VALUES ('jd','Synthetic JD','Synthetic description')")
    book = Workbook()
    book.active.append(["岗位名称", "公司"])
    book.active.append(["Synthetic career posting", "Example"])
    workbook = work / "jobs.xlsx"
    book.save(workbook)
    catalog_book = work / "directory.xlsx"
    catalog_book.write_bytes(build_workbook())
    subprocess.run(["node",str(ROOT/"admin/tests/career.browser.cjs")],check=True,timeout=180,
                   env={**os.environ, "CAREER_TEST_ORIGIN":urls["admin-gateway"],"CAREER_TEST_WORKBOOK":str(workbook),
                        "CAREER_TEST_CATALOG_BOOK":str(catalog_book)})
    with sqlite3.connect(work/"career.db") as conn:
        assert conn.execute("SELECT status,imported_rows FROM catalog_import_jobs WHERE version_id='ui-draft'").fetchone() == ("succeeded", 7)
        assert conn.execute("SELECT name FROM catalog_job_roles WHERE version_id='ui-draft'").fetchone() == ("产品经理",)
        assert conn.execute("SELECT status FROM job_jd_submissions WHERE job_title='Synthetic manual JD'").fetchone() == ("pending",)
        assert conn.execute("SELECT COUNT(*) FROM job_postings").fetchone() == (2,)
        assert conn.execute("SELECT review_status FROM catalog_job_suggestions WHERE id='test'").fetchone() == ("rejected",)


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as directory, contextlib.ExitStack() as resources:
        run(Path(directory), resources)
