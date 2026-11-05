"""管理网关不连接业务数据库，每个受保护动作都向身份服务确认授权。"""
import os

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from services.operations.journal import mount_journal
from fastapi.responses import JSONResponse

from services.career.limits import BodyLimit
from services.identity.browser import gateway_origins
from services.identity.gateway import admin_gateway_context
from services.identity.staff_adapter import mount_staff_auth
from shared.provider_settings import FIELDS as PUBLIC_MODEL_FIELDS
from shared.security_logging import audit_context, bind_actor
from shared.service_http import request_json
from .compatibility import compatibility_routes
from .native_admin_career import mount_career
from .routes import _endpoint, mount_business_routes, read_json_object


def platform_operator(actor):
    return (actor.get("school_id") == "platform" and actor.get("actor_type") == "admin"
            and actor.get("actor_id") in os.environ.get("PROVIDER_PLATFORM_ADMIN_IDS", "").split(","))


async def provider_snapshot(account, snapshot):
    snapshot["permissions"]["canQueryPlatformAudit"] = (
        account["school_id"] == "platform" and account["actor_type"] == "admin" and account["school_wide"]
        and "operations.audit.read" in account["permissions"]
        and account["actor_id"] in os.environ.get("OPERATIONS_PLATFORM_ADMIN_IDS","").split(","))
    if not platform_operator(account) or "model.config.read" not in account["permissions"]:
        return
    # 只有身份域确认的平台人员能委派平台权限，学校管理员在读请求中也不能切换学校标识。
    snapshot["permissions"].update(canViewAgents=True,
                                   canManageSettings="model.config.write" in account["permissions"])
    try:
        snapshot["settings"] = await request_json("providers", "GET", "/settings", actor=account, scope="providers.read")
    except HTTPException:
        snapshot["settings"] = {"providerControlAvailable": False}


def create_app():
    app = FastAPI(title="Staff gateway")
    origins = gateway_origins("staff")
    app.add_middleware(BodyLimit, browser_admin_only=True)
    mount_journal(app, "admin-gateway")
    app.add_middleware(CORSMiddleware, allow_origins=sorted(origins), allow_credentials=True,
                       allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
                       allow_headers=["Content-Type"], expose_headers=["X-Request-ID", "Content-Disposition"])

    @app.exception_handler(HTTPException)
    async def browser_error(_request, exc):
        body = exc.detail if isinstance(exc.detail, dict) else {"error": str(exc.detail)}
        return JSONResponse(body, status_code=exc.status_code, headers=exc.headers)

    @app.get("/api/admin/health")
    def health():
        return {"ok": True, "service": "admin-gateway"}

    def provider_actor(request: Request):
        if request.method != "GET" and request.headers.get("origin") not in origins:
            raise HTTPException(403, "Untrusted browser origin")
        scope = "model.config.read" if request.method == "GET" else "model.config.write"
        actor = admin_gateway_context(request, scope)
        if not platform_operator(actor):
            raise HTTPException(403, "Platform administrator required")
        bind_actor(request, {"id": actor["actor_id"]}, actor["actor_type"])
        return actor

    @app.get("/api/admin/settings")
    async def read_settings(actor=Depends(provider_actor)):
        return await request_json("providers", "GET", "/settings", actor=actor, scope="providers.read")

    @app.patch("/api/admin/settings")
    async def update_settings(request: Request, actor=Depends(provider_actor)):
        body = await read_json_object(request)
        if not body or body.keys() - PUBLIC_MODEL_FIELDS.keys():
            raise HTTPException(400, "Only public provider settings can be changed")
        audit_context(request, action="settings.update", target_type="system_settings", target_id="ai-providers")
        values = await request_json("providers", "PATCH", "/settings", actor=actor, scope="providers.configure", body=body)
        return {"settings": values, "message": "配置已保存。"}

    @app.post("/api/admin/settings/report-providers/test")
    async def probe(request: Request, actor=Depends(provider_actor)):
        audit_context(request, action="settings.report_providers.test", target_type="system_settings", target_id="ai-providers")
        result = await request_json("providers", "POST", "/diagnostics", actor=actor, scope="providers.diagnose")
        return {"providers": result["providers"], "ok": any(p.get("status") == "ok" for p in result["providers"])}

    mount_business_routes(app, staff=True, origins=origins)
    for owner in ("interview", "assessment"):
        for path in ("/v1/records", "/v1/records/{record_id}", "/v1/workbench"):
            app.add_api_route("/api/admin/" + owner + path, _endpoint(
                owner, "GET", path, owner + ".records.read", admin_gateway_context, origins), methods=["GET"])
    # 先验权再调用对应服务。服务故障时保留失败状态，导出结果也不能退回旧页面。
    installed = {(r.path, m) for r in app.routes if hasattr(r, "methods") for m in r.methods}
    for service, rules in compatibility_routes(staff=True).items():
        for method, path, scope, _ in rules:
            if (path, method) not in installed:
                app.add_api_route(path, _endpoint(service, method, path, scope, admin_gateway_context, origins),
                                  methods=[method], name=f"{service}.{method}.{path}")
    for method in ("GET", "PUT"):
        path = "/api/admin/interviewer-policy"
        app.add_api_route(path, _endpoint("interview", method, path, "interview.policy.manage",
                                          admin_gateway_context, origins), methods=[method])
    for suffix, action in (("connection-logs","operations.rtc.read"),("security-logs","operations.audit.read")):
        app.add_api_route("/api/admin/" + suffix, _endpoint("operations","GET","/v1/" + suffix,
                          action, admin_gateway_context, origins),methods=["GET"])
    app.add_api_route("/api/admin/agent-templates", _endpoint("interview","GET","/v1/agent-templates",
                      "interview.templates.read",admin_gateway_context,origins),methods=["GET"])
    mount_career(app, origins)
    mount_staff_auth(app, snapshot_extension=provider_snapshot)
    return app
