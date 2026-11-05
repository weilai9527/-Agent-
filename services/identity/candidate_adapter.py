"""将原有学生登录 URL 接到持有会话的原生身份服务。"""
import re

from fastapi import APIRouter, HTTPException, Request, Response

from .gateway import session_mode
from .session_proxy import forward_session


class NativeStudentCookie:
    """阻止旧 HTTP 和 WebSocket 处理器继续使用切换前的会话。"""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in {"http", "websocket"}:
            headers = []
            tokens = []
            for key, value in scope.get("headers", ()):
                if key.lower() != b"cookie":
                    headers.append((key, value))
                    continue
                for pair in value.split(b";"):
                    name, _, token = pair.strip().partition(b"=")
                    if name == b"identity_student_session":
                        tokens.append(token)
            # 只接受身份服务写入的唯一规范会话，避免不同解析器选中不同账号。
            if len(tokens) == 1 and re.fullmatch(rb"[A-Za-z0-9_-]{43}", tokens[0]):
                headers.append((b"cookie", b"identity_student_session=" + tokens[0]))
            scope = {**scope, "headers": headers}
        await self.app(scope, receive, send)


def mount_candidate_auth(app):
    if session_mode() != "native":
        return
    app.add_middleware(NativeStudentCookie)
    prefix = "/api/auth/"
    # 旧自助找回和注册会修改另一套账号库。原生入口显式封闭这些路径，在身份服务故障时仍然关闭。
    app.router.routes[:] = [r for r in app.router.routes if not getattr(r, "path", "").startswith(prefix)]
    router = APIRouter(prefix="/api/auth")

    @router.post("/login")
    async def login(request: Request, response: Response, body: dict):
        payload = {"student_no": body.get("student_no") or body.get("studentNo"), "password": body.get("password")}
        return await forward_session(request, response, kind="student", operation="login", body=payload)

    @router.get("/me")
    async def me(request: Request, response: Response):
        try:
            return await forward_session(request, response, kind="student", operation="me")
        except HTTPException as exc:
            if exc.status_code != 401:
                raise
            response.headers["Cache-Control"] = "no-store"
            return {"user": None}

    @router.post("/change-initial-password")
    async def change(request: Request, response: Response, body: dict):
        payload = {"password": body.get("password"), "confirm_password": body.get("confirm_password") or body.get("confirmPassword")}
        return await forward_session(request, response, kind="student", operation="change-initial-password", body=payload)

    @router.post("/logout")
    async def logout(request: Request, response: Response):
        return await forward_session(request, response, kind="student", operation="logout")

    def unavailable():
        raise HTTPException(403, "请联系学校管理员处理账号。")

    for path in ("/register", "/password-reset/request", "/password-reset/verify", "/password-reset/confirm"):
        router.add_api_route(path, unavailable, methods=["POST"])
    app.include_router(router)
