"""资源所属服务在读取或修改学生数据前，实时核验教职工对该学生的权限。"""
import httpx
from fastapi import HTTPException

from .gateway import session_mode
from shared.service_http import service_origin
from shared.service_security import service_headers


def check_student_action(actor, student_id, action):
    if actor["actor_type"] == "student" or session_mode() != "native":
        return
    # 学生标识必须取自实际报告或凭证。禁止使用调用方另行提交的学生编号替代。
    expected = {key: actor[key] for key in ("school_id", "actor_id", "actor_type")}
    expected.update(student_id=student_id, action=action)
    try:
        headers = service_headers("identity", actor_id=actor["actor_id"], school_id=actor["school_id"],
                                  actor_type=actor["actor_type"], scopes=["identity.student.authorize"])
        with httpx.Client(timeout=5, trust_env=False, follow_redirects=False) as client:
            response = client.post(service_origin("identity") + "/internal/staff/authorize-student",
                                   headers=headers, json={"student_id": student_id, "action": action})
        if response.status_code in (403, 404):
            raise HTTPException(403, "Student or action outside current staff grant")
        response.raise_for_status()
        if response.json() != expected:
            raise ValueError("Identity response does not match the requested grant")
    except (KeyError, ValueError, httpx.HTTPError):
        raise HTTPException(503, "Cannot establish current student authorization") from None
