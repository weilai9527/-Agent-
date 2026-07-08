from __future__ import annotations

import json
import os
import re
import ssl
from collections.abc import Iterator
from contextlib import suppress
from uuid import uuid4


class QwenRealtimeTtsError(RuntimeError):
    pass


SUPPORTED_AUDIO_FORMATS = {"mp3", "opus", "wav", "pcm"}
SERVER_EVENTS = {"task-started", "result-generated", "task-finished", "task-failed"}
SENTENCE_BOUNDARY_PATTERN = re.compile(r"([^。！？!?；;\n]+[。！？!?；;]?)")


def _audio_format() -> str:
    response_format = os.environ.get("DASHSCOPE_REALTIME_TTS_FORMAT", "mp3").strip().lower() or "mp3"
    if response_format not in SUPPORTED_AUDIO_FORMATS:
        raise QwenRealtimeTtsError("DASHSCOPE_REALTIME_TTS_FORMAT 只支持 mp3、opus、wav 或 pcm。")
    return response_format


def get_qwen_realtime_tts_media_type() -> str:
    media_types = {
        "mp3": "audio/mpeg",
        "opus": "audio/ogg; codecs=opus",
        "wav": "audio/wav",
        "pcm": "audio/pcm",
    }
    return media_types[_audio_format()]


def _get_endpoint() -> str:
    region = os.environ.get("DASHSCOPE_TTS_REGION", "beijing").strip().lower()
    workspace_id = os.environ.get("DASHSCOPE_WORKSPACE_ID", "").strip()
    if region in {"singapore", "ap-southeast-1"}:
        if not workspace_id:
            raise QwenRealtimeTtsError("使用新加坡地域时需要配置 DASHSCOPE_WORKSPACE_ID。")
        return f"wss://{workspace_id}.ap-southeast-1.maas.aliyuncs.com/api-ws/v1/inference"
    if workspace_id:
        return f"wss://{workspace_id}.cn-beijing.maas.aliyuncs.com/api-ws/v1/inference"
    return "wss://dashscope.aliyuncs.com/api-ws/v1/inference"


def _get_ssl_options() -> dict:
    ssl_cert_file = os.environ.get("SSL_CERT_FILE") or os.environ.get("WEBSOCKET_CLIENT_CA_BUNDLE")
    if ssl_cert_file and os.path.isfile(ssl_cert_file):
        return {"cert_reqs": ssl.CERT_REQUIRED, "ca_certs": ssl_cert_file}
    return {"cert_reqs": ssl.CERT_REQUIRED}


def _event(**payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _task_event(action: str, task_id: str, payload: dict) -> str:
    return _event(
        header={
            "action": action,
            "task_id": task_id,
            "streaming": "duplex",
        },
        payload=payload,
    )


def _env_float(name: str, default: float) -> float:
    value = os.environ.get(name, "").strip()
    if not value:
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise QwenRealtimeTtsError(f"{name} 必须是数字。") from exc


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name, "").strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise QwenRealtimeTtsError(f"{name} 必须是整数。") from exc


def _split_text(text: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return []

    max_chars = _env_int("DASHSCOPE_REALTIME_TTS_CHUNK_SIZE", 240)
    if max_chars < 40:
        raise QwenRealtimeTtsError("DASHSCOPE_REALTIME_TTS_CHUNK_SIZE 不能小于 40。")

    sentences = [match.group(0).strip() for match in SENTENCE_BOUNDARY_PATTERN.finditer(normalized)]
    if not sentences:
        sentences = [normalized]

    chunks: list[str] = []
    current = ""

    def flush_current() -> None:
        nonlocal current
        if current:
            chunks.append(current)
            current = ""

    for part in sentences:
        if len(part) > max_chars:
            flush_current()
            chunks.extend(part[index : index + max_chars] for index in range(0, len(part), max_chars))
            continue
        if current and len(current) + len(part) > max_chars:
            chunks.append(current)
            current = part
        else:
            current += part
    if current:
        chunks.append(current)
    return chunks or [normalized]


def _build_run_task(task_id: str, model: str, voice: str, response_format: str, sample_rate: int) -> str:
    parameters = {
        "text_type": "PlainText",
        "voice": voice,
        "format": response_format,
        "sample_rate": sample_rate,
        "volume": _env_int("DASHSCOPE_REALTIME_TTS_VOLUME", 50),
        "rate": _env_float("DASHSCOPE_REALTIME_TTS_RATE", 1.0),
        "pitch": _env_float("DASHSCOPE_REALTIME_TTS_PITCH", 1.0),
        "enable_ssml": os.environ.get("DASHSCOPE_REALTIME_TTS_ENABLE_SSML", "false").lower() == "true",
    }

    instruction = os.environ.get("DASHSCOPE_REALTIME_TTS_INSTRUCTION", "").strip()
    if instruction:
        parameters["instruction"] = instruction

    language_hint = os.environ.get("DASHSCOPE_REALTIME_TTS_LANGUAGE_HINT", "").strip()
    if language_hint:
        parameters["language_hints"] = [language_hint]

    return _task_event(
        "run-task",
        task_id,
        {
            "task_group": "audio",
            "task": "tts",
            "function": "SpeechSynthesizer",
            "model": model,
            "parameters": parameters,
            "input": {},
        },
    )


def _header_event(message: dict) -> str:
    header = message.get("header")
    if not isinstance(header, dict):
        return ""
    return str(header.get("event") or "")


def _parse_server_event(raw_message: object, task_id: str) -> tuple[str, dict]:
    if isinstance(raw_message, bytes):
        raise QwenRealtimeTtsError("任务启动前收到了异常音频帧。")
    if not raw_message:
        raise QwenRealtimeTtsError("DashScope 返回了空事件。")
    try:
        message = json.loads(str(raw_message))
    except json.JSONDecodeError as exc:
        raise QwenRealtimeTtsError(f"DashScope 返回了无效 JSON 事件：{raw_message}") from exc

    if not isinstance(message, dict):
        raise QwenRealtimeTtsError("DashScope 返回事件格式不正确。")

    header = message.get("header")
    if not isinstance(header, dict):
        raise QwenRealtimeTtsError("DashScope 返回事件缺少 header。")
    response_task_id = str(header.get("task_id") or "")
    if response_task_id and response_task_id != task_id:
        raise QwenRealtimeTtsError("DashScope 返回了不匹配的 task_id，已中止本轮合成。")

    event_type = str(header.get("event") or "")
    if event_type not in SERVER_EVENTS:
        raise QwenRealtimeTtsError(f"DashScope 返回了未知事件：{event_type or 'unknown'}。")
    return event_type, message


def _raise_task_failure(message: dict) -> None:
    header = message.get("header") if isinstance(message.get("header"), dict) else {}
    error_message = header.get("error_message") or header.get("error_code") or "千问实时语音合成任务失败。"
    raise QwenRealtimeTtsError(str(error_message))


def stream_qwen_realtime_tts(text: str) -> Iterator[bytes]:
    chunks = _split_text(str(text or ""))
    if not chunks:
        raise QwenRealtimeTtsError("请提供要合成的文本。")

    api_key = os.environ.get("DASHSCOPE_API_KEY")
    if not api_key or api_key == "your-dashscope-api-key":
        raise QwenRealtimeTtsError("服务端未配置 DASHSCOPE_API_KEY，无法使用千问实时语音合成。")

    try:
        import websocket
    except ImportError as exc:
        raise QwenRealtimeTtsError("服务端未安装 websocket-client，无法使用千问实时语音合成。") from exc

    model = os.environ.get("DASHSCOPE_REALTIME_TTS_MODEL") or os.environ.get("DASHSCOPE_TTS_MODEL", "cosyvoice-v3-flash")
    voice = os.environ.get("DASHSCOPE_REALTIME_TTS_VOICE") or os.environ.get("DASHSCOPE_TTS_VOICE", "longanyang")
    response_format = _audio_format()
    sample_rate = _env_int("DASHSCOPE_REALTIME_TTS_SAMPLE_RATE", 22050)
    task_id = str(uuid4())

    headers = [f"Authorization: Bearer {api_key}", "user-agent: multi-agent-interview"]
    workspace_id = os.environ.get("DASHSCOPE_WORKSPACE_ID", "").strip()
    if workspace_id:
        headers.append(f"X-DashScope-WorkSpace: {workspace_id}")
    data_inspection = os.environ.get("DASHSCOPE_DATA_INSPECTION", "").strip()
    if data_inspection:
        headers.append(f"X-DashScope-DataInspection: {data_inspection}")

    ws = None
    try:
        ws = websocket.create_connection(
            _get_endpoint(),
            header=headers,
            timeout=_env_float("DASHSCOPE_REALTIME_TTS_TIMEOUT", 15),
            sslopt=_get_ssl_options(),
        )
        ws.send(_build_run_task(task_id, model, voice, response_format, sample_rate))

        while True:
            raw_message = ws.recv()
            event_type, message = _parse_server_event(raw_message, task_id)
            if event_type == "task-started":
                break
            if event_type == "task-failed":
                _raise_task_failure(message)
    except Exception as exc:
        if ws is not None:
            with suppress(Exception):
                ws.close()
        if isinstance(exc, QwenRealtimeTtsError):
            raise
        raise QwenRealtimeTtsError(f"无法连接 DashScope CosyVoice WebSocket：{exc}") from exc

    def audio_iterator() -> Iterator[bytes]:
        finished = False
        finish_sent = False
        try:
            for chunk in chunks:
                ws.send(_task_event("continue-task", task_id, {"input": {"text": chunk}}))
            ws.send(_task_event("finish-task", task_id, {"input": {}}))
            finish_sent = True

            while True:
                raw_message = ws.recv()
                if isinstance(raw_message, bytes):
                    yield raw_message
                    continue
                event_type, message = _parse_server_event(raw_message, task_id)
                if event_type == "task-finished":
                    finished = True
                    break
                if event_type == "task-failed":
                    _raise_task_failure(message)
        finally:
            if not finished and not finish_sent:
                with suppress(Exception):
                    ws.send(_task_event("finish-task", task_id, {"input": {}}))
            with suppress(Exception):
                ws.close()

    return audio_iterator()
