"""使用独立的测试进程和 MySQL 账号，验证源服务发布事件与目标服务接收投影的过程。"""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
from threading import Event
from unittest.mock import patch
from uuid import uuid4

from fastapi import BackgroundTasks, HTTPException


def publish_source(wire):
    from services.interview import runtime as main
    from services.interview.training_rounds import materialize
    school = os.environ["LEGACY_SCHOOL_ID"]
    student, attempt, interview, question = [str(uuid4()) for _ in range(4)]
    student = "s" + student[1:]  # 固定一个小写首字母，使后续大写标识符的越权测试不会误用同一个值。
    record = dict(attempt_id=attempt, interview_id=interview, school_id=school, student_id=student,
                  job_role="Engineer", status="started", questions=[dict(question_id=question, prompt="Explain locks")])
    materialize(attempt, record, student, school)
    from services.school_records import _detail, _records
    assert _detail("interview", school, interview, student)["kind"] == "training"
    assert [r["id"] for r in _records("interview", school, {student}, None, None, None, 25)] == [interview]
    assert not _records("interview", school, {student.upper()}, None, None, None, 25)
    active = main.managed_progress(interview)
    submission = dict(question_id=active["question_id"], submission_id="one", content="Used a row lock")
    assert not main.submit_turn(interview, submission, user={"id": student})["duplicate"]
    assert main.submit_turn(interview, submission, user={"id": student})["duplicate"]
    main.finish_interview(interview, BackgroundTasks(), {"id": student})
    assert not main.one("SHOW TABLES LIKE 'interview_reports'")
    assert not main.one("SHOW TABLES LIKE 'interview_evaluations'")
    # 模拟旧任务表未显式指定排序规则的部署，验证启动迁移能原地修复旧数据，使任务可以与事件表关联查询。
    main.db.execute("ALTER TABLE interview_jobs CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci").close()
    main.interview_jobs.migrate()
    main.interview_jobs.migrate()
    rows = main.all_rows("""SELECT e.body FROM interview_delivery_events e
                            JOIN interview_jobs j ON e.job_id=j.id
                            WHERE j.interview_id=? AND j.kind='project' ORDER BY CAST(j.version AS UNSIGNED)""",
                         (interview,))
    assert len(rows) == 3
    wire.write_text(json.dumps([json.loads(row["body"]) for row in rows]))


def receive_target(wire):
    import pymysql
    from services.assessment import runtime as main
    from services.assessment import inbox, versions
    from services.interview.worker import run_once
    # 即使源库和目标库位于同一 MySQL 实例，评估账号也不能直接读取面试库。
    try:
        main.one("SELECT id FROM verify_interview.interview_sessions LIMIT 1")
    except pymysql.MySQLError as exc:
        assert exc.args[0] in (1044, 1142), exc.args[0]
    else:
        raise AssertionError("Assessment account can read the source schema")
    assert not main.one("SHOW TABLES LIKE 'users'")
    assert main.one("SHOW STATUS LIKE 'Ssl_cipher'")["Value"]
    payloads = json.loads(wire.read_text())
    actor = dict(caller="interview", actor_id="interview", actor_type="system", school_id=os.environ["LEGACY_SCHOOL_ID"])
    try:
        inbox.accept(main, payloads[-1], actor)
    except HTTPException as exc:
        assert exc.status_code == 409
    else:
        raise AssertionError("Late completion skipped the previous answers")

    def deliver(body):
        try:
            receipt = inbox.accept(main, body, actor)
            assert receipt["sequence_no"] == body["sequence_no"]
        finally:
            main.db.connect().close()

    # 多个 InnoDB 事务并发投递同一事件流中的同一个序号，验证接收端去重。
    with ThreadPoolExecutor(max_workers=6) as pool:
        for body in payloads:
            list(pool.map(deliver, [body] * 6))
    student, interview, report_id = (body[key] for key in ("student_id", "interview_id", "report_id"))
    assert main.one("SELECT COUNT(*) AS n FROM interview_jobs WHERE kind='score'")["n"] == 1
    scored = dict(score=80, strengths="Clear", issues="Limited scope", suggestions="Add metrics",
                  dimension_scores={"technical_depth":80}, dimension_evidence={"technical_depth":"row lock"},
                  provider="fixture", model="fixture", prompt_version=main.EVALUATION_PROMPT_VERSION, fallback=False)

    def model_report(**kw):
        return {**kw["fallback_report"], "provider":"fixture", "model":"fixture",
                "prompt_version":main.REPORT_PROMPT_VERSION, "fallback":False}

    with patch.object(main, "generate_ai_evaluation", return_value=scored), patch.object(main, "generate_ai_report", model_report):
        assert run_once(main.interview_jobs, main.prepare_interview_job, kinds=("score",))
        while run_once(main.interview_jobs, main.prepare_interview_job, kinds=("report",)):
            pass
    report = main.get_interview_report(interview, {"id":student})["report"]
    assert (report["id"],report["generation_status"],report["scored_answer_count"]) == (report_id,"succeeded",1)
    from services.school_records import _detail, _records
    assert _detail("assessment", actor["school_id"], report_id, student)["total_score"] == report["total_score"]
    assert [r["id"] for r in _records("assessment", actor["school_id"], {student}, "training", None, None, 25)] == [report_id]
    assert not _records("assessment", actor["school_id"], {student.upper()}, None, None, None, 25)
    owner = dict(interview_id=interview, user_id=student)
    with versions.report_transaction(report_id, owner, 1) as (report, head):
        versions.change_score(report, head, 86, "A", "pass", "teacher", "Verified evidence", head["evidence_version"])
    with versions.report_transaction(report_id, owner, 2) as (report, head):
        versions.review(report, head, "approved", "teacher", "Approved version two")
    inbox.accept(main, payloads[-1], actor)
    history = versions.history(report_id)
    assert [v["version"] for v in history["versions"]] == [2,1]
    assert (history["reviews"][0]["version"],history["reviews"][0]["note"]) == (2,"Approved version two")
    exercise_mysql_permit(main, report_id, owner)
    exercise_emergency_export(report_id)


def exercise_emergency_export(report_id):
    """用真实 MySQL 恢复库导出最小状态快照，并拒绝其他学校的同一请求。"""
    import sqlite3
    from contextlib import closing
    from tempfile import TemporaryDirectory
    from types import SimpleNamespace
    from deploy.emergency_prepare import snapshot

    settings = {"EMERGENCY_SOURCE_"+key.removeprefix("ASSESSMENT_"): value
                for key,value in os.environ.items() if key.startswith("ASSESSMENT_MYSQL_")}
    settings["EMERGENCY_SOURCE_DB_ENGINE"] = "mysql"
    with TemporaryDirectory() as folder, patch.dict(os.environ, settings):
        out = Path(folder)/"snapshot.sqlite"
        school = os.environ["LEGACY_SCHOOL_ID"]
        args = SimpleNamespace(sqlite=None, legacy_sha256=None, as_of="2026-01-01T00:00:00Z",
                               school=school+"-foreign", output=out)
        try:
            snapshot(args)
        except ValueError as exc:
            assert "学校不一致" in str(exc)
        else:
            raise AssertionError("其他学校的应急快照请求被接受")
        assert not out.exists()
        args.school = school
        snapshot(args)
        with closing(sqlite3.connect(out.as_uri()+"?mode=ro", uri=True)) as conn:
            assert conn.execute("SELECT school FROM snapshot_meta").fetchone() == (school,)
            assert conn.execute("SELECT generation_status FROM report_status WHERE id=?", (report_id,)).fetchone() == ("succeeded",)
            assert [r[1] for r in conn.execute("PRAGMA table_info(report_status)")] == ["id","generation_status","review_status"]



def exercise_mysql_permit(main, report_id, owner):
    from services.assessment import app as api
    from shared.credential_reference import application_id

    school = os.environ["LEGACY_SCHOOL_ID"]
    teacher = dict(caller="credentials", actor_id="teacher", actor_type="teacher", school_id=school)
    # 对象授权另有 HTTP 测试覆盖。这里固定合成记录的所有者，专门验证数据库并发操作的执行顺序。
    with patch.object(api, "_verified_owner", return_value=owner):
        evidence = api.credential_evidence(report_id, teacher)
        n = evidence["version"]
        body = api.IssueIntent(application_id=application_id(school, owner["user_id"], report_id, n),
                               generation=1, serial=uuid4().hex, version=n, digest=evidence["digest"],
                               proof_digest="ab" * 32)
        inserted, writer_started, release = Event(), Event(), Event()
        execute = main.db.execute

        def barrier(sql, params=()):
            if inserted.is_set() and "FROM interview_sessions" in sql and "FOR UPDATE" in sql:
                writer_started.set()
            cursor = execute(sql, params)
            if "INSERT INTO assessment_issuance_permits" in sql:
                inserted.set()
                assert release.wait(timeout=10)
            return cursor

        def authorize():
            try:
                return api.authorize_issuance(report_id, body, teacher)
            finally:
                main.db.connect().close()

        def regrade():
            try:
                with api.versions.report_transaction(report_id, owner, n) as (row, head):
                    return api.versions.change_score(row, head, 88, "A", "pass", "teacher",
                                                     "After authorization", head["evidence_version"])
            finally:
                main.db.connect().close()

        with patch.object(main.db, "execute", barrier), ThreadPoolExecutor(max_workers=2) as pool:
            permit = pool.submit(authorize)
            try:
                assert inserted.wait(timeout=10)
                writer = pool.submit(regrade)
                assert writer_started.wait(timeout=10) and not writer.done()
            finally:
                release.set()
            receipt = permit.result(timeout=10)
            assert writer.result(timeout=10)["version"] == n + 1

        assert api.authorize_issuance(report_id, body, teacher) == receipt
        for changes in ({"serial": uuid4().hex}, {"proof_digest": "cd"*32}, {"generation": 2}):
            try:
                api.authorize_issuance(report_id, body.model_copy(update=changes), teacher)
            except HTTPException as error:
                assert error.status_code == 409
            else:
                raise AssertionError("Rebound or stale permit accepted")
        row = main.one("SELECT COUNT(*) AS n FROM assessment_issuance_permits WHERE report_id=?", (report_id,))
        assert row["n"] == 1


def exercise_projection(domain):
    wire = Path(os.environ["TEST_PROJECTION_WIRE"])
    (publish_source if domain == "interview" else receive_target)(wire)
