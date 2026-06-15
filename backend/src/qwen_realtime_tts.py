from __future__ import annotations

import base64
import json
import os
import ssl
from collections.abc import Iterator
from uuid import uuid4


class QwenRealtimeTtsError(RuntimeError):
    pass


def get_qwen_realtime_tts_media_type() -> str:
    response_format = os.environ.get("DASHSCOPE_REALTIME_TTS_FORMAT", "mp3").strip().lower()
    media_types = {
        "mp3": "audio/mpeg",
        "opus": "audio/ogg; codecs=opus",
        "wav": "audio/wav",
        "pcm": "audio/pcm",
    }
    return media_types.get(response_format, "application/octet-stream")


def _get_endpoint(model: str) -> str:
    region = os.environ.get("DASHSCOPE_TTS_REGION", "beijing").strip().lower()
    if region in {"singapore", "ap-southeast-1"}:
        workspace_id = os.environ.get("DASHSCOPE_WORKSPACE_ID", "").strip()
        if not workspace_id:
            raise QwenRealtimeTtsError("使用新加坡地域时需要配置 DASHSCOPE_WORKSPACE_ID。")
        return f"wss://{workspace_id}.ap-southeast-1.maas.aliyuncs.com/api-ws/v1/realtime?model={model}"
    return f"wss://dashscope.aliyuncs.com/api-ws/v1/realtime?model={model}"


def _get_ssl_options() -> dict:
    ssl_cert_file = os.environ.get("SSL_CERT_FILE") or os.environ.get("WEBSOCKET_CLIENT_CA_BUNDLE")
    if ssl_cert_file:
        return {"cert_reqs": ssl.CERT_REQUIRED, "ca_certs": ssl_cert_file}
    return {"cert_reqs": ssl.CERT_REQUIRED}


def _event(event_type: str, **payload: object) -> str:
    return json.dumps({"event_id": f"event_{uuid4().hex}", "type": event_type, **payload}, ensure_ascii=False)


def stream_qwen_realtime_tts(text: str) -> Iterator[bytes]:
    content = " ".join(str(text or "").split()).strip()
    if not content:
        raise QwenRealtimeTtsError("请提供要合成的文本。")

    api_key = os.environ.get("DASHSCOPE_API_KEY")
    if not api_key or api_key == "your-dashscope-api-key":
        raise QwenRealtimeTtsError("服务端未配置 DASHSCOPE_API_KEY，无法使用千问实时语音合成。")

    try:
        import websocket
    except ImportError as exc:
        raise QwenRealtimeTtsError("服务端未安装 websocket-client，无法使用千问实时语音合成。") from exc

    model = os.environ.get("DASHSCOPE_REALTIME_TTS_MODEL", "qwen3-tts-flash-realtime")
    voice = os.environ.get("DASHSCOPE_REALTIME_TTS_VOICE", "Cherry")
    mode = os.environ.get("DASHSCOPE_REALTIME_TTS_MODE", "commit")
    language_type = os.environ.get("DASHSCOPE_REALTIME_TTS_LANGUAGE", "Chinese")
    response_format = os.environ.get("DASHSCOPE_REALTIME_TTS_FORMAT", "mp3")
    sample_rate = int(os.environ.get("DASHSCOPE_REALTIME_TTS_SAMPLE_RATE", "24000"))
    instructions = os.environ.get("DASHSCOPE_REALTIME_TTS_INSTRUCTIONS", "").strip()

    headers = [f"Authorization: Bearer {api_key}", "user-agent: multi-agent-interview"]
    workspace_id = os.environ.get("DASHSCOPE_WORKSPACE_ID", "").strip()
    if workspace_id:
        headers.append(f"X-DashScope-WorkSpace: {workspace_id}")

    ws = websocket.create_connection(
        _get_endpoint(model),
        header=headers,
        timeout=float(os.environ.get("DASHSCOPE_REALTIME_TTS_TIMEOUT", "15")),
        sslopt=_get_ssl_options(),
    )

    try:
        session = {
            "voice": voice,
            "mode": mode,
            "language_type": language_type,
            "response_format": response_format,
            "sample_rate": sample_rate,
        }
        if instructions:
            session["instructions"] = instructions
            session["optimize_instructions"] = os.environ.get("DASHSCOPE_REALTIME_TTS_OPTIMIZE_INSTRUCTIONS", "false").lower() == "true"

        ws.send(_event("session.update", session=session))
        ws.send(_event("input_text_buffer.append", text=content))
        ws.send(_event("input_text_buffer.commit"))

        while True:
            raw_message = ws.recv()
            if not raw_message:
                continue
            message = json.loads(raw_message)
            event_type = message.get("type")

            if event_type == "response.audio.delta":
                delta = message.get("delta")
                if delta:
                    yield base64.b64decode(delta)
                continue

            if event_type == "error":
                detail = message.get("error") or {}
                raise QwenRealtimeTtsError(detail.get("message") or "千问实时语音合成失败。")

            if event_type in {"response.done", "session.finished"}:
                break

        ws.send(_event("session.finish"))
    finally:
        ws.close()
