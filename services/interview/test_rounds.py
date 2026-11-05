"""离线验证服务间协作，每个用例使用独立数据库和全新的模块导入状态。"""
import os
from pathlib import Path
import subprocess
import sys


def test_interview_service_and_durable_scoring(tmp_path):
    env = {**os.environ, "APP_ENV":"test", "LEGACY_SCHOOL_ID":"school", "ASSESSMENT_STORAGE_MODE":"isolated",
           "INTERVIEW_DB_ENGINE":"sqlite", "INTERVIEW_SQLITE_PATH":str(tmp_path/"interview.sqlite"),
           "USAGE_SERVICE_URL":"http://127.0.0.1:1", "ASSESSMENT_DB_ENGINE":"sqlite", "ASSESSMENT_SQLITE_PATH":str(tmp_path/"assessment.sqlite"),
           "WIRE":str(tmp_path/"events.json")}
    for owner in ("interview", "assessment"):
        subprocess.run([sys.executable, "-m", "services.interview.test_rounds", owner],
                       cwd=Path(__file__).resolve().parents[2], env={**env,"SERVICE_ID":owner}, check=True, timeout=65)


def scenario():
    import json
    import socket
    from unittest.mock import patch
    from uuid import uuid4

    # 阻止开发目录的 .env 启用真实供应商，任何联网尝试都应使测试失败。
    from backend.src import env
    env.load_env_file = env.reload_runtime_ai_env = lambda: None

    def offline(*args, **kwargs):
        raise AssertionError("test attempted network I/O")

    socket.socket.connect = offline

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from fastapi.testclient import TestClient
    from services.interview import runtime as main
    from services.interview import app as service
    from services.interview.worker import run_once
    from shared.service_security import service_headers

    client = TestClient(service.app)
    uid, other, attempt_id, interview_id = (str(uuid4()) for _ in range(4))
    from services.interview import student_reference
    async def identity(service, method, url, *, actor, scope):
        assert url == "/internal/students/me"
        return dict(actor_id=actor["actor_id"],school_id=actor["school_id"],status="normal",
                    must_change_password=False,name="Synthetic")
    student_reference.request_json = identity
    scopes = ["interview.training.start", "interview.question.current", "interview.turn.submit", "interview.finish",
              "interview.read", "interview.create", "interview.message.create"]
    key = Ed25519PrivateKey.generate()
    pub = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    os.environ["SERVICE_KEY_ID"] = "test"
    os.environ["SERVICE_SIGNING_KEY"] = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    os.environ["SERVICE_TRUST_POLICY"] = json.dumps({"gateway": {"keys": {"test": pub.decode()},
        "schools": ["school", "wrong-school"], "grants": {"interview": {"student": scopes}}}})

    def headers(scope, user=uid, school="school"):
        with patch.dict(os.environ, SERVICE_ID="gateway"):
            return service_headers("interview", actor_id=user, school_id=school, actor_type="student", scopes=[scope])

    from shared.interviewer_policy import load_policy, save_policy
    policy = load_policy(main.db)
    policy["studentCanChoose"] = False
    save_policy(main.db, policy)
    policy_url = "/api/interviewer-policy"
    assert client.get(policy_url).status_code == 401
    assert client.get(policy_url, headers=headers("interview.create")).status_code == 403
    assert client.get(policy_url, headers=headers("interview.read", school="wrong-school")).status_code == 403
    assert client.get(policy_url, headers=headers("interview.read")).json() == {"policy": policy}

    prefix = "/api/interviews/"
    bind = prefix + "training-attempts/" + attempt_id
    path = prefix + interview_id
    questions = [{"question_id": "q/01", "prompt": "请给出第一个例子。"}, {"question_id": "Q:02", "prompt": "请解释第二个例子。"}]

    async def training(peer, method, url, *, actor, scope):
        assert (peer, method, url, scope) == ("training", "GET", "/attempts/" + attempt_id, "training.verify")
        return {"attempt_id": attempt_id, "interview_id": interview_id, "student_id": uid, "school_id": "school",
                "status": "started", "job_role": "工程师", "questions": questions}
    service.request_json = training
    assert client.post(bind, json={"actor_id": uid}).status_code == 401
    assert client.post(bind, headers=headers("interview.training.start", school="wrong-school")).status_code == 403
    assert client.post(bind, headers=headers("interview.training.start", user=other), json={"student_id": uid}).status_code == 403
    assert client.post(bind, headers=headers("interview.read")).status_code == 403
    def post(url, scope, body=None):
        reply = client.post(url, headers=headers(scope), json=body)
        assert reply.is_success, reply.text
        return reply.json()
    for _ in range(2):
        assert post(bind, "interview.training.start", {"questions": [{"prompt": "spoof"}]})["interview_id"] == interview_id
    assert client.post(path + "/current-question", headers=headers("interview.question.current", user=other)).status_code == 404
    assert client.post(path + "/finish", headers=headers("interview.finish")).status_code == 409
    assert main.one("SELECT COUNT(*) AS n FROM interview_jobs WHERE kind='score'")["n"] == 0
    for i, item in enumerate(questions):
        question = post(path + "/current-question", "interview.question.current")["question"]
        assert (question["content"], question["frozen_question_id"]) == (item["prompt"], item["question_id"])
        content = "原始答案" + str(i)
        body = {"submission_id": "submit-" + str(i), "question_id": question["id"], "content": content}
        if i == 0:
            # 写入中断时，答案、轮次推进和入队任务应在同一事务中回滚。
            with patch.object(main.interview_jobs, "enqueue", side_effect=RuntimeError("queue unavailable")):
                try:
                    post(path + "/turns", "interview.turn.submit", body)
                except RuntimeError as exc:
                    assert "queue unavailable" in str(exc)
                else:
                    raise AssertionError("turn did not fail on enqueue error")
            assert main.one("SELECT COUNT(*) AS n FROM interview_turns")["n"] == 0
        turn = post(path + "/turns", "interview.turn.submit", body)
        duplicate = post(path + "/turns", "interview.turn.submit", body)
        assert not turn["duplicate"] and duplicate["answer"]["id"] == turn["answer"]["id"]
        join = main.one("""SELECT q.frozen_question_id FROM interview_training_questions q JOIN interview_messages m
                           ON m.reply_to_message_id=q.message_id WHERE m.id=?""", (turn["answer"]["id"],))
        assert join["frozen_question_id"] == item["question_id"]
    legacy_id = post("/api/interviews", "interview.create", {"target_role": "工程师"})["interview"]["id"]
    msg = {"sender_type": "candidate", "message_type": "transcript", "source": "aliyun_rtc",
           "source_ref": "rtc-1", "content": "回答"}
    assert not post(prefix + legacy_id + "/messages", "interview.message.create", msg)["duplicate"]
    assert post(prefix + legacy_id + "/messages", "interview.message.create", msg)["duplicate"]
    assert main.one("SELECT count(*) AS n FROM interview_jobs WHERE interview_id=? AND kind='project'", (legacy_id,))["n"] == 2

    assert post(path + "/finish", "interview.finish")["interview"]["status"] == "completed"
    post(path + "/finish", "interview.finish")
    assert main.one("SELECT COUNT(*) AS n FROM interview_jobs WHERE kind='train_complete' AND interview_id=?",
                    (interview_id,))["n"] == 1

    rows = main.all_rows("""SELECT e.body FROM interview_delivery_events e JOIN interview_jobs j ON j.id=e.job_id
        WHERE j.kind='project' AND j.interview_id=? ORDER BY CAST(j.version AS INTEGER)""", (interview_id,))
    Path(os.environ["WIRE"]).write_text(json.dumps([uid, interview_id, questions, [json.loads(r["body"]) for r in rows]]))


def score_scenario():
    import json
    from services.assessment import runtime as main, inbox
    from services.interview.worker import run_once
    uid, interview_id, questions, events = json.loads(Path(os.environ["WIRE"]).read_text())
    actor = dict(school_id="school",actor_id="interview",actor_type="system",caller="interview")
    for event in events:
        inbox.accept(main,event,actor)
    jobs = main.all_rows("SELECT * FROM interview_jobs WHERE kind='score'")
    assert len(jobs) == 2 and not main.all_rows("SELECT id FROM interview_evaluations")

    def evaluate(**kwargs):
        assert not main.db.connect().in_transaction
        assert kwargs["question"] in [q["prompt"] for q in questions]
        return {"score": 60, "strengths": "", "issues": "", "suggestions": "", "dimension_scores": {"technical_depth": 60},
                "dimension_evidence": {"technical_depth": kwargs["answer"]}, "provider": "fake", "model": "fake",
                "prompt_version": main.EVALUATION_PROMPT_VERSION, "fallback": False}
    main.generate_ai_evaluation = evaluate
    # 浏览器无需调用 POST /evaluations；这些任务由独立工作进程消费。
    for job in jobs:
        assert run_once(main.interview_jobs, main.prepare_interview_job, job_id=job["id"])
        assert main.interview_jobs.get(job["id"])["state"] == "done"
    assert len(main.all_rows("SELECT id FROM interview_evaluations WHERE score=60")) == 2

    from fastapi import HTTPException, Response
    from services.assessment import versions
    main.generate_ai_report = lambda **kw: {**kw["fallback_report"], "provider": "test", "model": "test",
                                            "prompt_version": "test", "fallback": False}
    report = main.create_report(interview_id, Response(), user={"id": uid})["report"]
    first = jobs[0]
    with main.db:
        main.interview_jobs.request_retry(first["id"], include_done=True)
    claim = main.interview_jobs.claim(120, job_id=first["id"])
    main.generate_ai_evaluation = lambda **kw: {**evaluate(**kw), "score": 95, "dimension_scores": {"technical_depth": 95}}
    publish = main.prepare_score_job(claim)
    owner = {"user_id": uid, "interview_id": interview_id}
    with versions.report_transaction(report["id"], owner) as (locked, version):
        versions.review(locked, version, "approved", "teacher", "checked")
    assert main.interview_jobs.finish(claim, publish)
    assert main.find_evaluation_by_message_id(interview_id, first["subject_id"])["score"] == 60

    def expect_protected():
        try:
            main.create_evaluation(interview_id, Response(),
                                   {"message_id": first["subject_id"], "force": True}, user={"id": uid})
        except HTTPException as exc:
            assert exc.status_code == 403
        else:
            raise AssertionError("student could overwrite teacher's decision")

    expect_protected()
    with versions.report_transaction(report["id"], owner) as (locked, version):
        versions.change_score(locked, version, 72, "C", "borderline", "teacher", "adjusted",
                              main.current_report_evidence_version(interview_id, uid))
    expect_protected()


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    (score_scenario if sys.argv[-1] == "assessment" else scenario)()
