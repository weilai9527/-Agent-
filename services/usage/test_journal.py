"""在临时文件库上使用真实任务队列，验证派发日志、租约接管及崩溃恢复。"""
import hashlib
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest
from fastapi import HTTPException

from services.interview.jobs import JobQueue
from services.interview.test_jobs import SQLite
from services.usage import journal
from services.usage.provider_calls import ProviderAttemptFailed
from services.usage.text import TextAdmission

ACTOR = {"school_id": "schoolA", "actor_id": "student", "actor_type": "student"}
DIGEST = "f" * 64


@pytest.fixture
def queue(tmp_path, monkeypatch):
    monkeypatch.setenv("SERVICE_ID", "assessment")
    db = SQLite(tmp_path / "worker.sqlite")
    with db:
        db.execute("CREATE TABLE interview_sessions(id CHAR(36) PRIMARY KEY)").close()
        db.execute("INSERT INTO interview_sessions VALUES ('i')").close()
    q = JobQueue(db, "sqlite")
    q.migrate()
    journal.migrate(q)
    with db:
        q.enqueue("score", "i", "answer", "v1")
    yield q
    db.connect().close()


class Meter:
    def __init__(self):
        self.holds, self.spent, self.pinned = {}, {}, set()
        self.pending = False
        self.expired = False

    def reserve(self, actor, *, operation_id, purpose, **kwargs):
        key = operation_id + ":" + purpose
        rid = self.holds.setdefault(key, hashlib.sha256(key.encode()).hexdigest()[:32])
        if rid in self.spent:
            return TextAdmission("settled", key, rid, actual_units=self.spent[rid])
        if rid in self.pinned:
            return TextAdmission("in_flight", key, rid)
        if self.expired and purpose == "http.0":
            return TextAdmission("deferred", key, rid, reason="reservation_expired")
        return TextAdmission("reserved", key, rid, int(time.time()) + 300)

    def begin(self, actor, rid):
        if rid in self.spent:
            raise HTTPException(409, "settled hold")
        self.pinned.add(rid)
        return {"state": "in_flight"}

    def settle(self, actor, rid, *, actual_units):
        assert self.spent.setdefault(rid, actual_units) == actual_units
        if self.pending:
            raise HTTPException(503, "lost acknowledgement")


@pytest.fixture
def meter(monkeypatch):
    m = Meter()
    monkeypatch.setattr(journal, "reserve_text", m.reserve)
    monkeypatch.setattr(journal, "settle_text", m.settle)
    monkeypatch.setattr(journal, "begin_text", m.begin)
    return m


def run(queue, job, dispatch, purpose="first", actor=ACTOR, digest=DIGEST):
    return journal.run_request(queue, job, actor, dispatch=dispatch, purpose=purpose, request_fingerprint=digest)


def reclaim(q, job):
    with q.db:
        q.db.execute("UPDATE interview_jobs SET ready_at=0 WHERE id=?", (job["id"],)).close()
    return q.claim(60)


def forbidden():
    pytest.fail("provider called twice")


def test_response_survives_restart_and_job_wide_reconciliation(queue, meter):
    job = queue.claim(60)
    meter.pending = True
    with pytest.raises(journal.TextJobDeferred, match="settlement_pending"):
        run(queue, job, lambda: "saved model answer")
    new = reclaim(queue, job)
    meter.pending = False
    journal.reconcile_job(queue, new, ACTOR)
    assert run(queue, new, forbidden) == "saved model answer"
    assert len(meter.holds) == 1 and list(meter.spent.values()) == [1]
    with pytest.raises(journal.TextJobDeferred, match="worker_lease_lost"):
        run(queue, job, forbidden)


@pytest.mark.parametrize(("outcome", "status", "amount"), [("unsent", None, 0), ("rejected", 429, 0), ("invalid", 200, 1)])
def test_replays_classified_failure_without_dispatch(queue, meter, outcome, status, amount):
    job = queue.claim(60)
    def fail():
        raise ProviderAttemptFailed(outcome, status)
    for callback in (fail, forbidden):
        with pytest.raises(ProviderAttemptFailed) as err:
            run(queue, job, callback)
        assert (err.value.outcome, err.value.status) == (outcome, status)
    assert list(meter.spent.values()) == [amount]


def test_unknown_dispatch_blocks_other_slots_and_does_not_refund(queue, meter):
    job = queue.claim(60)
    def timeout():
        raise ProviderAttemptFailed("unknown", 504)
    with pytest.raises(journal.TextJobDeferred, match="reconciliation"):
        run(queue, job, timeout)
    with pytest.raises(journal.TextJobDeferred, match="reconciliation"):
        run(queue, reclaim(queue, job), forbidden, purpose="fallback")
    assert len(meter.holds) == 1 and not meter.spent


def test_concurrent_call_fenced_even_for_same_lease_and_late_response_survives(queue, meter):
    job = queue.claim(60)
    entered, proceed = Event(), Event()
    def slow():
        entered.set()
        assert proceed.wait(5)
        return "late receipt"
    with ThreadPoolExecutor(1) as pool:
        executing = pool.submit(run, queue, job, slow)
        assert entered.wait(5)
        try:
            with pytest.raises(journal.TextJobDeferred, match="reconciliation"):
                run(queue, job, forbidden, purpose="alternate")
            new = reclaim(queue, job)
            with pytest.raises(journal.TextJobDeferred, match="reconciliation"):
                journal.reconcile_job(queue, new, ACTOR)
        finally:
            proceed.set()
        with pytest.raises(journal.TextJobDeferred, match="worker_lease_lost"):
            executing.result()
    assert run(queue, new, forbidden) == "late receipt"
    assert len(meter.holds) == 1 and list(meter.spent.values()) == [1]


def test_expired_unspent_hold_rotates_only_before_dispatch(queue, meter):
    job = queue.claim(60)
    meter.expired = True
    with pytest.raises(journal.TextJobDeferred, match="reservation_expired"):
        run(queue, job, forbidden)
    assert run(queue, job, lambda: "ok") == "ok"
    assert sorted(k.split(":")[-1] for k in meter.holds) == ["http.0", "http.1"]
    assert len(meter.spent) == 1


def test_identity_fingerprint_and_lease_change_fail_closed(queue, meter, monkeypatch):
    job = queue.claim(60)
    first_reserve = meter.reserve
    new_job = []
    def steal(*args, **kwargs):
        new_job.append(reclaim(queue, job))
        return first_reserve(*args, **kwargs)
    monkeypatch.setattr(journal, "reserve_text", steal)
    with pytest.raises(journal.TextJobDeferred, match="worker_lease_lost"):
        run(queue, job, forbidden)
    monkeypatch.setattr(journal, "reserve_text", first_reserve)
    new = new_job[0]
    for changed in ({"actor_id":"other"}, {"school_id":"SchoolA"}, {"actor_type":"system"}):
        with pytest.raises(journal.TextJobDeferred, match="usage_identity_changed"):
            run(queue, new, forbidden, actor={**ACTOR, **changed})
    monkeypatch.setenv("SERVICE_ID", "interview")
    with pytest.raises(journal.TextJobDeferred, match="usage_identity_changed"):
        journal.reconcile_job(queue, new, ACTOR)
    monkeypatch.setenv("SERVICE_ID", "assessment")
    assert run(queue, new, lambda: "ok") == "ok"
    assert len(meter.holds) == 1
    with pytest.raises(journal.TextJobDeferred, match="model_request_changed"):
        run(queue, new, forbidden, digest="a" * 64)


def test_worker_dies_after_committed_dispatch_never_reissues(queue, meter):
    # 记录派发意图后立即硬退出。新进程只能依靠持久记录判断能否重发，不能依赖清理回调和内存锁。
    child = """
import os, sys, time
from services.interview.test_jobs import SQLite
from services.interview.jobs import JobQueue
from services.usage import journal
from services.usage.test_journal import ACTOR, Meter, run
q = JobQueue(SQLite(sys.argv[1]), 'sqlite')
job = q.claim(60)
meter = Meter()
journal.reserve_text = meter.reserve
journal.begin_text = meter.begin
run(q, job, lambda: os._exit(71))
"""
    crash = subprocess.run([sys.executable, "-c", child, str(queue.db.path)],
                           cwd=Path(__file__).resolve().parents[2], timeout=20)
    assert crash.returncode == 71
    old = queue._one("SELECT * FROM interview_jobs", ())
    new = reclaim(queue, old)
    with pytest.raises(journal.TextJobDeferred, match="reconciliation"):
        run(queue, new, forbidden, purpose="next_provider")
    assert queue._one("SELECT state FROM worker_model_attempts", ())["state"] == "unknown"
    assert not meter.holds


def test_hard_exit_after_content_saved_recovers_without_model(queue, meter):
    child = """
import os, sys
from services.interview.test_jobs import SQLite
from services.interview.jobs import JobQueue
from services.usage import journal
from services.usage.test_journal import Meter, run
q = JobQueue(SQLite(sys.argv[1]), 'sqlite')
meter = Meter()
journal.reserve_text = meter.reserve
journal.begin_text = meter.begin
journal.settle_text = lambda *args, **kwargs: os._exit(72)
run(q, q.claim(60), lambda: 'persisted before crash')
"""
    crash = subprocess.run([sys.executable, "-c", child, str(queue.db.path)],
                           cwd=Path(__file__).resolve().parents[2], timeout=20)
    assert crash.returncode == 72
    saved = queue._one("SELECT state,content FROM worker_model_attempts", ())
    assert saved == {"state":"received", "content":"persisted before crash"}
    job = reclaim(queue, queue._one("SELECT * FROM interview_jobs", ()))
    assert run(queue, job, forbidden) == saved["content"]
    assert not meter.holds and list(meter.spent.values()) == [1]


def test_published_generation_keeps_fence_and_allows_new_generation(queue, meter):
    job = queue.claim(60)
    assert run(queue, job, lambda: "first", purpose="g0.slot1") == "first"
    def publish():
        queue.db.execute("""UPDATE worker_model_attempts SET state='published',content=NULL
                          WHERE job_id=? AND state='settled'""", (job["id"],)).close()
    assert queue.finish(job, publish)
    with queue.db:
        queue.request_retry(job["id"], include_done=True)
    rerun = queue.claim(60)
    with pytest.raises(journal.TextJobDeferred):
        run(queue, rerun, forbidden, purpose="g0.slot1")
    assert run(queue, rerun, lambda: "new business request", purpose="g1.slot1") == "new business request"
    assert sorted(meter.spent.values()) == [1, 1]


@pytest.mark.parametrize("pin_before_cancel", [False, True])
def test_old_begin_cannot_dispatch_after_new_worker_refunds(queue, meter, monkeypatch, pin_before_cancel):
    job = queue.claim(60)
    entered, proceed = Event(), Event()
    def racing_begin(actor, rid):
        if pin_before_cancel:
            meter.begin(actor, rid)
        entered.set()
        assert proceed.wait(5)
        if not pin_before_cancel:
            meter.begin(actor, rid)
    monkeypatch.setattr(journal, "begin_text", racing_begin)
    with ThreadPoolExecutor(1) as pool:
        old = pool.submit(run, queue, job, forbidden)
        assert entered.wait(5)
        try:
            newer = reclaim(queue, job)
            journal.reconcile_job(queue, newer, ACTOR)
            assert list(meter.spent.values()) == [0]
            assert queue._one("SELECT state,generation FROM worker_model_attempts", ()) == {
                "state":"prepared", "generation":1}
        finally:
            proceed.set()
        with pytest.raises(journal.TextJobDeferred):
            old.result()
    monkeypatch.setattr(journal, "begin_text", meter.begin)
    assert run(queue, newer, lambda: "replacement") == "replacement"
    assert sorted(meter.spent.values()) == [0, 1]


def test_unpinned_expiry_after_lost_begin_is_cleared_by_reclaimer(queue, meter, monkeypatch):
    def never_reached(*args):
        raise HTTPException(503, "usage down")
    monkeypatch.setattr(journal, "begin_text", never_reached)
    job = queue.claim(60)
    with pytest.raises(journal.TextJobDeferred, match="authorization_reconciliation_pending"):
        run(queue, job, forbidden)
    meter.expired = True
    new = reclaim(queue, job)
    journal.reconcile_job(queue, new, ACTOR)
    assert not meter.spent
    monkeypatch.setattr(journal, "begin_text", meter.begin)
    assert run(queue, new, lambda: "ok") == "ok"


def test_model_switch_before_dispatch_fences_late_reservation(queue, meter, monkeypatch):
    job = queue.claim(60)
    entered, proceed = Event(), Event()
    def old_reservation(actor, **kwargs):
        hold = meter.reserve(actor, **kwargs)
        if kwargs["purpose"] == "http.0":
            entered.set()
            assert proceed.wait(5)
        return hold
    monkeypatch.setattr(journal, "reserve_text", old_reservation)
    with ThreadPoolExecutor(1) as pool:
        old = pool.submit(run, queue, job, forbidden)
        assert entered.wait(5)
        try:
            assert run(queue, job, lambda: "new model", digest="1"*64) == "new model"
        finally:
            proceed.set()
        with pytest.raises(journal.TextJobDeferred, match="model_attempt_changed"):
            old.result()
    assert len(meter.pinned) == 1 and list(meter.spent.values()) == [1]


def test_real_ledger_pin_keeps_budget_until_late_settlement(queue, tmp_path, monkeypatch):
    from services.usage import text
    from services.usage.app import Reservation
    from services.usage.ledger import UsageLedger
    from shared.service_db import ServiceDatabase

    ledger = UsageLedger(ServiceDatabase.from_env("usage", {
        "USAGE_DB_ENGINE":"sqlite", "USAGE_SQLITE_PATH":str(tmp_path / "ledger.sqlite")}))
    ledger.initialize()
    ledger.configure("schoolA", 1, 0)
    # 选取未来某月的第一周，保证两次观测属于同一账期，不受测试运行日期影响。
    from datetime import datetime, timedelta, timezone
    first = datetime.now(timezone.utc).replace(day=1)
    clock = [int((first + timedelta(days=35)).timestamp())]
    monkeypatch.setattr(ledger, "_now", lambda tx: clock[0])
    available = [False]
    def route(actor, scope, path, body):
        ctx = {**actor, "caller":"assessment"}
        if scope == "usage.reserve":
            return ledger.reserve(ctx, Reservation(**body))
        rid = path.split("/")[-2]
        if scope == "usage.dispatch":
            return ledger.begin(ctx, rid)
        assert scope == "usage.settle"
        if not available[0]:
            raise HTTPException(503, "temporarily offline")
        return ledger.settle(ctx, rid, body["actual_units"])
    monkeypatch.setattr(text, "_post", route)
    job = queue.claim(60)
    with pytest.raises(journal.TextJobDeferred, match="settlement_pending"):
        run(queue, job, lambda: "persisted")
    clock[0] += 3601
    assert ledger.quota("schoolA")["text"]["available"] == 0
    available[0] = True
    assert run(queue, reclaim(queue, job), forbidden) == "persisted"
    with ledger.store.transaction() as tx:
        assert tx.one("SELECT actual_units FROM usage_reservations") == {"actual_units":1}
        assert tx.one("SELECT units FROM usage_spent") == {"units":1}
