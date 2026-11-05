"""验证原生首次开校的并发边界和审计，不创建历史账号或启动旧应用。"""
import json
from concurrent.futures import ThreadPoolExecutor

from services.identity.bootstrap import provision
from services.identity.permissions import TEACHER_ONLY
from shared.service_db import ServiceDatabase


def test_empty_school_can_be_initialized_only_once(tmp_path):
    store = ServiceDatabase.from_env("identity", {"IDENTITY_DB_ENGINE":"sqlite",
                                                 "IDENTITY_SQLITE_PATH":str(tmp_path / "identity.sqlite")})

    def create(index):
        try:
            return provision(store, "a", f"staff{index}@example.test", "教务主管", "School-bootstrap-fixture-012")
        except ValueError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(bool(x) for x in pool.map(create, (1, 2))) == 1
    with store.transaction() as tx:
        account = tx.one("SELECT * FROM identity_staff WHERE school_id='a'")
        assert account["actor_type"] == "admin" and account["school_wide"] == 1
        grants = set(json.loads(account["permissions"]))
        assert "permissions.manage" in grants and grants.isdisjoint(TEACHER_ONLY | {"model.config.write"})
        assert "profile.student.read" not in grants
        assert tx.one("SELECT count(*) AS n FROM identity_audit WHERE action='staff.bootstrap'")["n"] == 1
