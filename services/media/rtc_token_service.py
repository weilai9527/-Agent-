import os
import re
import time

# 使用同一包内的编解码器，不能通过修改 sys.path 让第三方同名模块截获令牌签名。
from .token_codec.app_token import AppToken
from .token_codec.service import Service


RTC_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is not configured")
    return value


def _token_ttl_seconds() -> int:
    raw_value = os.getenv("RTC_TOKEN_TTL_SECONDS", "300").strip()
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RuntimeError("RTC_TOKEN_TTL_SECONDS must be an integer") from exc
    return max(60, min(value, 900))


def normalize_rtc_user_name(value: object) -> str:
    user_name = str(value or "").strip() or "候选人"
    while len(user_name.encode("utf-8")) > 64:
        user_name = user_name[:-1]
    return user_name or "候选人"


def generate_rtc_token(channel_id: str, user_id: str, expires_in: int | None = None):
    app_id = _required_env("RTC_APP_ID")
    app_key = _required_env("RTC_APP_KEY")

    if not RTC_ID_PATTERN.fullmatch(channel_id):
        raise ValueError("channel_id must contain only letters, digits, underscores, or hyphens and be at most 64 characters")
    if not RTC_ID_PATTERN.fullmatch(user_id):
        raise ValueError("user_id must contain only letters, digits, underscores, or hyphens and be at most 64 characters")

    expires_in = _token_ttl_seconds() if expires_in is None else max(60, min(int(expires_in), 900))
    timestamp = int(time.time()) + expires_in

    app_token = AppToken(app_id, app_key, timestamp)
    service = Service(channel_id, user_id)
    # 候选人浏览器仅需发布麦克风音频，因此令牌只授予音频发布权限。
    service.add_audio_publish_privilege()
    app_token.set_service(service)

    token = app_token.build()

    return {
        "app_id": app_id,
        "channel_id": channel_id,
        "user_id": user_id,
        "timestamp": timestamp,
        "expires_in": expires_in,
        "token": token,
    }
