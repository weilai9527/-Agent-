"""浏览器身份由身份服务核验。路由决定授权动作，浏览器不能自行指定。"""
import os

import httpx
from fastapi import HTTPException, Request

from .permissions import authorize_staff, legacy_school_id


def session_mode():
    from shared.offline_fixture import offline_fixture_enabled

    if offline_fixture_enabled() and os.getenv("IDENTITY_SESSION_MODE", "legacy") == "legacy":
        return "legacy"
    if os.getenv("IDENTITY_SESSION_MODE", "native") != "native":
        raise HTTPException(503, "正常服务只接受原生身份模式")
    return "native"


def resolve_native(request, scope, kind):
    """网关用自己的服务签名内省会话，浏览器仅提供不透明的会话标识。"""
    from shared.service_security import service_headers
    from shared.service_http import service_origin
    from .browser import check_origin, gateway_origins

    if kind not in {"student", "staff"}:
        raise ValueError("Unknown account kind")
    check_origin(request, extra_origins=gateway_origins(kind))
    token = request.cookies.get(f"identity_{kind}_session")
    if not token or len(token) > 128:
        raise HTTPException(401, "Browser session required")
    school_id = legacy_school_id()
    base = service_origin("identity")
    if os.getenv("APP_ENV", "").lower() == "production" and not base.startswith("https://"):
        raise HTTPException(503, "Identity service URL unavailable")
    try:
        headers = service_headers("identity", actor_id="gateway", actor_type="system",
                                  school_id=school_id, scopes=["identity.session.resolve"])
        with httpx.Client(trust_env=False, follow_redirects=False, timeout=5) as client:
            result = client.post(f"{base}/internal/sessions/{kind}/resolve", headers=headers,
                                 json={"token": token, "action": scope})
        if result.status_code in (401, 403):
            raise HTTPException(result.status_code, "Browser session or action denied")
        result.raise_for_status()
        context = result.json()
        actor_id = context["actor_id"]
        roles = {"student"} if kind == "student" else {"teacher", "admin"}
        if (not isinstance(actor_id, str) or not actor_id or len(actor_id) > 128
                or context["school_id"] != school_id or context["actor_type"] not in roles
                or context["scopes"] != [scope]):
            raise ValueError("Invalid identity response")
        return {key: context[key] for key in ("actor_type", "school_id", "actor_id", "scopes")}
    except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
        raise HTTPException(503, "Identity service unavailable") from exc


def admin_gateway_context(request: Request, scope: str):
    if session_mode() == "native":
        return resolve_native(request, scope, "staff")
    # 只有显式启用的隔离测试夹具能进入此分支。正常网关不导入旧管理应用。
    from admin_backend.offline.main import require_admin, validate_admin_origin

    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        validate_admin_origin(request)
    account = require_admin(request)
    authorize_staff(account, scope)
    return {"actor_id": account["id"], "actor_type": account["actor_type"],
            "school_id": legacy_school_id(), "scopes": [scope]}


def candidate_gateway_context(request: Request, scope: str):
    from .candidate import candidate_gateway_context as resolve_student
    return resolve_student(request, scope)
