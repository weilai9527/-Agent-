"""每次媒体操作先确认一个准入单位已结算，再向厂商派发；账本不可用时提示转文字。"""
import re
from uuid import uuid4

import httpx
from fastapi import HTTPException
from jwt.exceptions import PyJWTError

from shared.service_http import service_origin
from shared.service_security import service_headers


def admit(actor, operation):
    identity = {key: actor[key] for key in ("actor_id", "actor_type", "school_id")}
    request_id = uuid4().hex
    try:
        path = service_origin("usage") + "/internal/usage/reservations"
    except HTTPException:
        raise HTTPException(503, {"code": "usage_unavailable", "fallback": "text"}) from None

    def post(client, url, scope, payload):
        # 账本可能已提交但响应丢失。仅对传输错误重试，沿用同一业务键或预留号。
        for attempt in range(2):
            try:
                return client.post(url, headers=service_headers("usage", **identity, scopes=[scope]), json=payload)
            except httpx.TransportError:
                if attempt:
                    raise

    try:
        with httpx.Client(timeout=5, trust_env=False, follow_redirects=False) as client:
            reserved = post(client, path, "usage.reserve",
                            {"request_id": request_id, "resource": "media", "units": 1, "ttl_seconds": 60})
            if reserved.status_code == 429:
                raise HTTPException(429, {"code": "quota_exhausted", "operation": operation, "fallback": "text"})
            reserved.raise_for_status()
            hold = reserved.json()
            rid = hold["reservation_id"]
            if (not isinstance(rid, str) or not re.fullmatch(r"[0-9a-f]{32}", rid)
                    or hold["state"] != "reserved" or hold["units"] != 1 or hold["resource"] != "media"):
                raise ValueError("Reservation unavailable")
            settled = post(client, f"{path}/{rid}/settle", "usage.settle", {"actual_units": 1})
            settled.raise_for_status()
            result = settled.json()
            if (result["reservation_id"] != rid or result["state"] != "settled"
                    or result["actual_units"] != 1 or result["resource"] != "media"):
                raise ValueError("Unconfirmed settlement")
    except (httpx.HTTPError, PyJWTError, ValueError, TypeError, KeyError):
        raise HTTPException(503, {"code": "usage_unavailable", "fallback": "text"}) from None
