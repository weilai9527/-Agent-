"""两个业务网关和服务间调用共用的签名 HTTP 传输。"""
import ipaddress
import os
from urllib.parse import quote, urlsplit

import httpx
from fastapi import HTTPException

from .service_security import service_headers


def service_origin(service: str) -> str:
    # 服务目的地由部署配置决定，防止浏览器利用绝对 URL 或重定向窃取下游令牌。
    value = os.environ.get(f"{service.upper()}_SERVICE_URL", "").rstrip("/")
    try:
        parts = urlsplit(value)
        hostname = parts.hostname or ""
        try:
            local = ipaddress.ip_address(hostname).is_loopback
        except ValueError:
            local = hostname == "localhost"
        valid_scheme = parts.scheme == "https" or (parts.scheme == "http" and local)
        valid_origin = (hostname and not parts.path and not parts.query and not parts.fragment
                        and parts.username is None and parts.password is None)
        _ = parts.port
        if (not valid_scheme or not valid_origin or "\\" in value or "%" in value
                or any(c.isspace() or ord(c) < 32 for c in value)):
            raise ValueError
    except ValueError:
        raise HTTPException(503, f"{service} service endpoint is not configured") from None
    return value


def resource_segment(value: str) -> str:
    if (not value or value in {".", ".."} or any(c in value for c in "/\\%")
            or any(ord(c) < 32 for c in value)):
        raise HTTPException(400, "Invalid resource identifier")
    return quote(value, safe="")


async def service_request(service, method, path, *, actor, scope, body=None, params=None):
    """转发固定路径和已授权的身份，不携带浏览器提供的内部身份头。"""
    if not path.startswith("/") or path.startswith("//") or "?" in path or "#" in path:
        raise ValueError("Supply a service-local path and separate query parameters")
    url = service_origin(service) + path
    try:
        headers = service_headers(service, actor_id=actor["actor_id"], school_id=actor["school_id"],
                                  actor_type=actor["actor_type"], scopes=[scope])
    except (KeyError, ValueError):
        raise HTTPException(503, "Service credentials unavailable") from None
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, url, params=params, json=body, headers=headers)
    except httpx.RequestError:
        raise HTTPException(503, f"{service} service unavailable") from None
    if response.status_code == 503:
        # 下游明确表示暂不可用，调用端可提示等待；不转发上游错误正文或旧业务数据。
        raise HTTPException(503, f"{service} service unavailable")
    if 300 <= response.status_code < 400 or response.status_code >= 500:
        raise HTTPException(502, f"{service} service failed to handle the request")
    if response.status_code >= 400:
        # 校验失败可能回显学生输入。仅向浏览器传递限长提示，不复制内部响应或凭据头。
        try:
            detail = response.json().get("detail")
        except (ValueError, AttributeError):
            detail = None
        raise HTTPException(response.status_code, detail[:300] if isinstance(detail, str) else "Request rejected")
    return response


async def request_json(service, method, path, *, actor, scope, body=None, params=None):
    response = await service_request(service, method, path, actor=actor, scope=scope,
                                     body=body, params=params)
    if response.status_code == 204:
        return None
    try:
        return response.json()
    except ValueError:
        raise HTTPException(502, f"Invalid response from {service} service") from None
