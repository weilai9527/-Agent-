"""验证原生名册的学校隔离、并发更改保护、凭据发放和历史回填。"""
import base64
import json
import os
from io import BytesIO

import pytest
from openpyxl import Workbook, load_workbook

from shared.service_security import service_headers
from shared.account_security import verify_password
from services.identity.test_staff import api
from services.identity.app import app
from services.identity import registrations as book


@pytest.fixture
def office(api, monkeypatch):
    client, _, _ = api
    trust = json.loads(os.environ["SERVICE_TRUST_POLICY"])
    for role in ("admin", "teacher"):
        trust["admin-gateway"]["grants"]["identity"][role] = list(book.ACTIONS)
    monkeypatch.setenv("SERVICE_TRUST_POLICY", json.dumps(trust))
    with app.state.store.transaction(write=True) as tx:
        tx.execute("UPDATE identity_staff SET permissions=?", (json.dumps([*book.ACTIONS, "roster.import"]),))
    def call(method, path="", body=None, scope=book.READ, school="A", role="admin", user="manager"):
        monkeypatch.setenv("SERVICE_ID", "admin-gateway")
        header = service_headers("identity", actor_id=user, actor_type=role, school_id=school, scopes=[scope])
        monkeypatch.setenv("SERVICE_ID", "identity")
        return client.request(method, "/v1/registrations"+path, json=body, headers=header)
    return call


def excel():
    w = Workbook()
    sheet = w.active
    sheet.append(["学号", "姓名", "辅导员"])
    sheet.append(["STU-123", "陈同学", "辅导员甲"])
    file = BytesIO()
    w.save(file)
    return {"filename": "注册.xlsx", "content": base64.b64encode(file.getvalue()).decode()}


def test_sheet_lifecycle_and_audit(office):
    call = office
    assert call("POST", "/import-xlsx", excel(), book.IMPORT).json()["created"] == 1
    assert call("POST", "/import-xlsx", excel(), book.IMPORT).json()["unchanged"] == 1
    assert call("GET", "?state=pending&counselor=辅导员甲").json()["total"] == 1
    assert call("GET", school="B").json()["items"] == []
    assert call("GET", role="teacher", user="reader").status_code == 403
    def batch(op, rev, scope, school="A"):
        return call("POST", "/"+op, {"items":[{"student_no":"STU-123","revision":rev}], **({"reason":"凭据遗失"} if op=="reissue" else {})}, scope, school)
    assert batch("issue", 1, book.ISSUE, "B").status_code == 404
    first = batch("issue", 1, book.ISSUE).json()["handout"][0]["temporary_password"]
    assert batch("issue", 1, book.ISSUE).status_code == 409
    row = call("GET").json()["items"][0]
    uid = row["actor_id"]
    with app.state.store.transaction(write=True) as tx:
        acct = tx.one("SELECT * FROM identity_student_credentials WHERE school_id='A' AND actor_id=?", (uid,))
        assert verify_password(first, acct["password_hash"]) and acct["must_change_password"]
        tx.execute("INSERT INTO identity_student_sessions VALUES ('dummy','A',?,9999999999)", (uid,))
    second = batch("reissue", 2, book.RESET).json()["handout"][0]["temporary_password"]
    assert first != second
    assert batch("archive", 3, book.STATUS).status_code == 200
    assert call("GET", "?state=archived").json()["items"][0]["login_status"] == "normal"
    assert batch("restore", 4, book.STATUS).status_code == 200
    assert batch("revoke", 5, book.STATUS).status_code == 200
    assert call("GET", "?state=pending").json()["items"][0]["actor_id"] == uid
    assert batch("issue", 6, book.ISSUE).status_code == 200
    assert call("GET").json()["items"][0]["actor_id"] == uid
    with app.state.store.transaction() as tx:
        assert tx.one("SELECT 1 FROM identity_student_sessions WHERE actor_id=?", (uid,)) is None
        assert tx.one("SELECT COUNT(*) AS n FROM identity_student_credentials")["n"] == 1
        for table in ("identity_registrations", "identity_audit", "identity_student_credentials"):
            rows = str(tx.all("SELECT * FROM " + table))
            assert first not in rows and second not in rows
    assert call("GET", "/export?q=STU-123", scope=book.READ).status_code == 403
    exported = call("GET", "/export?q=STU-123", scope=book.EXPORT).json()["content"]
    sheet = load_workbook(BytesIO(base64.b64decode(exported)), read_only=True).active
    assert "临时密码" not in next(sheet.values) and next(iter(list(sheet.values)[1])) == "STU-123"


def test_conflicting_batch_rolls_back(office):
    call = office
    rows = [{"name": "甲", "student_no": "NO001"}, {"name": "乙", "student_no": "NO002", "class_id": "no-such-class"}]
    assert call("POST", "/import", {"rows": rows}, book.IMPORT).status_code == 200
    r = call("POST", "/issue", {"items":[{"student_no": r["student_no"], "revision": 1} for r in rows]}, book.ISSUE)
    assert r.status_code == 409
    with app.state.store.transaction() as tx:
        assert tx.one("SELECT 1 FROM identity_student_credentials LIMIT 1") is None
        assert tx.one("SELECT 1 FROM identity_audit WHERE action='registration.issue'") is None
    assert call("GET","?state=pending").json()["total"] == 2
    assert call("POST", "/import", {"rows": [rows[0], rows[0]]}, book.IMPORT).status_code == 422


def test_occupied_organization_cannot_be_retired(tmp_path):
    """停用父级不能隐式撤销或重新激活教师、学生归属。"""
    from services.identity.organization import College, _upsert_node, Program
    from services.identity.app import initialize
    from shared.service_db import ServiceDatabase
    from fastapi import HTTPException
    db = ServiceDatabase.from_env("identity", {"IDENTITY_DB_ENGINE": "sqlite", "IDENTITY_SQLITE_PATH": str(tmp_path/"org.sqlite")})
    initialize(db)
    with db.transaction(write=True) as tx:
        college = College(id="d", name="学院")
        program = Program(id="p", college_id="d", name="专业")
        _upsert_node(tx, "A", "org_colleges", college)
        _upsert_node(tx, "A", "org_programs", program, "college_id")
        with pytest.raises(HTTPException) as denied:
            _upsert_node(tx, "A", "org_colleges", college.model_copy(update={"status":"inactive"}))
        assert denied.value.status_code == 409
        _upsert_node(tx, "A", "org_programs", program.model_copy(update={"status":"inactive"}), "college_id")
        _upsert_node(tx, "A", "org_colleges", college.model_copy(update={"status":"inactive"}))
        assert tx.one("SELECT status FROM org_colleges WHERE id='d'")["status"] == "inactive"


def test_apply_updates_live_account_and_export_is_text_only(office):
    call = office
    row = {"name":"=危险公式","student_no":"NO421","counselor":"陈老师"}
    assert call("POST","/import", {"rows":[row]}, book.IMPORT).status_code == 200
    batch = lambda rev: {"items":[{"student_no":"NO421","revision":rev}]}
    assert call("POST","/issue", batch(1), book.ISSUE).status_code == 200
    updates = {**row,"name":"=修订姓名","student_status":"退学"}
    assert call("POST","/import", {"rows":[updates]}, book.IMPORT).json()["updated"] == 1
    assert call("GET").json()["items"][0]["login_status"] == "normal"
    assert call("POST","/apply",batch(3), book.STATUS).status_code == 200
    result = call("GET","?counselor=陈老师").json()["items"][0]
    assert result["login_status"] == "disabled" and result["name"] == "=修订姓名"
    xlsx = call("GET","/export",scope=book.EXPORT).json()["content"]
    wb = load_workbook(BytesIO(base64.b64decode(xlsx)), read_only=True, data_only=False)
    assert wb.active["B2"].data_type == "s" and wb.active["B2"].value == "=修订姓名"
    wb.close()


def test_workbook_preserves_padded_numbers_and_rejects_formulas():
    from services.identity.registration_workbook import read_rows
    from fastapi import HTTPException
    w = Workbook()
    w.active.append(["学号","姓名"])
    w.active.append([123,"示例"])
    w.active["A2"].number_format = "000000"
    def read():
        buf = BytesIO()
        w.save(buf)
        return read_rows("名单.xlsx",base64.b64encode(buf.getvalue()).decode())
    assert read() == [{"student_no":"000123","name":"示例"}]
    w.active["B2"] = "=1+1"
    with pytest.raises(HTTPException) as invalid: read()
    assert invalid.value.status_code == 422


def test_school_file_import_matches_unique_parent_and_preserves_assignments(office):
    from types import SimpleNamespace
    from fastapi import HTTPException
    from services.identity.organization_workbook import import_workbook
    from services.identity.organization import organization_details

    db = app.state.store
    ctx = {"school_id":"A", "actor_id":"manager", "actor_type":"admin", "caller":"admin-gateway"}
    req = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(store=db)))
    with db.transaction(write=True) as tx:
        tx.execute("UPDATE identity_staff SET permissions=? WHERE school_id='A' AND actor_id='manager'",
                   (json.dumps(["organization.manage"]),))
    w = Workbook()
    classes = w.active
    classes.append(["专业","行政班","班主任"])
    classes.append(["软件","一班","记录姓名"])
    programs = w.create_sheet("专业")
    programs.append(["学院名称","专业名","标准专业代码"])
    programs.append(["计算机学院","软件","123"])
    buf = BytesIO()
    w.save(buf)
    file = book.Workbook(filename="分表.xlsx",content=base64.b64encode(buf.getvalue()).decode())
    assert import_workbook(file,req,ctx) == {"colleges":1,"programs":1,"classes":1}
    assert import_workbook(file,req,ctx) == {"colleges":0,"programs":0,"classes":0}
    csv = "学院,专业,行政班\n另一学院,软件,另一个班\n,软件,名称不唯一\n".encode()
    with pytest.raises(HTTPException) as conflict:
        import_workbook(book.Workbook(filename="组织.csv",content=base64.b64encode(csv).decode()),req,ctx)
    assert conflict.value.status_code==422
    with db.transaction() as tx:
        assert tx.one("SELECT COUNT(*) AS n FROM org_colleges WHERE school_id='A'")=={"n":1}
        assert tx.one("SELECT 1 FROM org_staff_classes") is None
        groups = {"org_classes":tx.all("SELECT id FROM org_classes WHERE school_id='A'")}
        organization_details.attach(tx,"A",groups)
        assert groups["org_classes"][0]["details"]["advisor"]=="记录姓名"
