"""在 check_mysql_services 创建的临时 MySQL 实例中，用合成记录验证标识符隔离。"""
import hashlib
from itertools import product
import time

SCHOOLS = ("School-Cafe", "school-cafe", "School-Café")
ACTORS = ("Staff-Jose", "staff-jose", "Staff-José")


def denied(call, status):
    from fastapi import HTTPException
    try:
        call()
    except HTTPException as exc:
        assert exc.status_code == status, exc
    else:
        raise AssertionError("Different signed identifier was accepted")


def exercise_identity():
    from shared.service_db import ServiceDatabase
    from services.identity.app import initialize
    from services.identity.staff import _session

    db = ServiceDatabase.from_env("identity")
    with db.transaction(write=True) as tx:
        for school, actor in product(SCHOOLS, ACTORS):
            marker = f"{school}/{actor}"
            digest = hashlib.sha256(marker.encode()).hexdigest()
            tx.execute("""INSERT INTO identity_staff
                (school_id,actor_id,email,password_hash,name,actor_type,status,permissions,school_wide)
                VALUES (?,?,?,'!','Synthetic','teacher','normal','[]',0)""",
                       (school, actor, digest + "@example.test"))
            tx.execute("INSERT INTO identity_staff_sessions VALUES (?,?,?,?)",
                       (digest, school, actor, int(time.time()) + 600))
    with db.transaction() as tx:
        for school, actor in product(SCHOOLS, ACTORS):
            token = f"{school}/{actor}"
            row = _session(tx, token, school)
            assert (row["school_id"], row["actor_id"]) == (school, actor)
            for other in SCHOOLS:
                if school != other:
                    denied(lambda: _session(tx, token, other), 401)

    # 即使表的默认排序规则是二进制，显式使用不区分大小写规则的列仍然不安全。验证重启时会拒绝这种列。
    with db.transaction(write=True) as tx:
        tx.execute("ALTER TABLE org_write_lock MODIFY school_id VARCHAR(128) COLLATE utf8mb4_unicode_ci NOT NULL")
    try:
        initialize(db)
    except RuntimeError as exc:
        assert "org_write_lock.school_id" in str(exc), exc
    else:
        raise AssertionError("Existing case/accent-insensitive authority accepted")
    with db.transaction(write=True) as tx:
        tx.execute("ALTER TABLE org_write_lock MODIFY school_id VARCHAR(128) COLLATE utf8mb4_bin NOT NULL")
    initialize(db)


def exercise_usage():
    from shared.service_db import ServiceDatabase
    from services.usage.app import Reservation
    from services.usage.ledger import UsageLedger

    ledger = UsageLedger(ServiceDatabase.from_env("usage"))
    request = Reservation(request_id="same-request", resource="text", units=1)
    receipts = {}
    for n, school in enumerate(SCHOOLS, start=5):
        ledger.configure(school, n, 0)
        for actor in ACTORS:
            ctx = {"school_id": school, "actor_id": actor, "actor_type": "student", "caller": "interview"}
            receipts[(school, actor)] = ledger.reserve(ctx, request)["reservation_id"]
    assert len(set(receipts.values())) == 9
    for n, school in enumerate(SCHOOLS, start=5):
        assert ledger.quota(school)["text"]["limit"] == n
    for (school, actor), key in receipts.items():
        for other_school, other_actor in ((SCHOOLS[0], ACTORS[0]), (school, ACTORS[1]), (SCHOOLS[1], actor)):
            if (school, actor) != (other_school, other_actor):
                ctx = {"caller": "interview", "school_id": other_school, "actor_id": other_actor, "actor_type": "student"}
                denied(lambda: ledger.settle(ctx, key, 0), 404)
