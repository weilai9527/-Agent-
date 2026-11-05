"""在只含原生源码的临时工件里运行招聘、目录、简历快照和授权模型匹配。"""
from contextlib import ExitStack
from io import BytesIO
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch


def test_career_business_paths_in_native_package(tmp_path):
    from services.profile.test_standalone import run_native_package

    run_native_package(tmp_path, __file__)


def catalog_sheet():
    from openpyxl import Workbook
    book = Workbook()
    book.remove(book.active)
    for title, columns, row in (
        ("学院", ["编码", "名称"], ["C1", "测试学院"]),
        ("专业", ["编码", "名称", "学院编码"], ["M1", "测试专业", "C1"]),
        ("培养方向", ["编码", "名称", "专业编码"], ["T1", "技术研发", "M1"]),
        ("就业方向", ["编码", "名称", "培养方向编码"], ["D1", "软件研发", "T1"]),
        ("岗位", ["编码", "名称", "就业方向编码"], ["J1", "测试开发工程师", "D1"]),
        ("能力", ["编码", "名称", "类别"], ["A1", "测试设计", "工程"]),
        ("岗位能力", ["岗位编码", "能力编码", "要求等级", "权重"], ["J1", "A1", 3, 5]),
    ):
        sheet = book.create_sheet(title)
        sheet.append(columns)
        sheet.append(row)
    out = BytesIO()
    book.save(out)
    return out.getvalue()


def publish_catalog(call):
    versions = "/v1/admin/catalog/versions"
    draft = call("career", "POST", versions, "catalog.write", "admin", json={"code":"native", "name":"新目录"})
    assert draft.status_code == 201, draft.text
    draft_path = versions + "/" + draft.json()["version"]["id"]
    imported = call("career", "POST", draft_path + "/imports", "catalog.import", "admin",
                    files={"file":("catalog.xlsx", catalog_sheet())})
    assert imported.status_code == 201 and imported.json()["import_job"]["imported_rows"] == 7, imported.text
    assert call("career", "POST", draft_path + "/publish", "catalog.publish", "admin").status_code == 200
    published = call("career", "GET", "/v1/catalog/tree?version=native", "catalog.read", "student").json()
    assert published["version"]["status"] == "published" and published["colleges"][0]["majors"][0]["name"] == "测试专业"


def import_posting(call, job_name):
    from openpyxl import load_workbook

    postings = "/v1/admin/job-postings"
    template = call("career", "GET", postings + "/template", "posting.admin.read", "admin")
    assert template.status_code == 200
    book = load_workbook(BytesIO(template.content))
    fields = {"岗位名称":job_name, "公司":"Example Co", "技能要求":"Python", "任职要求":"PRIVATE_JD Python",
              "关联标准岗位":"测试开发工程师", "外部编号":"source-1"}
    book.active.append([fields.get(cell.value) for cell in book.active[1]])
    workbook = BytesIO()
    book.save(workbook)
    for count in ("created", "updated"):
        response = call("career", "POST", postings + "/import", "posting.import", "admin",
                        files={"file":("jobs.xlsx", workbook.getvalue())})
        assert response.status_code == 200 and response.json()[count] == 1, response.text
    export = call("career", "GET", postings + "/export", "posting.admin.read", "admin")
    rows = list(load_workbook(BytesIO(export.content), read_only=True).active.values)
    assert len(rows) == 2 and dict(zip(*rows))["岗位名称"] == job_name
    visible = call("career", "GET", "/v1/job-postings", "posting.read", "student").json()["postings"]
    assert len(visible) == 1 and visible[0]["catalog_job_name"] == "测试开发工程师"
    return visible[0]["id"]


def check_feed_sync(call):
    from urllib.request import OpenerDirector

    # 只替换数据源的最后一次网络读取，运行真实的解析、校验和幂等更新。
    def synthetic_feed(_client, request, *, timeout):
        assert request.full_url == "https://feed.invalid/jobs" and timeout > 0
        return BytesIO(b'{"items":[{"id":"external-1","title":"Imported engineer"}]}')

    with patch.object(OpenerDirector, "open", synthetic_feed):
        for field in ("created", "updated"):
            reply = call("career", "POST", "/v1/admin/job-postings/sync", "posting.sync", "admin")
            assert reply.status_code == 200 and reply.json()[field] == 1, reply.text


def run_case():
    import httpx
    import jwt
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from fastapi.testclient import TestClient
    from services.career.app import app as career
    from services.profile.app import app as profile
    from services.providers.app import app as providers
    from shared.provider_settings import RUNTIME_SCOPE
    from shared.service_security import service_headers

    root = Path.cwd()
    assert not (root / "backend").exists() and not (root / "admin_backend").exists()
    school, student = "native-school", "candidate-1"
    job_name, secret = "私有招聘岗位", "PRIVATE_RESUME_MARKER"
    model_url, model_name = "https://advice.invalid/v1", "career-from-control"
    apps = {"career": career, "profile": profile, "providers": providers}
    opened = set()
    def check_store(event, args):
        if event == "sqlite3.connect":
            service = os.environ.get("SERVICE_ID")
            if service not in apps or Path(args[0]).resolve() != root / (service + ".sqlite"):
                raise AssertionError("访问了不属于该服务的数据库")
            opened.add(service)
    sys.addaudithook(check_store)
    career_routes = {"PROVIDERS_SERVICE_URL": "https://providers.test", "PROFILE_SERVICE_URL": "https://profile.test"}
    grants = {
        "admin-gateway": {"career": {"admin": ["catalog.write", "catalog.import", "catalog.publish",
                                               "posting.import", "posting.admin.read", "posting.sync"]},
                          "providers": {"admin": ["providers.configure"]}},
        "student-gateway": {"career": {"student": ["catalog.read", "posting.read", "match.create", "match.read"]},
                            "profile": {"student": ["profile.upload"]}},
        "career": {"profile": {"student": ["profile.snapshot.read"]}, "providers": {"system": [RUNTIME_SCOPE]}},
    }
    keys, public, policies = {}, {}, {}
    for peer in (*grants, "profile", "providers"):
        key = Ed25519PrivateKey.generate()
        keys[peer] = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption()).decode()
        public[peer] = key.public_key()
        pem = public[peer].public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        policies[peer] = {"keys": {"k": pem.decode()}, "schools": [school, "platform"], "grants": grants.get(peer, {})}

    def environment(peer):
        # 进程间只共享公钥策略，不把控制库连接配置或模型密钥注入其它服务。
        values = {"SERVICE_ID": peer, "SERVICE_KEY_ID": "k", "SERVICE_SIGNING_KEY": keys[peer],
                  "SERVICE_TRUST_POLICY": json.dumps(policies), "APP_ENV": "test"}
        if peer in apps:
            values.update({peer.upper() + "_DB_ENGINE": "sqlite",
                           peer.upper() + "_SQLITE_PATH": str(root / (peer + ".sqlite"))})
        if peer in ("career", "providers"):
            values["PROVIDER_ALLOWED_CUSTOM_ENDPOINTS"] = model_url
        if peer == "providers":
            values["PROVIDER_PLATFORM_ADMIN_IDS"] = "operator"
        if peer == "career":
            values.update(career_routes, CAREER_SCHOOL_ID=school, JOB_POSTING_SYNC_ENDPOINT="https://feed.invalid/jobs",
                          AI_API_KEY="synthetic-secret",
                          AI_MODEL="unconfigured", CAREER_MODEL_BY_SCHOOL=json.dumps({school: "custom"}))
        # 父进程提供的解释器依赖、运行目录与文件审计配置保留，但各服务的库配置彼此隔离。
        clean = {k:v for k,v in os.environ.items() if not k.startswith(("CAREER_", "PROFILE_", "PROVIDERS_", "AI_"))}
        return patch.dict(os.environ, {**clean, **values}, clear=True)

    upstream, generated, clients = [], [], {}
    with ExitStack() as stack:
        career_lifespan = stack.enter_context(ExitStack())
        for peer, app in apps.items():
            with environment(peer):
                lifespan = career_lifespan if peer == "career" else stack
                clients[peer] = lifespan.enter_context(TestClient(app))

        def call(peer, method, path, scope, role, *, who=None, **kwargs):
            caller = "admin-gateway" if role == "admin" else "student-gateway"
            with environment(caller):
                headers = service_headers(peer, actor_id=who or (student if role == "student" else "staff"),
                                          school_id="platform" if peer == "providers" else school,
                                          actor_type=role, scopes=[scope])
            with environment(peer):
                return clients[peer].request(method, path, headers=headers, **kwargs)

        def deliver(req, body):
            assert os.environ["SERVICE_ID"] == "career" and "PROVIDERS_DB_ENGINE" not in os.environ
            if req.url.host == "advice.invalid":
                assert str(req.url) == model_url + "/chat/completions" and req.method == "POST"
                assert req.headers["Authorization"] == "Bearer synthetic-secret"
                payload = json.loads(body)
                assert payload["model"] == model_name
                messages = json.dumps(payload["messages"], ensure_ascii=False)
                assert "Python" in messages and all(x not in messages for x in (secret, job_name, student, school, "PRIVATE_JD"))
                generated.append(payload["model"])
                return httpx.Response(200, json={"choices": [{"message": {"content": '{"summary":"测试模型建议"}'}}]})
            peer = {"profile.test":"profile", "providers.test":"providers"}[req.url.host]
            signed = jwt.decode(req.headers["Authorization"].split()[1], public["career"], algorithms=["EdDSA"],
                                issuer="career", audience=peer)
            expected = (("system", "career", "platform", RUNTIME_SCOPE, "/internal/runtime-settings")
                        if peer == "providers" else
                        ("student", student, school, "profile.snapshot.read", "/api/profile/versions/current"))
            assert (signed["actor_type"], signed["sub"], signed["school_id"], *signed["scopes"], req.url.path) == expected
            assert req.method == "GET" and not body and "cookie" not in req.headers
            upstream.append(peer)
            with environment(peer):
                response = clients[peer].send(httpx.Request(req.method, req.url, headers=req.headers, content=body))
            return httpx.Response(response.status_code, headers=response.headers, content=response.content)

        async def async_wire(_transport, request):
            return deliver(request, await request.aread())

        stack.enter_context(patch.object(httpx.AsyncHTTPTransport, "handle_async_request", async_wire))
        stack.enter_context(patch.object(httpx.HTTPTransport, "handle_request", lambda _, req: deliver(req, req.read())))

        control = call("providers", "PATCH", "/settings", "providers.configure", "admin", who="operator",
                       json={"reportCustomBaseUrl":model_url, "reportCustomModel":model_name})
        assert control.status_code == 200, control.text
        publish_catalog(call)
        posting_id = import_posting(call, job_name)
        check_feed_sync(call)
        upload = call("profile", "POST", "/api/profile/resume-upload", "profile.upload", "student",
                      files={"file":("candidate.txt", ("Python SQL\n"+secret).encode())})
        assert upload.status_code == 200 and upload.json()["version"] == 1, upload.text
        match = call("career", "POST", "/v1/job-matches", "match.create", "student", json={"job_posting_id": posting_id})
        assert match.status_code == 201, match.text
        entry = match.json()["job_match"]
        assert (entry["provider"], entry["model"], entry["result"]["profileVersion"], entry["result"]["summary"]) == (
            "custom", model_name, 1, "测试模型建议")
        assert entry["result"]["fallback"] is False and generated == [model_name]
        assert "providers" in upstream and "profile" in upstream

        # 重启所有者后再从正式读接口读取，验证结果已持久化且不能被其他学生查看。
        with environment("career"):
            career_lifespan.close()
            clients["career"] = stack.enter_context(TestClient(career))
        path = "/v1/job-matches/" + entry["id"]
        saved = call("career", "GET", path, "match.read", "student")
        assert saved.status_code == 200 and saved.json()["job_match"] == entry and secret not in saved.text
        assert call("career", "GET", path, "match.read", "student", who="different-student").status_code == 404

        # 收回控制服务地址后，即使有模型密钥和已缓存的结果，也不得退回静态配置或旧库继续生成。
        del career_routes["PROVIDERS_SERVICE_URL"]
        blocked = call("career", "POST", "/v1/job-matches", "match.create", "student", json={"job_posting_id": posting_id})
        assert blocked.status_code == 503 and generated == [model_name]
        history = call("career", "GET", "/v1/job-matches", "match.read", "student").json()["matches"]
        assert [r["id"] for r in history] == [entry["id"]]
        with environment("career"):
            from services.career.store import school_store

            with school_store(school).transaction() as tx:
                row = tx.one("SELECT * FROM job_matches WHERE id=?", (entry["id"],))
            assert row["provider"] == "custom" and row["model"] == model_name
            assert secret not in json.dumps(row, ensure_ascii=False)
        assert opened == set(apps)


if __name__ == "__main__":
    run_case()
