"""职业服务与浏览器网关共用的入站请求体积限制。"""
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from starlette.datastructures import Headers, MutableHeaders


class BodyLimit:
    """表单写入临时文件前同时校验 Content-Length 和分块累计字节数。"""
    def __init__(self, app, *, browser_admin_only=False, browser_student_only=False):
        self.app = app
        if browser_admin_only and browser_student_only:
            raise ValueError("Choose one browser gateway")
        self.prefixes = ()
        if browser_admin_only:
            self.prefixes = ("/api/admin/catalog", "/api/admin/job-postings",
                             "/api/admin/job-matches", "/api/admin/jd-submissions")
        elif browser_student_only:
            self.prefixes = ("/api/catalog", "/api/job-postings", "/api/job-matches")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        if self.prefixes and not any(path == prefix or path.startswith(prefix + "/") for prefix in self.prefixes):
            return await self.app(scope, receive, send)
        headers = Headers(scope=scope)
        limit = 2 * 1024 * 1024
        if headers.get("content-type", "").lower().startswith("multipart/"):
            if path.endswith("/job-postings/import"):
                limit = 5 * 1024 * 1024 + 65536
            elif "/catalog/versions/" in path and path.endswith("/imports"):
                limit = 10 * 1024 * 1024 + 65536
        try:
            size = int(headers.get("content-length", "0"))
        except ValueError:
            size = -1
        if size < 0 or size > limit:
            return await JSONResponse({"detail": "请求正文过大或无效。"}, 413)(scope, receive, send)
        total = 0

        async def bounded_receive():
            nonlocal total
            msg = await receive()
            total += len(msg.get("body", b""))
            if total > limit:
                raise HTTPException(413, "请求正文过大。")
            return msg

        async def private_send(message):
            if message["type"] == "http.response.start" and any(
                    word in path.split("/") for word in ("job-matches", "jd-submissions")):
                MutableHeaders(scope=message)["Cache-Control"] = "private, no-store"
            await send(message)

        return await self.app(scope, bounded_receive, private_send)
