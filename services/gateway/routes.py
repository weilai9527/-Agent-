"""浏览器接口采用白名单，持久任务、内部回执及事件消费接口不暴露给浏览器。"""
import json
import os

from fastapi import Depends, HTTPException, Request
from fastapi.responses import Response

from services.identity.gateway import admin_gateway_context, candidate_gateway_context
from shared.security_logging import audit_context, bind_actor
from shared.service_http import resource_segment, service_request


# 每项显式指定方法、外部路径和委派动作，服务新增内部事件接口时不会自动公开。
STUDENT_ROUTES = {
    "training": [
        ("GET", "/tasks", "training.read"),
        ("POST", "/tasks/{task_id}/attempts", "training.start"),
    ],
    "analytics": [("GET", "/v1/me/weaknesses", "analytics.self.read")],
    "credentials": [
        ("POST", "/applications", "credential.apply"),
        ("GET", "/me/applications", "credential.read"),
    ],
}

ADMIN_ROUTES = {
    "identity": [
        ("GET", "/v1/student-accounts/summary", "student.read"),
        ("GET", "/v1/student-accounts/pending-summary", "registration.read"),
        ("GET", "/v1/organization", "organization.read"),
        ("POST", "/v1/organization/import", "organization.manage"),
        ("POST", "/v1/classes/{class_id}/roster/import", "roster.import"),
        ("POST", "/students/import", "student.import"),
        ("POST", "/v1/students/{student_id}/reset-password", "student.reset"),
        ("PATCH", "/v1/students/{student_id}/status", "student.status"),
        ("POST", "/v1/staff", "permissions.manage"),
        ("PUT", "/v1/staff/{staff_id}/grants", "permissions.manage"),
        ("GET", "/v1/legacy-permission-requests", "permissions.manage"),
        ("GET", "/v1/audit", "audit.read"),
    ],
    "training": [
        ("GET", "/classes", "training.read"),
        ("GET", "/tasks", "training.read"),
        ("GET", "/tasks/{task_id}/roster", "training.read"),
        ("POST", "/tasks", "training.assign"),
    ],
    "analytics": [
        ("GET", "/v1/teaching/summary", "analytics.teaching.read"),
        ("GET", "/v1/teaching/weaknesses", "analytics.teaching.read"),
        ("POST", "/v1/teaching/practice", "analytics.practice.assign"),
    ],
    "credentials": [
        ("GET", "/students/{student_id}/applications", "credential.read"),
        ("POST", "/applications/{id}/review", "credential.approve"),
        ("POST", "/applications/{id}/issue", "credential.issue"),
        ("POST", "/certificates/{id}/revoke", "credential.revoke"),
        ("POST", "/certificates/{id}/reissue", "credential.reissue"),
    ],
}


async def read_json_object(request):
    data = bytearray()
    async for block in request.stream():
        if len(data) + len(block) > 1024 * 1024:
            raise HTTPException(413, "Request too large")
        data.extend(block)
    if not data:
        return None
    if request.headers.get("content-type", "").partition(";")[0].lower() != "application/json":
        raise HTTPException(415, "Use application/json")
    try:
        value = json.loads(data)
    except (ValueError, RecursionError):
        raise HTTPException(400, "Invalid JSON body") from None
    if not isinstance(value, dict):
        raise HTTPException(422, "Expected a JSON object")
    return value


def _endpoint(service, method, template, scope, resolve, allowed_origins):
    def authenticated(request: Request):
        if method not in {"GET", "HEAD"} and request.headers.get("origin") not in allowed_origins:
            raise HTTPException(403, "Untrusted browser origin")
        actor = resolve(request, scope)
        bind_actor(request, {"id": actor["actor_id"], "school_id": actor["school_id"]}, actor["actor_type"])
        if method not in {"GET", "HEAD"} or scope in {
                "operations.rtc.read", "operations.audit.read", "assessment.export", "assessment.history", "interview.records.read", "assessment.records.read", "audit.read"}:
            audit_context(request, action=scope, target_type=service)
        return actor

    async def forward(request: Request, actor=Depends(authenticated)):
        path = template.format(**{k: resource_segment(v) for k, v in request.path_params.items()})
        body = await read_json_object(request) if method not in {"GET", "HEAD"} else None
        result = await service_request(service, method, path, actor=actor, scope=scope,
                                       params=request.query_params.multi_items(), body=body)
        headers = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
        for name in ("content-type", "content-disposition"):
            if name in result.headers:
                headers[name] = result.headers[name]
        return Response(result.content, status_code=result.status_code, headers=headers)

    return forward


def mount_business_routes(app, *, staff: bool, origins):
    resolve = admin_gateway_context if staff else candidate_gateway_context
    prefix = "/api/admin" if staff else "/api"
    for service, routes in (ADMIN_ROUTES if staff else STUDENT_ROUTES).items():
        for method, path, scope in routes:
            app.add_api_route(f"{prefix}/{service}{path}",
                              _endpoint(service, method, path, scope, resolve, set(origins)),
                              methods=[method], name=f"{service}.{method}.{path}")
    if staff:
        for method, scope in (("GET", "usage.read"), ("PUT", "usage.configure")):
            app.add_api_route("/api/admin/usage/quota",
                              _endpoint("usage", method, "/internal/usage/quota", scope, resolve, set(origins)),
                              methods=[method], name=scope)
    # 同一组浏览器地址只绑定一个业务所有者；下游故障时不能改走本地第二条写入路径。
    from .compatibility import compatibility_routes
    for service, rules in compatibility_routes(staff).items():
        for method, path, scope, always in rules:
            if not always and not os.environ.get(f"{service.upper()}_SERVICE_URL"):
                continue
            app.router.routes[:] = [
                r for r in app.router.routes
                if not (getattr(r, "path", None) == path and method in (getattr(r, "methods", None) or ()))
            ]
            app.add_api_route(path, _endpoint(service, method, path, scope, resolve, set(origins)),
                              methods=[method], name=f"{service}.{method}.{path}")
