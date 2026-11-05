"""保留学生端 RTC 地址，在面试服务校验资源归属后仅传递脱敏诊断。"""

from fastapi import Depends, HTTPException, Query, Request
from starlette.concurrency import run_in_threadpool
from shared.service_http import request_json, resource_segment
from .events import rtc_data


def mount(app, authenticate_student, find_owned):
    path = "/api/interviews/{interview_id}/webrtc-events"

    async def owner(request, interview_id):
        actor = request.state.interview_actor
        row = await run_in_threadpool(find_owned, interview_id, actor["actor_id"])
        if (
            not row
            or row["id"] != interview_id
            or row["user_id"] != actor["actor_id"]
            or actor["actor_type"] != "student"
            or actor["caller"] != "student-gateway"
        ):
            raise HTTPException(404, "面试不存在")
        return actor

    @app.get(path, dependencies=[Depends(authenticate_student("interview.diagnostics.read"))])
    async def read(request: Request, interview_id: str, limit: int = Query(200, ge=1, le=500)):
        actor = await owner(request, interview_id)
        return await request_json(
            "operations",
            "GET",
            "/internal/rtc/" + resource_segment(interview_id),
            actor=actor,
            scope="operations.rtc.self",
            params={"limit": limit},
        )

    @app.post(
        path, status_code=201, dependencies=[Depends(authenticate_student("interview.diagnostics.write"))]
    )
    async def append(request: Request, interview_id: str, body: dict):
        actor = await owner(request, interview_id)
        try:
            safe = rtc_data(body, from_trusted_bridge=True)
        except ValueError:
            raise HTTPException(422, "RTC 诊断字段格式无效") from None
        # 只把本场会话的匿名摘要传入日志服务，自由文本及原始会话号止于此处。
        return await request_json(
            "operations",
            "POST",
            "/internal/rtc/" + resource_segment(interview_id),
            actor=actor,
            scope="operations.rtc.append",
            body=safe,
        )
