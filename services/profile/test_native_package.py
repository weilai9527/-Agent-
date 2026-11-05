"""仅安装 services/shared 的简历业务验收。所有 HTTP 调用都经真实接收方或供应商模拟传输。"""


def test_profile_package_without_monoliths(tmp_path):
    from services.profile.test_standalone import run_native_package

    run_native_package(tmp_path, __file__)


def selectable_pdf(text):
    import io
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                             NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("ascii"))
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def run_case():
    import json
    import os
    import sys
    from contextlib import ExitStack
    from pathlib import Path
    from unittest.mock import patch

    import httpx
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from fastapi.testclient import TestClient
    from services.career.app import app as career
    from services.identity.app import app as identity
    from services.profile.app import app as profile
    from services.providers.app import app as providers
    from shared.service_security import service_headers

    package = Path.cwd()
    app_cwd = package/"other-working-directory"
    app_cwd.mkdir()
    os.chdir(app_cwd)
    workers = []

    def record_parser(event, args):
        if event == "subprocess.Popen" and isinstance(args[1], list) and "services.profile.parser" in args[1]:
            assert Path(args[2]).resolve() == package
            assert not ({"SERVICE_SIGNING_KEY", "AI_API_KEY", "PYTHONPATH"} & set(args[3]))
            workers.append(args[1][-1])

    sys.addaudithook(record_parser)
    # 模拟 --app-dir 加载后进程的 cwd 并不包含包根目录，真实 PDF 子进程也必须可以独立导入解析器。
    admin = "fixture-operator"
    schools = ["A", "B"]
    grants = {
        "gateway": {
            "profile":{"student":["profile.read","profile.write","profile.upload","profile.analyze","profile.versions.read"],
                       "teacher":["profile.student.read"]},
            "providers":{"admin":["providers.configure"]},
        },
        "profile": {
            "identity":{"teacher":["identity.student.authorize"],"student":["organization.options.read"]},
            "career":{"student":["catalog.read"]}, "providers":{"system":["providers.runtime.read"]},
        },
    }
    keys = {name:Ed25519PrivateKey.generate() for name in ("gateway","profile","career","identity","providers")}
    private = {name:key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption()).decode() for name,key in keys.items()}
    policy = {name:{"schools":[*schools,"platform"], "keys":{"k":keys[name].public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()}, "grants":scopes}
        for name,scopes in grants.items()}
    os.environ.update({
        "APP_ENV":"test", "IDENTITY_SESSION_MODE":"native", "ASSESSMENT_STORAGE_MODE":"isolated",
        "SERVICE_KEY_ID":"k","SERVICE_ID":"profile","SERVICE_SIGNING_KEY":private["profile"],
        "SERVICE_TRUST_POLICY":json.dumps(policy), "PROFILE_DB_ENGINE":"sqlite",
        "PROFILE_SQLITE_PATH":str(app_cwd/"profile.sqlite"), "IDENTITY_DB_ENGINE":"sqlite",
        "IDENTITY_SQLITE_PATH":str(app_cwd/"identity.sqlite"), "CAREER_DB_ENGINE":"sqlite",
        "CAREER_SCHOOL_DATABASES":json.dumps({s:str(app_cwd/(s+".sqlite")) for s in schools}),
        "IDENTITY_SERVICE_URL":"https://identity.test","CAREER_SERVICE_URL":"https://career.test",
        "PROVIDERS_SERVICE_URL":"https://providers.test","PROVIDER_PLATFORM_ADMIN_IDS":admin,
        "PROFILE_MODEL_BY_SCHOOL":'{"A":"custom"}', "AI_API_KEY":"synthetic-token",
        # 必须通过控制服务取得允许的模型和 URL；以下环境值故意无效。
        "AI_MODEL":"wrong", "AI_BASE_URL":"https://forbidden.invalid",
        "PROVIDER_ALLOWED_CUSTOM_ENDPOINTS":"https://model.test/v1",
    })
    envs = {name:{"SERVICE_ID":name,"SERVICE_SIGNING_KEY":key} for name,key in private.items()}
    envs["providers"].update(PROVIDERS_DB_ENGINE="sqlite", PROVIDERS_SQLITE_PATH=str(app_cwd/"providers.sqlite"))
    apps = {"profile":profile,"identity":identity,"career":career,"providers":providers}
    wire, routes = [], []
    with ExitStack() as stack:
        clients = {}
        for name, app in apps.items():
            with patch.dict(os.environ,envs[name]):
                clients[name]=stack.enter_context(TestClient(app))

        def request(service, method, path, scope, school="A", user="s", role="student", **kwargs):
            with patch.dict(os.environ,envs["gateway"]):
                headers=service_headers(service, actor_id=user, actor_type=role, school_id=school, scopes=[scope])
            with patch.dict(os.environ,envs[service]):
                return clients[service].request(method,path,headers=headers,**kwargs)

        def transport(req, content):
            service = req.url.host.split(".")[0]
            if service == "controller-offline":
                raise httpx.ConnectError("合成控制服务不可用", request=req)
            if service=="model":
                assert req.url.path=="/v1/chat/completions" and req.headers["Authorization"]=="Bearer synthetic-token"
                payload = json.loads(content)
                assert payload["model"]=="configured-remotely"
                wire.append(json.dumps(payload,ensure_ascii=False))
                reply={"candidate_summary":"基于已观察技能的合成分析","recommended_directions":[{"name":"后端开发","score":84}]}
                return httpx.Response(200,json={"choices":[{"message":{"content":json.dumps(reply)}}]})
            assert service in {"identity","career","providers"}
            routes.append((service,req.url.path))
            with patch.dict(os.environ,envs[service]):
                resp=clients[service].request(req.method,req.url.path,headers=req.headers,content=content)
            return httpx.Response(resp.status_code,headers=resp.headers,content=resp.content)

        def sync(_transport,req):
            return transport(req,req.read())
        async def async_dispatch(_transport,req):
            return transport(req,await req.aread())
        stack.enter_context(patch.object(httpx.HTTPTransport,"handle_request",sync))
        stack.enter_context(patch.object(httpx.AsyncHTTPTransport,"handle_async_request",async_dispatch))

        reply=request("providers","PATCH","/settings","providers.configure","platform",admin,"admin",json={
            "reportCustomModel":"configured-remotely","reportCustomBaseUrl":"https://model.test/v1"})
        assert reply.status_code==200,reply.text
        with identity.state.store.transaction(write=True) as tx:
            for school in schools:
                tx.execute("""INSERT INTO identity_student_credentials
                    (school_id,actor_id,student_no,name,password_hash,status,must_change_password)
                    VALUES (?,'s','number','合成学生','unused','normal',0)""",(school,))
                tx.execute("INSERT INTO org_colleges VALUES (?,'c',?,'active')",(school,"组织学院"+school))
                tx.execute("INSERT INTO org_programs VALUES (?,'p','c','组织专业','active')",(school,))
                tx.execute("INSERT INTO org_classes VALUES (?,'k','p','甲班','active')",(school,))
                tx.execute("INSERT INTO org_enrollments VALUES (?,'s','k','active')",(school,))
            tx.execute("""INSERT INTO identity_staff
                (school_id,actor_id,email,password_hash,name,actor_type,status,permissions,school_wide)
                VALUES ('A','t','fixture@example.test','unused','教师','teacher','normal',?,0)""",
                       (json.dumps(["profile.student.read"]),))
            tx.execute("INSERT INTO org_staff_classes VALUES ('A','t','k')")
        for school in schools:
            before=len(wire)
            def profile_request(method,path,scope,**kwargs):
                return request("profile",method,path,scope,school=school,**kwargs)

            options=profile_request("GET","/api/resume-form/settings","profile.read")
            assert options.status_code==200 and "组织学院"+school in options.text
            saved=profile_request("PUT","/api/resume-form","profile.write",
                                  json={"college":"组织学院"+school,"skills":"Python","projects":"主导馆藏索引重建"})
            assert saved.status_code==200 and saved.json()["version"]==1
            content="Python Flask project with SQL private-canary-792 person@example.test"
            for suffix, data in (("txt",content.encode()),("pdf",selectable_pdf(content))):
                upload=profile_request("POST","/api/profile/resume-upload","profile.upload",
                                       files={"file":("fixture."+suffix,data)})
                assert upload.status_code==200,upload.text
                assert upload.json()["filename"]=="fixture."+suffix and content in upload.json()["text"]
            analysis=profile_request("POST","/api/profile/resume-analysis","profile.analyze").json()["resume_analysis"]
            assert (analysis["provider"],analysis["fallback"])==(("custom",False) if school=="A" else ("local",False))
            assert len(wire)-before==(1 if school=="A" else 0)
            if school=="A":
                assert analysis["model"]=="configured-remotely" and "Python" in wire[0]
                assert "private-canary" not in wire[0] and "person@" not in wire[0] and "fixture.pdf" not in wire[0]
            # 相同版本和策略的成功结果可复用，不能在缓存命中时重复出站。
            assert profile_request("POST","/api/profile/resume-analysis","profile.analyze").status_code==200
            assert len(wire)-before==(1 if school=="A" else 0)
        assert workers == ["pdf", "pdf"]
        # 控制面失联并且没有可复用的配置快照时，即使存在静态密钥也不允许外部生成。
        # 使用不同的控制服务地址触发独立缓存槽，不改控制服务或模型策略代码。
        with patch.dict(os.environ,PROVIDERS_SERVICE_URL="https://controller-offline.test"):
            failed=request("profile","POST","/api/profile/resume-analysis","profile.analyze",json={"force":True})
            assert failed.status_code==503 and len(wire)==1
            history=request("profile","GET","/api/profile/resume-analysis","profile.read")
            assert history.status_code==200 and history.json()["stale"] and history.json()["resume_analysis"]["provider"]=="custom"
        teaching=request("profile","GET","/v1/admin/students/s/profile","profile.student.read",user="t",role="teacher")
        assert teaching.status_code==200,teaching.text
        data=teaching.json()
        assert data["school_id"]=="A" and data["version"]==3 and "主导馆藏索引重建" in data["profile"]["project_experience"]
        assert "private-canary" not in teaching.text and "fixture.pdf" not in teaching.text
        with identity.state.store.transaction(write=True) as tx:
            tx.execute("DELETE FROM org_staff_classes WHERE school_id='A' AND staff_id='t'")
        assert request("profile","GET","/v1/admin/students/s/profile","profile.student.read",user="t",role="teacher").status_code==403
        assert ("providers","/internal/runtime-settings") in routes and ("identity","/internal/staff/authorize-student") in routes


if __name__ == "__main__":
    run_case()
