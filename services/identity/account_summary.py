"""按当前登录学校和教职员的有效班级范围统计原生学生账号。"""

from fastapi import APIRouter, Depends, HTTPException, Request

from shared.service_security import require_service
from . import registrations
from .dashboard_scope import require_visible_filter
from .organization import Identifier, _school_wide
from .staff import require_staff
from .student_directory import STUDENT_SOURCE

router = APIRouter()


@router.get("/v1/student-accounts/summary")
def account_summary(request: Request, college_id: Identifier | None = None, class_id: Identifier | None = None,
                    ctx=Depends(require_service("identity", "student.read"))):
    school = ctx["school_id"]
    with request.app.state.store.transaction() as tx:
        # 服务凭据只授权调用。账号状态、动作和当前班级关系必须在本校名册中重新核验。
        staff = require_staff(tx, ctx, "student.read")
        require_visible_filter(tx, ctx, staff, college_id=college_id, class_id=class_id)
        whole_school = _school_wide(staff)
        source = STUDENT_SOURCE
        params = [school, school]
        if not whole_school:
            source += """ AND s.status='normal' AND EXISTS (
                SELECT 1 FROM org_staff_classes a WHERE a.school_id=s.school_id
                AND a.staff_id=? AND a.class_id=placement.class_id)"""
            params.append(ctx["actor_id"])
        # 过滤条件进一步缩小已授权的集合；重名学院以及外校同 ID 均不参与匹配。
        if college_id:
            source += " AND placement.college_id=?"
            params.append(college_id)
        if class_id:
            source += " AND placement.class_id=?"
            params.append(class_id)
        counts = tx.one("""SELECT COUNT(*) AS accounts,
                      COUNT(CASE WHEN s.status='normal' THEN 1 END) AS normal_accounts,
                      COUNT(CASE WHEN s.status<>'normal' THEN 1 END) AS disabled_accounts,
                      COUNT(CASE WHEN s.status='normal' AND s.must_change_password=1 THEN 1 END) AS must_change_password,
                      COUNT(CASE WHEN s.status='normal' AND placement.class_id IS NULL THEN 1 END) AS unassigned_normal_accounts,
                      COUNT(placement.class_id) AS assigned_accounts""" + source, tuple(params))
    # 首次改密和管理员重置后的改密均计入待改密；这些都是已经开通的账号。
    return {"school_id": school, "scope": "school" if whole_school else "classes",
            **counts, "unassigned_accounts": counts["accounts"] - counts["assigned_accounts"]}


async def whole_queue_only(request: Request):
    if request.query_params:
        raise HTTPException(422, "待开通摘要按本校全校统计，不支持筛选。")
    async for block in request.stream():
        if block:
            raise HTTPException(422, "读取待开通摘要不接受请求正文。")


@router.get("/v1/student-accounts/pending-summary")
def pending_summary(request: Request, ctx=Depends(require_service("identity", registrations.READ)),
                    _=Depends(whole_queue_only)):
    school = ctx["school_id"]
    with request.app.state.store.transaction() as tx:
        registrations.manager(tx, ctx, registrations.READ)
        # 被撤销开户的登记也回到待办理状态。资格校验属于实际开户动作；
        # 登录账号停用、待改密和历史归档均不能替代登记表的当前状态。
        source = " FROM identity_registrations WHERE school_id=? AND archived=0 AND opened=0"
        count = tx.one("SELECT COUNT(*) AS n" + source, (school,))["n"]
        items = tx.all("SELECT name,student_no" + source + " ORDER BY student_no LIMIT 5", (school,))
    return {"school_id": school, "pending_accounts": count, "items": items}
