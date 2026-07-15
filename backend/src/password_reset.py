from __future__ import annotations

from dataclasses import dataclass
from email.message import EmailMessage
import os
import smtplib
import ssl
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


@dataclass(frozen=True)
class PasswordResetEmailConfig:
    host: str
    port: int
    username: str
    password: str
    sender: str
    use_tls: bool
    use_ssl: bool
    timeout: float


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def password_reset_email_config() -> PasswordResetEmailConfig | None:
    host = os.environ.get("PASSWORD_RESET_SMTP_HOST", "").strip()
    sender = os.environ.get("PASSWORD_RESET_EMAIL_FROM", "").strip()
    if not host or not sender:
        return None
    return PasswordResetEmailConfig(
        host=host,
        port=int(os.environ.get("PASSWORD_RESET_SMTP_PORT", "587")),
        username=os.environ.get("PASSWORD_RESET_SMTP_USERNAME", "").strip(),
        password=os.environ.get("PASSWORD_RESET_SMTP_PASSWORD", ""),
        sender=sender,
        use_tls=_env_bool("PASSWORD_RESET_SMTP_USE_TLS", True),
        use_ssl=_env_bool("PASSWORD_RESET_SMTP_USE_SSL", False),
        timeout=float(os.environ.get("PASSWORD_RESET_SMTP_TIMEOUT", "10")),
    )


def build_password_reset_url(token: str) -> str:
    configured = os.environ.get("PASSWORD_RESET_URL_BASE", "").strip()
    if configured:
        base_url = configured
    else:
        origin = os.environ.get("FRONTEND_ORIGIN", "http://127.0.0.1:5173").split(",", 1)[0].strip()
        base_url = f"{origin.rstrip('/')}/"
    parsed = urlparse(base_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["reset_token"] = token
    return urlunparse(parsed._replace(query=urlencode(query)))


def send_password_reset_email(email: str, token: str) -> bool:
    config = password_reset_email_config()
    if not config:
        return False

    message = EmailMessage()
    message["Subject"] = "重置你的多 Agent 面试系统密码"
    message["From"] = config.sender
    message["To"] = email
    reset_url = build_password_reset_url(token)
    message.set_content(
        "我们收到了你的密码重置申请。\n\n"
        f"请在 20 分钟内打开以下链接设置新密码：\n{reset_url}\n\n"
        "如果不是你本人发起，请忽略此邮件。该链接只能使用一次。"
    )

    smtp_class = smtplib.SMTP_SSL if config.use_ssl else smtplib.SMTP
    kwargs: dict[str, Any] = {"host": config.host, "port": config.port, "timeout": config.timeout}
    if config.use_ssl:
        kwargs["context"] = ssl.create_default_context()
    with smtp_class(**kwargs) as client:
        if config.use_tls and not config.use_ssl:
            client.starttls(context=ssl.create_default_context())
        if config.username:
            client.login(config.username, config.password)
        client.send_message(message)
    return True


def validate_new_password(password: str, confirmation: str | None = None) -> str | None:
    if len(password) < 8:
        return "密码至少需要 8 位。"
    if len(password) > 256:
        return "密码不能超过 256 位。"
    if confirmation is not None and password != confirmation:
        return "两次输入的密码不一致。"
    return None


def find_valid_reset_token(db: Any, token_hash: str, now: str) -> dict | None:
    cursor = db.execute(
        """
        SELECT tokens.id, tokens.user_id, tokens.expires_at
        FROM password_reset_tokens AS tokens
        JOIN users ON users.id = tokens.user_id
        WHERE tokens.token_hash = ?
          AND tokens.used_at IS NULL
          AND tokens.expires_at > ?
          AND users.status = 'normal'
        """,
        (token_hash, now),
    )
    try:
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        cursor.close()


def consume_reset_token(db: Any, token_hash: str, user_id: str, password_hash: str, now: str) -> bool:
    with db:
        cursor = db.execute(
            """
            UPDATE password_reset_tokens
            SET used_at = ?
            WHERE token_hash = ? AND user_id = ? AND used_at IS NULL AND expires_at > ?
            """,
            (now, token_hash, user_id, now),
        )
        try:
            consumed = cursor.rowcount == 1
        finally:
            cursor.close()
        if not consumed:
            return False
        cursor = db.execute(
            "UPDATE users SET password_hash = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND status = 'normal'",
            (password_hash, user_id),
        )
        cursor.close()
        cursor = db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        cursor.close()
        cursor = db.execute(
            "UPDATE password_reset_tokens SET used_at = ? WHERE user_id = ? AND used_at IS NULL",
            (now, user_id),
        )
        cursor.close()
    return True
