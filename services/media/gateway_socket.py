"""浏览器 WebSocket 代理。仅向媒体服务签发对应动作的凭据。"""
import asyncio
import inspect
import json
from contextlib import AsyncExitStack

import anyio
from fastapi import HTTPException, Request, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, WebSocketException

from shared.service_http import resource_segment, service_origin
from shared.service_security import service_headers
from .omni_socket import MAX_AUDIO_BYTES, MAX_CONTROL_CHARS, MIME_TYPES

SCOPE = "media.voice.connect"
OUTPUT_FIELDS = {
    "status": ("message",), "error": ("message", "code", "fallback"), "text": ("role", "text", "content"),
    "transcript": ("role", "text", "content"), "audio_delta": ("data",),
    "audio_done": (), "done": (), "response.done": (),
}


class DirectConnection(connect):
    def process_redirect(self, exc):
        # 拒绝重定向，避免将签名凭据转交其他主机。
        return exc


def _connect(interview_id, actor):
    origin = service_origin("media")
    url = origin.replace("http", "ws", 1) + "/ws/interviews/" + resource_segment(interview_id) + "/qwen/omni-realtime"
    identity = {key: actor[key] for key in ("actor_id", "school_id", "actor_type")}
    headers = service_headers("media", **identity, scopes=[SCOPE])
    options = {"proxy": None} if "proxy" in inspect.signature(connect).parameters else {}
    return DirectConnection(url, additional_headers=headers, max_size=MAX_AUDIO_BYTES,
                            close_timeout=2, open_timeout=10, **options)


def _event(text, max_chars):
    if len(text) > max_chars:
        raise HTTPException(413, "Voice message too large")
    try:
        value = json.loads(text)
    except (ValueError, RecursionError):
        value = None
    if not isinstance(value, dict) or not isinstance(value.get("type"), str):
        raise HTTPException(400, "Invalid voice control")
    return value


async def _to_media(browser, upstream, authorize, identity):
    recording_bytes = None
    while True:
        frame = await browser.receive()
        if frame["type"] == "websocket.disconnect":
            return
        chunk = frame.get("bytes")
        if chunk is not None:
            if recording_bytes is None:
                raise HTTPException(400, "Audio before start")
            recording_bytes += len(chunk)
            if recording_bytes > MAX_AUDIO_BYTES:
                raise HTTPException(413, "Recording too large")
            await upstream.send(chunk)
            continue
        event = _event(frame.get("text") or "", MAX_CONTROL_CHARS)
        kind = event["type"]
        if kind == "start" and recording_bytes is None:
            mime, rate = event.get("mimeType", "audio/webm"), event.get("sampleRate", 48000)
            if not isinstance(mime, str) or mime not in MIME_TYPES or type(rate) != int or not 8000 <= rate <= 192000:
                raise HTTPException(400, "Invalid recording format")
            # 旧页面附带的题目和角色仅用于展示，发往媒体服务的控制帧不携带这两项。
            control = {"type": kind, "mimeType": mime, "sampleRate": rate}
            recording_bytes = 0
        elif kind == "stop" and recording_bytes:
            control = {"type": kind}
            recording_bytes = None
        else:
            raise HTTPException(400, "Invalid control for recording state")
        fresh = await authorize()
        if any(fresh[k] != identity[k] for k in ("actor_id", "school_id", "actor_type")):
            raise HTTPException(403, "Session identity changed")
        await upstream.send(json.dumps(control))


async def _to_browser(upstream, browser):
    async for frame in upstream:
        if isinstance(frame, bytes):
            await browser.send_bytes(frame)
            continue
        event = _event(frame, MAX_AUDIO_BYTES)
        kind = event["type"]
        if kind in OUTPUT_FIELDS:
            # 自托管供应商可能附带调试数据，仅将界面使用的字段交给浏览器。
            allowed = {k: event[k] for k in OUTPUT_FIELDS[kind] if isinstance(event.get(k), str)}
            await browser.send_json({"type": kind, **allowed})


async def relay_socket(websocket: WebSocket, interview_id: str):
    from .gateway import sync_browser_context

    await relay_with_context(websocket, interview_id, sync_browser_context)


async def relay_with_context(websocket: WebSocket, interview_id: str, sync_context):
    # 按 POST 校验原始 Cookie 与 Origin，让长连接的握手、开录和停录沿用身份服务的来源检查。
    request = Request({**websocket.scope, "type": "http", "method": "POST",
                       "scheme": "https" if websocket.scope["scheme"] == "wss" else "http"})

    async def authorize():
        return await sync_context(request, interview_id, SCOPE)

    code = 1000
    connections = AsyncExitStack()
    tasks = []
    try:
        identity = await authorize()
        peer = _connect(interview_id, identity)
        await websocket.accept()
        upstream = await connections.enter_async_context(peer)
        tasks = [asyncio.create_task(_to_media(websocket, upstream, authorize, identity)),
                 asyncio.create_task(_to_browser(upstream, websocket))]
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    except WebSocketDisconnect:
        return
    except HTTPException as exc:
        code = 1009 if exc.status_code == 413 else 1011 if exc.status_code >= 500 else 1008
    except ConnectionClosed as exc:
        code = exc.rcvd.code if exc.rcvd and exc.rcvd.code in {1000, 1001, 1008, 1009} else 1011
    except (WebSocketException, OSError, TimeoutError, ValueError, KeyError):
        code = 1011
    finally:
        # 浏览器断开与 ASGI 取消可能同时发生，仍需关闭下游套接字；等待由 close_timeout 限制。
        with anyio.CancelScope(shield=True):
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await connections.aclose()
            if (websocket.client_state != WebSocketState.DISCONNECTED and
                    websocket.application_state != WebSocketState.DISCONNECTED):
                try:
                    if code == 1011 and websocket.application_state == WebSocketState.CONNECTED:
                        await websocket.send_json({"type": "error", "code": "media_unavailable", "fallback": "text",
                                                   "message": "语音服务暂不可用，可继续文字面试。"})
                    await websocket.close(code=code)
                except WebSocketDisconnect:
                    pass
