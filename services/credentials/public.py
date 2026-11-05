"""公开只读的 ASGI 入口。由调用方提供验真函数，启动时不执行建表操作。"""
import base64
import hashlib
from html import escape

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.exceptions import HTTPException

from .signing import SigningConfigurationError


_STYLE = """
:root { color-scheme: light; font-family: system-ui, sans-serif; color: #172635; background: #f0f5f5; }
body { margin: 0; padding: 8vh 1rem; }
main { box-sizing: border-box; max-width: 36rem; margin: auto; padding: clamp(1.5rem, 5vw, 3rem);
  background: white; border-top: .35rem solid #226b66; border-radius: .5rem; }
h1 { font-size: 1.75rem; margin: 0 0 1rem; }
p { line-height: 1.6; }
dl { margin: 1.5rem 0 0; }
dt { margin-top: 1rem; color: #415464; font-size: .9rem; }
dd { margin: .25rem 0; overflow-wrap: anywhere; line-height: 1.6; }
"""
_STYLE_HASH = base64.b64encode(hashlib.sha256(_STYLE.encode()).digest()).decode()
_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Robots-Tag": "noindex, nofollow",
    "X-Content-Type-Options": "nosniff",
    "Vary": "Accept",
    "Content-Security-Policy": (
        f"default-src 'none'; style-src 'sha256-{_STYLE_HASH}'; "
        "frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
    ),
}


def _html_requested(request):
    # 默认返回 JSON；浏览器明确优先接受 text/html 时才返回网页。
    weights = {}
    for item in request.headers.get("accept", "").lower().split(","):
        media, *params = (part.strip() for part in item.split(";"))
        quality = next((part[2:] for part in params if part.startswith("q=")), "1")
        try:
            weight = float(quality)
        except ValueError:
            continue
        if 0 <= weight <= 1:
            weights[media] = max(weights.get(media, 0), weight)
    html = weights.get("text/html", 0)
    json_weight = weights.get("application/json", weights.get("application/*", weights.get("*/*", 0)))
    return html > 0 and html >= json_weight


def _page(message, rows=(), status_code=200):
    fields = "".join(f"<dt>{escape(label)}</dt><dd>{escape(str(value))}</dd>" for label, value in rows)
    details = f"<dl>{fields}</dl>" if fields else ""
    return HTMLResponse(
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>教学证书验真</title><style>{_STYLE}</style></head><body><main>"
        f"<h1>教学证书验真</h1><p>{escape(message)}</p>{details}</main></body></html>",
        status_code=status_code,
    )


def _public_fields(result):
    # 将浏览器和 JSON 共用的披露范围固定在出口，查证函数中的新字段默认保持私有。
    status = result["status"]
    if status == "invalid_signature":
        return {"status": status, "valid": False}
    if status not in ("valid", "revoked") or result["valid"] is not (status == "valid"):
        raise HTTPException(503)
    public = {key: result[key] for key in ("status", "valid", "title", "issuer", "issued_at")}
    anchor = result["anchor"]
    public["anchor"] = {key: anchor[key] for key in (
        "status", "network", "fixture", "tx_hash", "block_number",
    ) if key in anchor}
    return public


def _render(result):
    status = result["status"]
    if status == "invalid_signature":
        return _page("学校签名验证失败，无法确认此证书。")
    anchor = result["anchor"]
    state = {"pending": "等待提交", "submitted": "交易已提交，等待确认",
             "confirmed": "已确认", "failed": "存证失败"}.get(anchor["status"], "尚未确认")
    if anchor.get("fixture") or anchor.get("network") == "fixture":
        state = "本地测试链（fixture） · " + state
    rows = [("证书类型", result["title"]), ("签发学校", result["issuer"]),
            ("签发时间", result["issued_at"]), ("撤销存证" if status == "revoked" else "签发存证", state)]
    message = "此证书已撤销。" if status == "revoked" else "学校签名已验证，此证书当前有效。"
    return _page(message, rows)


def create_public_app(lookup, *, lifespan=None):
    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None, redirect_slashes=False)

    @app.middleware("http")
    async def privacy_headers(request, call_next):
        response = await call_next(request)
        response.headers.update(_HEADERS)
        return response

    @app.exception_handler(HTTPException)
    @app.exception_handler(SigningConfigurationError)
    async def error(request, exc):
        code = exc.status_code if isinstance(exc, HTTPException) else 503
        message = {404: "未找到此证书。", 405: "此地址仅支持只读查询。"}.get(code, "暂时无法验证证书。")
        return (_page(message, status_code=code) if _html_requested(request)
                else JSONResponse({"detail": message}, status_code=code))

    @app.exception_handler(Exception)
    async def unavailable(request, exc):
        # 未捕获的数据库错误由外层中间件处理，此路径需要自行添加隐私响应头。
        response = await error(request, exc)
        response.headers.update(_HEADERS)
        return response

    @app.get("/verify/{serial}")
    def verify(serial: str, request: Request):
        result = _public_fields(lookup(serial))
        return _render(result) if _html_requested(request) else result

    return app
