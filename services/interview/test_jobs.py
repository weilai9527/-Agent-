"""离线验证工作进程的任务存储，测试期间不导入旧版环境配置加载器。"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Barrier, local
from time import monotonic, sleep
import unittest

from services.interview.jobs import JobQueue, RetryJob
from services.interview.worker import run_once


class SQLite:
    def __init__(self, path):
        self.path = path
        self._local = local()

    def connect(self):
        if not hasattr(self._local, "conn"):
            conn = sqlite3.connect(self.path, timeout=10)
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return self._local.conn

    def execute(self, sql, params=()):
        return self.connect().execute(sql, params)

    def __enter__(self):
        return self.connect().__enter__()

    def __exit__(self, *args):
        return self.connect().__exit__(*args)


class DurableJobsTest(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = SQLite(Path(tmp.name) / "isolated.sqlite")
        self.addCleanup(self.db.connect().close)
        self.queue = JobQueue(self.db, "sqlite")
        self.queue.migrate()
        with self.db:
            self.db.execute("CREATE TABLE interview_sessions(id TEXT PRIMARY KEY)").close()
            self.db.execute("INSERT INTO interview_sessions VALUES ('interview')").close()
            self.db.execute("CREATE TABLE results(value TEXT)").close()

    def enqueue(self, version="evidence-v1"):
        with self.db:
            return self.queue.enqueue("score", "interview", "answer", version)

    def write(self, value):
        self.db.execute("INSERT INTO results VALUES (?)", (value,)).close()

    def results(self):
        with closing(self.db.execute("SELECT value FROM results ORDER BY value")) as rows:
            return [r["value"] for r in rows]

    def expire(self, key):
        with self.db:
            self.db.execute("UPDATE interview_jobs SET ready_at=0 WHERE id=?", (key,)).close()

    def test_domain_write_and_enqueue_rollback_or_commit_together(self):
        with self.assertRaises(RuntimeError), self.db:
            self.write("answer")
            key = self.queue.enqueue("score", "interview", "answer", "evidence-v1")
            raise RuntimeError()
        self.assertEqual([], self.results())
        self.assertIsNone(self.queue.get(key))
        self.assertEqual(key, self.enqueue())
        self.assertEqual(key, self.enqueue())
        self.assertNotEqual(key, self.enqueue("evidence-v2"))
        self.queue.migrate()
        self.assertEqual("pending", self.queue.get(key)["state"])

    def test_crash_reclaim_and_fence(self):
        key = self.enqueue()
        # 在领取任务的事务提交后、发布结果前终止子进程。
        # 新进程可以重新领取该任务，无需重发原请求。
        code = """
import os, sys
from services.interview.test_jobs import SQLite
from services.interview.jobs import JobQueue
q = JobQueue(SQLite(sys.argv[1]), 'sqlite')
job = q.claim(120)
assert job['id'] == sys.argv[2]
os._exit(73)
"""
        child = subprocess.run([sys.executable, "-c", code, str(self.db.path), key],
                               cwd=Path(__file__).resolve().parents[2], timeout=10)
        self.assertEqual(73, child.returncode)
        old = self.queue.get(key)
        self.assertIsNone(self.queue.claim(120))
        self.expire(key)
        self.assertFalse(self.queue.renew(old, 120))
        self.assertFalse(self.queue.finish(old, lambda: self.write("expired")))
        new = self.queue.claim(120)
        self.assertNotEqual(old["lease_token"], new["lease_token"])
        self.assertFalse(self.queue.retry(old, ValueError()))
        self.assertFalse(self.queue.finish(old, lambda: self.write("stale")))
        self.assertTrue(self.queue.finish(new, lambda: self.write("current")))
        self.assertEqual(["current"], self.results())
        self.assertEqual(key, self.enqueue())
        self.assertIsNone(self.queue.claim(120))

    def test_concurrent_claim_has_one_winner(self):
        self.enqueue()
        barrier = Barrier(4)

        def claim(_):
            try:
                barrier.wait(timeout=5)
                return self.queue.claim(120)
            finally:
                self.db.connect().close()

        with ThreadPoolExecutor(4) as pool:
            jobs = list(pool.map(claim, range(4)))
        self.assertEqual(1, sum(job is not None for job in jobs))

    def test_failed_publication_rolls_back_then_partial_result_can_retry(self):
        key = self.enqueue()

        def failing_publish():
            self.write("would-be-leak")
            raise ValueError("private provider detail")

        self.assertTrue(run_once(self.queue, lambda _: failing_publish))
        self.assertEqual([], self.results())
        self.assertEqual("ValueError", self.queue.get(key)["last_error"])
        self.assertFalse(run_once(self.queue, lambda _: self.fail()))
        with self.db:
            self.queue.request_retry(key)

        def partial():
            self.write("partial")
            return RetryJob(60)

        run_once(self.queue, lambda _: partial)
        self.assertEqual(["partial"], self.results())
        self.assertEqual("pending", self.queue.get(key)["state"])
        self.expire(key)
        run_once(self.queue, lambda _: lambda: self.write("finished"))
        self.assertEqual(["finished", "partial"], self.results())
        with self.db:
            self.queue.request_retry(key)
        self.assertEqual("done", self.queue.get(key)["state"])
        with self.db:
            self.queue.request_retry(key, include_done=True)
        job = self.queue.claim(120)
        with self.db:
            self.queue.request_retry(key, include_done=True)
        self.assertTrue(self.queue.finish(job, lambda: None))

    def test_prepare_runs_without_db_lock_and_worker_renews_lease(self):
        key = self.enqueue()

        def slow_prepare(job):
            # 准备阶段尚未结束时，验证工作线程会续租。
            deadline = monotonic() + 6
            while monotonic() < deadline:
                if self.queue.get(key)["ready_at"] > job["ready_at"]:
                    break
                sleep(0.05)
            else:
                self.fail("lease not renewed while computing")
            return lambda: self.write("renewed")

        run_once(self.queue, slow_prepare, lease_seconds=4)
        self.assertEqual(["renewed"], self.results())

    def test_removed_interview_discards_work(self):
        key = self.enqueue()
        old = self.queue.claim(120)
        with self.db:
            self.db.execute("DELETE FROM interview_sessions").close()
        self.assertTrue(self.queue.finish(old, lambda: self.fail("deleted interview")))
        self.assertEqual("done", self.queue.get(key)["state"])


if __name__ == "__main__":
    unittest.main()
