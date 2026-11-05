"""在 MySQL 上并发重试权限申请和审批，验证学校级锁能否避免重复处理。"""
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace


def exercise_staff_requests():
    from services.identity.permission_requests import Application, Decision, apply, decide
    from services.identity.staff import ReplaceGrants, edit_grants
    from shared.service_db import ServiceDatabase

    store = ServiceDatabase.from_env("identity")
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(store=store)))
    applicant = {"actor_type":"teacher", "school_id":"mysql-school", "actor_id":"reader"}
    manager = {**applicant, "actor_type":"admin", "actor_id":"manager"}
    with store.transaction(write=True) as tx:
        for ctx, rights in ((applicant,'[]'), (manager,'["permissions.manage"]')):
            tx.execute("""INSERT INTO identity_staff
                (school_id,actor_id,email,password_hash,name,actor_type,status,permissions,school_wide)
                VALUES (?,?,?,?,?,?,'normal',?,?)""", (ctx["school_id"],ctx["actor_id"],ctx["actor_id"]+"@example.test",
                          "test-unused",ctx["actor_id"],ctx["actor_type"],rights,int(ctx is manager)))
    form = Application(request_key="mysql-retry", actions=["score.adjust"], reason="教学")
    with ThreadPoolExecutor(2) as writers:
        first, second = list(writers.map(lambda _:apply(form, request, applicant), range(2)))
    assert first == second
    decision = Decision(status="approved", note="核实任课情况")
    with ThreadPoolExecutor(2) as writers:
        outcomes = list(writers.map(lambda _:decide(first["id"], decision, request, manager), range(2)))
    assert outcomes[0] == outcomes[1]
    edit_grants("reader", ReplaceGrants(permissions=[], actor_type="teacher"), request, manager)
    assert decide(first["id"], decision, request, manager) == outcomes[0]
    with store.transaction() as tx:
        assert tx.one("SELECT permissions FROM identity_staff WHERE school_id=? AND actor_id='reader'",
                      (manager["school_id"],))["permissions"] == "[]"
        assert tx.one("SELECT COUNT(*) AS n FROM identity_audit WHERE school_id=? AND target_id=?",
                      (manager["school_id"],first["id"]))["n"] == 2
