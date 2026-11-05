"""向下游服务转发已核验的操作者和学校身份。"""

import httpx
from fastapi import HTTPException
from pydantic import ValidationError

from shared.service_http import resource_segment, service_origin
from shared.service_security import service_headers
from .models import Attempt, Roster, VisibleClasses


def call(ctx, service, scope, method, path, body=None):
    url = service_origin(service)
    try:
        headers = service_headers(service, actor_id=ctx["actor_id"], school_id=ctx["school_id"],
                                  actor_type=ctx["actor_type"], scopes=[scope])
        with httpx.Client(timeout=5.0, trust_env=False) as client:
            response = client.request(method, url + path, headers=headers, json=body)
        if response.status_code in (403, 404, 409, 422):
            raise HTTPException(response.status_code, f"{service} declined the request")
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError, KeyError):
        raise HTTPException(503, f"{service} unavailable") from None


def completed_attempt(ctx, attempt_id):
    result = call(ctx, "training", "training.verify", "GET",
                  "/attempts/" + resource_segment(attempt_id))
    try:
        attempt = Attempt.model_validate(result)
    except ValidationError:
        raise HTTPException(502, "Invalid training attempt") from None
    if attempt.attempt_id != attempt_id or attempt.school_id != ctx["school_id"]:
        raise HTTPException(404, "Attempt unavailable")
    if attempt.status != "completed":
        raise HTTPException(409, "Training completion pending")
    if len({q.question_id for q in attempt.questions}) != len(attempt.questions):
        raise HTTPException(502, "Ambiguous training question")
    return attempt


def current_roster(ctx, requested_class=None):
    # 冻结名单只证明发布时的归属。每次查询和下发都重新核验当前师生关系。
    result = call(ctx, "identity", "identity.classes.read", "GET", "/classes")
    try:
        classes = {row.class_id for row in VisibleClasses.model_validate(result).items}
        if requested_class is not None:
            classes.intersection_update([requested_class])
        ids = sorted(classes)
        visible = {}
        for start in range(0, len(ids), 100):
            batch = ids[start:start + 100]
            result = call(ctx, "identity", "identity.roster.read", "POST", "/classes/roster",
                          {"class_ids": batch})
            rows = Roster.model_validate(result).classes
            if len(rows) != len(batch) or {row.class_id for row in rows} != set(batch):
                raise HTTPException(502, "Incomplete identity roster")
            visible.update({row.class_id: set(row.student_ids) for row in rows})
        return visible
    except ValidationError:
        raise HTTPException(502, "Invalid identity roster") from None


def assign(ctx, practice, row):
    return call(ctx, "training", "training.assign", "POST", "/tasks/repractice", {
        "source_attempt_id": practice.attempt_id, "request_id": practice.request_id,
        "question_id": practice.question_id, "prompt": row["question_text"],
        "deadline": practice.deadline.isoformat(),
        "max_attempts": practice.max_attempts,
    })
