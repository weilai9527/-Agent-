"""学生媒体入口。语音连接、发布视频和逐题片段均使用面试服务持有的回合状态。"""
from fastapi import APIRouter, FastAPI, HTTPException, Request, Response, WebSocket
from starlette.concurrency import run_in_threadpool

from services.identity.gateway import resolve_native
from services.media.gateway import browser_router
from services.media.gateway_socket import relay_with_context
from shared.service_http import request_json, resource_segment
from .routes import read_json_object
from services.operations.events import rtc_data


async def sync_native_context(request, interview_id, scope):
    actor = await run_in_threadpool(resolve_native, request, scope, "student")
    path = "/interviews/" + resource_segment(interview_id)
    # 每次启动媒体操作都用当前会话回查题目与归属。即使 WebSocket 已连通，
    # 下游故障时也不能接受浏览器自报的题目、学生、角色或学校作为替代。
    row = await request_json("interview", "GET", "/internal" + path + "/media-context",
                             actor=actor, scope="interview.media.context")
    if (not isinstance(row, dict) or row.get("interview_id") != interview_id
            or row.get("student_id") != actor["actor_id"] or row.get("school_id") != actor["school_id"]
            or not isinstance(row.get("context"), dict)):
        raise HTTPException(502, "无法核验面试服务返回的回合归属，请刷新后重试。")
    await request_json("media", "PUT", path + "/context", actor=actor, scope="media.context.sync",
                       body=row["context"])
    return actor


router = APIRouter()
router.include_router(browser_router(sync_native_context))


@router.websocket("/ws/interviews/{interview_id}/qwen/omni-realtime")
async def voice_socket(websocket: WebSocket, interview_id: str):
    await relay_with_context(websocket, interview_id, sync_native_context)


@router.get("/api/interviews/{interview_id}/webrtc-events")
async def list_diagnostics(interview_id: str, request: Request, response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    scope = "interview.diagnostics.read"
    actor = await run_in_threadpool(resolve_native, request, scope, "student")
    return await request_json("interview", "GET", "/api/interviews/" + resource_segment(interview_id) + "/webrtc-events",
                              actor=actor, scope=scope, params=request.query_params.multi_items())


@router.post("/api/interviews/{interview_id}/webrtc-events", status_code=201)
async def record_diagnostics(interview_id: str, request: Request, response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    scope = "interview.diagnostics.write"
    actor = await run_in_threadpool(resolve_native, request, scope, "student")
    try:
        fields = rtc_data(await read_json_object(request) or {})
    except ValueError:
        raise HTTPException(422, "RTC 诊断字段格式无效") from None
    return await request_json("interview", "POST", "/api/interviews/" + resource_segment(interview_id) + "/webrtc-events",
                              actor=actor, scope=scope, body=fields)


def mount_native_media(app: FastAPI):
    app.include_router(router)
