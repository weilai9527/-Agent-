"""用独立数据库、合成记录和临时密钥验证证书、评估、训练和身份服务之间的契约。"""
import json
import os
import shutil
import subprocess
import sys
from contextlib import ExitStack
from pathlib import Path
from importlib.util import find_spec
from unittest.mock import patch


def test_published_report_contract(tmp_path):
    # 子进程只接收源码和本次测试的配置，项目中的 dotenv 和业务库都不复制。
    root = Path(__file__).resolve().parents[3]
    for directory in ("services", "shared"):
        for source in (root / directory).rglob("*.py"):
            target = tmp_path / source.relative_to(root)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    # 不传身份及存储模式开关，直接验证新部署的默认链路。
    env = {"PATH": os.environ["PATH"], "APP_ENV": "test", "LEGACY_SCHOOL_ID": "fixture"}
    # 只传 pip --target 的依赖目录，不让子进程回到工作区导入退役模块。
    dependencies = {str(Path(find_spec(name).origin).parent.parent) for name in ("openpyxl", "jwt", "fastapi")}
    env["PYTHONPATH"] = os.pathsep.join(sorted(dependencies))
    module = "services.credentials.tests.test_evidence_contract"
    source_db = tmp_path / "interview.sqlite"
    source = subprocess.run([sys.executable, "-m", module, "interview"], cwd=tmp_path,
                            env={**env, "SERVICE_ID": "interview", "INTERVIEW_DB_ENGINE": "sqlite",
                                 "INTERVIEW_SQLITE_PATH": str(source_db)},
                            capture_output=True, text=True, timeout=90)
    assert source.returncode == 0, source.stderr
    # 评估进程只接收面试写出的事件。移走源库，将通用 SQLite 路径指向目录，误用它就会报错。
    source_db.rename(tmp_path / "offline-interview.sqlite")
    env.update(SERVICE_ID="assessment", DB_ENGINE="sqlite", SQLITE_PATH=str(tmp_path))
    for name in ("identity", "training", "credentials", "assessment", "usage"):
        env.update({name.upper() + "_DB_ENGINE": "sqlite",
                    name.upper() + "_SQLITE_PATH": str(tmp_path / (name + ".sqlite"))})
    for name in ("identity", "training", "assessment", "usage", "providers"):
        env[name.upper() + "_SERVICE_URL"] = "https://" + name + ".invalid"
    result = subprocess.run([sys.executable, "-m", "services.credentials.tests.test_evidence_contract"],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stderr
    assert not source_db.exists()


def seed(identity, training):
    with identity.state.store.transaction(write=True) as tx:
        tx.execute("""INSERT INTO identity_staff
            (school_id,actor_id,email,password_hash,name,actor_type,status,permissions)
            VALUES ('fixture','t','t@test.invalid','test','Teacher','teacher','normal',?)""",
                   (json.dumps(["credential.approve", "credential.issue", "score.adjust"]),))
        tx.execute("""INSERT INTO identity_student_credentials
            (school_id,actor_id,student_no,name,password_hash,status,must_change_password)
            VALUES ('fixture','s','syn123','Synthetic','test','normal',0)""")
        tx.execute("INSERT INTO org_colleges VALUES ('fixture','college','College','active')")
        tx.execute("INSERT INTO org_programs VALUES ('fixture','p','college','Program','active')")
        tx.execute("INSERT INTO org_classes VALUES ('fixture','c','p','Class','active')")
        tx.execute("INSERT INTO org_enrollments VALUES ('fixture','s','c','active')")
        tx.execute("INSERT INTO org_staff_classes VALUES ('fixture','t','c')")
    with training.state.db.transaction(write=True) as tx:
        tx.execute("""INSERT INTO training_tasks
            (task_id,school_id,teacher_id,request_id,fingerprint,title,job_role,job_id,
             deadline_us,max_attempts,questions,class_ids,student_count,created_us)
            VALUES ('task','fixture','t','once','fake','Test','QA','qa',0,1,?,'["c"]',1,0)""",
                   (json.dumps([{"question_id": "q", "prompt": "Explain retries."}]),))
        tx.execute("INSERT INTO training_enrollments VALUES ('task','s','c',1)")
        tx.execute("""INSERT INTO training_attempts
            (attempt_id,interview_id,task_id,student_id,request_id,attempt_no,status,created_us,completed_us)
            VALUES ('a','i','task','s','once',1,'completed',1,2)""")


def produce_interview_events():
    from fastapi import BackgroundTasks
    from services.interview import runtime as source
    from services.interview.training_rounds import materialize

    assert not source.all_rows("SELECT name FROM sqlite_master WHERE name='users'")
    materialize("a", {"attempt_id": "a", "interview_id": "i", "student_id": "s", "school_id": "fixture",
                      "job_role": "QA", "status": "started",
                      "questions": [{"question_id": "q", "prompt": "Explain retries."}]}, "s", "fixture",
                native_verified=True)
    question = source.managed_progress("i")["question_id"]
    source.submit_turn("i", {"question_id": question, "submission_id": "answer",
                             "content": "Store idempotency keys."}, user={"id": "s"})
    source.finish_interview("i", BackgroundTasks(), {"id": "s"})
    events = source.all_rows("""SELECT e.body FROM interview_delivery_events e
        JOIN interview_jobs j ON j.id=e.job_id WHERE j.kind='project' ORDER BY j.version""")
    assert not source.all_rows("SELECT name FROM sqlite_master WHERE name='interview_reports'")
    Path("projections.json").write_text(json.dumps([json.loads(event["body"]) for event in events]))


def run_assessment_jobs(assessment):
    from services.interview.worker import run_once

    for kind in ("score", "report"):
        while run_once(assessment.interview_jobs, assessment.prepare_interview_job, kinds=(kind,)):
            pass
    assert not assessment.one("SELECT name FROM sqlite_master WHERE name='users'")


def exercise():
    import httpx
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from fastapi.testclient import TestClient
    from services.assessment.app import app as assessment_app
    from services.assessment import runtime as assessment
    from services.credentials.app import app as credentials
    from services.providers.app import app as providers
    from services.usage.app import app as usage
    from shared.provider_settings import save_public_settings
    from services.identity.app import app as identity
    from services.training.app import app as training
    from shared.service_security import service_headers

    apps = {"identity": identity, "training": training, "credentials": credentials, "assessment": assessment_app,
            "usage": usage, "providers": providers}
    read = ["assessment.credential-evidence"]
    verify = ["training.verify"]
    grants = {
        "gateway": {"credentials": {"student": ["credential.apply"], "teacher": ["credential.approve", "credential.issue"]},
                    "assessment": {"teacher": ["assessment.score"]},
                    "usage": {"admin": ["usage.configure", "usage.read"]}},
        "credentials": {"assessment": {"student": read, "teacher": read + ["assessment.credential-authorize"]},
                        "training": {"student": verify, "teacher": verify},
                        "identity": {"teacher": ["identity.student.authorize"]}},
        "assessment": {"training": {"teacher": verify}, "identity": {"teacher": ["identity.student.authorize"]},
                       "providers": {"system": ["providers.runtime.read"]},
                       "usage": {"student": ["usage.reserve", "usage.dispatch", "usage.settle"]}},
        "interview": {"assessment": {"system": ["assessment.project"]}},
        "training": {"identity": {"teacher": ["identity.roster.read"]}},
    }
    settings, policy = {}, {}

    def pem_pair():
        key = Ed25519PrivateKey.generate()
        return (key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                  serialization.NoEncryption()).decode(),
                key.public_key().public_bytes(serialization.Encoding.PEM,
                                              serialization.PublicFormat.SubjectPublicKeyInfo).decode())

    for name in {"gateway", "interview", *apps}:
        private, public = pem_pair()
        settings[name] = {"SERVICE_ID": name, "SERVICE_SIGNING_KEY": private, "SERVICE_KEY_ID": "k"}
        policy[name] = {"keys": {"k": public}, "schools": ["fixture"], "grants": grants.get(name, {})}
    policy["assessment"]["schools"].append("platform")
    settings["providers"].update(PROVIDERS_DB_ENGINE="sqlite", PROVIDERS_SQLITE_PATH=str(Path("providers.sqlite").resolve()))
    settings["assessment"]["AI_API_KEY"] = "synthetic-test-only"
    os.environ["PROVIDER_ALLOWED_CUSTOM_ENDPOINTS"] = "https://model.invalid/v1"
    os.environ["CUSTOM_TRUST_ENV"] = "false"
    os.environ["SERVICE_TRUST_POLICY"] = json.dumps(policy)
    private, public = pem_pair()
    os.environ["CREDENTIALS_SIGNING_KEYS_JSON"] = json.dumps({"fixture": {"kid": "school", "private_key": private}})
    os.environ["CREDENTIALS_PUBLIC_KEYS_JSON"] = json.dumps({"fixture": {"school": public}})
    with ExitStack() as stack:
        clients = {}
        for name, app in apps.items():
            with patch.dict(os.environ, settings[name]):
                clients[name] = stack.enter_context(TestClient(app))
        # 模型配置库只在控制服务的身份下打开，评估进程通过签名接口读取配置。
        with patch.dict(os.environ, settings["providers"]):
            save_public_settings({"reportCustomModel": "fixture-model", "reportCustomBaseUrl": "https://model.invalid/v1",
                                  "evaluationProviderOrder": "custom", "reportProviderOrder": "custom"})
        model_calls = []
        seed(identity, training)

        # 许可事务提交后丢弃一次响应，重试仍需通过对象授权和版本校验。
        lose_permit_response = False

        def transport(_, request):
            nonlocal lose_permit_response
            if request.url == httpx.URL("https://model.invalid/v1/chat/completions"):
                # 仅替换提供商网络响应；请求仍经过真实的评分、派发、响应解析及结算路径。
                slot = request.headers["X-Client-Request-Id"]
                payload = json.loads(request.content)
                assert payload["model"] == "fixture-model" and slot not in model_calls
                user_message = payload["messages"][-1]["content"]
                assert "idempotency keys" in user_message
                if "question_types" in user_message:
                    answer = {"question_types": ["technical"], "dimension_scores": {"technical_accuracy": 75},
                              "dimension_evidence": {"technical_accuracy": "idempotency keys"}}
                else:
                    assert "timeline" in user_message or "已评分问答" in user_message
                    answer = {"summary": "合成报告", "suggestions": ["合成建议"]}
                model_calls.append(slot)
                return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(answer)}}]})
            name = request.url.host.split(".")[0]
            assert request.url.host == name + ".invalid" and name in clients
            with patch.dict(os.environ, settings[name]):
                result = clients[name].request(request.method, request.url.raw_path.decode(),
                                               content=request.content, headers=request.headers)
            if (lose_permit_response and request.url.path.endswith("/authorize")
                    and result.status_code == 200):
                lose_permit_response = False
                raise httpx.ReadTimeout("Synthetic lost permit response", request=request)
            return httpx.Response(result.status_code, content=result.content, headers=result.headers)

        stack.enter_context(patch.object(httpx.HTTPTransport, "handle_request", transport))

        def call(name, who, role, method, path, scope, body=None, expected=200):
            with patch.dict(os.environ, settings["gateway"]):
                headers = service_headers(name, actor_id=who, actor_type=role, school_id="fixture", scopes=[scope])
            with patch.dict(os.environ, settings[name]):
                res = clients[name].request(method, path, headers=headers, json=body)
            assert res.status_code == expected, (path, res.status_code, res.text)
            return res.json()

        projections = json.loads(Path("projections.json").read_text())
        assert projections
        for event in projections:
            with patch.dict(os.environ, settings["interview"]):
                headers = service_headers("assessment", actor_id="interview", actor_type="system",
                                          school_id="fixture", scopes=["assessment.project"])
            response = clients["assessment"].post("/internal/interview-projections", headers=headers, json=event)
            assert response.status_code == 200, response.text
        quota_path = "/internal/usage/quota"
        configured = call("usage", "budget-admin", "admin", "PUT", quota_path, "usage.configure", {"text": 2, "media": 0})
        assert configured["text"] == {"limit": 2, "used": 0, "reserved": 0, "available": 2}
        with patch.dict(os.environ, settings["assessment"]):
            run_assessment_jobs(assessment)
        # 每次合成 HTTP 回复都应对应一个已发布任务、一次真实预留和一笔结算。
        attempts = assessment.all_rows("""SELECT a.id,a.reservation_id,j.kind FROM worker_model_attempts a
            JOIN interview_jobs j ON j.id=a.job_id WHERE a.state='published' AND a.outcome='success'""")
        assert sorted(row["kind"] for row in attempts) == ["report", "score"], attempts
        assert len(model_calls) == 2 and set(model_calls) == {row["id"] for row in attempts}
        with usage.state.ledger.store.transaction() as tx:
            settled = tx.all("""SELECT r.reservation_id FROM usage_reservations r JOIN usage_dispatches d
                ON d.reservation_id=r.reservation_id WHERE r.school_id='fixture' AND r.caller='assessment'
                AND r.actor_type='student' AND r.actor_id='s' AND r.resource='text' AND r.units=1 AND r.actual_units=1""")
        assert {row["reservation_id"] for row in settled} == {row["reservation_id"] for row in attempts}
        balance = call("usage", "budget-admin", "admin", "GET", quota_path, "usage.read")
        assert balance["text"] == {"limit": 2, "used": 2, "reserved": 0, "available": 0}
        report_id = projections[-1]["report_id"]

        def apply(who="s", expected=200):
            return call("credentials", who, "student", "POST", "/applications", "credential.apply",
                        {"report_id": report_id}, expected)

        def review(row, who="t", expected=200):
            evidence = row["evidence"]
            return call("credentials", who, "teacher", "POST", "/applications/" + row["id"] + "/review",
                        "credential.approve", {"decision": "approved", "version": evidence["version"],
                                               "digest": evidence["digest"]}, expected)

        def issue(row, expected=200):
            return call("credentials", "t", "teacher", "POST", "/applications/" + row["id"] + "/issue",
                        "credential.issue", expected=expected)

        apply("other-student", 404)
        first = apply()
        version = first["evidence"]["version"]
        assert first["evidence"]["training_id"] == "task" and version >= 1
        review(first, "other-teacher", 404)
        review(first)
        # 教师复核即使给出相同分数也会产生新版本，旧审批不能用于新报告。
        call("assessment", "t", "teacher", "PATCH", f"/api/admin/reports/{report_id}/score", "assessment.score",
             {"expected_version": version, "total_score": 75, "reason": "Second review"})
        issue(first, 409)
        second = apply()
        assert second["decision"] == "pending" and second["id"] != first["id"]
        assert second["evidence"]["digest"] != first["evidence"]["digest"]
        assert second["evidence"]["version"] == version + 1
        issue(second, 409)
        review(second)
        lose_permit_response = True
        issue(second, 503)
        from services.credentials.storage import database
        with database().transaction() as tx:
            pending = tx.one("SELECT serial FROM credential_issuance_intents WHERE application_id=?", (second["id"],))
            assert pending and tx.one("SELECT COUNT(*) AS n FROM teaching_certificates")["n"] == 0
        permit = assessment.one("SELECT serial,version,digest FROM assessment_issuance_permits")
        assert permit == {"serial": pending["serial"], "version": version + 1, "digest": second["evidence"]["digest"]}
        # 许可提交后再改分，重试应恢复原来的证书序号，不能多发一张。
        call("assessment", "t", "teacher", "PATCH", f"/api/admin/reports/{report_id}/score", "assessment.score",
             {"expected_version": version + 1, "total_score": 80, "reason": "After permit"})
        serial = issue(second)
        assert serial["id"] == pending["serial"] and issue(second) == serial
        with database().transaction() as tx:
            assert tx.one("SELECT COUNT(*) AS n FROM teaching_certificates")["n"] == 1
            assert tx.one("SELECT COUNT(*) AS n FROM credential_outbox")["n"] == 1
        assert clients["credentials"].get(serial["verification_url"]).json()["valid"] is True
        # 保留班级与审核权限，单独收回签发权限；网关原有的委派也不能继续签发。
        with identity.state.store.transaction(write=True) as tx:
            tx.execute("UPDATE identity_staff SET permissions=? WHERE school_id='fixture' AND actor_id='t'",
                       (json.dumps(["credential.approve"]),))
        issue(second, 403)
        with identity.state.store.transaction(write=True) as tx:
            tx.execute("UPDATE identity_staff SET permissions=? WHERE school_id='fixture' AND actor_id='t'",
                       (json.dumps(["credential.issue"]),))
            tx.execute("DELETE FROM org_staff_classes WHERE school_id='fixture' AND staff_id='t'")
        # 教师与班级解绑后，即使重试已完成的签发，也要重新校验当前权限。
        issue(second, 403)


if __name__ == "__main__":
    def deny_network(event, args):
        if event == "socket.connect":
            raise AssertionError("Integration fixture attempted a network connection")
    sys.addaudithook(deny_network)
    if sys.argv[1:] == ["interview"]:
        produce_interview_events()
    else:
        exercise()
