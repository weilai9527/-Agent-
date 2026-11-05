"""对管理工作台的学院及班级组合先检查当前职员的有效组织范围。"""
from fastapi import HTTPException

from .organization import CLASS_QUERY, _school_wide


def require_visible_filter(tx, actor, account, *, college_id=None, class_id=None):
    if not (college_id or class_id):
        return
    school_wide = _school_wide(account)
    params = [actor["school_id"]]
    if school_wide and not class_id:
        # 全校管理员可选择尚未设班的有效学院，汇总应为空而非拒绝访问。
        query = "SELECT 1 FROM org_colleges WHERE school_id=? AND id=? AND status='active'"
        params.append(college_id)
    else:
        query = CLASS_QUERY
        if not school_wide:
            query += """ AND EXISTS (SELECT 1 FROM org_staff_classes sc
                        WHERE sc.school_id=c.school_id AND sc.class_id=c.id AND sc.staff_id=?)"""
            params.append(actor["actor_id"])
        if college_id:
            query += " AND d.id=?"
            params.append(college_id)
        if class_id:
            query += " AND c.id=?"
            params.append(class_id)
    if not tx.one(query + " LIMIT 1", tuple(params)):
        raise HTTPException(403, "学院或班级不在当前可见范围。")
