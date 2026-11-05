"""在一次性 MySQL 中重放并发开通、旧版号补发和职员重置，区分业务冲突与数据库故障。"""
import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from fastapi import HTTPException


def exercise_school_office():
    from services.identity import registrations as book
    from services.identity import staff_maintenance as staff
    from shared.service_db import ServiceDatabase

    db = ServiceDatabase.from_env("identity")
    req = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(store=db)))
    ctx = dict(actor_type="admin", caller="admin-gateway", school_id="office-synthetic", actor_id="manager")
    with db.transaction(write=True) as tx:
        for actor, role, rights in (("manager", "admin", [*book.ACTIONS, staff.RESET]), ("teacher", "teacher", [])):
            tx.execute("""INSERT INTO identity_staff (school_id,actor_id,email,password_hash,name,actor_type,status,permissions,school_wide)
                       VALUES (?,?,?,'unused',?,?,'normal',?,?)""",
                       (ctx["school_id"], actor, actor+"@test.invalid", actor, role, json.dumps(rights), int(role=="admin")))
    book.save_rows([book.Row(student_no="MYSQL-01",name="并发测试学生")], req, ctx)
    batch = book.Batch(items=[book.Selected(student_no="MYSQL-01",revision=1)])
    def issue(_):
        try:
            result = book.operation(book.ISSUE,"issue")(batch, req, ctx)
            assert len(result["handout"]) == 1
            return 200
        except HTTPException as exc:
            return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(issue, range(2))) == [200,409]
    view = staff.inspect(staff.RESET)("teacher", req, ctx)
    expected = staff.Expected(expected_revision=view["revision"])
    assert staff.reissue("teacher", expected, req, ctx)["temporary_password"]
    try:
        staff.reissue("teacher", expected, req, ctx)
    except HTTPException as exc:
        assert exc.status_code == 409
    else:
        raise AssertionError("重复的旧密码补发请求生效")
    with db.transaction() as tx:
        assert tx.one("SELECT COUNT(*) AS n FROM identity_audit WHERE school_id=? AND action='registration.issue'",
                      (ctx["school_id"],))["n"] == 1
        assert tx.one("SELECT COUNT(*) AS n FROM identity_staff_password_rotation WHERE school_id=?",
                      (ctx["school_id"],))["n"] == 1
