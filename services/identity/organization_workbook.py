"""按父级范围导入组织工作簿，保留已有节点编号、任课关系和学籍。"""
import re
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from shared.service_security import require_service
from .organization import SchoolClass, Program, College, _upsert_node, audit, lock_school
from .registration_workbook import read_table
from .registrations import Workbook, manager

router = APIRouter()
COLUMNS = {"college": ("学院", "学院名称", "院系", "所属学院", "college", "collegename"),
           "program": ("专业", "专业名称", "专业名", "major", "program", "majorname"),
           "class_name": ("班级", "班级名称", "行政班", "class", "classname"),
           "code": ("学院编码", "学院代码", "collegecode"), "advisor": ("辅导员", "班主任", "advisor"),
           "invite_code": ("邀请码", "班级邀请码", "invitecode"), "direction": ("培养方向", "direction"),
           "standard_major_code": ("标准专业代码",), "coordinator": ("专业负责人",), "graduation_year": ("毕业年份",)}
HEADERS = {alias:key for key, aliases in COLUMNS.items() for alias in aliases}


def normalize_header(name):
    return re.sub(r"[\s_\-()（）【】\[\]:：/]+", "", name).lower()


def find_or_create(tx, school, table, model, name, details, counts, parent=None, parent_id=None):
    if not name or len(name) > 160:
        raise HTTPException(422, "组织名称为空或过长。")
    query = f"SELECT id,status FROM {table} WHERE school_id=? AND name=?"
    params = (school, name)
    if parent:
        query += f" AND {parent}=?"
        params += (parent_id,)
    found = tx.all(query+" LIMIT 2", params)
    if found:
        if len(found)!=1 or found[0]["status"]!="active":
            raise HTTPException(409, "同级组织重名或已停用，请按编号在组织维护中核对。")
        return found[0]["id"]
    node = model(id=str(uuid4()), name=name, details=details, **({parent:parent_id} if parent else {}))
    _upsert_node(tx, school, table, node, parent)
    counts[table] += 1
    return node.id


@router.post("/v1/organization/import-workbook")
def import_workbook(body: Workbook, request: Request, ctx=Depends(require_service("identity", "organization.manage"))):
    store, school = request.app.state.store, ctx["school_id"]
    with store.transaction() as tx:
        manager(tx, ctx, "organization.manage")
    rows = read_table(body.filename, body.content, HEADERS, set(), all_sheets=True, header_normalizer=normalize_header)
    if not rows:
        raise HTTPException(422, "未读到有效组织数据。")
    counts = dict(org_colleges=0, org_programs=0, org_classes=0)
    # 先学院、再专业、最后班级；分表顺序不影响结果，无法唯一定位上级时整批回滚。
    rows.sort(key=lambda row: 2 if row.get("class_name") else 1 if row.get("program") else 0)
    with store.transaction(write=True) as tx:
        lock_school(tx, store, school)
        manager(tx, ctx, "organization.manage")
        for row in rows:
            program, group = row.get("program"), row.get("class_name")
            if group and not program:
                raise HTTPException(422, "班级行必须填写所属专业。")
            if row.get("college"):
                cid = find_or_create(tx, school, "org_colleges", College, row["college"], {"code":row.get("code","")}, counts)
            elif program:
                parents = tx.all("""SELECT DISTINCT p.college_id FROM org_programs p JOIN org_colleges d
                    ON d.school_id=p.school_id AND d.id=p.college_id AND d.status='active'
                    WHERE p.school_id=? AND p.name=? AND p.status='active' LIMIT 2""", (school, program))
                if len(parents) != 1:
                    raise HTTPException(422, "无法唯一定位所属学院，请补全学院名称。")
                cid = parents[0]["college_id"]
            else:
                raise HTTPException(422, "组织行缺少学院或专业。")
            if program:
                details = {k:row[k] for k in ("direction","coordinator","standard_major_code") if row.get(k)}
                pid = find_or_create(tx, school, "org_programs", Program, program, details, counts, "college_id", cid)
                if group:
                    details = {k:row[k] for k in ("advisor","graduation_year","invite_code") if row.get(k)}
                    find_or_create(tx, school, "org_classes", SchoolClass, group, details, counts, "program_id", pid)
        audit(tx, ctx, "organization.workbook.import", school, summary=str(list(counts.values())))
    return {"colleges": counts["org_colleges"], "programs": counts["org_programs"], "classes": counts["org_classes"]}
