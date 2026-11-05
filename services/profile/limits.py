"""在解析表单或 JSON 前限制 ASGI 请求正文的字节数。"""

from fastapi import HTTPException
from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse

from .parser import MAX_FILE


class BodyLimit:
    """按接收的实际字节限制请求，分块上传同样受限，避免超大文件先落临时盘。"""
    def __init__(self, app, profile_only=False):
        self.app = app
        self.profile_only = profile_only

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope["path"].rstrip("/")
        private = (path in {"/api/profile", "/api/resume-form", "/api/admin/resume-form-settings"}
                   or path.startswith(("/api/profile/", "/api/resume-form/"))
                   or (path.startswith("/v1/admin/students/") and path.endswith("/profile")))
        if self.profile_only and not private:
            return await self.app(scope, receive, send)

        async def send_response(message):
            if private and message["type"] == "http.response.start":
                MutableHeaders(scope=message)["Cache-Control"] = "private, no-store"
            await send(message)

        if scope["method"] not in {"PUT", "POST"}:
            return await self.app(scope, receive, send_response)
        upload = path == "/api/profile/resume-upload"
        limit = MAX_FILE + 65536 if upload else 256 * 1024
        for key, value in scope["headers"]:
            if key == b"content-length" and (not value.isdigit() or len(value) > 12 or int(value) > limit):
                return await JSONResponse({"detail": "请求过大。"}, 413)(scope, receive, send_response)
        total = 0

        async def limited_receive():
            nonlocal total
            message = await receive()
            total += len(message.get("body", b""))
            if total > limit:
                raise HTTPException(413, "请求过大。")
            return message

        return await self.app(scope, limited_receive, send_response)
