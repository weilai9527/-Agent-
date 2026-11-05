"""离线调用保留原导入名；RTC 和语音的实际实现位于媒体服务。"""
import sys

from services.media import qwen_tts as _native

sys.modules[__name__] = _native
