"""生产浏览器会话强制使用 HTTPS 安全 Cookie。"""
import os


def secure_cookie(setting="COOKIE_SECURE"):
    return (os.getenv("APP_ENV", "").strip().lower() == "production"
            or os.getenv(setting, "").strip().lower() == "true")
