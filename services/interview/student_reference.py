"""使用旧单校库的外键前，先向身份服务核验学生当前的归属和访问资格。"""


from fastapi import HTTPException

from services.identity.permissions import legacy_school_id
from shared.service_http import request_json


async def resolve_student(actor):
    school = legacy_school_id()
    if actor["school_id"] != school or actor["actor_type"] != "student":
        raise HTTPException(403, "Student outside this school's boundary")
    account = await request_json("identity", "GET", "/internal/students/me", actor=actor,
                                 scope="identity.student.read")
    if (not isinstance(account, dict) or account.get("actor_id") != actor["actor_id"]
            or account.get("school_id") != school or account.get("status") != "normal"
            or account.get("must_change_password") is not False or not isinstance(account.get("name"), str)
            or not 0 < len(account["name"]) <= 120):
        raise HTTPException(403, "Identity could not verify this student")
    if len(actor["actor_id"]) > 36:
        raise HTTPException(409,"学生编号超过面试记录支持的长度。")
    return {"id": actor["actor_id"], "name": account["name"], "_native": True}
