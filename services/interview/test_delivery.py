"""通过进程内 HTTP 传输，验证持久化任务由真实工作进程投递。"""
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import httpx

from services.interview import delivery
from services.interview.jobs import JobQueue
from services.interview.test_jobs import SQLite
from services.interview.worker import run_once


class OutboundTest(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = SQLite(Path(tmp.name) / "delivery.sqlite")
        self.addCleanup(self.db.connect().close)
        self.db.connect().executescript("""
            PRAGMA foreign_keys=ON;
            CREATE TABLE interview_sessions(id TEXT PRIMARY KEY, user_id TEXT, status TEXT);
            CREATE TABLE interview_training_attempts(interview_id,attempt_id,student_id,school_id);
            CREATE TABLE interview_training_questions(interview_id,position,frozen_question_id,message_id);
            CREATE TABLE interview_turns(interview_id,question_id,answer_id);
            INSERT INTO interview_turns VALUES ('i','qid','ans');
            CREATE TABLE interview_messages(id,interview_id,reply_to_message_id,content,sender_type,message_type,order_index);
            INSERT INTO interview_sessions VALUES ('i','u','completed'),('regular','u','completed');
            INSERT INTO interview_training_attempts VALUES ('i','a','u','school');
            INSERT INTO interview_training_questions VALUES ('i',1,'frozen','qid');
            INSERT INTO interview_messages VALUES
                ('ans','i','qid','full original answer','candidate','answer',2),
                ('foreign','i','qid','unrelated answer','candidate','answer',4);
        """)
        self.queue = JobQueue(self.db, "sqlite")
        self.queue.migrate()
        self.report = {"id": "r", "interview_id": "i", "timeline_review": json.dumps([
            {"message_id": "ans", "dimension_scores": {"logic": 0}},
            {"message_id": "foreign", "dimension_scores": {"logic": 82}},
        ])}
        self.env = patch.dict(os.environ, {"LEGACY_SCHOOL_ID": "school", "SERVICE_ID": "assessment",
                                          "TRAINING_SERVICE_URL": "https://training.invalid",
                                          "ANALYTICS_SERVICE_URL": "https://analytics.invalid"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.signer = patch("shared.service_security.service_headers",
                            return_value={"Authorization": "Bearer internal-test"})
        self.headers = self.signer.start()
        self.addCleanup(self.signer.stop)

    def run_job(self, key, peer):
        with self.db:
            self.queue.request_retry(key)
        client = httpx.Client(transport=httpx.MockTransport(peer), trust_env=False)
        with patch("httpx.Client", return_value=client):
            self.assertTrue(run_once(self.queue, lambda job: delivery.prepare_delivery(self.queue, job), job_id=key))

    def test_training_receipt_gates_immutable_analytics_even_after_lost_reply(self):
        with self.db:
            complete = delivery.enqueue_training_complete(self.queue, "i")
            first = delivery.enqueue_analytics(self.queue, self.report, 1)
        self.run_job(first, lambda _: self.fail("analytics sent before completion"))
        self.assertEqual("pending", self.queue.get(first)["state"])

        requests = []
        def training(req):
            self.assertEqual("https://training.invalid/attempts/a/complete", str(req.url))
            self.assertEqual("Bearer internal-test", req.headers["authorization"])
            requests.append(json.loads(req.content))
            if len(requests) == 1:
                raise httpx.ReadTimeout("peer has already committed")
            if len(requests) == 2:
                return httpx.Response(200, json={"attempt_id": "other"})
            return httpx.Response(200, json={"attempt_id": "a", "interview_id": "i", "student_id": "u",
                                             "school_id": "school", "status": "completed"})

        for expected in ("pending", "pending", "done"):
            self.run_job(complete, training)
            self.assertEqual(expected, self.queue.get(complete)["state"])
        self.assertEqual([{"event_id": complete, "interview_id": "i"}] * 3, requests)
        self.headers.assert_called_with("training", actor_id="assessment", school_id="school",
                                        actor_type="system", scopes=["training.complete"])

        sent = []
        def analytics(req):
            self.assertEqual("https://analytics.invalid/v1/completions", str(req.url))
            body = json.loads(req.content)
            sent.append(body)
            return httpx.Response(200, json={"attempt_id": "a", "version": body["version"], "applied": True})

        with self.db:
            self.db.execute("UPDATE interview_messages SET content='later revision' WHERE id='ans'").close()
            self.report["timeline_review"] = [{"message_id": "ans", "dimension_scores": {"logic": 94}}]
            revised = delivery.enqueue_analytics(self.queue, self.report, 2)
            self.assertEqual(first, delivery.enqueue_analytics(self.queue, self.report, 1))
        self.run_job(first, analytics)
        self.run_job(revised, analytics)
        self.headers.assert_called_with("analytics", actor_id="assessment", school_id="school",
                                        actor_type="system", scopes=["analytics.completion.write"])
        self.assertEqual([(first, 1), (revised, 2)], [(r["event_id"], r["version"]) for r in sent])
        self.assertEqual([{"question_id": "frozen", "original_answer": "full original answer",
                           "dimension": "logic", "score": 0}], sent[0]["questions"])
        self.assertEqual([{"question_id": "frozen", "original_answer": "later revision",
                           "dimension": "logic", "score": 94}], sent[1]["questions"])

    def test_unbound_or_open_interview_has_no_event_and_rollback_leaves_no_work(self):
        with self.db:
            self.assertIsNone(delivery.enqueue_training_complete(self.queue, "regular"))
            self.db.execute("UPDATE interview_sessions SET status='active' WHERE id='i'").close()
            self.assertIsNone(delivery.enqueue_analytics(self.queue, self.report, 1))
        with self.assertRaises(ValueError), self.db:
            self.db.execute("UPDATE interview_sessions SET status='completed' WHERE id='i'").close()
            delivery.enqueue_analytics(self.queue, self.report, 1)
            raise ValueError()
        self.assertIsNone(self.queue.claim(60))
        self.assertEqual([], self.db.execute("SELECT * FROM interview_delivery_events").fetchall())

    def test_deployment_scope_and_worker_filter(self):
        with self.db:
            key = delivery.enqueue_training_complete(self.queue, "i")
        self.assertIsNone(self.queue.claim(60, kinds=("analytics", "score")))
        with patch.dict(os.environ, {"LEGACY_SCHOOL_ID": "wrong-school"}):
            self.run_job(key, lambda _: self.fail("sent for another school"))
        self.assertEqual("pending", self.queue.get(key)["state"])
        self.headers.assert_not_called()


if __name__ == "__main__":
    unittest.main()
