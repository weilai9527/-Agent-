"""千问语音录制。开始与停止时分别核对题目和角色，避免把跨轮次录音交给供应商。"""
import asyncio
import json
import inspect
import os
from time import monotonic

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from starlette.concurrency import run_in_threadpool

from shared.env_values import first_env_value
from shared.provider_settings import approved_endpoint
from shared.service_security import require_service
from .access import owned_session
from .meter import admit
from .speech import media_settings

router = APIRouter()
authorize = require_service("media", "media.voice.connect")
MAX_AUDIO_BYTES = 8 * 1024 * 1024
MAX_CONTROL_CHARS = 32_768
MAX_RECORD_SECONDS = 120
IDLE_SECONDS = 90
MAX_RESPONSE_SECONDS = 150
MIME_TYPES = {"audio/webm", "audio/webm;codecs=opus", "audio/ogg", "audio/ogg;codecs=opus",
              "audio/mp4", "audio/wav", "audio/mpeg"}


def provider_url():
    ws_url = os.environ.get("QWEN_OMNI_REALTIME_WS_URL", "").strip()
    transport = os.environ.get("QWEN_OMNI_TRANSPORT", "").strip()
    # 兼容原先明确指向自托管网关的部署。仅有通用 API 密钥不能授权将录音发往官方 HTTP。
    if not transport and ws_url:
        transport = "ws"
    try:
        if transport == "ws":
            if not ws_url or not first_env_value("QWEN_OMNI_REALTIME_API_KEY"):
                raise HTTPException(503, "自托管语音网关地址或专用密钥未配置，可使用文字面试。")
            url = approved_endpoint("qwen_ws", ws_url, scheme="wss")
        elif transport == "http":
            if not first_env_value("QWEN_OMNI_API_KEY", "DASHSCOPE_API_KEY"):
                raise HTTPException(503, "千问语音服务未配置，可使用文字面试。")
            url = approved_endpoint("qwen", os.environ.get(
                "QWEN_OMNI_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1").rstrip("/"))
        else:
            raise HTTPException(503, "未配置有效的千问语音传输方式，可使用文字面试。")
    except ValueError:
        raise HTTPException(503, "千问语音接入地址未获授权，可使用文字面试。") from None
    media_settings()
    return url


def round_id(session):
    return session["question_order"], session["question_id"], session["role_id"]


async def stream_http(socket, audio, mime_type, config, url):
    from .speech import _stream_qwen_omni_http_response
    # 模型指令、角色和当前题目均来自已验证的轮次快照。
    await _stream_qwen_omni_http_response(socket, audio, mime_type, config, {}, base_url=url)


async def stream_ws(socket, audio, mime_type, config, url, sample_rate):
    import websockets

    # 拒绝重定向，避免将凭据和面试内容发送给其他主机。
    class DirectConnection(websockets.connect):
        def process_redirect(self, exc):
            return exc

    key = first_env_value("QWEN_OMNI_REALTIME_API_KEY")
    headers = {"Authorization": "Bearer " + key} if key else None
    options = {"proxy": None} if "proxy" in inspect.signature(websockets.connect).parameters else {}
    async with DirectConnection(url, additional_headers=headers, **options, max_size=16 * 1024 * 1024,
                                open_timeout=10, close_timeout=2) as upstream:
        await upstream.send(json.dumps({"type": "session.start", "session": config}, ensure_ascii=False))
        await upstream.send(json.dumps({"type": "start", "mimeType": mime_type, "sampleRate": sample_rate,
                                       "currentQuestion": config["current_question"], "activeAgent": config["active_agent"]},
                                      ensure_ascii=False))
        await upstream.send(audio)
        await upstream.send('{"type":"stop"}')
        async for frame in upstream:
            if isinstance(frame, bytes):
                await socket.send_bytes(frame)
                continue
            event = json.loads(frame)
            if event.get("type") == "error":
                await socket.send_json({"type": "error", "message": "千问语音网关处理失败，可使用文字面试。", "fallback": "text"})
                return
            await socket.send_text(frame)
            if event.get("type") in {"audio_done", "done", "response.done"}:
                return


async def current(interview_id, actor):
    session = await run_in_threadpool(owned_session, interview_id, actor)
    if not session["question_id"]:
        raise HTTPException(409, "尚无可回答的面试题目。")
    return session


async def serve(socket, interview_id, actor, url):
    recording = None
    deadline = 0.0
    audio = bytearray()
    while True:
        timeout = IDLE_SECONDS if recording is None else deadline - monotonic()
        if timeout <= 0:
            raise HTTPException(408, "录音时间过长，请缩短回答。")
        try:
            frame = await asyncio.wait_for(socket.receive(), timeout)
        except TimeoutError:
            raise HTTPException(408, "语音连接或录音已超时，请重新连接。") from None
        if frame["type"] == "websocket.disconnect":
            return
        chunk = frame.get("bytes")
        if chunk is not None:
            if recording is None:
                raise HTTPException(400, "请先开始录音。")
            if len(audio) + len(chunk) > MAX_AUDIO_BYTES:
                raise HTTPException(413, "录音过大，请缩短回答。")
            audio.extend(chunk)
            continue
        raw = frame.get("text") or ""
        if len(raw) > MAX_CONTROL_CHARS:
            raise HTTPException(413, "控制消息过大。")
        try:
            event = json.loads(raw)
        except (ValueError, RecursionError):
            raise HTTPException(400, "无效的语音控制消息。") from None
        kind = event.get("type") if isinstance(event, dict) else None
        if kind == "start" and recording is None:
            mime_type = event.get("mimeType", "audio/webm")
            sample_rate = event.get("sampleRate", 48000)
            if (not isinstance(mime_type, str) or mime_type not in MIME_TYPES or type(sample_rate) is not int
                    or not 8000 <= sample_rate <= 192000):
                raise HTTPException(400, "不支持的录音格式。")
            recording = round_id(await current(interview_id, actor))
            deadline = monotonic() + MAX_RECORD_SECONDS
            await socket.send_json({"type": "status", "message": "正在录音，停止后提交本题回答。"})
            continue
        if kind != "stop" or recording is None or not audio:
            raise HTTPException(400, "语音控制消息与录音状态不匹配。")

        session = await current(interview_id, actor)
        if round_id(session) != recording:
            # 音频此时仍在本进程中；轮次不一致就丢弃，避免错题派发和计量。
            raise HTTPException(409, "面试题目或角色已变化，请为新题重新录音。")
        # 长连接握手时的配置可能已被撤回，每段录音在计量前重新检查，拒绝会话中途更换接收端。
        if await run_in_threadpool(provider_url) != url:
            raise HTTPException(409, "语音接收端已变更，请重新连接后再录音。")
        self_hosted = url.startswith("wss://")
        config = {"type": "realtime", "interview_id": interview_id, "instructions": session["prompt"],
                  "current_question": session["greeting"], "active_agent": session["active_agent"],
                  "provider": "qwen-omni-self-hosted" if self_hosted else "qwen-omni-http"}
        await run_in_threadpool(admit, actor, "omni.voice")
        recording = None
        payload = bytes(audio)
        audio.clear()
        stream = (stream_ws(socket, payload, mime_type, config, url, sample_rate) if self_hosted else
                  stream_http(socket, payload, mime_type, config, url))
        await asyncio.wait_for(stream, MAX_RESPONSE_SECONDS)
        del payload, stream


@router.websocket("/ws/interviews/{interview_id}/qwen/omni-realtime")
async def qwen_omni_realtime_ws(websocket: WebSocket, interview_id: str):
    # 长连接握手携带服务签名，校验与 HTTP 动作相同的学校及权限。
    try:
        actor = await run_in_threadpool(authorize, websocket)
        await current(interview_id, actor)
    except HTTPException:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    try:
        url = await run_in_threadpool(provider_url)
        await websocket.send_json({"type": "status", "message": "千问语音通道已就绪。"})
        await serve(websocket, interview_id, actor, url)
    except WebSocketDisconnect:
        pass
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        message = exc.detail if isinstance(exc.detail, str) else detail.get("error", "媒体服务暂不可用，可使用文字面试。")
        event = {"type": "error", "message": message}
        if exc.status_code >= 500 or exc.status_code == 429:
            event.update(fallback="text", code=detail.get("code", "voice_unavailable"))
        await websocket.send_json(event)
        await websocket.close(code=1009 if exc.status_code == 413 else 1008)
    except Exception:
        # 供应商错误可能包含私有地址或学生内容，浏览器只接收统一的降级提示。
        await websocket.send_json({"type": "error", "message": "千问语音服务连接失败，可使用文字面试。", "fallback": "text"})
        await websocket.close(code=1011)
