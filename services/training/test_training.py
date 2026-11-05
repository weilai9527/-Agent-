"""通过进程内请求和临时数据库验证授权、事务并发与幂等性。"""

import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from services.training import app as api


def context(actor="t1", role="teacher", school="north", caller="gateway"):
    return {"actor_id": actor, "actor_type": role, "school_id": school, "caller": caller,
            "scopes": []}


class TrainingTest(unittest.TestCase):
    def setUp(self):
        tmp = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch.dict(os.environ, {"TRAINING_DB_ENGINE": "sqlite",
                                                  "TRAINING_SQLITE_PATH": str(Path(tmp, "test.sqlite"))}))
        self.client = self.enterContext(TestClient(api.app))
        self.members = {"c1": ["s1", "s2"], "c2": ["s3"]}

        def identity(ctx, method, path, scope, body=None):
            if ctx["school_id"] != "north" or ctx["actor_id"] not in ("t1", "admin"):
                raise HTTPException(403)
            if path == "/classes":
                return {"items": [{"class_id": c, "name": c} for c in self.members]}
            ids = body["class_ids"]
            if not set(ids) <= set(self.members):
                raise HTTPException(403)
            return {"classes": [{"class_id": c, "student_ids": self.members[c]} for c in ids]}

        self.enterContext(patch.object(api.identity, "_request", side_effect=identity))
        self.addCleanup(api.app.dependency_overrides.clear)
        self.delegate(context())
        self.body = {
            "request_id": "assign-key", "title": "数据库基础", "job_role": "数据库开发",
            "class_ids": ["c1"], "deadline": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            "max_attempts": 2, "questions": [{"question_id": "q1", "prompt": "如何防止并发超限？"}],
        }

    def delegate(self, actor):
        for dependency in (api.read, api.assign, api.start, api.verify, api.complete):
            api.app.dependency_overrides[dependency] = lambda: actor

    def publish(self):
        self.delegate(context())
        response = self.client.post("/tasks", json=self.body)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["task_id"]

    def launch(self, tid, request_id="start-key"):
        return self.client.post(f"/tasks/{tid}/attempts", json={"request_id": request_id})

    def finish(self, attempt, key="done-key"):
        return self.client.post("/attempts/" + attempt["attempt_id"] + "/complete",
                                json={"event_id": key, "interview_id": attempt["interview_id"]})

    def test_assignment_snapshot_and_scopes(self):
        tid = self.publish()
        self.members["c1"] = ["s1", "late"]
        self.assertEqual(self.publish(), tid)
        self.assertEqual(self.client.post("/tasks", json={**self.body, "title": "other"}).status_code, 409)
        self.assertEqual(self.client.post("/tasks", json={**self.body, "student_ids": ["late"]}).status_code, 422)
        self.assertEqual(self.client.post("/tasks", json={**self.body, "class_ids": ["outside"]}).status_code, 403)
        self.assertEqual(self.client.get(f"/tasks/{tid}/roster").json()["items"][0]["student_id"], "s1")
        self.delegate(context("late", "student"))
        self.assertFalse(self.client.get("/tasks").json()["items"])
        self.assertEqual(self.launch(tid).status_code, 404)
        self.delegate(context("s2", "student"))
        self.assertEqual(self.launch(tid).status_code, 200)
        self.delegate(context("s2", "student", "south"))
        self.assertFalse(self.client.get("/tasks").json()["items"])
        self.assertEqual(self.launch(tid).status_code, 404)
        self.delegate(context("other"))
        self.assertEqual(self.client.get(f"/tasks/{tid}/roster").status_code, 404)

    def test_student_cannot_enumerate_other_target_classes(self):
        self.body["class_ids"] = ["c1", "c2"]
        self.publish()
        self.delegate(context("s1", "student"))
        item = self.client.get("/tasks").json()["items"][0]
        self.assertEqual(item["class_ids"], ["c1"])
        self.assertNotIn("student_count", item)
        self.assertEqual(self.client.get("/classes").status_code, 403)

    def test_workbench_counts_effective_assignments_and_honors_partial_revocation(self):
        # s1 有两项任务，重复完成其中一项；s3 在教师失去 c2 权限前完成任务。
        # 新转入或已转出的学生均不得改变有效应到口径或暴露撤权班级的数据。
        self.body["class_ids"] = ["c1", "c2"]
        across = self.publish()
        self.body.update(request_id="second-task", class_ids=["c1"])
        single = self.publish()
        self.delegate(context("s1", "student"))
        a = self.launch(across, "a1").json()
        b = self.launch(across, "a2").json()
        self.assertEqual(self.client.get("/tasks?view=workbench").status_code, 403)
        self.delegate(context("s3", "student"))
        hidden = self.launch(across).json()
        self.delegate(context("engine", "system", caller="interview"))
        for i, attempt in enumerate([a, b, hidden]):
            self.assertEqual(self.finish(attempt, "event-" + str(i)).status_code, 200)
        self.members["c2"] = ["new-in-c2"]
        self.delegate(context())
        inactive = self.client.get("/tasks?view=workbench").json()
        self.assertTrue(all(item["class_ids"] == ["c1"] for item in inactive["items"]))
        empty_class = next(c for c in inactive["classes"] if c["class_id"] == "c2")
        self.assertEqual(empty_class["task_count"], 0)
        del self.members["c2"]
        self.members.update(c1=["s1", "late"], c3=["idle"])
        self.delegate(context())
        with patch.object(api.identity, "roster", wraps=api.identity.roster) as rosters:
            normal = self.client.get("/tasks").json()["items"]
            rosters.assert_not_called()
            self.assertEqual([(t["class_ids"], t["student_count"]) for t in normal], [(["c1"], 2)] * 2)
            result = self.client.get("/tasks?view=workbench").json()
            self.assertEqual(rosters.call_count, 1)
            self.assertEqual(set(rosters.call_args.args[1]), {"c1", "c3"})
        self.assertEqual(result["summary"], {
            "task_count": 2, "enrolled_students": 3, "assigned_students": 1, "completed_students": 1,
            "assigned_task_students": 2, "completed_task_students": 1,
        })
        self.assertEqual({t["task_id"]: (t["student_count"], t["completed_count"]) for t in result["items"]},
                         {across: (1, 1), single: (1, 0)})
        groups = {row["class_id"]: row for row in result["classes"]}
        self.assertEqual(set(groups), {"c1", "c3"})
        self.assertEqual((groups["c1"]["enrolled_students"], groups["c1"]["assigned_students"],
                          groups["c1"]["task_count"], groups["c1"]["completed_task_students"]), (2, 1, 2, 1))
        self.assertEqual((groups["c3"]["enrolled_students"], groups["c3"]["task_count"]), (1, 0))
        roster = self.client.get(f"/tasks/{across}/roster").json()["items"]
        self.assertEqual([(r["student_id"], r["completed_attempts"]) for r in roster], [("s1", 2)])
        self.members.pop("c1")
        self.assertEqual(self.client.get(f"/tasks/{across}/roster").status_code, 404)
        self.assertFalse(self.client.get("/tasks?view=workbench").json()["items"])

    def test_workbench_isolates_teachers_and_schools_even_with_same_visible_class(self):
        self.publish()
        self.delegate(context("t2"))
        with patch.object(api.identity, "classes", return_value=[{"class_id": "c1", "name": "c1"}]), \
             patch.object(api.identity, "roster", return_value={"c1": ["s1", "s2"]}):
            self.assertEqual(self.client.get("/tasks?view=workbench").json()["summary"]["task_count"], 0)
            self.delegate(context("admin", "admin"))
            self.assertEqual(self.client.get("/tasks?view=workbench").json()["summary"]["task_count"], 1)
            self.delegate(context("admin", "admin", "other-school"))
            self.assertEqual(self.client.get("/tasks?view=workbench").json()["summary"]["task_count"], 0)

    def test_racing_same_request_and_last_slot(self):
        tid = self.publish()
        self.delegate(context("s1", "student"))
        with ThreadPoolExecutor(8) as pool:
            first = list(pool.map(lambda _: self.launch(tid), range(8)))
            self.assertEqual({r.status_code for r in first}, {200})
            self.assertEqual(len({r.json()["attempt_id"] for r in first}), 1)
            final = list(pool.map(lambda n: self.launch(tid, f"key-{n}"), range(8)))
        self.assertEqual(sorted(r.status_code for r in final), [200] + [409] * 7)
        winner = next(r.json() for r in final if r.status_code == 200)
        self.assertNotEqual(first[0].json()["interview_id"], winner["interview_id"])
        item = self.client.get("/tasks").json()["items"][0]
        self.assertEqual(item["used_attempts"], 2)
        self.assertEqual(item["latest_attempt"]["attempt_id"], winner["attempt_id"])

    def test_deadline_idempotent_recovery_and_late_completion(self):
        tid = self.publish()
        self.delegate(context("s1", "student"))
        attempt = self.launch(tid).json()
        cutoff = int(datetime.fromisoformat(self.body["deadline"]).timestamp() * 1000000)
        with patch.object(api, "now_us", return_value=cutoff):
            self.assertEqual(self.launch(tid).json(), attempt)
            self.assertEqual(self.launch(tid, "new").status_code, 409)
            self.delegate(context("engine", "system", caller="interview"))
            self.assertEqual(self.finish(attempt).json()["status"], "completed")

    def test_completion_ledger_and_authority(self):
        tid = self.publish()
        self.delegate(context("s1", "student"))
        a, b = self.launch(tid).json(), self.launch(tid, "second").json()
        self.assertEqual(self.finish(a).status_code, 403)
        self.delegate(context("engine", "system", caller="wrong"))
        self.assertEqual(self.finish(a).status_code, 403)
        self.delegate(context("engine", "system", caller="interview"))
        self.assertEqual(self.finish({**a, "interview_id": b["interview_id"]}).status_code, 404)
        with ThreadPoolExecutor(8) as pool:
            responses = list(pool.map(lambda _: self.finish(a), range(8)))
        self.assertEqual({r.status_code for r in responses}, {200})
        self.assertEqual(len({r.json()["completed_at"] for r in responses}), 1)
        self.assertEqual(self.finish(b).status_code, 409)
        self.assertEqual(self.client.get("/attempts/" + b["attempt_id"]).json()["status"], "started")
        self.delegate(context("t1"))
        record = self.client.get("/interviews/" + a["interview_id"] + "/attempt").json()
        self.assertEqual((record["teacher_id"], record["student_id"], record["school_id"]), ("t1", "s1", "north"))
        self.delegate(context("t2"))
        self.assertEqual(self.client.get("/attempts/" + a["attempt_id"]).status_code, 404)
        self.delegate(context("any", "system", "south"))
        self.assertEqual(self.client.get("/attempts/" + a["attempt_id"]).status_code, 404)
        self.delegate(context("t1"))
        self.members["c1"] = ["s2"]
        self.assertEqual(self.client.get("/attempts/" + a["attempt_id"]).status_code, 404)

    def test_repractice_frozen_original_and_recipient(self):
        tid = self.publish()
        self.delegate(context("s1", "student"))
        attempt = self.launch(tid).json()
        self.delegate(context("engine", "system", caller="interview"))
        self.finish(attempt)
        body = {"source_attempt_id": attempt["attempt_id"], **self.body["questions"][0],
                "request_id": "retry-practice", "max_attempts": 1, "deadline": self.body["deadline"]}
        self.delegate(context())
        self.assertEqual(self.client.post("/tasks/repractice", json=body).status_code, 403)
        self.delegate(context(caller="analytics"))
        self.assertEqual(self.client.post("/tasks/repractice", json={**body, "prompt": "replaced"}).status_code, 409)
        result = self.client.post("/tasks/repractice", json=body).json()
        self.assertEqual(result["student_count"], 1)
        self.assertEqual(result["questions"], self.body["questions"])
        self.assertEqual(self.client.post("/tasks/repractice", json=body).json(), result)
        self.delegate(context("s2", "student"))
        self.assertEqual(self.launch(result["task_id"]).status_code, 404)
        self.members["c1"] = ["s2"]
        self.delegate(context(caller="analytics"))
        self.assertEqual(self.client.post("/tasks/repractice", json={**body, "request_id": "new"}).status_code, 404)


if __name__ == "__main__":
    unittest.main()
