"""浏览器媒体代理只开放学生可执行的动作，轮次上下文仅由受信服务发布。"""
import json

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from shared.service_http import resource_segment, service_origin
from shared.service_security import service_headers

# 浏览器路由逐项指定权限，避免通配转发把更新会话归属或直接调用供应商的能力公开。
ROUTES = {
    "rtc/token": "media.rtc.token", "rtc/session": "media.rtc.read",
    "rtc/session/heartbeat": "media.rtc.heartbeat", "rtc/agent/start": "media.rtc.start",
    "rtc/agent/notify": "media.rtc.notify", "rtc/agent/stop": "media.rtc.stop",
    "rtc/caption/validate": "media.rtc.caption",
    "qwen/tts": "media.speech.synthesize", "qwen/realtime-tts": "media.speech.synthesize",
    "qwen/speech": "media.speech.synthesize", "realtime/sdp": "media.voice.connect",
    "qwen/omni-realtime/sdp": "media.voice.connect", "qwen/omni-webrtc/offer": "media.voice.connect",
    "qwen/omni-webrtc/stop": "media.voice.connect", "media/video/token": "media.video.publish",
    "media/questions/{question_id}/recording/start": "media.recording.start",
    "media/questions/{question_id}/recording/stop": "media.recording.stop",
    "media/questions/{question_id}/playback": "media.playback.read",
}


def make_snapshot(interview, agents, messages, *, user_name="", analysis=None, prompt_builder=None):
    """供面试服务将已核对归属的角色、题目和历史整理成媒体快照。"""
    if prompt_builder is None:
        from services.interview.prompts import build_rtc_ai_agent_prompt
        prompt_builder = build_rtc_ai_agent_prompt

    question = next((m for m in reversed(messages) if m["sender_type"] == "agent" and
                     m["message_type"] in ("question", "follow_up")), {})
    role = next((a for a in agents if a["id"] == question.get("agent_id")), None)
    if role is None:
        role = next((a for a in agents if a["status"] == "active"), agents[0] if agents else {})
    return {"status": interview["status"], "question_id": question.get("id") or "",
            "role_id": role.get("id") or "", "question_order": max(0, int(question.get("order_index") or 0)),
            "active_agent": role.get("agent_name") or "", "user_name": user_name or "候选人",
            "greeting": question.get("content") or "",
            "prompt": prompt_builder(interview, [role] if role else [], messages, analysis)}


async def sync_browser_context(request, interview_id, scope):
    # 两个浏览器入口使用同一个原生鉴权与快照流程。延迟导入是因为原生路由复用了本模块的路由工厂。
    from services.gateway.native_media import sync_native_context
    return await sync_native_context(request, interview_id, scope)


async def input_body(request, suffix):
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > 160 * 1024:
            raise HTTPException(413, "媒体请求过大。")
        data.extend(chunk)
    if suffix == "realtime/sdp":
        try:
            return {"sdp": data.decode("utf-8")}
        except UnicodeDecodeError:
            raise HTTPException(400, "无效的 SDP。") from None
    try:
        body = json.loads(data) if data else {}
        if not isinstance(body, dict):
            raise ValueError
    except (ValueError, RecursionError):
        raise HTTPException(400, "请使用 JSON 对象。") from None
    if suffix in {"qwen/omni-realtime/sdp", "qwen/omni-webrtc/offer"}:
        # 兼容客户端会附带展示用字段；角色、题目和提示词以面试服务快照为准。
        return {k: body[k] for k in ("sdp", "type") if k in body}
    return body


async def forward(request, interview_id, suffix, scope, sync_context, question_id=None):
    try:
        actor = await sync_context(request, interview_id, scope)
    except HTTPException as exc:
        if exc.status_code < 500:
            raise
        raise HTTPException(exc.status_code, {"code": "media_context_unavailable", "fallback": "text",
                            "error": "无法确认当前面试上下文，可继续文字面试。"}) from None
    body = await input_body(request, suffix) if request.method != "GET" else None
    path = suffix.replace("{question_id}", resource_segment(question_id)) if question_id is not None else suffix
    url = service_origin("media") + "/interviews/" + resource_segment(interview_id) + "/" + path
    headers = service_headers("media", actor_id=actor["actor_id"], school_id=actor["school_id"],
                              actor_type="student", scopes=[scope])
    client = httpx.AsyncClient(timeout=210, trust_env=False)
    try:
        upstream = await client.send(client.build_request(request.method, url, headers=headers, json=body), stream=True)
        if not 200 <= upstream.status_code < 300:
            try:
                detail = json.loads(await upstream.aread()).get("detail")
            except (ValueError, AttributeError):
                detail = None
            fallback = detail.get("fallback") if isinstance(detail, dict) else None
            message = detail if isinstance(detail, str) else "媒体操作未完成。"
            failure = {"error": message[:300]}
            if fallback == "text":
                code = detail.get("code", "media_unavailable")
                message = ("学校媒体额度已用尽，可切换文字继续本题。" if code == "quota_exhausted" else
                           "媒体服务暂不可用，可切换文字继续本题。")
                failure.update(error=message, fallback="text", code=code)
            raise HTTPException(upstream.status_code if upstream.status_code >= 400 else 502, failure)
    except BaseException as exc:
        await client.aclose()
        if isinstance(exc, httpx.RequestError):
            raise HTTPException(503, {"error": "媒体服务暂不可用，可继续文字面试。", "fallback": "text"}) from None
        raise
    # 音频分块回传。播放结束或浏览器取消时关闭两端连接，只转发播放器所需的响应头。
    async def relay():
        try:
            async for chunk in upstream.aiter_bytes():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    safe = {k: v for k, v in upstream.headers.items() if k in (
        "content-type", "x-qwen-tts-provider", "x-qwen-tts-request-id", "x-qwen-tts-fallback-from")}
    return StreamingResponse(relay(), status_code=upstream.status_code, headers={**safe, "Cache-Control": "no-store"})


def register(router, suffix, scope, sync_context):
    if "{question_id}" in suffix:
        async def handle(request: Request, interview_id: str, question_id: str):
            return await forward(request, interview_id, suffix, scope, sync_context, question_id)
    else:
        async def handle(request: Request, interview_id: str):
            return await forward(request, interview_id, suffix, scope, sync_context)
    router.add_api_route("/" + suffix, handle, methods=["GET" if suffix == "rtc/session" else "POST"],
                         name=suffix.replace("/", "-"))


def browser_router(sync_context):
    routes = APIRouter(prefix="/api/interviews/{interview_id}")
    for suffix, scope in ROUTES.items():
        register(routes, suffix, scope, sync_context)
    return routes


router = browser_router(sync_browser_context)


def finish(interview_id, actor_id, school_id):
    """先发布面试已结束，再停止语音任务，阻止随后到达的令牌和启动请求。"""
    if not school_id:
        raise RuntimeError("未配置面试所属学校")
    actor = {"school_id": school_id, "actor_id": actor_id, "actor_type": "student"}
    base = service_origin("media") + "/interviews/" + resource_segment(interview_id)
    closed = {"status": "completed", "question_id": "", "question_order": 0, "role_id": "",
              "prompt": "", "greeting": "", "user_name": ""}
    with httpx.Client(timeout=8, trust_env=False) as client:
        client.put(base + "/context", headers=service_headers("media", **actor, scopes=["media.context.sync"]),
                   json=closed).raise_for_status()
        response = client.post(base + "/rtc/agent/stop",
                               headers=service_headers("media", **actor, scopes=["media.rtc.stop"]), json={})
        response.raise_for_status()
        return response.json().get("rtc_session")
