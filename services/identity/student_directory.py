"""按当前组织范围提供只读学生目录。"""
from fastapi import APIRouter, Depends, Query, Request

from shared.service_security import require_service
from .organization import CLASS_QUERY
from .staff import require_staff

router = APIRouter()

# 当前学籍只匹配本校有效的学院、专业及班级。无有效班级的账号仍可由全校管理员维护。
STUDENT_SOURCE = f"""
    FROM identity_student_credentials s
    LEFT JOIN org_enrollments e ON e.school_id=s.school_id AND e.student_id=s.actor_id AND e.status='active'
    LEFT JOIN ({CLASS_QUERY}) placement ON placement.class_id=e.class_id
    WHERE s.school_id=?
"""


def student_self(tx, actor):
    return tx.one("""SELECT s.actor_id,s.school_id,s.name,s.student_no,s.status,s.must_change_password,
                     placement.college_name AS college""" + STUDENT_SOURCE + " AND s.actor_id=?",
                  (actor["school_id"], actor["school_id"], actor["actor_id"]))


@router.get("/v1/students")
def students(request: Request, q: str = Query("", max_length=128), limit: int = Query(25, ge=1, le=100),
             offset: int = Query(0, ge=0, le=2**31-1), actor=Depends(require_service("identity", "student.read"))):
    school = actor["school_id"]
    with request.app.state.store.transaction() as tx:
        staff = require_staff(tx, actor, "student.read")
        source = STUDENT_SOURCE
        args = (school, school)
        if not (staff["actor_type"] == "admin" and staff["school_wide"] == 1):
            # 统计、搜索、分页使用相同的成员、任课关系与账号状态过滤条件。
            source += """ AND s.status='normal' AND EXISTS (
                SELECT 1 FROM org_staff_classes a WHERE a.school_id=s.school_id
                AND a.staff_id=? AND a.class_id=placement.class_id)"""
            args += (actor["actor_id"],)
        if term := q.strip():
            source += """ AND (INSTR(LOWER(s.name),LOWER(?))>0 OR INSTR(LOWER(s.student_no),LOWER(?))>0
                               OR s.actor_id=?)"""
            args += (term, term, term)
        total = tx.one("SELECT COUNT(*) AS total" + source, args)["total"]
        rows = tx.all("""SELECT s.actor_id,s.student_no,s.name,s.status,s.must_change_password,
                         placement.college_name AS college, placement.program_name AS program,
                         placement.class_id,placement.name AS class_name""" + source +
                      " ORDER BY s.student_no,s.actor_id LIMIT ? OFFSET ?", (*args, limit, offset))
    return {"school_id": school, "items": [{**row, "must_change_password": bool(row["must_change_password"])} for row in rows],
            "total": total, "limit": limit, "offset": offset}
