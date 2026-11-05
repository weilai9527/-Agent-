"""固定路由的浏览器会话代理；服务凭据认证网关，独立的人类密码或会话认证用户。"""
import os
import re
from ipaddress import ip_address

import httpx
from fastapi import HTTPException, Request

from shared.service_http import service_origin
from shared.service_security import require_service, service_headers
from .browser import check_origin, gateway_origins
from .permissions import legacy_school_id

PROXY_SCOPE = "identity.session.proxy"
_proxy_peer = require_service("identity", PROXY_SCOPE)
_OPERATIONS = {
    "staff": {"login", "me", "logout"},
    "student": {"login", "me", "logout", "change-initial-password"},
}


def verify_proxy(request: Request):
    # 浏览器以密码或会话直接登录。声称来自网关的内部请求必须验证网关签名。
    if not request.headers.getlist("authorization"):
        return
    ctx = _proxy_peer(request)
    if ctx["actor_type"] != "system" or ctx["actor_id"] != "gateway":
        raise HTTPException(403, "Session proxy requires a gateway")
    request.state.session_school = ctx["school_id"]


def client_ip(request):
    if getattr(request.state, "session_school", None):
        try:
            return str(ip_address(request.headers.get("x-identity-client-ip", "")))
        except ValueError:
            pass
    return request.client.host if request.client else "unknown"


async def forward_session(request, response, *, kind, operation, body=None):
    if operation not in _OPERATIONS.get(kind, ()):
        raise ValueError("Unknown session operation")
    method = "GET" if operation == "me" else "POST"
    if request.method != method:
        raise HTTPException(405, "Invalid session method")
    check_origin(request, extra_origins=gateway_origins(kind))
    school = legacy_school_id()
    base = service_origin("identity")
    production = os.getenv("APP_ENV", "").strip().lower() == "production"
    if production and not base.startswith("https://"):
        raise HTTPException(503, "Identity service requires HTTPS")
    cookie_name = f"identity_{kind}_session"
    # 只转发所需字段，不转发任意浏览器请求头、地址或内部凭据。
    try:
        headers = service_headers("identity", actor_id="gateway", school_id=school, actor_type="system",
                                  scopes=[PROXY_SCOPE])
    except (ValueError, KeyError):
        raise HTTPException(503, "Identity service credentials unavailable") from None
    if request.client:
        try:
            headers["X-Identity-Client-IP"] = str(ip_address(request.client.host))
        except ValueError:
            pass
    if operation != "login":
        token = request.cookies.get(cookie_name)
        if token and re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
            headers["Cookie"] = f"{cookie_name}={token}"
    else:
        body = {**body, "school_id": school}
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=False, trust_env=False) as client:
            reply = await client.request(method, f"{base}/sessions/{kind}/{operation}", headers=headers, json=body)
    except httpx.RequestError:
        raise HTTPException(503, "Identity service unavailable") from None
    response.headers["Cache-Control"] = "no-store"
    if reply.status_code != 200:
        # 下游校验错误可能带回密码，网关只向浏览器和日志返回固定错误。
        errors = {400: "登录信息或新密码无效。", 401: "登录凭据无效，请重新登录。", 403: "当前身份不能完成此操作。",
                  409: "账户状态已变更，请重新登录。", 428: "请先修改管理员补发的临时密码。", 422: "提交格式有误。", 429: "登录尝试过于频繁，请稍后再试。"}
        status = reply.status_code if reply.status_code in errors else 503
        raise HTTPException(status, errors.get(status, "身份服务暂时不可用。"), headers={"Cache-Control": "no-store"})
    try:
        data = reply.json()
        if not isinstance(data, dict):
            raise ValueError
        if operation != "logout":
            returned_school = data["user"]["schoolId"] if kind == "student" else data["school_id"]
            if returned_school != school:
                raise ValueError
        if operation in {"login", "change-initial-password"}:
            new_token = reply.cookies.get(cookie_name)
            if not new_token or not re.fullmatch(r"[A-Za-z0-9_-]{43}", new_token):
                raise ValueError
            ttl = 7 * 24 * 3600 if kind == "student" else 8 * 3600
            response.set_cookie(cookie_name, new_token, max_age=ttl, path="/", httponly=True,
                                secure=production or os.getenv("COOKIE_SECURE") == "true", samesite="lax")
        elif operation == "logout":
            response.delete_cookie(cookie_name, path="/", httponly=True,
                                   secure=production or os.getenv("COOKIE_SECURE") == "true", samesite="lax")
    except (ValueError, KeyError, TypeError, httpx.CookieConflict):
        raise HTTPException(502, "Invalid identity service response") from None
    return data
