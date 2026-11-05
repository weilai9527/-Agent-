"""用 SQLite、实际签名的身份凭据和进程内训练服务测试评估流程。"""
import os
from pathlib import Path
import shutil
import subprocess
import sys


def test_assessment_service(tmp_path):
    root = Path(__file__).resolve().parents[2]
    # 旧代码会读取相邻的 .env 文件。这里只复制 Python 源码，
    # 以隔离本机密钥、运维数据库和运行配置。
    for name in ("backend/src", "backend/rtc_token_lib", "shared", "services"):
        for source in (root / name).rglob("*.py"):
            dest = tmp_path / source.relative_to(root)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, dest)
    env = {"PATH": os.environ["PATH"], "APP_ENV":"test", "SERVICE_ID":"assessment", "USAGE_SERVICE_URL":"http://127.0.0.1:1", "ASSESSMENT_DB_ENGINE": "sqlite", "ASSESSMENT_SQLITE_PATH": str(tmp_path / "fixture.db"),
           "LEGACY_SCHOOL_ID": "campus", "TRAINING_SERVICE_URL": "https://training.test"}
    if os.getenv("PYTHONPATH"):
        env["PYTHONPATH"] = os.environ["PYTHONPATH"]
    result = subprocess.run([sys.executable, "-m", "services.assessment.test_assessment"], cwd=tmp_path,
                            env=env, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stderr


def exercise():
    import json
    from concurrent.futures import ThreadPoolExecutor
    from unittest.mock import patch

    import httpx
    import jwt
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from fastapi.testclient import TestClient

    from services.assessment import app as api
    from shared.service_security import service_headers

    db = api.assessment.db
    with db:
        db.execute("INSERT INTO assessment_projection_inbox VALUES ('i',0,'campus','s1',?)", ("0"*64,)).close()
        db.execute("INSERT INTO interview_sessions(id,user_id,target_role,status) VALUES ('i','s1','QA','completed')")
        db.execute("""INSERT INTO interview_reports (id,user_id,interview_id,total_score,grade,pass_recommendation,
                  ability_radar,agent_feedback,timeline_review,summary,suggestions,review_status,reviewed_by)
                  VALUES ('r','s1','i',70,'C','borderline','{}','[]','[]','test','test','approved','old')""")

    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    os.environ["SERVICE_KEY_ID"] = "test-key"
    os.environ["SERVICE_SIGNING_KEY"] = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    peer_policy = {
        "keys": {"test-key": public}, "schools": ["campus", "other"], "grants": {"assessment": {
            "teacher": ["assessment.history", "assessment.score", "assessment.review", "assessment.credential-evidence", "assessment.credential-authorize"],
            "student": ["assessment.read", "assessment.generate", "assessment.credential-evidence"], "admin": ["assessment.score"]}}}
    os.environ["SERVICE_TRUST_POLICY"] = json.dumps({"gateway": peer_policy, "credentials": peer_policy})

    def signed(scope, actor="t1", role="teacher", school="campus", caller="gateway"):
        os.environ["SERVICE_ID"] = caller
        h = service_headers("assessment", actor_id=actor, school_id=school, actor_type=role, scopes=[scope])
        os.environ["SERVICE_ID"] = "assessment"
        return h

    attempt = {"school_id": "campus", "student_id": "s1", "teacher_id": "t1", "interview_id": "i"}
    def peer(_transport, req):
        claims = jwt.decode(req.headers["Authorization"].split()[1], public, algorithms=["EdDSA"], audience="training")
        assert claims["iss"] == "assessment" and claims["scopes"] == ["training.verify"]
        assert req.url == httpx.URL("https://training.test/interviews/i/attempt")
        return httpx.Response(200, json=attempt)

    score_url = "/api/admin/reports/r/score"
    history_url = "/api/admin/reports/r/history"
    review_url = "/api/admin/reports/r/review"
    edit = {"expected_version": 1, "total_score": 82, "reason": "补充项目证据"}
    async def student_peer(service, method, path, *, actor, scope):
        assert service == "identity" and path == "/internal/students/me" and scope == "identity.student.read"
        return {"actor_id":actor["actor_id"],"school_id":actor["school_id"],"status":"normal",
                "must_change_password":False,"name":"Synthetic Student"}

    with TestClient(api.app) as client, patch.object(httpx.HTTPTransport, "handle_request", peer), \
            patch.object(api,"request_json",student_peer), patch.object(api,"check_student_action"):

        def get(h):
            return client.get(history_url, headers=h)
        assert get({}).status_code == 401
        assert client.get("/api/reports/r", headers=signed("assessment.read", "s2", "student")).status_code == 404
        own = client.get("/api/reports/r", headers=signed("assessment.read", "s1", "student"))
        assert own.status_code == 200 and own.json()["report"]["total_score"] == 70
        assert get(signed("assessment.history", school="other")).status_code == 403
        assert get(signed("assessment.history", actor="wrong")).status_code == 403
        assert client.patch(score_url, json=edit, headers=signed("assessment.score", role="admin")).status_code == 403
        hh = signed("assessment.history")
        for field in ("student_id", "school_id", "interview_id"):
            with patch.dict(attempt, {field: "mismatch"}):
                assert get(hh).status_code == 403
        with patch.object(httpx.HTTPTransport, "handle_request", side_effect=httpx.ConnectError("offline")):
            assert get(hh).status_code == 503
        before = get(hh).json()
        assert before["versions"][0]["source"] == "legacy" and before["reviews"][0]["actor_id"] == "old"
        sh = signed("assessment.score")
        assert client.patch(score_url, json={**edit, "teacher_id": "t1"}, headers=sh).status_code == 422
        def race(n):
            return client.patch(score_url, json={**edit, "total_score": n}, headers=sh).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(race, [82, 84])) == [200, 409]
        rh = signed("assessment.review")
        assert client.patch(review_url, json={"expected_version": 1, "status": "approved"}, headers=rh).status_code == 409
        assert client.patch(review_url, json={"expected_version": 2, "status": "approved"}, headers=rh).status_code == 200
        # 响应丢失后重发同一 PATCH 请求，仍应只有一条审核记录。
        assert client.patch(review_url, json={"expected_version": 2, "status": "approved"}, headers=rh).status_code == 200
        result = get(hh).json()
        assert result["report"]["review_status"] == "approved" and result["report"]["grade"] == "B"
        assert [v["version"] for v in result["versions"]] == [2, 1]
        assert result["versions"][0]["snapshot"]["review_status"] == "pending"
        assert [(e["version"], e["actor_id"]) for e in result["reviews"]] == [(2, "t1"), (1, "old")]
        with api.assessment.locked_session("i", "s1"):
            assert not api.versions.should_publish_report("r", result["versions"][0]["evidence_version"])
        try:
            with api.assessment.locked_session("i", "s1"):
                assert api.versions.should_publish_report("r", "new-evidence")
                db.execute("UPDATE interview_reports SET total_score=5,review_status='pending' WHERE id='r'")
                api.versions.record_generated_report("r", "new-evidence")
                raise RuntimeError("abort publication")
        except RuntimeError as exc:
            assert str(exc) == "abort publication"
        assert get(hh).json() == result

        credential = "/internal/credential-evidence/r"
        cscope = "assessment.credential-evidence"
        own_evidence = signed(cscope, "s1", "student", caller="credentials")
        assert client.get(credential, headers=signed(cscope, "s1", "student")).status_code == 403
        assert client.get(credential, headers=signed(cscope, "s2", "student", caller="credentials")).status_code == 404
        assert client.get(credential, headers=own_evidence).status_code == 409  # 历史投影不能作为签发依据
        with db:
            db.execute("""INSERT INTO interview_messages(id,interview_id,sender_type,message_type,content)
                          VALUES ('q','i','agent','question','Explain the isolation.')""").close()
            db.execute("""INSERT INTO interview_messages(id,interview_id,sender_type,message_type,content,
                          reply_to_message_id,order_index) VALUES ('a','i','candidate','answer','row lock','q',1)""").close()
            db.execute("""INSERT INTO interview_evaluations(id,interview_id,message_id,score,strengths,issues,
                          suggestions,dimension_scores,dimension_evidence,provider,model,prompt_version,
                          generation_status,fallback) VALUES ('e','i','a',80,'ok','gap','use locks',
                          '{"technical_depth":80}','{"technical_depth":"row lock"}','custom','test-model',?,
                          'succeeded',0)""", (api.assessment.EVALUATION_PROMPT_VERSION,)).close()
        def generated(**kw):
            return {**kw["fallback_report"], "provider": "custom", "model": "test-model",
                    "prompt_version": api.assessment.REPORT_PROMPT_VERSION, "fallback": False}
        with patch.object(api.assessment, "generate_ai_report", generated):
            built = client.post("/api/interviews/i/report", headers=signed("assessment.generate", "s1", "student"))
        assert built.status_code == 200, built.text
        attested = client.get(credential, headers=own_evidence)
        assert attested.status_code == 200, attested.text
        reference = attested.json()
        assert reference["version"] == 3 and len(reference["digest"]) == 64
        assert client.get(credential, headers=own_evidence).json() == reference
        published = api.assessment.one("SELECT snapshot FROM assessment_report_versions WHERE report_id='r' AND version=3")
        snapshot = json.loads(published["snapshot"])
        answer = json.loads(snapshot["timeline_review"])[0]
        malformed = ["{", "[]", json.dumps({}), json.dumps({**snapshot, "timeline_review": "null"})]
        for bad_timeline in ([], [None], {"q": answer}, [{**answer, "dimension_scores": "bad"}],
                             [{**answer, "dimension_evidence": ["row lock"]}],
                             [{**answer, "dimension_evidence": {"technical_depth": 1}}]):
            malformed.append(json.dumps({**snapshot, "timeline_review": json.dumps(bad_timeline)}))
        for raw in malformed:
            with db:
                db.execute("UPDATE assessment_report_versions SET snapshot=? WHERE report_id='r' AND version=3",
                           (raw,)).close()
            assert client.get(credential, headers=own_evidence).status_code == 409
        with db:
            db.execute("UPDATE assessment_report_versions SET snapshot=? WHERE report_id='r' AND version=3",
                       (published["snapshot"],)).close()
        from shared.credential_reference import application_id
        permit = {"application_id": application_id("campus", "s1", "r", 3), "generation": 1, "serial": "a" * 32,
                  "version": 3, "digest": reference["digest"], "proof_digest": "c" * 64}
        permit_url = credential + "/authorize"
        auth_scope = "assessment.credential-authorize"
        assert client.post(permit_url, json=permit, headers=signed(auth_scope)).status_code == 403
        permit_auth = signed(auth_scope, caller="credentials")
        assert client.post(permit_url, json={**permit, "digest": "0"*64}, headers=permit_auth).status_code == 409
        # 在签发许可事务核对证据后暂停，
        # 等教师发起修改后再允许事务提交。
        from threading import Event
        entered, waiting, release = Event(), Event(), Event()
        original_execute = db.execute
        def pause_insert(sql, params=()):
            if "INSERT INTO assessment_issuance_permits" in sql:
                entered.set()
                assert release.wait(timeout=8)
            elif entered.is_set() and "BEGIN IMMEDIATE" in sql:
                waiting.set()
            return original_execute(sql, params)
        with patch.object(db, "execute", pause_insert), ThreadPoolExecutor(2) as pool:
            pending = pool.submit(client.post, permit_url, json=permit, headers=permit_auth)
            try:
                assert entered.wait(timeout=8)
                edit_request = pool.submit(client.patch, score_url, json={**edit, "expected_version": 3}, headers=sh)
                assert waiting.wait(timeout=8) and not edit_request.done()
            finally:
                release.set()
            assert pending.result(timeout=8).status_code == 200
            assert edit_request.result(timeout=8).status_code == 200
        assert client.post(permit_url, json=permit, headers=permit_auth).status_code == 200
        for changes in ({"serial": "f"*32}, {"proof_digest": "f"*64}, {"generation": 2}):
            assert client.post(permit_url, json={**permit, **changes}, headers=permit_auth).status_code == 409
        assert api.assessment.one("SELECT COUNT(*) AS n FROM assessment_issuance_permits")["n"] == 1
        revised = client.get(credential, headers=own_evidence).json()
        assert revised["version"] == 4 and revised["digest"] != reference["digest"]
        with db:
            db.execute("UPDATE interview_messages SET content='updated evidence' WHERE id='a'").close()
        assert client.get(credential, headers=own_evidence).status_code == 409
        assert client.patch(review_url, json={"expected_version": 4, "status": "approved"}, headers=rh).status_code == 409

    exercise_repair(api)


def exercise_repair(api):
    legacy, versions = api.assessment, api.versions
    owner = {"interview_id": "i", "user_id": "s1"}
    def publish_fallback(evidence):
        with legacy.locked_session("i", "s1"):
            assert versions.should_publish_report("r", evidence)
            legacy.db.execute("""UPDATE interview_reports SET generation_status='degraded',fallback=1,
                                 review_status='pending',reviewed_at=NULL,reviewed_by=NULL WHERE id='r'""").close()
            return versions.record_generated_report("r", evidence)

    n = publish_fallback("outage")
    with legacy.locked_session("i", "s1"):
        assert versions.can_repair_degraded("r", "outage")
        assert not versions.can_repair_degraded("r", "other")
        assert not versions.should_publish_report("r", "outage")
        try:
            versions.record_generated_report("r", "outage", repairing=True)
        except RuntimeError:
            pass
        else:
            raise AssertionError("Repeated fallback generated a new version")
        legacy.db.execute("UPDATE interview_reports SET generation_status='succeeded',fallback=0 WHERE id='r'").close()
        assert versions.record_generated_report("r", "outage", repairing=True) == n + 1
        assert not versions.can_repair_degraded("r", "outage")
        try:
            versions.record_generated_report("r", "outage", repairing=True)
        except RuntimeError:
            pass
        else:
            raise AssertionError("An already successful revision was replaced")

    n = publish_fallback("reviewed-outage")
    with versions.report_transaction("r", owner, n) as (report, revision):
        versions.review(report, revision, "pending", "t1", "待核实")
    with legacy.locked_session("i", "s1"):
        assert not versions.can_repair_degraded("r", "reviewed-outage")
    # 教师审核了降级报告后，模型结果才返回。
    # 即使调用方跳过预检，发布阶段也必须回滚该次更新。
    try:
        with legacy.locked_session("i", "s1"):
            legacy.db.execute("UPDATE interview_reports SET generation_status='succeeded',fallback=0 WHERE id='r'").close()
            versions.record_generated_report("r", "reviewed-outage", repairing=True)
    except RuntimeError:
        pass
    else:
        raise AssertionError("A reviewed fallback was replaced")
    n = publish_fallback("teacher-outage")
    with versions.report_transaction("r", owner, n) as (report, revision):
        versions.change_score(report, revision, 90, "A", "strong_pass", "t1", "核实", "teacher-outage")
    with legacy.locked_session("i", "s1"):
        assert not versions.can_repair_degraded("r", "teacher-outage")


if __name__ == "__main__":
    def deny_network(event, args):
        if event == "socket.connect":
            raise RuntimeError("External sockets are forbidden in this test")
    sys.addaudithook(deny_network)
    exercise()
