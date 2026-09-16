import os
import sys
import time
from pathlib import Path

RTC_LIB = Path(__file__).resolve().parent.parent / "rtc_token_lib"

if str(RTC_LIB) not in sys.path:
    sys.path.insert(0, str(RTC_LIB))

from app_token import AppToken
from service import Service


def generate_rtc_token(channel_id: str, user_id: str, expires_in: int = 3600):
    app_id = os.getenv("RTC_APP_ID")
    app_key = os.getenv("RTC_APP_KEY")

    if not app_id:
        raise RuntimeError("RTC_APP_ID is not configured")

    if not app_key:
        raise RuntimeError("RTC_APP_KEY is not configured")

    if not channel_id:
        raise ValueError("channel_id is required")

    if not user_id:
        raise ValueError("user_id is required")

    expires_in = max(60, min(int(expires_in), 86400))
    timestamp = int(time.time()) + expires_in

    app_token = AppToken(app_id, app_key, timestamp)
    app_token.set_service(Service(channel_id, user_id))

    token = app_token.build()

    return {
        "app_id": app_id,
        "channel_id": channel_id,
        "user_id": user_id,
        "timestamp": timestamp,
        "expires_in": expires_in,
        "token": token,
    }
