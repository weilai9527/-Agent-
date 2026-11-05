"""按当前教职工的实时可见范围分页读取学生目录。"""

from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field

from shared.service_security import require_service
from .dashboard_scope import require_visible_filter
from .organization import Identifier, Input, _school_wide
from .staff import require_staff
from .student_directory import STUDENT_SOURCE

router = APIRouter()
ACTIONS = {"interview": "interview.records.read", "assessment": "report.read"}
BATCH = 100


class RecordScope(Input):
    purpose: Literal["records", "templates", "template_usage"] = "records"
    check_only: bool = Field(default=False, strict=True)
    class_name: str | None = Field(default=None, min_length=1, max_length=160)
    q: str | None = Field(default=None, min_length=1, max_length=128)
    after_student: Identifier | None = None
    include_start: bool = Field(default=False, strict=True)
    student_ids: list[Identifier] | None = Field(default=None, min_length=1, max_length=20)
    student_id: Identifier | None = None
    class_id: Identifier | None = None
    college_id: Identifier | None = None


@router.post("/internal/staff/record-students")
def record_students(
    body: RecordScope, request: Request, ctx=Depends(require_service("identity", "identity.records.scope"))
):
    action = ACTIONS.get(ctx["caller"])
    if body.student_ids is not None and body.purpose != "template_usage":
        raise HTTPException(422, "批量学生查询仅用于已授权的模板使用明细")
    if body.purpose != "records":
        if ctx["caller"] != "interview":
            raise HTTPException(403, "面试官模板仅由面试服务查询")
        action = "interview.templates.read"
    if not action:
        raise HTTPException(403, "Record owner required")
    school, actor = ctx["school_id"], ctx["actor_id"]
    with request.app.state.store.transaction() as tx:
        account = require_staff(tx, ctx, action)
        if body.purpose == "template_usage":
            # 仅有模板汇总权限的人员不能看使用明细，网关的可见菜单不能代替此检查。
            require_staff(tx, ctx, "interview.records.read")
        whole = (
            body.purpose != "records"
            and _school_wide(account)
            and not any(
                (body.q, body.class_id, body.college_id, body.class_name, body.student_id, body.student_ids)
            )
        )
        require_visible_filter(tx, ctx, account, college_id=body.college_id, class_id=body.class_id)
        query = (
            """SELECT s.actor_id AS student_id,s.name,s.student_no,
            placement.class_id,placement.name AS class_name,placement.college_id,placement.college_name
            """
            + STUDENT_SOURCE
            + " AND s.status='normal'"
        )
        params = [school, school]
        if not _school_wide(account):
            query += """ AND EXISTS (SELECT 1 FROM org_staff_classes a WHERE
                a.school_id=s.school_id AND a.class_id=placement.class_id AND a.staff_id=?)"""
            params.append(actor)
        if body.class_id:
            query += " AND placement.class_id=?"
            params.append(body.class_id)
        if body.college_id:
            query += " AND placement.college_id=?"
            params.append(body.college_id)
        if body.class_name:
            query += " AND INSTR(LOWER(placement.name),LOWER(?))>0"
            params.append(body.class_name)
        if body.q:
            query += " AND (INSTR(LOWER(s.name),LOWER(?))>0 OR INSTR(LOWER(s.student_no),LOWER(?))>0)"
            params.extend((body.q, body.q))
        if body.student_id:
            query += " AND s.actor_id=?"
            params.append(body.student_id)
        if body.student_ids:
            query += " AND s.actor_id IN (" + ",".join("?" for _ in body.student_ids) + ")"
            params.extend(body.student_ids)
        if body.after_student:
            query += " AND s.actor_id " + (">=" if body.include_start else ">") + " ?"
            params.append(body.after_student)
        rows = (
            []
            if body.check_only or whole
            else tx.all(query + " ORDER BY s.actor_id LIMIT ?", (*params, BATCH + 1))
        )
    return {
        **({"purpose": body.purpose, "whole": whole} if body.purpose != "records" else {}),
        "school_id": school,
        "actor_id": actor,
        "actor_type": ctx["actor_type"],
        "action": action,
        "items": rows[:BATCH],
        "has_more": len(rows) > BATCH,
    }
