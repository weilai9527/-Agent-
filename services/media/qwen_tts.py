"""标准 MP3 合成与实时语音合成共用禁止重定向的 DashScope 传输层，保留标准合成的模型、音色和采样率。"""
from .qwen_realtime_tts import QwenRealtimeTtsError, stream_qwen_realtime_tts


class QwenTtsError(RuntimeError):
    pass


def get_qwen_tts_media_type() -> str:
    return "audio/mpeg"


def stream_qwen_tts(text: str):
    try:
        return stream_qwen_realtime_tts(text, standard=True)
    except QwenRealtimeTtsError as exc:
        raise QwenTtsError(str(exc)) from exc
