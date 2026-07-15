from __future__ import annotations

import sqlite3
from urllib.parse import parse_qs, urlparse

from backend.src.password_reset import (
    build_password_reset_url,
    consume_reset_token,
    find_valid_reset_token,
    send_password_reset_email,
    validate_new_password,
)


def _database() -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript(
        """
        CREATE TABLE users (
          id TEXT PRIMARY KEY,
          password_hash TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'normal',
          updated_at TEXT
        );
        CREATE TABLE sessions (id TEXT PRIMARY KEY, user_id TEXT NOT NULL);
        CREATE TABLE password_reset_tokens (
          id TEXT PRIMARY KEY,
          user_id TEXT NOT NULL,
          token_hash TEXT NOT NULL UNIQUE,
          expires_at TEXT NOT NULL,
          used_at TEXT
        );
        INSERT INTO users (id, password_hash) VALUES ('user-1', 'old-hash');
        INSERT INTO sessions (id, user_id) VALUES ('session-1', 'user-1');
        INSERT INTO password_reset_tokens (id, user_id, token_hash, expires_at)
        VALUES ('reset-1', 'user-1', 'token-hash', '2030-01-01 00:00:00');
        INSERT INTO password_reset_tokens (id, user_id, token_hash, expires_at)
        VALUES ('reset-2', 'user-1', 'other-token', '2030-01-01 00:00:00');
        """
    )
    return db


def test_password_validation_enforces_length_and_confirmation():
    assert validate_new_password("short", "short") == "密码至少需要 8 位。"
    assert validate_new_password("long-enough", "different") == "两次输入的密码不一致。"
    assert validate_new_password("long-enough", "long-enough") is None


def test_reset_url_preserves_existing_query(monkeypatch):
    monkeypatch.setenv("PASSWORD_RESET_URL_BASE", "https://app.example/reset?source=email")

    parsed = urlparse(build_password_reset_url("a token/+"))
    query = parse_qs(parsed.query)

    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == "https://app.example/reset"
    assert query == {"source": ["email"], "reset_token": ["a token/+"]}


def test_unconfigured_mail_transport_does_not_send(monkeypatch):
    monkeypatch.delenv("PASSWORD_RESET_SMTP_HOST", raising=False)
    monkeypatch.delenv("PASSWORD_RESET_EMAIL_FROM", raising=False)

    assert send_password_reset_email("candidate@example.com", "secret-token") is False


def test_mail_transport_uses_tls_and_auth_without_logging_token(monkeypatch):
    events = []

    class FakeSmtp:
        def __init__(self, **kwargs):
            events.append(("connect", kwargs["host"], kwargs["port"]))

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def starttls(self, **_kwargs):
            events.append(("starttls",))

        def login(self, username, password):
            events.append(("login", username, password))

        def send_message(self, message):
            events.append(("send", message["To"], message.get_content()))

    monkeypatch.setenv("PASSWORD_RESET_SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("PASSWORD_RESET_SMTP_PORT", "587")
    monkeypatch.setenv("PASSWORD_RESET_SMTP_USERNAME", "smtp-user")
    monkeypatch.setenv("PASSWORD_RESET_SMTP_PASSWORD", "smtp-password")
    monkeypatch.setenv("PASSWORD_RESET_EMAIL_FROM", "no-reply@example.test")
    monkeypatch.setenv("PASSWORD_RESET_URL_BASE", "https://app.example/reset")
    monkeypatch.setattr("backend.src.password_reset.smtplib.SMTP", FakeSmtp)

    assert send_password_reset_email("candidate@example.com", "secret-token") is True
    assert events[0] == ("connect", "smtp.example.test", 587)
    assert events[1] == ("starttls",)
    assert events[2] == ("login", "smtp-user", "smtp-password")
    assert events[3][0:2] == ("send", "candidate@example.com")
    assert "secret-token" in events[3][2]


def test_consume_reset_token_is_one_time_and_revokes_sessions():
    db = _database()
    reset = find_valid_reset_token(db, "token-hash", "2029-01-01 00:00:00")

    assert reset and reset["user_id"] == "user-1"
    assert consume_reset_token(db, "token-hash", "user-1", "new-hash", "2029-01-01 00:00:00") is True
    assert db.execute("SELECT password_hash FROM users WHERE id = 'user-1'").fetchone()[0] == "new-hash"
    assert db.execute("SELECT COUNT(*) FROM sessions WHERE user_id = 'user-1'").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM password_reset_tokens WHERE user_id = 'user-1' AND used_at IS NULL").fetchone()[0] == 0
    assert consume_reset_token(db, "token-hash", "user-1", "another-hash", "2029-01-01 00:00:00") is False


def test_expired_reset_token_is_rejected():
    db = _database()

    assert find_valid_reset_token(db, "token-hash", "2031-01-01 00:00:00") is None
