"""学生日常使用的 HTTP 和 WebSocket 入口，业务数据由所属服务读写。"""
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from services.operations.journal import mount_journal
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from services.identity.browser import gateway_origins
from services.identity.gateway import resolve_native
from .compatibility import compatibility_routes
from .native_account import mount_native_account
from .native_media import mount_native_media
from .routes import STUDENT_ROUTES, _endpoint


def _student_session(request, scope):
    # 逐操作校验原生学生会话。学校和学生从身份服务取得，请求体不能替换这两个值。
    return resolve_native(request, scope, "student")


def create_app():
    app = FastAPI(title="原生学生网关")
    origins = gateway_origins("student")
    mount_journal(app, "student-gateway")
    app.add_middleware(CORSMiddleware, allow_origins=sorted(origins), allow_credentials=True,
                       allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
                       allow_headers=["Content-Type"], expose_headers=["X-Request-ID", "Content-Disposition"])

    @app.exception_handler(HTTPException)
    async def browser_error(_request, exc):
        # 媒体配额不足时，页面还要读取 fallback 才能保留当前题并切换为文字作答。
        if isinstance(exc.detail, dict):
            body = exc.detail
        else:
            message = str(exc.detail)
            if message.isascii():
                message = {
                    401: "请重新登录后再试。",
                    403: "当前会话无权执行这个操作。",
                    404: "未找到请求的记录或接口。",
                    429: "请求达到额度或频率上限，请稍后再试。",
                    502: "业务服务返回异常，请稍后重试。",
                    503: "服务暂时不可用，请稍后重试。",
                }.get(exc.status_code, message)
            body = {"error": message}
        headers = {**(exc.headers or {}), "Cache-Control": "no-store"}
        return JSONResponse(body, status_code=exc.status_code, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request, _exc):
        # 默认校验错误可能回显原请求中的密码或整份简历。
        return JSONResponse({"error": "提交格式有误，请检查后重试。"}, status_code=422,
                            headers={"Cache-Control": "no-store"})

    @app.get("/api/health")
    def health():
        return {"ok": True, "service": "student-gateway"}

    mount_native_account(app)
    mount_native_media(app)

    def remote(service, method, browser_path, owner_path, scope):
        endpoint = _endpoint(service, method, owner_path, scope, _student_session, origins)
        app.add_api_route(browser_path, endpoint, methods=[method], name=f"{service}.{method}.{owner_path}")

    for service, routes in STUDENT_ROUTES.items():
        for method, path, scope in routes:
            remote(service, method, f"/api/{service}{path}", path, scope)

    # 保留原学生 URL。即使未配置某个服务，也挂载同一条授权路由并在访问时返回 503；
    # 真正不存在的资源保留 404，两个情况都不会启动应急应用或接触旧库。
    for service, routes in compatibility_routes(staff=False).items():
        for method, path, scope, _ in routes:
            remote(service, method, path, path, scope)
    policy = "/api/interviewer-policy"
    remote("interview", "GET", policy, policy, "interview.read")
    return app
