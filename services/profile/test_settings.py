"""使用临时学校库、真实签名令牌和模拟的校内服务验证简历选项。"""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import HTTPException
from fastapi.testclient import TestClient

from services.career.migrate import migrate
from services.profile import settings_store
from services.profile.app import app
from shared.service_security import service_headers


ADMIN = "/api/admin/resume-form-settings"
STUDENT = "/api/resume-form/settings"


def college(name, majors=(), *, id=None):
    return {"id": id or name, "name": name, "majors": [{"id": m, "name": m} for m in majors]}


@pytest.fixture
def api(tmp_path, monkeypatch):
    public, private = {}, {}
    for peer in ("gateway", "profile"):
        key = Ed25519PrivateKey.generate()
        private[peer] = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()).decode()
        public[peer] = key.public_key().public_bytes(serialization.Encoding.PEM,
                                                     serialization.PublicFormat.SubjectPublicKeyInfo)
    scopes = ["profile.read","profile.settings.read","profile.settings.write"]
    policy = {"gateway": {"schools":["A","a"], "keys":{"k":public["gateway"].decode()},
                          "grants":{"profile":{role:scopes for role in ("student","teacher","admin")}}}}
    for var, value in {
        "PROFILE_DB_ENGINE":"sqlite", "PROFILE_SQLITE_PATH":str(tmp_path/"profile.sqlite"),
        "IDENTITY_SERVICE_URL":"https://identity.test", "CAREER_SERVICE_URL":"https://career.test",
        "SERVICE_KEY_ID":"k", "SERVICE_TRUST_POLICY":json.dumps(policy),
        "SERVICE_ID":"profile", "SERVICE_SIGNING_KEY":private["profile"],
    }.items():
        monkeypatch.setenv(var, value)
    peers = {"org":[college("计算机学院", ["软件工程","软件工程"]),college("空院", id="org")],
             "catalog":[college("计算机学院", ["目录专业"]),college("空院", ["目录专业"]),college("目录学院",["计算机"])],
             "fault":{}, "calls":[]}

    def dispatch(request):
        if "handle" in peers:
            return peers["handle"](request)
        identity = request.url.host == "identity.test"
        claims = jwt.decode(request.headers["Authorization"].split()[1], public["profile"], algorithms=["EdDSA"],
                            audience="identity" if identity else "career")
        action, = claims["scopes"]
        resource = request.url.path
        school = claims["school_id"]
        assert claims["iss"] == "profile"
        peers["calls"].append((resource, school, claims["sub"], action))
        fault = peers["fault"].get(resource)
        if fault == "disconnect":
            raise httpx.ConnectError("合成测试网络不可用", request=request)
        if fault == "forbidden":
            return httpx.Response(403, json={"detail":"校级管理权限已撤回"})
        if resource.startswith("/internal/staff/resume-form-settings/"):
            assert identity and action == "profile.settings." + resource.rsplit("/", 1)[-1]
            data = {"school_id":school,"actor_id":claims["sub"],"actor_type":claims["actor_type"],"action":action}
        else:
            assert claims["actor_type"] == "student"
            if identity:
                assert (resource,action) == ("/internal/resume-form/organization","organization.options.read")
            else:
                assert (resource,action) == ("/internal/resume-form/catalog","catalog.read")
            data = {"school_id":school, "colleges":peers["org" if identity else "catalog"] if school == "A" else []}
        if fault == "wrong_school":
            data["school_id"] = "OTHER"
        if fault == "bad_schema":
            data["colleges"] = [{"name":"学院"}]
        return httpx.Response(200, json=data)
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw:original(transport=httpx.MockTransport(dispatch), **kw))
    with TestClient(app) as client:
        def call(method, path, action, *, school="A", role="admin", subject="account", **kwargs):
            with monkeypatch.context() as patch:
                patch.setenv("SERVICE_ID","gateway")
                patch.setenv("SERVICE_SIGNING_KEY",private["gateway"])
                header = service_headers("profile", actor_id=subject, actor_type=role, school_id=school, scopes=[action])
            return client.request(method,path,headers=header,**kwargs)
        yield call, peers, app.state.db


def test_settings_are_scoped_and_source_priority_matches_legacy(api):
    call, peers, db = api
    initial = call("GET",ADMIN,"profile.settings.read",role="teacher")
    assert initial.status_code == 200 and initial.json() == {"school_id":"A", "revision":0,"colleges":[]}
    manual = [college("计算机学院",["自定义专业"]),college("目录学院",["重复"]),college("校设",["自设专业"])]
    saved = call("PUT", ADMIN,"profile.settings.write",json={"colleges":manual,"expected_revision":0})
    assert saved.status_code == 200 and saved.json()["revision"]==1
    assert call("GET", ADMIN,"profile.settings.read").json()["colleges"] == manual
    assert call("GET", ADMIN,"profile.settings.read",school="a").json()["revision"] == 0
    result = call("GET", STUDENT,"profile.read",role="student",subject="student-1")
    assert result.json()["colleges"] == [college("计算机学院",["软件工程"]),college("空院",["目录专业"],id="org"),
                                          college("目录学院",["计算机"]),college("校设",["自设专业"])]
    assert call("GET", STUDENT,"profile.read",role="student",school="a").json()=={"colleges":[]}
    assert ("/internal/resume-form/organization","A","student-1","organization.options.read") in peers["calls"]
    for role in ("teacher","student"):
        assert call("PUT",ADMIN,"profile.settings.write",role=role,json={"colleges":[]}).status_code == 403
    assert call("GET",ADMIN,"profile.read",role="student").status_code == 403
    assert call("PUT",ADMIN,"profile.settings.write",json={"colleges":[],"school_id":"a"}).status_code == 400
    assert call("PUT",ADMIN,"profile.settings.write",json={"colleges":[],"expected_revision":0}).status_code == 409
    # 带有效版本的两个并发写入中，只允许先取得行锁的一个提交。
    def write(name):
        try:
            return settings_store.replace(db,"A","admin",[college(name)],expected_revision=1)["revision"]
        except HTTPException as exc:
            return exc.status_code
    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(write,("校一","校二"))) == [2,409]


@pytest.mark.parametrize("url", ["/internal/resume-form/organization","/internal/resume-form/catalog"])
@pytest.mark.parametrize("fault,status", [("disconnect",503),("wrong_school",502),("bad_schema",502)])
def test_unavailable_sources_never_fall_back_to_partial_private_configuration(api,url,fault,status):
    call, peers, _ = api
    call("PUT",ADMIN,"profile.settings.write",json={"colleges":[college("不得在错误响应中回传")]})
    peers["fault"][url]=fault
    response=call("GET",STUDENT,"profile.read",role="student")
    assert response.status_code == status and "不得在错误响应中回传" not in response.text


def test_live_admin_authorization_and_validation(api):
    call, peers, db = api
    path="/internal/staff/resume-form-settings/write"
    for fault, code in (("disconnect",503),("forbidden",403),("wrong_school",403)):
        peers["fault"][path]=fault
        assert call("PUT",ADMIN,"profile.settings.write",json={"colleges":[college("不能提交")]}).status_code == code
        assert settings_store.read(db,"A")["revision"]==0
    peers["fault"].clear()
    for body in ({"colleges":"not-list"},{"colleges":[{"name":"  "}]},{"colleges":[college("x",["y","y"])]},
                 {"colleges":[college("x"),college("x")]},{"colleges":[],"expected_revision":True}):
        assert call("PUT",ADMIN,"profile.settings.write",json=body).status_code==400
    res=call("PUT",ADMIN,"profile.settings.write",json={"colleges":[{"name":" 经管学院 ","majors":[{"name":"会计"}]}]})
    assert res.json()["colleges"]==[college("经管学院",["会计"])]


def test_offline_settings_migration_is_tenant_checked_and_repeatable(tmp_path,monkeypatch):
    source=tmp_path/"old.db"
    target=tmp_path/"settings.db"
    for var,value in {"LEGACY_SOURCE_DB_ENGINE":"sqlite","LEGACY_SOURCE_SQLITE_PATH":str(source),
                      "PROFILE_DB_ENGINE":"sqlite","PROFILE_SQLITE_PATH":str(target),"LEGACY_SCHOOL_ID":"A"}.items():
        monkeypatch.setenv(var,value)
    with closing(sqlite3.connect(source)) as db:
        db.execute("CREATE TABLE resume_form_settings(id TEXT PRIMARY KEY, school_id TEXT, colleges TEXT, updated_at TEXT)")
        db.execute("INSERT INTO resume_form_settings VALUES ('s','a','[]','01')")
        db.commit()
        with pytest.raises(ValueError,match="Mixed"):
            migrate("profile-settings","A")
        assert not target.exists()
        db.execute("UPDATE resume_form_settings SET school_id='A', colleges='invalid JSON'")
        db.commit()
        with pytest.raises(ValueError,match="无效"):
            migrate("profile-settings","A")
        db.execute("UPDATE resume_form_settings SET colleges='[]'")
        rows=[{"name":"旧院","id":1,"majors":[{"id":10,"name":"旧专业"}]}]
        db.execute("INSERT INTO resume_form_settings VALUES ('t','A',?,'02')",(json.dumps(rows),))
        db.commit()
    assert migrate("profile-settings","A")=={"form_settings":"imported"}
    assert migrate("profile-settings","A")=={"form_settings":"already_present"}
    from shared.service_db import ServiceDatabase
    store=ServiceDatabase.from_env("profile")
    expected=[{"id":"1","name":"旧院","majors":[{"id":"10","name":"旧专业"}]}]
    assert settings_store.read(store,"A")["colleges"]==expected
    settings_store.replace(store,"A","updated-by",[])
    assert migrate("profile-settings","A")=={"form_settings":"already_present"}
    assert settings_store.read(store,"A")["colleges"]==[]


def test_real_identity_and_career_endpoints_recheck_staff_and_student(api, tmp_path, monkeypatch):
    """仅替换网络传输；接收方实际验签，并从各自临时库核验账号、授权和选项。"""
    import os
    from contextlib import ExitStack
    from unittest.mock import patch
    from services.career.app import app as career
    from services.identity.app import app as identity

    call, peers, _ = api
    signing = serialization.load_pem_private_key(os.environ["SERVICE_SIGNING_KEY"].encode(),password=None)
    public = signing.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    policy = json.loads(os.environ["SERVICE_TRUST_POLICY"])
    policy["profile"] = {"schools":["A","a"],"keys":{"k":public.decode()}, "grants":{
        "career":{"student":["catalog.read"]},
        "identity":{"student":["organization.options.read"],"admin":["profile.settings.read","profile.settings.write"]}}}
    monkeypatch.setenv("SERVICE_TRUST_POLICY",json.dumps(policy))
    monkeypatch.setenv("IDENTITY_DB_ENGINE","sqlite")
    monkeypatch.setenv("IDENTITY_SQLITE_PATH",str(tmp_path/"identity.sqlite"))
    monkeypatch.setenv("CAREER_DB_ENGINE","sqlite")
    monkeypatch.setenv("CAREER_SCHOOL_DATABASES",json.dumps({"A":str(tmp_path/"upper.sqlite"),"a":str(tmp_path/"lower.sqlite")}))
    with ExitStack() as stack:
        clients = {name:stack.enter_context(TestClient(app)) for name,app in (("identity",identity),("career",career))}
        def peer_request(request):
            service = request.url.host.split(".")[0]
            with patch.dict(os.environ,SERVICE_ID=service):
                reply = clients[service].get(request.url.path, headers={"Authorization":request.headers["Authorization"]})
            return httpx.Response(reply.status_code, json=reply.json())
        peers["handle"] = peer_request
        with identity.state.store.transaction(write=True) as tx:
            for school, name in (("A","活动校院"),("a","外校院系")):
                tx.execute("""INSERT INTO identity_student_credentials
                    (school_id,actor_id,student_no,name,password_hash,status,must_change_password)
                    VALUES (?,'s','number','合成学生','unused','normal',0)""",(school,))
                tx.execute("INSERT INTO org_colleges VALUES (?,'c',?,'active')",(school,name))
                tx.execute("INSERT INTO org_programs VALUES (?,'p','c','院内专业','active')",(school,))
                tx.execute("INSERT INTO org_programs VALUES (?,'off','c','已停专业','inactive')",(school,))
            tx.execute("""INSERT INTO identity_staff
                (school_id,actor_id,email,password_hash,name,actor_type,status,permissions,school_wide)
                VALUES ('A','account','test@example.test','unused','合成管理员','admin','normal',?,1)""",
                (json.dumps(["profile.settings.write"]),))
        manual=[college("管理员补充",["自定义专业"])]
        assert call("PUT",ADMIN,"profile.settings.write",json={"colleges":manual}).status_code==200
        assert call("GET",ADMIN,"profile.settings.read").json()["colleges"]==manual
        res=call("GET",STUDENT,"profile.read",role="student",subject="s")
        assert res.status_code==200, res.text
        by_name={item["name"]:item for item in res.json()["colleges"]}
        assert "管理员补充" in by_name and "计算机学院" in by_name and "外校院系" not in by_name
        assert by_name["活动校院"]["majors"]==[{"id":"p","name":"院内专业"}]
        other=call("GET",STUDENT,"profile.read",role="student",subject="s",school="a")
        assert "外校院系" in other.text and "管理员补充" not in other.text and "活动校院" not in other.text
        with identity.state.store.transaction(write=True) as tx:
            tx.execute("UPDATE identity_staff SET school_wide=0 WHERE school_id='A' AND actor_id='account'")
            tx.execute("UPDATE identity_student_credentials SET status='disabled' WHERE school_id='A' AND actor_id='s'")
        assert call("PUT",ADMIN,"profile.settings.write",json={"colleges":[]}).status_code==403
        assert call("GET",STUDENT,"profile.read",role="student",subject="s").status_code==403
