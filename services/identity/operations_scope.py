"""每次检索日志都从身份库读取当前授权与名册，调班后立即收窄可见范围。"""

from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field

from shared.service_security import require_service
from .organization import Input, _school_wide
from .staff import require_staff
from .student_directory import STUDENT_SOURCE

router = APIRouter()
BATCH = 100


class ScopeQuery(Input):
    action: Literal["operations.rtc.read", "operations.audit.read"]
    student_q: str = Field(default="", max_length=128)
    after_student: str = Field(default="", max_length=128)


@router.post("/internal/operations/scope")
def scope(
    body: ScopeQuery,
    request: Request,
    actor=Depends(require_service("identity", "identity.operations.scope")),
):
    if actor["caller"] != "operations" or actor["actor_type"] not in {"teacher", "admin"}:
        raise HTTPException(403, "需要诊断服务委派的教职员身份")
    school = actor["school_id"]
    with request.app.state.store.transaction() as tx:
        staff = require_staff(tx, actor, body.action)
        whole = _school_wide(staff)
        if body.action == "operations.audit.read" and not whole:
            raise HTTPException(403, "安全审计限已授权的全校管理员")
        directory = not whole or bool(body.student_q)
        rows = []
        if directory:
            sql = "SELECT DISTINCT s.actor_id,s.name " + STUDENT_SOURCE + " AND s.status='normal'"
            params = [school, school]
            if not whole:
                sql += """ AND EXISTS (SELECT 1 FROM org_staff_classes a WHERE a.school_id=s.school_id
                           AND a.class_id=placement.class_id AND a.staff_id=?)"""
                params.append(actor["actor_id"])
            if body.student_q:
                sql += " AND (s.actor_id=? OR INSTR(LOWER(s.name),LOWER(?))>0 OR s.student_no=?)"
                params.extend([body.student_q] * 3)
            sql += " AND s.actor_id>? ORDER BY s.actor_id LIMIT ?"
            rows = tx.all(sql, (*params, body.after_student, BATCH + 1))
    return {
        "school_id": school,
        "actor_id": actor["actor_id"],
        "actor_type": actor["actor_type"],
        "action": body.action,
        "all": not directory,
        "students": rows[:BATCH],
        "next": rows[BATCH - 1]["actor_id"] if len(rows) > BATCH else "",
    }
