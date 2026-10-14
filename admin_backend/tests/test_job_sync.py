"""Isolated feed tests: no live DB, credentials, or upstream service required."""
import io
import json
import os
import sqlite3
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from admin_backend.src import job_sync
from shared.recruitment import ensure_recruitment_schema


class JobSyncTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        ensure_recruitment_schema(self.db, "sqlite")
        self.env = patch.dict(os.environ, {"JOB_POSTING_SYNC_ENDPOINT": "https://feed.example.test/jobs", "JOB_POSTING_SYNC_TOKEN": "", "JOB_POSTING_SYNC_SOURCE": "test"})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.db.close()

    def fetch(self, data):
        with patch.object(job_sync, "build_opener") as opener:
            opener.return_value.open.return_value = io.BytesIO(data)
            return job_sync.fetch_job_feed()

    def test_feed_shapes_and_invalid_responses(self):
        for payload in ([], {"items": []}):
            self.assertEqual(self.fetch(json.dumps(payload).encode()), [])
        for content in (b"<html>error</html>", b'{"data": []}', b'null', b'{}', b'\xff'):
            with self.assertRaises(job_sync.JobSyncError):
                self.fetch(content)
        with self.assertRaisesRegex(job_sync.JobSyncError, "最多"):
            self.fetch(json.dumps([{}] * (job_sync.MAX_ROWS + 1)).encode())
        with patch.object(job_sync, "MAX_BYTES", 10), self.assertRaisesRegex(job_sync.JobSyncError, "5 MB"):
            self.fetch(b" " * 11)

    def test_config_and_upstream_errors_do_not_expose_secrets(self):
        for endpoint in ("", "file:///secret", "https://user:password@example.test/jobs"):
            with patch.dict(os.environ, {"JOB_POSTING_SYNC_ENDPOINT": endpoint}), self.assertRaises(job_sync.JobSyncError):
                job_sync.fetch_job_feed()
        for failure in (URLError("secret-token"), HTTPError("https://secret-token", 401, "secret-token", {}, None)):
            with patch.object(job_sync, "build_opener") as opener:
                opener.return_value.open.side_effect = failure
                with self.assertRaises(job_sync.JobSyncError) as caught:
                    job_sync.fetch_job_feed()
                self.assertNotIn("secret-token", str(caught.exception))

    def test_auth_header_and_redirects(self):
        with patch.dict(os.environ, {"JOB_POSTING_SYNC_TOKEN": "test-token"}), patch.object(job_sync, "build_opener") as opener:
            opener.return_value.open.return_value = io.BytesIO(b"[]")
            job_sync.fetch_job_feed()
            request = opener.return_value.open.call_args.args[0]
            self.assertEqual(request.get_header("Authorization"), "Bearer test-token")
            self.assertIsInstance(opener.call_args.args[0], job_sync.NoRedirects)
        with patch.dict(os.environ, {"JOB_POSTING_SYNC_ENDPOINT": "http://feed.example.test", "JOB_POSTING_SYNC_TOKEN": "test-token"}), self.assertRaises(job_sync.JobSyncError):
            job_sync.fetch_job_feed()
        self.assertIsNone(job_sync.NoRedirects().redirect_request(None, None, 302, "", {}, "https://elsewhere.test"))

    def test_repeat_sync_updates_without_duplicate_or_losing_fields(self):
        row = {"id": "job-1", "title": "工程师", "company": "示例公司", "skills": ["Python", "SQL"], "description": "保留描述"}
        first = job_sync.import_job_feed(self.db, [row], created_by="tester")
        second = job_sync.import_job_feed(self.db, [{"id": "job-1", "title": "高级工程师", "status": "disabled"}], created_by="tester")
        self.assertEqual((first["created"], second["updated"]), (1, 1))
        rows = self.db.execute("SELECT * FROM job_postings").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "高级工程师")
        self.assertEqual(rows[0]["description"], "保留描述")
        self.assertEqual(rows[0]["skills"], "Python、SQL")
        self.assertEqual(rows[0]["status"], "disabled")

    def test_bad_rows_reported_and_other_sources_not_overwritten(self):
        row = {"id": 0, "title": "工程师"}
        result = job_sync.import_job_feed(self.db, [row, {}, "bad", {"id": "bad", "title": "test", "status": "unexpected"}], created_by="tester")
        self.assertEqual((result["total"], result["created"], result["skipped"]), (4, 1, 3))
        self.assertEqual(len(result["errors"]), 3)
        with patch.dict(os.environ, {"JOB_POSTING_SYNC_SOURCE": "other"}):
            self.assertEqual(job_sync.import_job_feed(self.db, [row], created_by="tester")["created"], 1)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM job_postings").fetchone()[0], 2)

    def test_real_http_feed_to_database_and_rejected_redirect(self):
        class FeedHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == '/redirect':
                    self.send_response(302)
                    self.send_header('Location', '/jobs')
                    self.end_headers()
                    return
                content = json.dumps({"items": [{"id": "http-job", "title": "HTTP 同步工程师", "company": "测试公司"}]}, ensure_ascii=False).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(content)))
                self.end_headers()
                self.wfile.write(content)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), FeedHandler)
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            base = f'http://127.0.0.1:{server.server_port}'
            with patch.dict(os.environ, {'JOB_POSTING_SYNC_ENDPOINT': base + '/jobs'}):
                first = job_sync.import_job_feed(self.db, job_sync.fetch_job_feed(), created_by='tester')
                second = job_sync.import_job_feed(self.db, job_sync.fetch_job_feed(), created_by='tester')
            self.assertEqual((first['created'], second['updated']), (1, 1))
            self.assertEqual(self.db.execute('SELECT title FROM job_postings').fetchone()[0], 'HTTP 同步工程师')
            with patch.dict(os.environ, {'JOB_POSTING_SYNC_ENDPOINT': base + '/redirect'}), self.assertRaisesRegex(job_sync.JobSyncError, 'HTTP 302'):
                job_sync.fetch_job_feed()
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=5)

    def test_database_failure_rolls_back_entire_batch(self):
        original = job_sync.upsert_job_posting_by_source
        def fail_second(db, payload, **kwargs):
            if payload['title'] == '第二条':
                raise RuntimeError('simulated database failure')
            return original(db, payload, **kwargs)
        with patch.object(job_sync, 'upsert_job_posting_by_source', side_effect=fail_second), self.assertRaises(RuntimeError):
            job_sync.import_job_feed(self.db, [{'id': 'a', 'title': '第一条'}, {'id': 'b', 'title': '第二条'}], created_by='tester')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM job_postings').fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
