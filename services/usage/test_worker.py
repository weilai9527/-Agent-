"""在临时专库中执行普通模型调用路径。任务租约、发布事务、日志和跨进程重放均使用真实实现。"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from shared.text_provider import _call_provider_content
from services.interview.jobs import JobQueue
from services.interview.test_jobs import SQLite
from services.interview.worker import run_once
from services.usage import journal, worker
from services.usage.test_journal import Meter
from services.usage.test_provider_calls import FIRST, GOOD, install_transport


@pytest.fixture
def queue(tmp_path, monkeypatch):
    monkeypatch.setenv("ASSESSMENT_STORAGE_MODE", "isolated")
    monkeypatch.setenv("LEGACY_SCHOOL_ID", "school-a")
    monkeypatch.setenv("SERVICE_ID", "assessment")
    monkeypatch.delenv("USAGE_SERVICE_URL", raising=False)
    db = SQLite(tmp_path / "worker.sqlite")
    with db:
        db.execute("CREATE TABLE interview_sessions(id TEXT PRIMARY KEY, user_id TEXT)").close()
        db.execute("INSERT INTO interview_sessions VALUES ('i','student')").close()
        db.execute("CREATE TABLE interview_training_attempts(interview_id TEXT, school_id TEXT, student_id TEXT)").close()
        db.execute("""CREATE TABLE assessment_projection_inbox
                      (interview_id TEXT, sequence_no INTEGER, school_id TEXT, student_id TEXT)""").close()
        db.execute("INSERT INTO assessment_projection_inbox VALUES ('i',0,'school-a','student')").close()
        db.execute("CREATE TABLE published(response TEXT)").close()
    q = JobQueue(db, "sqlite")
    q.migrate()
    yield q
    db.connect().close()


def enqueue(q):
    with q.db:
        return q.enqueue("score", "i", "answer", "v1")


def business(q, *, fail_publish=False):
    @worker.metered(q)
    def prepare(job):
        result = _call_provider_content(FIRST, [{"role": "user", "content": "synthetic private reply"}], json_mode=True)

        def publish():
            q.db.execute("INSERT INTO published VALUES (?)", (result,)).close()
            if fail_publish:
                raise ValueError("failed to publish")

        return publish
    return prepare


def activate(q, monkeypatch):
    monkeypatch.setenv("USAGE_SERVICE_URL", "https://usage.test")
    worker.initialize(q)


def stub_quota(monkeypatch):
    meter = Meter()
    monkeypatch.setattr(journal, "reserve_text", meter.reserve)
    monkeypatch.setattr(journal, "begin_text", meter.begin)
    monkeypatch.setattr(journal, "settle_text", meter.settle)
    return meter


def test_fresh_native_database_cannot_dispatch_without_usage_url(queue, monkeypatch):
    calls = install_transport(monkeypatch, [])
    meter = stub_quota(monkeypatch)
    worker.initialize(queue)
    assert worker.policy(queue) == {"school_id": "school-a", "caller": "assessment"}
    key = enqueue(queue)
    assert run_once(queue, business(queue), job_id=key)
    assert not calls and not meter.holds
    assert queue.get(key)["state"] == "pending"
    assert queue._one("SELECT wait_reason FROM worker_text_runs", ())["wait_reason"] == "usage_unavailable"


def test_unmetered_compatibility_requires_an_explicit_temporary_fixture(tmp_path):
    # 新解释器中逐步增加授权，避免其他测试曾启用离线夹具影响结果。
    script = """
from pathlib import Path
import os
from shared.offline_fixture import enable_offline_fixture
from services.interview.jobs import JobQueue
from services.interview.test_jobs import SQLite
from services.usage import worker
q = JobQueue(SQLite(Path(os.environ["SQLITE_PATH"])), "sqlite")
try:
    worker.initialize(q)
except RuntimeError:
    pass
else:
    raise AssertionError("仅设置 shared 和 APP_ENV=test 不应启用离线模式")
enable_offline_fixture()
worker.initialize(q)
assert worker.prepare_metered(q, {}, lambda job: "合成结果") == "合成结果"
os.environ["SERVICE_ID"] = "assessment"
try:
    worker.prepare_metered(q, {}, lambda job: "错误授权")
except RuntimeError:
    pass
else:
    raise AssertionError("业务身份不能沿用夹具许可")
"""
    env = {**os.environ, "APP_ENV": "test", "DB_ENGINE": "sqlite", "SQLITE_PATH": str(tmp_path / "legacy.sqlite"),
           "ASSESSMENT_STORAGE_MODE": "shared", "SERVICE_ID": "offline-fixture"}
    env.pop("USAGE_SERVICE_URL", None)
    subprocess.run([sys.executable, "-c", script], cwd=Path(__file__).resolve().parents[2],
                   env=env, check=True, timeout=30)


@pytest.mark.parametrize("lost", ["url", "caller", "school"])
def test_persisted_policy_survives_replica_misconfiguration(queue, monkeypatch, lost):
    activate(queue, monkeypatch)
    key = enqueue(queue)
    calls = install_transport(monkeypatch, [])
    if lost == "url":
        monkeypatch.delenv("USAGE_SERVICE_URL")
    elif lost == "caller":
        monkeypatch.setenv("SERVICE_ID", "other-replica")
    else:
        monkeypatch.setenv("LEGACY_SCHOOL_ID", "other-school")
    # 新进程连接同一专库后，仍须遵守原先绑定的学校和计量身份。
    other = JobQueue(SQLite(queue.db.path), "sqlite")
    try:
        worker.initialize(other)
        assert worker.policy(other) == {"school_id": "school-a", "caller": "assessment"}
        assert run_once(other, business(other), job_id=key)
        assert other.get(key)["state"] == "pending" and not calls
        if lost == "caller":
            assert not other._one("SELECT * FROM worker_text_runs", ())
        else:
            reason = "usage_unavailable" if lost == "url" else "usage_worker_identity_mismatch"
            assert other._one("SELECT wait_reason FROM worker_text_runs", ())["wait_reason"] == reason
        assert not other._one("SELECT * FROM published", ())
    finally:
        other.db.connect().close()


@pytest.mark.parametrize(("isolated", "school", "student", "reason"), [
    (False, "school-b", "student", "usage_training_owner_mismatch"),
    (False, "school-a", "other", "usage_training_owner_mismatch"),
    (True, None, None, "usage_projection_owner_mismatch"),
    (True, "school-b", "student", "usage_projection_owner_mismatch"),
    (True, "school-a", "other", "usage_projection_owner_mismatch"),
])
def test_source_owner_mismatch_never_reserves_or_dispatches(queue, monkeypatch, isolated, school, student, reason):
    activate(queue, monkeypatch)
    meter = stub_quota(monkeypatch)
    calls = install_transport(monkeypatch, [])
    with queue.db:
        if isolated:
            queue.db.execute("DELETE FROM assessment_projection_inbox").close()
        if isolated and school:
            queue.db.execute("INSERT INTO assessment_projection_inbox VALUES ('i',0,?,?)", (school, student)).close()
        elif not isolated:
            queue.db.execute("INSERT INTO interview_training_attempts VALUES ('i',?,?)", (school, student)).close()
    key = enqueue(queue)
    assert run_once(queue, business(queue), job_id=key)
    assert not calls and not meter.holds
    assert queue.get(key)["state"] == "pending"
    assert queue._one("SELECT wait_reason FROM worker_text_runs", ())["wait_reason"] == reason


def test_paid_response_survives_publish_rollback_restart_and_explicit_force(queue, monkeypatch):
    activate(queue, monkeypatch)
    key = enqueue(queue)
    meter = stub_quota(monkeypatch)
    another = {"choices": [{"message": {"content": '{"score": 21}'}}]}
    calls = install_transport(monkeypatch, [(200, GOOD), (200, another)])
    assert run_once(queue, business(queue, fail_publish=True), job_id=key)
    assert queue.get(key)["state"] == "pending" and queue.get(key)["last_error"] == "ValueError"
    assert queue._one("SELECT * FROM published", ()) is None
    assert queue._one("SELECT state,content FROM worker_model_attempts", ()) == {
        "state": "settled", "content": '{"score": 17}'}
    assert len(calls) == 1 and list(meter.spent.values()) == [1]
    with queue.db:
        queue.request_retry(key)

    # 未配置模型的副本可能要求稍后重试；已付费的回执必须保留给能重放原调用的工作进程。
    from services.interview.jobs import RetryJob
    no_provider = worker.metered(queue)(lambda job: lambda: RetryJob())
    assert run_once(queue, no_provider, job_id=key)
    assert queue._one("SELECT execution_no,wait_reason FROM worker_text_runs", ()) == {
        "execution_no": 1, "wait_reason": "model_replay_pending"}
    assert queue._one("SELECT state,content FROM worker_model_attempts", ()) == {
        "state": "settled", "content": '{"score": 17}'}
    with queue.db:
        queue.request_retry(key)

    # 新解释器没有内存缓存，禁用网络后仍应从持久回执完成发布。
    child = """
import sys
from unittest.mock import patch
from services.interview.jobs import JobQueue
from services.interview.test_jobs import SQLite
from services.interview.worker import run_once
from services.usage.test_worker import business
from services.usage import worker
q = JobQueue(SQLite(sys.argv[1]), "sqlite")
worker.initialize(q)
with patch("httpx.Client", side_effect=AssertionError("unexpected network")) as network:
    assert run_once(q, business(q), job_id=sys.argv[2])
    network.assert_not_called()
assert q.get(sys.argv[2])["state"] == "done"
q.db.connect().close()
"""
    subprocess.run([sys.executable, "-c", child, str(queue.db.path), key],
                   cwd=Path(__file__).resolve().parents[2], timeout=30, check=True)
    assert queue._one("SELECT response FROM published", ()) == {"response": '{"score": 17}'}
    assert queue._one("SELECT execution_no FROM worker_text_runs", ())["execution_no"] == 2
    assert queue._one("SELECT state,content FROM worker_model_attempts", ()) == {"state": "published", "content": None}
    assert not run_once(queue, business(queue), job_id=key)

    with queue.db:
        queue.request_retry(key, include_done=True)
    assert run_once(queue, business(queue), job_id=key)
    assert len(calls) == 2 and sorted(meter.spent.values()) == [1, 1]
    assert queue.get(key)["state"] == "done"
    assert [r["response"] for r in queue.db.execute("SELECT response FROM published ORDER BY rowid")] == [
        '{"score": 17}', '{"score": 21}']
    assert [tuple(row) for row in queue.db.execute(
        "SELECT purpose,state,content FROM worker_model_attempts ORDER BY purpose")] == [
        ("g1.call1", "published", None), ("g2.call1", "published", None)]
    assert [r.headers["X-Client-Request-Id"] for r in calls] == [
        row["id"] for row in queue.db.execute("SELECT id FROM worker_model_attempts ORDER BY purpose")]
