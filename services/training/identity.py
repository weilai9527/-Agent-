"""训练服务使用已验证凭据中的教师和学校身份查询名册。"""

import httpx
from fastapi import HTTPException

from shared.service_http import service_origin
from shared.service_security import service_headers


def _request(ctx, method, path, scope, body=None):
    url = service_origin("identity")
    try:
        headers = service_headers("identity", actor_id=ctx["actor_id"], school_id=ctx["school_id"],
                                  actor_type=ctx["actor_type"], scopes=[scope])
        with httpx.Client(timeout=5, trust_env=False) as client:
            response = client.request(method, url + path, json=body, headers=headers)
        if response.status_code in (403, 404):
            raise HTTPException(403, "Class outside current teaching scope")
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, KeyError, ValueError):
        raise HTTPException(503, "Identity service unavailable") from None


def identifier(value):
    return isinstance(value, str) and 0 < len(value) <= 128 and all(
        not c.isspace() and ord(c) >= 32 for c in value
    )


def classes(ctx):
    response = _request(ctx, "GET", "/classes", "identity.classes.read")
    try:
        rows = response["items"]
        if not isinstance(rows, list) or not all(identifier(row["class_id"]) and isinstance(row["name"], str) for row in rows):
            raise ValueError()
        return [{"class_id": row["class_id"], "name": row["name"]} for row in rows]
    except (KeyError, TypeError, ValueError):
        raise HTTPException(503, "Invalid identity class list") from None


def roster(ctx, class_ids):
    response = _request(ctx, "POST", "/classes/roster", "identity.roster.read", {"class_ids": class_ids})
    try:
        rows = response["classes"]
        result = {row["class_id"]: row["student_ids"] for row in rows}
        # 若身份服务遗漏目标班级，应拒绝发布，避免教师误以为所有目标班都已布置。
        if set(result) != set(class_ids) or len(rows) != len(result):
            raise ValueError()
        if any(not isinstance(ids, list) or not all(identifier(s) for s in ids) for ids in result.values()):
            raise ValueError()
        return result
    except (KeyError, TypeError, ValueError):
        raise HTTPException(503, "Incomplete identity roster") from None
