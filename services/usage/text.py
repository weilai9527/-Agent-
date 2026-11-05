"""持久任务使用的同步文字配额客户端。每个模型请求占用一个文字单位。"""
import hashlib
import json
import re
import time
from dataclasses import dataclass
from typing import Literal

import httpx
from fastapi import HTTPException
from jwt.exceptions import PyJWTError

from shared.service_http import service_origin
from shared.service_security import service_headers

RESERVATIONS = "/internal/usage/reservations"


@dataclass(frozen=True)
class TextAdmission:
    state: Literal["reserved", "in_flight", "settled", "deferred"]
    request_id: str
    reservation_id: str | None = None
    expires_at: int | None = None
    actual_units: int | None = None
    reason: str | None = None


def _request_id(interview_id, operation_id, purpose):
    # 重试复用固定的业务操作标识和服务端指定的用途。分别编码各字段，避免输入中的分隔符造成键冲突。
    parts = (interview_id, operation_id, purpose)
    if any(not isinstance(p, str) or not p.strip() or len(p) > 128 for p in parts):
        raise ValueError("Expected persistent interview, operation and purpose identifiers")
    return "text." + hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()


def _post(actor, scope, path, payload):
    url = service_origin("usage") + path
    try:
        headers = service_headers("usage", actor_id=actor["actor_id"], school_id=actor["school_id"],
                                  actor_type=actor["actor_type"], scopes=[scope])
    except (KeyError, ValueError, PyJWTError):
        raise HTTPException(503, "Usage service credential unavailable") from None
    try:
        with httpx.Client(timeout=5, follow_redirects=False, trust_env=False) as client:
            response = client.post(url, headers=headers, json=payload)
    except httpx.RequestError:
        raise HTTPException(503, "Usage service unavailable") from None
    if response.status_code != 200:
        status = response.status_code
        raise HTTPException(status if 400 <= status < 500 else 503, "Usage request rejected")
    try:
        result = response.json()
        if (not isinstance(result, dict) or not isinstance(result.get("reservation_id"), str)
                or not re.fullmatch(r"[a-f0-9]{32}", result["reservation_id"])
                or result.get("resource") != "text" or type(result.get("units")) is not int or result["units"] != 1
                or type(result.get("expires_at")) is not int):
            raise ValueError()
        state = result["state"]
        actual = result["actual_units"]
        if state == "settled":
            if type(actual) is not int or actual not in (0, 1):
                raise ValueError()
        elif state not in ("reserved", "in_flight", "expired") or actual is not None:
            raise ValueError()
        return result
    except (KeyError, ValueError):
        raise HTTPException(502, "Invalid response from usage service") from None


def reserve_text(actor, *, interview_id, operation_id, purpose, required_seconds=60, ttl_seconds=300):
    """向供应商派发前预留额度。任务队列另行判定执行权。

    只有持有效租约并确认该次尝试尚未派发的工作进程才可发送模型请求。
    若用量已结算，应重放已有结果或进入核对流程。
    """
    if (type(ttl_seconds) is not int or type(required_seconds) is not int
            or not 1 <= required_seconds <= ttl_seconds <= 3600):
        raise ValueError("Expected a lease covering the operation and settlement")
    key = _request_id(interview_id, operation_id, purpose)
    payload = {"resource": "text", "request_id": key, "units": 1, "ttl_seconds": ttl_seconds}
    try:
        result = _post(actor, "usage.reserve", RESERVATIONS, payload)
    except HTTPException as exc:
        if exc.status_code == 429:
            return TextAdmission("deferred", key, reason="quota_exhausted")
        if exc.status_code >= 500:
            return TextAdmission("deferred", key, reason="usage_unavailable")
        raise
    rid, expiry = result["reservation_id"], result["expires_at"]
    if result["state"] == "settled":
        return TextAdmission("settled", key, rid, expiry, result["actual_units"])
    if result["state"] == "in_flight":
        return TextAdmission("in_flight", key, rid, expiry)
    if result["state"] == "expired":
        return TextAdmission("deferred", key, rid, expiry, reason="reservation_expired")
    if expiry - time.time() < required_seconds:
        return TextAdmission("deferred", key, rid, expiry, reason="insufficient_lease")
    return TextAdmission("reserved", key, rid, expiry)


def begin_text(actor, reservation_id):
    """发送前确认预留进入执行状态；重复确认不会产生扣费。"""
    if not isinstance(reservation_id, str) or not re.fullmatch(r"[a-f0-9]{32}", reservation_id):
        raise ValueError("Invalid text reservation identifier")
    result = _post(actor, "usage.dispatch", f"{RESERVATIONS}/{reservation_id}/begin", {})
    if result["reservation_id"] != reservation_id or result["state"] != "in_flight":
        raise HTTPException(502, "Unconfirmed text dispatch hold")
    return result


def settle_text(actor, reservation_id, *, actual_units):
    """结算确认丢失时，以原预留号和相同实际用量重试。"""
    if not isinstance(reservation_id, str) or not re.fullmatch(r"[a-f0-9]{32}", reservation_id):
        raise ValueError("Invalid text reservation identifier")
    if type(actual_units) is not int or actual_units not in (0, 1):
        raise ValueError("Expected zero or one actual text request")
    result = _post(actor, "usage.settle", f"{RESERVATIONS}/{reservation_id}/settle",
                   {"actual_units": actual_units})
    if (result["reservation_id"] != reservation_id or result["state"] != "settled"
            or result["actual_units"] != actual_units):
        raise HTTPException(502, "Unconfirmed text settlement")
    return result
