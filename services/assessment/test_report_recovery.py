"""运行方式为 python -m unittest services.assessment.test_report_recovery。"""
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


PRELUDE = """
import sys, socket
def offline(event, args):
    if event == "open" and isinstance(args[0], str) and args[0].split("/")[-1] == ".env":
        raise AssertionError("No real environment files in tests")
    if event in {"socket.connect", "socket.sendto", "socket.getaddrinfo"}:
        if event != "socket.connect" or args[0].family != socket.AF_UNIX:
            raise AssertionError("Network is disabled")
sys.addaudithook(offline)
from backend.src import env
env.load_env_file = env.reload_runtime_ai_env = lambda: None
from shared.offline_fixture import enable_offline_fixture
enable_offline_fixture()
from backend.offline import main
from fastapi import BackgroundTasks, Response
"""

MOCK_AI = """
def score(*, answer, **kwargs):
    return dict(score=71, dimension_scores={"technical_accuracy":71},
                dimension_evidence={"technical_accuracy":answer}, strengths="s", issues="", suggestions="",
                provider="custom", model="offline-provider", prompt_version=main.EVALUATION_PROMPT_VERSION,
                fallback=False)
def narrative(fallback_report, **kwargs):
    return dict(fallback_report, provider="custom", model="offline-provider",
                prompt_version=main.REPORT_PROMPT_VERSION, fallback=False)
main.generate_ai_evaluation = score
main.generate_ai_report = narrative
"""


class ReportRecovery(unittest.TestCase):
    def test_finish_exit_and_stale_equal_coverage(self):
        with TemporaryDirectory() as dest:
            params = dict(os.environ, SQLITE_PATH=str(Path(dest) / "app.sqlite"), DB_ENGINE="sqlite", APP_ENV="test")
            # 排除其他服务的数据库配置对本测试的影响。
            params.pop("PROVIDERS_DB_ENGINE", None)

            def process(code):
                subprocess.run([sys.executable, "-c", PRELUDE + code], cwd=Path(__file__).resolve().parents[2],
                               env=params, timeout=60, check=True)

            process("""
import os
from fastapi.testclient import TestClient
client = TestClient(main.app)
client.post("/api/auth/register", json={"email":"recovery@example.com","password":"Password123!"}).raise_for_status()
def session():
    return client.post("/api/interviews", json={"target_role":"QA"}).json()["interview"]
interview = session()
student = {"id":interview["user_id"]}
prefix = "/api/interviews/"+interview["id"]
agent = main.list_agents_by_interview_id(interview["id"])[0]["id"]
client.post(prefix+"/messages",json={"agent_id":agent,"sender_type":"agent","message_type":"question","content":"Explain CAS"}).raise_for_status()
client.post(prefix+"/messages",json={"sender_type":"candidate","message_type":"answer","content":"Compare the version."}).raise_for_status()
# 升级后也要接管旧版服务写入的待生成报告。
old = session()
with main.locked_session(old["id"], student["id"]):
    main.db.execute("UPDATE interview_sessions SET status='completed' WHERE id=?", (old["id"],)).close()
    main.insert_queued_report(old["id"], student)
tasks = BackgroundTasks()
main.finish_interview(interview["id"], tasks, student)
assert main.one("SELECT COUNT(*) AS n FROM interview_jobs")["n"] == 2
os._exit(0)
""")
            process(MOCK_AI + """
main.reconcile_queued_reports()
for _ in range(8):
    main.run_interview_job(main.interview_jobs, main.prepare_interview_job)
assert main.one("SELECT COUNT(*) AS n FROM interview_jobs WHERE state<>'done'")["n"] == 0
assert main.one("SELECT COUNT(*) AS n FROM interview_reports WHERE generation_status='queued'")["n"] == 0
r = main.one("SELECT * FROM interview_reports WHERE answer_count=1")
assert r["total_score"] == 71 and r["scored_answer_count"] == 1
assert main.one("SELECT total_score FROM interview_reports WHERE answer_count=0")["total_score"] == 0
# 模拟报告生成较慢时，相同答题覆盖范围的重新评分先完成。
iid, uid = r["interview_id"], r["user_id"]
def regrade(points):
    with main.locked_session(iid, uid):
        main.db.execute("UPDATE interview_evaluations SET score=?, dimension_scores=? WHERE interview_id=?",
                        (points, main.json.dumps({"technical_accuracy":points}), iid)).close()
        return main.enqueue_report_if_completed(iid, uid)
q = main.interview_jobs
count = "SELECT COUNT(*) AS n FROM assessment_report_versions WHERE report_id=?"
before = main.one(count,(r["id"],))["n"]
first = q.claim(120, job_id=regrade(79))
old_result = main.prepare_report_job(first)
newer = regrade(89)
main.run_interview_job(q, main.prepare_interview_job, job_id=newer)
assert q.finish(first, old_result)
current = main.find_report_by_id(r["id"], uid)
assert current["total_score"] == 89
assert main.one(count,(r["id"],))["n"] == before + 1
# 分数修改后再改回原值会生成新版本，重放同一结果仍沿用当前版本。
restored = regrade(71)
main.run_interview_job(q, main.prepare_interview_job, job_id=restored)
assert main.find_report_by_id(r["id"], uid)["total_score"] == 71
main.create_report(iid, Response(), user={"id":uid})
assert main.one(count,(r["id"],))["n"] == before + 2

# 报告生成服务短暂中断时，先发布一次已有分数。
# 服务恢复后可用相同证据补全一次报告，无需重新评分。
def outage(**kwargs):
    raise main.AiEvaluationError("offline")
main.generate_ai_report = outage
repair_id = regrade(65)
main.run_interview_job(q, main.prepare_interview_job, job_id=repair_id)
assert q.get(repair_id)["state"] == "pending"
main.create_report(iid, Response(), user={"id":uid})
assert main.one(count,(r["id"],))["n"] == before + 3
main.generate_ai_report = narrative
main.create_report(iid, Response(), user={"id":uid})
assert main.find_report_by_id(r["id"], uid)["generation_status"] == "succeeded"
assert q.get(repair_id)["state"] == "done"
assert main.one(count,(r["id"],))["n"] == before + 4
""")


if __name__ == "__main__":
    unittest.main()
