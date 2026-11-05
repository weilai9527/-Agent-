"""验证原生学生/教师网关投递的回答能由独立评分进程计量和发布。

从仓库根目录运行 python -m services.usage.smoke_worker_usage。
复用临时学校数据、随机端口与签名密钥；子进程仅能连接本机服务。
"""
import sqlite3
import tempfile
import time
from contextlib import ExitStack, closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from unittest.mock import patch
from uuid import uuid4

import httpx
import jwt

from scripts import smoke_microservices as smoke
from smoke_school_fixture import ChatFixture

SCHOOL = smoke.SCHOOL
CONTROL_MODEL = "worker-usage-fixture"


def browser(dep, stack, name):
    url = dep.urls[name]
    return stack.enter_context(httpx.Client(base_url=url, headers={"Origin": url}, timeout=20, trust_env=False))


def submit_answer(dep, stack, manager):
    """由教师向本校班级布置练习，学生用原生会话提交并重放同一条回答。"""
    teacher = browser(dep, stack, "admin-gateway")
    student = browser(dep, stack, "student-gateway")
    initial = "Semester-Student-111!"
    added = smoke.call(manager, "POST", "/api/admin/identity/students/import", {"students": [
        {"name": "Usage smoke student", "student_no": "SMK100", "temporary_password": initial}]})
    sid = added["students"][0]["actor_id"]
    smoke.call(manager, "POST", "/api/admin/identity/v1/classes/cls/roster/import", {"student_ids": [sid]})
    smoke.call(student, "POST", "/api/auth/login", {"student_no": "SMK100", "password": initial})
    smoke.call(student, "POST", "/api/auth/change-initial-password", {
        "password": smoke.PASSWORD, "confirm_password": smoke.PASSWORD})
    smoke.call(teacher, "POST", "/api/admin/auth/login", {
        "email": "owner@example.test", "password": smoke.TEACHER_PASSWORD})
    task = smoke.call(teacher, "POST", "/api/admin/training/tasks", {
        "class_ids": ["cls"], "title": "Usage smoke", "job_role": "Engineer", "max_attempts": 1,
        "questions": [{"question_id": "question-1", "prompt": "Explain a row lock."}],
        "deadline": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()})["task_id"]
    attempt = smoke.call(student, "POST", f"/api/training/tasks/{task}/attempts", {"request_id": "first"})
    iid = smoke.call(student, "POST", "/api/interviews/training-attempts/" + attempt["attempt_id"], {})["interview_id"]
    path = "/api/interviews/" + iid
    question = smoke.call(student, "POST", path + "/current-question", {})["question"]
    answer = {"question_id": question["id"], "submission_id": "accepted-answer", "content": smoke.ANSWER}
    assert smoke.call(student, "POST", path + "/turns", answer)["action"] == "finish_interview"
    assert smoke.call(student, "POST", path + "/turns", answer)["duplicate"] is True
    smoke.call(student, "POST", path + "/finish", {})
    return student, path, sid, iid


def usage(manager, limit=None):
    method = "GET" if limit is None else "PUT"
    body = None if limit is None else {"text": limit, "media": 0}
    return smoke.call(manager, method, "/api/admin/usage/quota", body)["text"]


def query(db, sql, params=()):
    with closing(sqlite3.connect("file:" + str(db) + "?mode=ro", uri=True)) as conn:
        return conn.execute(sql, params).fetchall()


def configure_model(dep):
    """平台管理身份将合成模型写入控制面；账本验收须使用此模型，而非环境默认值。"""
    now = int(time.time())
    token = jwt.encode({"iss": "admin-gateway", "aud": "providers", "sub": "fixture-operator",
                        "actor_type": "admin", "school_id": "platform", "scopes": ["providers.configure"],
                        "iat": now, "exp": now + 30, "jti": uuid4().hex},
                       dep.keys["admin-gateway"][0], algorithm="EdDSA",
                       headers={"kid": "smoke", "typ": "service+jwt"})
    response = dep.checker.patch(dep.urls["providers"] + "/settings",
                                 headers={"Authorization": "Bearer " + token},
                                 json={"reportCustomModel": CONTROL_MODEL,
                                       "reportCustomBaseUrl": dep.env["AI_BASE_URL"],
                                       "evaluationProviderOrder": "custom", "reportProviderOrder": "custom"})
    response.raise_for_status()
    assert response.json()["reportCustomModel"] == CONTROL_MODEL


def run_once(dep, kind):
    # 与常驻评分进程使用同一 CLI、服务身份、配置来源及独立评估库；每次重新启动并等待任务结束。
    name = "score-worker"
    dep.start(name, "assessment", ["-m", "services.interview.worker", "--once", "--kinds", kind])
    if dep.processes[name].wait(timeout=120):
        raise AssertionError((dep.temp / (name + ".log")).read_text()[-1800:])


def exercise(dep, stack, dispatches):
    active = ("identity", "profile", "training", "interview", "assessment", "providers", "usage", "operations",
              "student-gateway", "admin-gateway")
    dep.env.update(USAGE_SERVICE_URL=dep.urls["usage"], USAGE_DB_ENGINE="sqlite",
                   USAGE_SQLITE_PATH=str(dep.temp / "usage.sqlite"),
                   PROFILE_SERVICE_URL=dep.urls["profile"], PROFILE_DB_ENGINE="sqlite",
                   PROFILE_SQLITE_PATH=str(dep.temp / "profile.sqlite"),
                   PROVIDERS_SERVICE_URL=dep.urls["providers"])
    # 空校从身份服务正式开户；子进程的源码包不包含旧应用，整个流程也不创建旧库。
    dep.command(["-m", "services.identity.bootstrap", "--school", SCHOOL, "--email", smoke.MASTER,
                 "--name", "验收校管", "--password-stdin"], SERVICE_ID="identity",
                stdin_text=dep.master_env["ADMIN_MASTER_PASSWORD"] + "\n")
    for name in active:
        # 同步强制重评也需能执行模型，以验证额度检查真正发生在发请求之前。
        with patch.dict(dep.env, {"AI_API_KEY": "synthetic-model-token"} if name == "assessment" else {}):
            dep.start_app(name)
    for name in active:
        smoke.until(name, lambda: dep.ready(name), 120)
    dep.seed_teaching_accounts()
    configure_model(dep)
    dep.start("projection-worker", "interview", ["-m", "services.interview.worker", "--kinds", "project,train_complete"])
    manager = browser(dep, stack, "admin-gateway")
    smoke.call(manager, "POST", "/api/admin/auth/login", {
        "email": smoke.MASTER, "password": dep.master_env["ADMIN_MASTER_PASSWORD"]})
    usage(manager, 0)
    student, path, sid, iid = submit_answer(dep, stack, manager)
    db = dep.temp / "assessment.sqlite"
    jobs = "SELECT attempts,state FROM interview_jobs WHERE kind=? AND interview_id=?"
    smoke.until("answer projected and scoring job ready", lambda: query(db, jobs, ("score", iid)))
    source = Path(dep.env["INTERVIEW_SQLITE_PATH"])
    legacy = Path(dep.env["IDENTITY_SOURCE_SQLITE_PATH"])
    assert legacy == dep.temp / "legacy.sqlite" and source not in {legacy, db}
    assert not legacy.exists(), "原生学校开通或答题路径意外创建了历史库"
    assert query(source, "SELECT COUNT(*) FROM interview_messages WHERE interview_id=? AND content=?",
                 (iid, smoke.ANSWER)) == [(1,)]
    run_once(dep, "score")
    print("zero-budget score attempt", query(db, jobs, ("score", iid)), "dispatches", list(dispatches), flush=True)
    assert query(db, jobs, ("score", iid)) == [(1, "pending")]
    assert not dispatches and usage(manager)["used"] == 0, "A provider call escaped admission at zero budget"

    usage(manager, 1)
    def run_until_used(kind, units):
        def check():
            run_once(dep, kind)
            return usage(manager)["used"] == units
        smoke.until(kind + " confirmed usage", check, 100)
    run_until_used("score", 1)
    assert dispatches == [200] and query(db, jobs, ("score", iid))[0][1] == "done"
    smoke.until("report queued", lambda: query(db, jobs, ("report", iid)))
    # 队列里可能有旧版证据任务。继续领取，直到当前版本的报告实际因额度不足而等待。
    def report_attempted():
        run_once(dep, "report")
        return query(db, """SELECT 1 FROM interview_jobs WHERE interview_id=? AND kind='report'
                            AND attempts>0 AND state='pending'""", (iid,))
    smoke.until("report waiting for quota", report_attempted, 100)
    current = usage(manager)
    assert dispatches == [200] and current == {"limit": 1, "used": 1, "reserved": 0, "available": 0}
    print("PASS accepted answer, quota-denied score, resumed score, quota-denied report; model requests=1", flush=True)

    usage(manager, 2)
    run_until_used("report", 2)
    report = smoke.call(student, "GET", path + "/report")["report"]
    assert report["generation_status"] == "succeeded" and report["scored_answer_count"] == 1
    assert report["model"] == CONTROL_MODEL
    # 重启进程、重放证据后再次检查实际请求和账本，已经发布的结果不能重复计量。
    run_once(dep, "score")
    run_once(dep, "report")
    assert dispatches == [200, 200] and usage(manager) == {"limit": 2, "used": 2, "reserved": 0, "available": 0}
    charges = query(dep.temp / "usage.sqlite", """SELECT caller, school_id, actor_type, actor_id, actual_units
                    FROM usage_reservations WHERE resource='text'""")
    assert charges == [("assessment", SCHOOL, "student", sid, 1)] * 2, charges
    scores = smoke.call(student, "GET", path + "/evaluations")["evaluations"]
    assert len(scores) == 1 and scores[0]["score"] is not None
    previous = scores[0]
    assert previous["model"] == CONTROL_MODEL
    regrade = smoke.call(student, "POST", path + "/evaluations",
                         {"message_id": previous["message_id"], "force": True}, ok=(202,))
    assert regrade["assessment_pending"] is True and regrade["job_id"]
    assert regrade["evaluation"]["score"] == previous["score"]
    assert query(db, "SELECT wait_reason FROM worker_text_runs WHERE job_id=?", (regrade["job_id"],)) == [
        ("quota_exhausted",)]
    assert usage(manager)["used"] == 2 and dispatches == [200, 200]
    print("PASS quota-denied force regrade: HTTP 202, job ID, prior score retained", flush=True)
    print("PASS report succeeded; fresh worker replay: model HTTPS requests=2, charged=2, reserved_units=0", flush=True)


def main():
    dispatches = []
    lock = Lock()
    original = ChatFixture.send_response
    def record(handler, code, message=None):
        # 包括拒绝在内的所有模型 POST 都计数，防止把误派发的失败请求漏算为零。
        if handler.command == "POST":
            with lock:
                dispatches.append(code)
        return original(handler, code, message)

    with tempfile.TemporaryDirectory(prefix="worker-usage-") as folder, ExitStack() as stack:
        temp = Path(folder)
        smoke.prepare_sources(temp, include_archive=False)
        assert not (temp / "backend").exists() and not (temp / "admin_backend").exists()
        stack.enter_context(patch.dict(smoke.APPS, {"usage": "services.usage.app:app",
                                                   "profile": "services.profile.app:app"}))
        stack.enter_context(patch.dict(smoke.EDGES["interview"], {"profile": {"student": "profile.snapshot.read"}}))
        stack.enter_context(patch.dict(smoke.EDGES["admin-gateway"], {"usage": {"admin": "usage.configure usage.read"}}))
        stack.enter_context(patch.dict(smoke.EDGES["student-gateway"]["assessment"], {
            "student": "assessment.read assessment.evaluate"}))
        stack.enter_context(patch.dict(smoke.EDGES["assessment"], {"usage": {"student": "usage.reserve usage.dispatch usage.settle"}}))
        stack.enter_context(patch.object(ChatFixture, "send_response", record))
        dep = smoke.Deployment(temp, stack, "isolated")
        exercise(dep, stack, dispatches)


if __name__ == "__main__":
    main()
