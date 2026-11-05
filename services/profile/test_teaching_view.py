"""验证逐学生核权、教学摘要和访问审计。下游只使用测试传输。"""
import json
import os
from contextlib import closing
import sqlite3

import httpx
import pytest

from services.profile import store
from services.profile.test_settings import api


@pytest.fixture
def view(api, monkeypatch):
    call, peers, db = api
    action = "profile.student.read"
    trust = json.loads(os.environ["SERVICE_TRUST_POLICY"])
    for scopes in trust["gateway"]["grants"]["profile"].values():
        scopes.append(action)
    monkeypatch.setenv("SERVICE_TRUST_POLICY",json.dumps(trust))
    state = {"outcome":"allowed","checked":[]}
    def verify(req):
        body = json.loads(req.content)
        assert req.method=="POST" and req.url.path=="/internal/staff/authorize-student"
        assert body["action"]==action and set(body)=={"action","student_id"}
        state["checked"].append(body["student_id"])
        if state["outcome"]=="unavailable":
            raise httpx.ConnectError("模拟身份服务断网")
        if state["outcome"]=="denied":
            return httpx.Response(403)
        response={"school_id":"A","actor_type":"teacher","actor_id":"account",**body}
        if state["outcome"]=="wrong_subject":
            response["student_id"]="different"
        return httpx.Response(200,json=response)
    peers["handle"]=verify
    def staff(student="s", school="A", role="teacher"):
        return call("GET",f"/v1/admin/students/{student}/profile",action,school=school,role=role)
    return staff,db,state


def audit(db):
    with db.transaction() as tx:
        return tx.all("SELECT school_id,actor_id,actor_type,student_id,version,result FROM profile_access_audit")


def test_teaching_returns_real_current_responsibility_but_no_contacts_or_full_resume(view):
    staff,db,state = view
    old="负责维护未公开旧简历项目"
    store.save(db,("A","s"),"form",{"resume_text":old})
    source="""姓名：合成同学；身份证：110101200001018888；学号 STU-1234567
    住址：汇合路19号；邮箱 synth@example.test；联系方式 138-1111-2233
    本科，具备 3 年开发经验。
    负责开发网关重试机制并减少重复支付。作品链接：https://hidden.invalid/id
    """
    store.save(db,("A","s"),"form",{"nickname":"课堂别名","target_role":"支付平台后端工程师","skills":"Python SQL",
               "project_experience":"合成同学主导订单幂等处理，优化 SQL 索引；联系人 合成同学。",
               "resume_text":source,"resume_filename":"marked-private-file.pdf", "portfolio_links":"https://secret.invalid",
               "avatar_url":"https://avatar.invalid"},form={"certificates":"秘密证书"})
    response=staff()
    assert response.status_code==200 and response.headers["cache-control"]=="private, no-store"
    payload=response.json()
    assert set(payload)=={"school_id","student_id","version","profile"} and payload["version"]==2
    export=payload["profile"]
    assert set(export)=={"target_role","skills","education_level","project_experience","resume_summary"}
    assert all(isinstance(v,str) for v in export.values())
    assert "后端工程师" in export["target_role"] and "Python" in export["skills"]
    assert "本科" in export["education_level"] and "3 年" in export["resume_summary"]
    assert "订单幂等处理" in export["project_experience"] and "减少重复支付" in export["project_experience"]
    for private in (old,"合成同学","课堂别名","110101200001018888","STU-1234567","汇合路19号","synth@example.test",
                    "138-1111-2233","hidden.invalid","marked-private-file","secret.invalid","avatar.invalid","秘密证书"):
        assert private not in response.text
    assert state["checked"]==["s"]
    assert audit(db)==[{"school_id":"A","actor_type":"teacher","actor_id":"account","student_id":"s","version":2,"result":"allowed"}]


def test_denied_or_unverifiable_teaching_view_never_reads_profile(view, monkeypatch):
    staff,db,state=view
    def forbidden(*args):
        raise AssertionError("核权失败时读取了简历")
    monkeypatch.setattr(store,"snapshot",forbidden)
    for outcome,status in (("denied",403),("unavailable",503),("wrong_subject",403)):
        state["outcome"]=outcome
        assert staff().status_code==status
    state["outcome"]="allowed"
    # 同一主体和目标，错误学校的回执也必须拒绝。
    assert staff(school="a").status_code==403
    assert staff(role="student").status_code==403
    assert len(state["checked"])==4
    assert [row["result"] for row in audit(db)]==["denied","unavailable","denied","denied","denied"]
    assert all(row["version"] is None for row in audit(db))


def test_missing_and_uncommitted_audit_cannot_release_teaching_view(view):
    staff,db,_=view
    assert staff().status_code==404
    assert audit(db)[0]["result"]=="not_found"
    store.save(db,("A","s"),"form",{"resume_text":"负责实现内部计费系统"})
    # 用数据库故障验证审计和读取被视为同一操作。
    with closing(sqlite3.connect(db._path)) as conn:
        conn.execute("""CREATE TRIGGER never_audit BEFORE INSERT ON profile_access_audit
                        BEGIN SELECT RAISE(ABORT,'模拟审计写入失败'); END""")
        conn.commit()
    response=staff()
    assert response.status_code==503 and "计费系统" not in response.text and len(audit(db))==1


@pytest.mark.parametrize("role,skills", [
    ("护士", "伤口评估、慢病随访"), ("编辑", "选题策划、稿件审校"), ("律师", "诉讼检索、合同审查"),
    ("翻译", "中德交替传译"), ("产品策划", "竞品研究"), ("数据科学家", "生存分析、贝叶斯建模"),
])
def test_teaching_preserves_structured_fields_across_professions(view,role,skills):
    staff,db,_=view
    store.save(db,("A","s"),"form",{
        "nickname":"示例姓名","target_role":role+"；手机：13611119999","skills":skills+"；联系地址：样本路16号",
        "education_level":"法学硕士","years_of_experience":"2年",
        "project_experience":"负责制定跨校调研提纲，覆盖40家门店，协调排期。https://example.invalid/secret",
    })
    response=staff()
    assert response.status_code==200 and response.headers["cache-control"]=="private, no-store"
    data=response.json()["profile"]
    assert data["target_role"]==role and data["skills"]==skills
    assert data["education_level"]=="法学硕士" and "2年" in data["resume_summary"]
    assert "制定跨校调研提纲" in data["project_experience"] and "覆盖40家门店" in data["resume_summary"]
    assert not any(term in response.text for term in ("1361111","样本路","example.invalid","示例姓名"))
