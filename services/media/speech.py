"""千问语音合成及流式传输。记录响应耗时和字节数，不记录学生原文。"""
import base64
import json
import os
import time
from collections.abc import Iterator
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from uuid import uuid4

import httpx
from fastapi import HTTPException, WebSocket
from fastapi.responses import StreamingResponse

from shared.env_values import first_env_value
from services.interview.decision import ANSWER_CONTEXT_POLICY
from services.media.qwen_realtime_tts import QwenRealtimeTtsError, get_qwen_realtime_tts_media_type, stream_qwen_realtime_tts
from services.media.qwen_tts import QwenTtsError, get_qwen_tts_media_type, stream_qwen_tts
from shared.provider_settings import approved_endpoint, qwen_workspace_endpoint, runtime_settings


def error(status, message):
    return HTTPException(status, {"error": message})


def log_qwen_tts_metric(event: str, **payload: Any) -> None:
    print(
        "Qwen TTS:",
        json.dumps({"event": event, **payload}, ensure_ascii=False),
        flush=True,
    )


def stream_with_qwen_tts_metrics(
    audio_stream: Iterator[bytes],
    *,
    request_id: str,
    provider: str,
    text_length: int,
    fallback_from: str | None = None,
) -> Iterator[bytes]:
    started_at = time.perf_counter()
    first_packet_ms: int | None = None
    total_bytes = 0
    chunk_count = 0
    status = "completed"
    error_message: str | None = None

    log_qwen_tts_metric(
        "start",
        request_id=request_id,
        provider=provider,
        fallback_from=fallback_from,
        text_length=text_length,
    )

    try:
        for chunk in audio_stream:
            if not chunk:
                continue
            chunk_count += 1
            total_bytes += len(chunk)
            if first_packet_ms is None:
                first_packet_ms = round((time.perf_counter() - started_at) * 1000)
                log_qwen_tts_metric(
                    "first_packet",
                    request_id=request_id,
                    provider=provider,
                    first_packet_ms=first_packet_ms,
                    first_packet_bytes=len(chunk),
                )
            yield chunk
    except Exception as exc:
        status = "failed"
        error_message = type(exc).__name__
        raise
    finally:
        log_qwen_tts_metric(
            "finish",
            request_id=request_id,
            provider=provider,
            fallback_from=fallback_from,
            status=status,
            first_packet_ms=first_packet_ms,
            duration_ms=round((time.perf_counter() - started_at) * 1000),
            chunk_count=chunk_count,
            total_bytes=total_bytes,
            text_length=text_length,
            error=error_message,
        )


def build_qwen_tts_response(text: str, provider_preference: str = "auto") -> StreamingResponse:
    normalized_preference = (provider_preference or "auto").strip().lower()
    if normalized_preference not in {"auto", "realtime", "standard"}:
        raise error(400, "语音合成 provider 只支持 auto、realtime 或 standard。")

    request_id = str(uuid4())
    fallback_from: str | None = None

    if normalized_preference in {"auto", "realtime"}:
        try:
            audio_stream = stream_qwen_realtime_tts(text)
            provider = "realtime"
            media_type = get_qwen_realtime_tts_media_type()
        except QwenRealtimeTtsError as exc:
            # 只有 auto 允许改用同一供应商的标准合成，显式选择实时链路时直接返回文字降级。
            if normalized_preference == "realtime":
                raise HTTPException(503, {"code": "speech_unavailable", "fallback": "text",
                                    "error": "实时语音合成暂不可用，可继续文字面试。"}) from exc
            fallback_from = "realtime"
            log_qwen_tts_metric(
                "fallback",
                request_id=request_id,
                from_provider="realtime",
                to_provider="standard",
                reason=type(exc).__name__,
            )
        else:
            return StreamingResponse(
                stream_with_qwen_tts_metrics(
                    audio_stream,
                    request_id=request_id,
                    provider=provider,
                    text_length=len(text),
                ),
                media_type=media_type,
                headers={"X-Qwen-TTS-Provider": provider, "X-Qwen-TTS-Request-Id": request_id},
            )

    try:
        audio_stream = stream_qwen_tts(text)
    except QwenTtsError as exc:
        raise HTTPException(503, {"code": "speech_unavailable", "fallback": "text",
                                  "error": "语音合成暂不可用，可继续文字面试。"}) from exc

    provider = "standard"
    headers = {"X-Qwen-TTS-Provider": provider, "X-Qwen-TTS-Request-Id": request_id}
    if fallback_from:
        headers["X-Qwen-TTS-Fallback-From"] = fallback_from
    return StreamingResponse(
        stream_with_qwen_tts_metrics(
            audio_stream,
            request_id=request_id,
            provider=provider,
            fallback_from=fallback_from,
            text_length=len(text),
        ),
        media_type=get_qwen_tts_media_type(),
        headers=headers,
    )


def _qwen_omni_audio_format(mime_type: str) -> str:
    normalized = (mime_type or "").lower()
    if "wav" in normalized:
        return "wav"
    if "mpeg" in normalized or "mp3" in normalized:
        return "mp3"
    if "mp4" in normalized or "m4a" in normalized:
        return "mp4"
    if "ogg" in normalized or "opus" in normalized:
        return "ogg"
    if "webm" in normalized:
        return "webm"
    return os.environ.get("QWEN_OMNI_INPUT_AUDIO_FORMAT", "webm").strip() or "webm"


def _build_qwen_omni_prompt(session_config: dict, start_payload: dict) -> str:
    current_question = str(start_payload.get("currentQuestion") or session_config.get("current_question") or "").strip()
    active_agent = str(start_payload.get("activeAgent") or session_config.get("active_agent") or "").strip()
    asked_questions = session_config.get("asked_questions") or []
    asked_questions_text = "\n".join([f"- {question}" for question in asked_questions[-5:]]) or "- 暂无"
    return "\n".join(
        [
            "候选人刚刚用语音回答了当前问题。请先准确理解这段语音，再继续面试。",
            "绝对不要复述当前问题，不要重新开场，不要介绍系统功能。",
            "如果听清了：先给一句很短的自然反馈，再提出一个新的追问。",
            ANSWER_CONTEXT_POLICY,
            "如果没有听清：只用一句话请候选人重复或补充。",
            "输出要像真实电话面试：简洁、口语化、每次只问一个问题。",
            f"当前面试官：{active_agent or '技术面试 Agent'}",
            f"当前问题：{current_question or '请围绕候选人的项目经历继续追问。'}",
            f"已问过的问题，避免重复：\n{asked_questions_text}",
        ]
    )


def _build_qwen_omni_messages(session_config: dict, start_payload: dict, audio_data_url: str, input_format: str) -> list[dict]:
    qwen_messages: list[dict] = [
        {
            "role": "system",
            "content": "\n".join(
                [
                    str(session_config.get("instructions") or ""),
                    "现在进入 Qwen-Omni 语音轮次：请根据最后一条用户音频推进面试，不要复述旧问题。",
                ]
            ),
        }
    ]

    recent_messages = session_config.get("recent_messages") or []
    for message in recent_messages[-6:]:
        content = str(message.get("content") or "").strip()
        if not content:
            continue
        qwen_messages.append(
            {
                "role": "user" if message.get("sender_type") == "candidate" else "assistant",
                "content": content[:1200],
            }
        )

    qwen_messages.append(
        {
            "role": "user",
            "content": [
                {"type": "input_audio", "input_audio": {"data": audio_data_url, "format": input_format}},
                {"type": "text", "text": _build_qwen_omni_prompt(session_config, start_payload)},
            ],
        }
    )
    return qwen_messages


def _env_float_value(name: str, default: float) -> float:
    value = os.environ.get(name, "").strip()
    if not value:
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise QwenRealtimeTtsError(f"{name} 必须是数字。") from exc


def _env_int_value(name: str, default: int) -> int:
    value = os.environ.get(name, "").strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise QwenRealtimeTtsError(f"{name} 必须是整数。") from exc


def _env_bool_value(name: str, default: bool = False) -> bool:
    value = os.environ.get(name, "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


def _append_query_param(url: str, key: str, value: str) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.setdefault(key, value)
    return urlunparse(parsed._replace(query=urlencode(query)))


def media_settings():
    """收费前取得媒体工作负载的已授权控制面配置；无法核实时让本轮降级为文字。"""
    try:
        return runtime_settings()
    except HTTPException as exc:
        raise HTTPException(exc.status_code, {"code": "media_settings_unavailable", "fallback": "text",
                            "error": "媒体配置暂不可用，可继续文字面试。"}) from None


def _qwen_realtime_model(settings=None) -> str:
    settings = media_settings() if settings is None else settings
    return settings.get("QWEN_OMNI_REALTIME_MODEL", "qwen3.5-omni-plus-realtime")


def _qwen_realtime_api_key() -> str:
    return first_env_value("QWEN_OMNI_REALTIME_API_KEY", "QWEN_OMNI_API_KEY", "DASHSCOPE_API_KEY")


def _qwen_realtime_webrtc_url(model: str, settings=None) -> str:
    settings = media_settings() if settings is None else settings
    endpoint = settings.get("QWEN_OMNI_REALTIME_WEBRTC_URL") or settings.get("QWEN_OMNI_REALTIME_WEBRTC_ENDPOINT")
    try:
        if not endpoint:
            workspace = settings.get("QWEN_OMNI_REALTIME_WORKSPACE_ID") or settings.get("DASHSCOPE_WORKSPACE_ID", "")
            region = settings.get("QWEN_OMNI_REALTIME_REGION") or settings.get("DASHSCOPE_TTS_REGION", "beijing")
            endpoint = qwen_workspace_endpoint("qwen_webrtc", workspace, region)
        endpoint = approved_endpoint("qwen_webrtc", endpoint)
    except ValueError as exc:
        raise QwenRealtimeTtsError(str(exc)) from exc
    return _append_query_param(endpoint, "model", model)


def build_qwen_realtime_session_update(session_config: dict, start_payload: dict | None = None, *, settings=None) -> dict:
    payload = start_payload or {}
    active_agent = str(payload.get("activeAgent") or session_config.get("active_agent") or "").strip()
    current_question = str(payload.get("currentQuestion") or session_config.get("current_question") or "").strip()
    instructions = "\n".join(
        [
            str(session_config.get("instructions") or ""),
            "当前使用 Qwen-Omni-Realtime WebRTC 直连链路。",
            "只有当前面试官 Agent 对候选人说话，后台分析 Agent 不要出声或自我介绍。",
            "如果候选人已经回答，请基于回答继续追问；如果候选人刚接入，请直接提出当前问题。",
            f"当前发声 Agent：{active_agent or session_config.get('active_agent') or '技术面试 Agent'}",
            f"当前问题：{current_question or session_config.get('current_question') or '请围绕候选人的项目经历继续追问。'}",
        ]
    )
    settings = media_settings() if settings is None else settings
    model = _qwen_realtime_model(settings)
    turn_detection_type = os.environ.get("QWEN_OMNI_REALTIME_TURN_DETECTION", "").strip()
    if not turn_detection_type:
        turn_detection_type = "semantic_vad" if "qwen3.5" in model else "server_vad"

    session: dict[str, Any] = {
        "modalities": ["text", "audio"],
        "voice": settings.get("QWEN_OMNI_REALTIME_VOICE") or os.environ.get("QWEN_OMNI_VOICE", "Tina"),
        "input_audio_format": "pcm",
        "output_audio_format": "pcm",
        "input_audio_transcription": {
            "model": os.environ.get("QWEN_OMNI_REALTIME_TRANSCRIPTION_MODEL", "qwen3-asr-flash-realtime"),
        },
        "instructions": instructions,
        "smooth_output": _env_bool_value("QWEN_OMNI_REALTIME_SMOOTH_OUTPUT", False),
        "turn_detection": {
            "type": turn_detection_type,
            "threshold": _env_float_value("QWEN_OMNI_REALTIME_VAD_THRESHOLD", 0.5),
            "prefix_padding_ms": _env_int_value("QWEN_OMNI_REALTIME_PREFIX_PADDING_MS", 500),
            "silence_duration_ms": _env_int_value("QWEN_OMNI_REALTIME_SILENCE_DURATION_MS", 800),
        },
    }

    if _env_bool_value("QWEN_OMNI_REALTIME_ENABLE_SEARCH", False):
        session["enable_search"] = True
        session["search_options"] = {"enable_source": _env_bool_value("QWEN_OMNI_REALTIME_SEARCH_SOURCE", True)}

    return {
        "event_id": f"event_{uuid4().hex}",
        "type": "session.update",
        "session": session,
    }


async def _stream_qwen_omni_http_response(websocket: WebSocket, audio_bytes: bytes, mime_type: str, session_config: dict, start_payload: dict, *, base_url: str | None = None) -> None:
    api_key = first_env_value("QWEN_OMNI_API_KEY", "DASHSCOPE_API_KEY")
    if not api_key:
        await websocket.send_json({"type": "error", "message": "请先配置 DASHSCOPE_API_KEY 或 QWEN_OMNI_API_KEY。"})
        return
    if not audio_bytes:
        await websocket.send_json({"type": "error", "message": "没有收到可提交给 Qwen-Omni 的录音。"})
        return

    base_url = approved_endpoint("qwen", base_url or os.environ.get("QWEN_OMNI_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1").rstrip("/"))
    model = os.environ.get("QWEN_OMNI_MODEL", "qwen3.5-omni-plus")
    voice = os.environ.get("QWEN_OMNI_VOICE", "Tina")
    audio_format = os.environ.get("QWEN_OMNI_OUTPUT_AUDIO_FORMAT", "wav")
    input_format = os.environ.get("QWEN_OMNI_INPUT_AUDIO_FORMAT", "").strip() or _qwen_omni_audio_format(mime_type)
    audio_base64 = base64.b64encode(audio_bytes).decode("ascii")
    audio_data_url = f"data:audio/{input_format};base64,{audio_base64}"

    stream_response = os.environ.get("QWEN_OMNI_STREAM", "false").lower() == "true"
    request_body = {
        "model": model,
        "messages": _build_qwen_omni_messages(session_config, start_payload, audio_data_url, input_format),
        "modalities": ["text", "audio"],
        "audio": {"voice": voice, "format": audio_format},
        "temperature": float(os.environ.get("QWEN_OMNI_TEMPERATURE", "0.7")),
        "stream": stream_response,
    }
    if stream_response:
        request_body["stream_options"] = {"include_usage": True}

    await websocket.send_json({"type": "status", "message": f"正在调用 Qwen-Omni API：{model}"})
    text_parts: list[str] = []
    audio_chunk_count = 0
    audio_byte_count = 0

    async def send_audio_data(audio_data: str | None) -> None:
        nonlocal audio_chunk_count, audio_byte_count
        if not audio_data:
            return
        clean_data = str(audio_data)
        if "," in clean_data and clean_data.lstrip().startswith("data:"):
            clean_data = clean_data.split(",", 1)[1]
        try:
            audio_byte_count += len(base64.b64decode(clean_data, validate=False))
        except Exception:
            pass
        audio_chunk_count += 1
        await websocket.send_json({"type": "audio_delta", "data": clean_data})

    try:
        async with httpx.AsyncClient(follow_redirects=False, trust_env=False, timeout=float(os.environ.get("QWEN_OMNI_TIMEOUT", "120"))) as client:
            if not stream_response:
                response = await client.post(
                    f"{base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json=request_body,
                )
                if not response.is_success:
                    message = "Qwen-Omni API 调用失败，可继续文字面试。"
                    await websocket.send_json({"type": "error", "message": message, "fallback": "text"})
                    return
                data = response.json()
                choices = data.get("choices") or []
                message = (choices[0].get("message") if choices else {}) or {}
                content = message.get("content")
                if content:
                    text_parts.append(str(content))
                    await websocket.send_json({"type": "text", "role": "agent", "text": str(content)})
                audio = message.get("audio") or {}
                transcript = audio.get("transcript")
                if transcript and not content:
                    text_parts.append(str(transcript))
                    await websocket.send_json({"type": "text", "role": "agent", "text": str(transcript)})
                await send_audio_data(audio.get("data"))
            else:
                async with client.stream(
                    "POST",
                    f"{base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json=request_body,
                ) as response:
                    if not response.is_success:
                        message = "Qwen-Omni API 调用失败，可继续文字面试。"
                        await websocket.send_json({"type": "error", "message": message, "fallback": "text"})
                        return

                    async for line in response.aiter_lines():
                        line = line.strip()
                        if not line or not line.startswith("data:"):
                            continue
                        data = line.removeprefix("data:").strip()
                        if data == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                        except ValueError:
                            continue
                        choices = chunk.get("choices") or []
                        if not choices:
                            continue
                        delta = choices[0].get("delta") or {}
                        content = delta.get("content")
                        if content:
                            text_parts.append(str(content))
                            await websocket.send_json({"type": "text", "role": "agent", "text": str(content)})
                        audio = delta.get("audio") or {}
                        await send_audio_data(audio.get("data"))
                        transcript = audio.get("transcript")
                        if transcript:
                            await websocket.send_json({"type": "text", "role": "agent", "text": str(transcript)})
        if text_parts:
            await websocket.send_json({"type": "transcript", "role": "agent", "text": "".join(text_parts)})
        if audio_chunk_count:
            await websocket.send_json({"type": "status", "message": f"已收到 Omni 音频：{audio_chunk_count} 段，约 {audio_byte_count} 字节。"})
            await websocket.send_json({"type": "audio_done"})
        else:
            await websocket.send_json({"type": "status", "message": "Qwen-Omni 本轮没有返回音频。"})
    except httpx.HTTPError:
        await websocket.send_json({"type": "error", "message": "无法连接 Qwen-Omni API，可继续文字面试。", "fallback": "text"})
