"""源端与接收端各在独立进程中运行，各自只持有本端数据库的连接信息。"""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import textwrap

import pytest


@pytest.fixture
def process(tmp_path):
    root = Path(__file__).resolve().parents[2]
    for component in ("backend", "shared", "services"):
        for source in (root / component).rglob("*.py"):
            dest = tmp_path / source.relative_to(root)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, dest)

    def run(actor, script, *, expected=0, **overrides):
        env = {k: os.environ[k] for k in ("PATH", "PYTHONPATH", "TMPDIR") if k in os.environ}
        env.update(APP_ENV="test", SERVICE_ID=actor, LEGACY_SCHOOL_ID="test-school",
                   ASSESSMENT_STORAGE_MODE="isolated")
        if actor == "assessment":
            env.update(USAGE_SERVICE_URL="http://127.0.0.1:1", ASSESSMENT_DB_ENGINE="sqlite", ASSESSMENT_SQLITE_PATH=str(tmp_path/"owned.sqlite"))
        else:
            env.update(INTERVIEW_DB_ENGINE="sqlite", INTERVIEW_SQLITE_PATH=str(tmp_path/"source.sqlite"),
                       DB_ENGINE="sqlite", SQLITE_PATH=str(tmp_path/"old.sqlite"))
        env.update(overrides)
        proc = subprocess.run([sys.executable, "-c", textwrap.dedent(script)], cwd=tmp_path,
                              capture_output=True, env=env, text=True, timeout=40)
        assert proc.returncode == expected, proc.stderr
        return proc.stdout

    return run


def test_transactional_projection_recovery_with_source_removed(tmp_path, process):
    run = process
    run("interview", """
        from services.interview import runtime as m
        from fastapi import BackgroundTasks
        from services.interview.assessment_events import capture
        from services.interview.training_rounds import materialize
        from pathlib import Path
        import json


        m.db.commit()
        materialize("a", dict(attempt_id="a", interview_id="i", student_id="s", school_id="test-school",
                    job_role="engineer", status="started", questions=[dict(question_id="q",prompt="Explain locks")]),
                    "s", "test-school")
        q=m.managed_progress("i")["question_id"]
        try:
            with m.locked_session("i","s"):
                m.db.execute("UPDATE interview_sessions SET target_role='rollback' WHERE id='i'").close()
                capture(m.interview_jobs, "i")
                raise RuntimeError("simulate failure")
        except RuntimeError:
            pass
        assert m.one("SELECT sequence_no FROM interview_assessment_streams")["sequence_no"] == 1
        assert m.one("SELECT target_role FROM interview_sessions")["target_role"] == "engineer"
        payload=dict(question_id=q,submission_id="n",content="I used a row lock")
        assert m.submit_turn("i", payload, user={"id":"s"})["duplicate"] is False
        assert m.submit_turn("i", payload, user={"id":"s"})["duplicate"] is True
        bg=BackgroundTasks()
        finished=m.finish_interview("i", bg, {"id":"s"})
        assert finished["report"]["generation_status"]=="queued" and not bg.tasks
        m.finish_interview("i", bg, {"id":"s"})
        assert not m.all_rows("SELECT name FROM sqlite_master WHERE name IN ('users','sessions','interview_evaluations','interview_reports')")
        jobs=m.all_rows("SELECT kind,state FROM interview_jobs")
        assert sorted(j["kind"] for j in jobs)==["project","project","project","train_complete"],jobs
        rows=m.all_rows("SELECT e.body FROM interview_delivery_events e JOIN interview_jobs j ON j.id=e.job_id WHERE j.kind='project' ORDER BY j.version")
        Path("wire.json").write_text(json.dumps([json.loads(x["body"]) for x in rows]))
    """)
    # 误连面试库时必须拒绝启动，
    # 不得创建评估收件表或修改原有表结构。
    run("assessment", "from services.assessment import runtime", expected=1,
                  ASSESSMENT_SQLITE_PATH=str(tmp_path/"source.sqlite"))
    (tmp_path/"source.sqlite").rename(tmp_path/"offline-source.sqlite")
    run("assessment", """
        from services.assessment import runtime as m
        from fastapi import HTTPException
        from services.assessment.inbox import accept
        from pathlib import Path
        import json
        actor=dict(school_id="test-school", actor_type="system",actor_id="interview",caller="interview")
        created,first,finish=json.loads(Path("wire.json").read_text())
        def denied(msg,n):
            try: accept(m,msg,actor)
            except HTTPException as exc: assert exc.status_code==n,exc
            else: raise AssertionError("expected refusal")
        denied(finish,409)
        denied({**first,"school_id":"other"},422)
        assert not m.all_rows("SELECT * FROM assessment_projection_inbox")
        accept(m,created,actor)
        assert m.get_stats(user={"id":"s"})["stats"]["total_interviews"] == 1
        accept(m,first,actor)
        accept(m,first,actor)
        tampered=json.loads(json.dumps(first))
        tampered["inputs"]["interview_messages"][0]["content"]="tampered replay"
        denied(tampered,409)
        assert m.one("SELECT COUNT(*) AS n FROM interview_jobs WHERE kind='score'")["n"]==1
    """)
    # 面试库离线期间，在两次确认之间重启评估服务。
    run("assessment", """
        from services.assessment import runtime as m
        from services.assessment.inbox import accept
        import json
        from pathlib import Path
        from services.interview.worker import run_once
        body=json.loads(Path("wire.json").read_text())[-1]
        actor=dict(school_id="test-school", actor_type="system",actor_id="interview",caller="interview")
        accept(m,body,actor); accept(m,body,actor)
        # 使用正式的评分和报告工作进程处理各自的输入，
        # 只模拟模型响应。
        def evaluate(**kw):
            assert "row lock" in kw["answer"]
            return dict(score=80,strengths="A",issues="B",suggestions="C",dimension_scores={"technical_depth":80},
                        dimension_evidence={"technical_depth":"row lock"},provider="test",model="test",
                        prompt_version=m.EVALUATION_PROMPT_VERSION,fallback=False)
        m.generate_ai_evaluation=evaluate
        m.generate_ai_report=lambda **kw:{**kw["fallback_report"],"provider":"test","model":"test",
                                           "prompt_version":m.REPORT_PROMPT_VERSION,"fallback":False}
        while run_once(m.interview_jobs,m.prepare_interview_job,kinds=("score","report")): pass
        report=m.get_interview_report("i",{"id":"s"})["report"]
        assert report["id"]==body["report_id"] and report["scored_answer_count"]==1,report
        assert report["generation_status"]=="succeeded" and report["total_score"]==80
        assert m.one("SELECT COUNT(*) AS n FROM assessment_report_versions")["n"]==1
        assert not m.one("SELECT name FROM sqlite_master WHERE name IN ('users','sessions','password_reset_tokens')")
        assert not m.one("SELECT id FROM interview_jobs WHERE kind IN ('project','train_complete')")
        assert m.one("SELECT id FROM interview_jobs WHERE kind='analytics'")
        assert not Path("source.sqlite").exists()
    """)



@pytest.mark.parametrize("manifest", ["no-permits", "with-permits", "legacy-needs-backfill"])
def test_cutover_preserves_teacher_decisions_and_history(tmp_path, process, manifest):
    process("offline-fixture", """
        from shared.offline_fixture import enable_offline_fixture
        enable_offline_fixture()
        from backend.offline import main as m
        from services.assessment import versions
        m.db.execute("INSERT INTO users(id,email,password_hash,name) VALUES ('s','s@test.invalid','!','S')").close()
        m.db.execute("INSERT INTO interview_sessions(id,user_id,target_role,status) VALUES ('i','s','tester','completed')").close()
        m.insert_queued_report("i", {"id":"s"}, report_id="original-report")
        import json, os
        from pathlib import Path
        from unittest.mock import patch
        from fastapi import Response
        from shared.credential_reference import application_id
        m.db.execute("INSERT INTO interview_messages(id,interview_id,sender_type,message_type,content) VALUES ('q','i','agent','question','Explain locks')").close()
        m.db.execute("INSERT INTO interview_messages(id,interview_id,sender_type,message_type,content,reply_to_message_id,order_index) VALUES ('a','i','candidate','answer','row lock','q',1)").close()
        m.db.execute("INSERT INTO interview_evaluations(id,interview_id,message_id,score,strengths,issues,suggestions,dimension_scores,dimension_evidence,provider,model,prompt_version,generation_status,fallback) VALUES ('e','i','a',80,'ok','gap','improve',?,?,'fixture','test',?,'succeeded',0)",
                     (json.dumps({"technical_depth":80}), json.dumps({"technical_depth":"row lock"}), m.EVALUATION_PROMPT_VERSION)).close()
        m.db.commit()
        with patch.object(m, "generate_ai_report", lambda **kw: {**kw["fallback_report"], "provider":"fixture",
                "model":"test", "prompt_version":m.REPORT_PROMPT_VERSION, "fallback":False}):
            m.create_report("i", Response(), {}, {"id":"s"})
        owner={"id":"original-report","interview_id":"i","user_id":"s"}
        if os.environ["VARIANT"] != "no-permits":
            from services.interview.assessment_events import digest
            row = m.one("SELECT evidence_version,source,actor_id,reason,snapshot FROM assessment_report_versions WHERE report_id='original-report' AND version=1")
            ids = dict(report_id="original-report", student_id="s", school_id="test-school", interview_id="i", version=1)
            permit = dict(ids, application_id=application_id("test-school","s","original-report",1),generation=1,
                          serial="a"*32,digest=digest({**row,**ids}),proof_digest="c"*64)
            m.db.execute("INSERT INTO assessment_issuance_permits(report_id,application_id,generation,serial,version,digest,proof_digest,authorized_by,school_id) VALUES(?,?,?,?,?,?,?,?,?)",
                         ("original-report",permit["application_id"],1,permit["serial"],1,permit["digest"],permit["proof_digest"],"teacher","test-school")).close()
            m.db.commit()
            Path("permit.json").write_text(json.dumps(permit))
        with versions.report_transaction("original-report", owner, 1) as (rep,rev):
            versions.change_score(rep,rev,86,"A","pass","teacher","verified source evidence","original-evidence")
        with versions.report_transaction("original-report", owner, 2) as (rep,rev):
            versions.review(rep,rev,"approved","teacher","accepted")
        if os.environ["VARIANT"] == "no-permits":
            m.db.execute("DROP TABLE assessment_issuance_permits").close()
        if os.environ["VARIANT"] == "legacy-needs-backfill":
            from services.interview.assessment_events import capture, initialize
            from services.assessment.migration import load_history, PERMITS
            initialize(m.db,False)
            with m.locked_session("i","s"):
                historical = load_history(m,"i")
                del historical[PERMITS]
                capture(m.interview_jobs,"i",history=historical)
    """, ASSESSMENT_STORAGE_MODE="shared", VARIANT=manifest)
    process("interview", """
        import sys,json,os
        from pathlib import Path
        from services.interview import runtime as m
        from services.interview.migration import main
        from services.assessment.migration import PERMITS
        variant = os.environ["VARIANT"]
        sys.argv=["migrate","--school","test-school","--source-sqlite",str(Path("old.sqlite").resolve())]
        main(); main()
        rows=m.all_rows("SELECT e.body FROM interview_delivery_events e JOIN interview_jobs j ON j.id=e.job_id ORDER BY j.version")
        bodies = [json.loads(row["body"]) for row in rows]
        assert len(bodies) == (2 if variant == "legacy-needs-backfill" else 1)
        assert (PERMITS in bodies[0]["history"]) == (variant == "with-permits")
        Path("archive.json").write_text(json.dumps(bodies))
        # 同一冻结快照可重试；换成其后改写的源数据时，不能覆盖新库或追加第二份清单。
        import sqlite3
        from services.interview.migration import migrate, open_snapshot
        other = Path("changed.sqlite").resolve()
        with sqlite3.connect("old.sqlite") as first, sqlite3.connect(other) as changed:
            first.backup(changed)
            changed.execute("UPDATE interview_sessions SET target_role='different' WHERE id='i'")
        try:
            with open_snapshot(other) as source:
                migrate(source,"test-school")
        except ValueError as exc:
            assert "快照内容" in str(exc)
        else:
            raise AssertionError("已导入的学校不能从不同的快照覆盖")
        assert m.one("SELECT target_role FROM interview_sessions WHERE id='i'")["target_role"]=="tester"
        assert m.one("SELECT COUNT(*) AS n FROM interview_delivery_events")["n"]==len(bodies)
    """, VARIANT=manifest)
    process("assessment", """
        from pathlib import Path
        import json, os, copy
        from fastapi import HTTPException
        from unittest.mock import patch
        from services.assessment import runtime as m
        from services.assessment import inbox, versions, app as api
        from services.assessment.migration import PERMITS
        archive=json.loads(Path("archive.json").read_text())
        ctx={"caller":"interview","actor_id":"interview","actor_type":"system","school_id":"test-school"}
        for event in archive:
            has_permits = "permit_backfill" in event or PERMITS in event.get("history",{})
            if has_permits:
                for k,v in (("application_id","0"*64),("school_id","other"),("version",2),("generation",2),
                            ("digest","0"*64),("report_id","different")):
                    bad = copy.deepcopy(event)
                    rows = bad.get("permit_backfill") or bad["history"][PERMITS]
                    rows[0][k] = v
                    try:
                        inbox.accept(m,bad,ctx)
                    except HTTPException as exc:
                        assert exc.status_code==409, exc
                    else:
                        raise AssertionError("invalid permit accepted")
                    assert m.one("SELECT COUNT(*) AS n FROM assessment_issuance_permits")["n"]==0
            inbox.accept(m,event,ctx)
            inbox.accept(m,event,ctx)
        if os.environ["VARIANT"] != "no-permits":
            receipt=json.loads(Path("permit.json").read_text())
            intent=api.IssueIntent(**{k:receipt[k] for k in api.IssueIntent.model_fields})
            owner={"id":"original-report","interview_id":"i","user_id":"s"}
            issuer=dict(actor_id="teacher",caller="credentials",school_id="test-school",actor_type="teacher")
            with patch.object(api,"_verified_owner",return_value=owner):
                assert api.authorize_issuance("original-report",intent,issuer)==receipt
                changed=intent.model_copy(update={"proof_digest":"e"*64})
                try:
                    api.authorize_issuance("original-report",changed,issuer)
                except HTTPException as exc:
                    assert exc.status_code==409
                else:
                    raise AssertionError("permit replay with modified proof was accepted")
            assert m.one("SELECT COUNT(*) AS n FROM assessment_issuance_permits")["n"]==1
        report=m.find_report_by_interview_id("i","s")
        assert (report["id"],report["total_score"],report["review_status"])==("original-report",86,"approved")
        history=versions.history(report["id"])
        assert [r["version"] for r in history["versions"]]==[2,1]
        assert (history["versions"][0]["actor_id"],history["versions"][0]["reason"])==("teacher","verified source evidence")
        assert (history["reviews"][0]["version"],history["reviews"][0]["note"])==(2,"accepted")
        assert m.all_rows("SELECT id FROM interview_jobs")==[]
    """, VARIANT=manifest)
