from __future__ import annotations

import os
import queue
import re
import threading
from collections.abc import Iterator


class QwenTtsError(RuntimeError):
    pass


def get_qwen_tts_media_type() -> str:
    return "audio/mpeg"


def _load_dashscope():
    try:
        import dashscope
        from dashscope.audio.tts_v2 import AudioFormat, ResultCallback, SpeechSynthesizer
    except ImportError as exc:
        raise QwenTtsError("服务端未安装 dashscope，无法使用千问语音合成。") from exc

    api_key = os.environ.get("DASHSCOPE_API_KEY")
    if not api_key or api_key == "your-dashscope-api-key":
        raise QwenTtsError("服务端未配置 DASHSCOPE_API_KEY，无法使用千问语音合成。")

    ssl_cert_file = os.environ.get("SSL_CERT_FILE") or os.environ.get("WEBSOCKET_CLIENT_CA_BUNDLE")
    if ssl_cert_file:
        os.environ["WEBSOCKET_CLIENT_CA_BUNDLE"] = ssl_cert_file
        os.environ.setdefault("REQUESTS_CA_BUNDLE", ssl_cert_file)

    dashscope.api_key = api_key
    region = os.environ.get("DASHSCOPE_TTS_REGION", "beijing").strip().lower()
    workspace_id = os.environ.get("DASHSCOPE_WORKSPACE_ID", "").strip()
    if region in {"singapore", "ap-southeast-1"}:
        if not workspace_id:
            raise QwenTtsError("使用新加坡地域时需要配置 DASHSCOPE_WORKSPACE_ID。")
        dashscope.base_websocket_api_url = f"wss://{workspace_id}.ap-southeast-1.maas.aliyuncs.com/api-ws/v1/inference"
    elif workspace_id:
        dashscope.base_websocket_api_url = f"wss://{workspace_id}.cn-beijing.maas.aliyuncs.com/api-ws/v1/inference"
    else:
        dashscope.base_websocket_api_url = "wss://dashscope.aliyuncs.com/api-ws/v1/inference"

    return AudioFormat, ResultCallback, SpeechSynthesizer


def _split_text(text: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return []

    pieces = re.split(r"([。！？!?；;，,、])", normalized)
    chunks: list[str] = []
    current = ""
    for index in range(0, len(pieces), 2):
        sentence = pieces[index]
        punctuation = pieces[index + 1] if index + 1 < len(pieces) else ""
        part = f"{sentence}{punctuation}".strip()
        if not part:
            continue
        if len(current) + len(part) > 80 and current:
            chunks.append(current)
            current = part
        else:
            current += part
    if current:
        chunks.append(current)
    return chunks or [normalized]


def stream_qwen_tts(text: str) -> Iterator[bytes]:
    chunks = _split_text(text)
    if not chunks:
        raise QwenTtsError("请提供要合成的文本。")

    AudioFormat, ResultCallback, SpeechSynthesizer = _load_dashscope()
    model = os.environ.get("DASHSCOPE_TTS_MODEL", "cosyvoice-v3-flash")
    voice = os.environ.get("DASHSCOPE_TTS_VOICE", "longanyang")
    audio_chunks: queue.Queue[bytes | object] = queue.Queue()
    done = object()
    errors: list[str] = []

    class Callback(ResultCallback):
        def on_data(self, data: bytes) -> None:
            if data:
                audio_chunks.put(data)

        def on_error(self, message: str) -> None:
            errors.append(message)

    def synthesize() -> None:
        try:
            synthesizer = SpeechSynthesizer(
                model=model,
                voice=voice,
                format=AudioFormat.MP3_22050HZ_MONO_256KBPS,
                callback=Callback(),
            )
            for chunk in chunks:
                synthesizer.streaming_call(chunk)
            synthesizer.streaming_complete()
        except Exception as exc:  # SDK errors surface from worker callbacks and calls.
            errors.append(str(exc))
        finally:
            audio_chunks.put(done)

    thread = threading.Thread(target=synthesize, daemon=True)
    thread.start()

    def audio_iterator() -> Iterator[bytes]:
        while True:
            item = audio_chunks.get()
            if item is done:
                break
            yield item  # type: ignore[misc]

        thread.join(timeout=1)
        if errors:
            raise QwenTtsError(errors[-1])

    return audio_iterator()
