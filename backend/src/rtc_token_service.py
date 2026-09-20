import os
import re
import sys
import time
from pathlib import Path

RTC_LIB = Path(__file__).resolve().parent.parent / "rtc_token_lib"

if str(RTC_LIB) not in sys.path:
    sys.path.insert(0, str(RTC_LIB))

from app_token import AppToken
from service import Service


RTC_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is not configured")
    return value


def _token_ttl_seconds() -> int:
    raw_value = os.getenv("RTC_TOKEN_TTL_SECONDS", "3600").strip()
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RuntimeError("RTC_TOKEN_TTL_SECONDS must be an integer") from exc
    return max(60, min(value, 86400))


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

    expires_in = _token_ttl_seconds() if expires_in is None else max(60, min(int(expires_in), 86400))
    timestamp = int(time.time()) + expires_in

    app_token = AppToken(app_id, app_key, timestamp)
    service = Service(channel_id, user_id)
    # The candidate client only needs microphone publishing. Do not grant
    # camera or screen-sharing privileges to the browser token.
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
