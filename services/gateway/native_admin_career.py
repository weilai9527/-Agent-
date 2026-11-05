"""原生教务入口逐项声明职业管理权限，并限制 Excel 上传体积。"""
from fastapi import Depends, HTTPException, Request
from starlette.datastructures import UploadFile as FormUpload

from services.career.admin_adapter import _native_students, _workbook_request, read_payload
from services.identity.gateway import admin_gateway_context
from shared.security_logging import audit_context, bind_actor
from shared.service_http import request_json, resource_segment


# 匹配及 JD 管理接口需要当前学籍范围。名单由受信服务重新计算，不能信任浏览器传入的头、查询或正文。
ROUTES = (
    ("GET", "/campus/program-jobs", "program_jobs.read"),
    ("PUT", "/campus/programs/{program_id}/jobs", "program_jobs.write"),
    ("GET", "/job-postings", "posting.admin.read"),
    ("GET", "/job-postings/template", "posting.admin.read"),
    ("GET", "/job-postings/export", "posting.admin.read"),
    ("POST", "/job-postings/import", "posting.import"),
    ("POST", "/job-postings/sync", "posting.sync"),
    ("POST", "/job-postings", "posting.write"),
    ("PUT", "/job-postings/{posting_id}", "posting.write"),
    ("DELETE", "/job-postings/{posting_id}", "posting.delete"),
    ("GET", "/job-matches", "match.admin.read"),
    ("GET", "/job-matches/{match_id}", "match.admin.read"),
    ("GET", "/jd-submissions", "jd.read"),
    ("POST", "/jd-submissions", "jd.write"),
    ("PUT", "/jd-submissions/{submission_id}", "jd.write"),
    ("DELETE", "/jd-submissions/{submission_id}", "jd.delete"),
    ("POST", "/jd-submissions/{submission_id}/approve", "jd.approve"),
    ("GET", "/catalog/versions", "catalog.admin.read"),
    ("POST", "/catalog/versions", "catalog.write"),
    ("GET", "/catalog/tree", "catalog.admin.read"),
    ("POST", "/catalog/versions/{version_id}/entities/{entity_type}", "catalog.write"),
    ("PATCH", "/catalog/versions/{version_id}/entities/{entity_type}/{entity_id}", "catalog.write"),
    ("DELETE", "/catalog/versions/{version_id}/entities/{entity_type}/{entity_id}", "catalog.write"),
    ("PUT", "/catalog/versions/{version_id}/jobs/{job_role_id}/competencies", "catalog.write"),
    ("POST", "/catalog/versions/{version_id}/publish", "catalog.publish"),
    ("POST", "/catalog/versions/{version_id}/imports", "catalog.import"),
    ("GET", "/catalog/job-suggestions", "catalog.admin.read"),
    ("POST", "/catalog/job-suggestions/{suggestion_id}/review", "catalog.review"),
    ("POST", "/catalog/job-suggestions/{suggestion_id}/merge", "catalog.review"),
    ("POST", "/catalog/job-suggestions/{suggestion_id}/approve-to-draft", "catalog.review"),
)
CREATED = {"/job-postings", "/jd-submissions", "/catalog/versions", "/catalog/versions/{version_id}/imports",
           "/catalog/versions/{version_id}/entities/{entity_type}", "/catalog/job-suggestions/{suggestion_id}/approve-to-draft"}
FILTERS = {"status", "keyword", "version", "jobPostingId", "limit", "mode"}


def _relay(method, template, scope, origins):
    def resolve(request: Request):
        if method != "GET" and request.headers.get("origin") not in origins:
            raise HTTPException(403, "Untrusted browser origin")
        ctx = admin_gateway_context(request, scope)
        bind_actor(request, {"id": ctx["actor_id"]}, ctx["actor_type"])
        audit_context(request, action=scope, target_type="career",
                      target_id=next(reversed(request.path_params.values()), ""))
        return {key: ctx[key] for key in ("school_id", "actor_id", "actor_type")}

    async def forward(request: Request, actor=Depends(resolve)):
        path = "/v1/admin" + template.format(**{k: resource_segment(v) for k, v in request.path_params.items()})
        query = {k: v for k, v in request.query_params.items() if k in FILTERS}
        if scope in {"posting.import", "catalog.import"}:
            # 先鉴权再解析表单。请求大小中间件也限制分块上传，避免解析器先把超限数据写入临时文件。
            async with request.form(max_files=1, max_fields=4) as form:
                upload = form.get("file")
                if not isinstance(upload, FormUpload):
                    raise HTTPException(422, "XLSX file required")
                return await _workbook_request(method, path, scope, actor, query, upload)
        if template in {"/job-postings/template", "/job-postings/export"}:
            return await _workbook_request(method, path, scope, actor, query, None)
        body = await read_payload(request) if method in {"POST", "PUT", "PATCH"} else None
        if scope.startswith(("match.", "jd.")):
            body = {"student_ids": await _native_students(actor), "payload": body}
        return await request_json("career", method, path, actor=actor, scope=scope, params=query, body=body)
    return forward


def _profile_viewer(request, scope):
    # 未核权的路径可能含有私人信息。网关只记动作与结果，具体对象由档案服务审计。
    audit_context(request, action=scope, target_type="student_profile")
    return admin_gateway_context(request, scope)


def mount_career(app, origins):
    from .routes import _endpoint
    app.add_api_route("/api/admin/students/{student_id}/profile",
                      _endpoint("profile", "GET", "/v1/admin/students/{student_id}/profile",
                                "profile.student.read", _profile_viewer, origins),
                      methods=["GET"], name="native.profile.student.read")
    for method, scope in (("GET", "profile.settings.read"), ("PUT", "profile.settings.write")):
        path = "/api/admin/resume-form-settings"
        app.add_api_route(path, _endpoint("profile", method, path, scope, admin_gateway_context, origins),
                          methods=[method], name=f"native.profile.{method}.settings")
    for method, path, scope in ROUTES:
        app.add_api_route("/api/admin" + path, _relay(method, path, scope, origins), methods=[method],
                          status_code=201 if method == "POST" and path in CREATED else 200,
                          name=f"native.career.{method}.{path}")
