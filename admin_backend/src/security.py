"""离线管理夹具使用原有密码和会话格式。正式算法仅由共享身份组件持有。"""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
from cryptography.fernet import Fernet, InvalidToken

from shared.account_security import (
    create_token, hash_staff_password as hash_password, hash_staff_token as hash_token,
    is_valid_email, normalize_email, verify_password,
)


TEMP_PASSWORD_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"


def generate_temporary_password(length: int = 12) -> str:
    """为每名学生生成便于打印的密码，避开外形容易混淆的字符。"""
    size = max(10, min(32, int(length)))
    required = [
        secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ"),
        secrets.choice("abcdefghijkmnopqrstuvwxyz"),
        secrets.choice("23456789"),
    ]
    characters = required + [secrets.choice(TEMP_PASSWORD_ALPHABET) for _ in range(size - len(required))]
    secrets.SystemRandom().shuffle(characters)
    return "".join(characters)


def _temporary_password_cipher() -> Fernet:
    configured_key = os.environ.get("STUDENT_TEMP_PASSWORD_KEY", "").strip()
    if configured_key:
        try:
            return Fernet(configured_key.encode("ascii"))
        except (TypeError, ValueError) as exc:
            raise RuntimeError("STUDENT_TEMP_PASSWORD_KEY 不是有效的 Fernet 密钥。") from exc

    if os.environ.get("APP_ENV", "development").strip().lower() == "production":
        raise RuntimeError("生产环境必须配置 STUDENT_TEMP_PASSWORD_KEY。")

    key_path = Path(__file__).resolve().parents[1] / "data" / "student-temp-password.key"
    key_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        key = key_path.read_bytes().strip()
    except FileNotFoundError:
        key = Fernet.generate_key()
        try:
            with key_path.open("xb") as handle:
                handle.write(key)
        except FileExistsError:
            key = key_path.read_bytes().strip()
    return Fernet(key)


def encrypt_temporary_password(password: str) -> str:
    return _temporary_password_cipher().encrypt(password.encode("utf-8")).decode("ascii")


def decrypt_temporary_password(encrypted_password: str) -> str:
    try:
        return _temporary_password_cipher().decrypt(str(encrypted_password).encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError, ValueError) as exc:
        raise ValueError("临时密码无法解密，请为该学生重新生成。") from exc


def _json_list(value: object) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if not isinstance(value, str) or not value.strip():
        return []
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return decoded if isinstance(decoded, list) else []


def sanitize_admin(admin: dict | None) -> dict | None:
    if not admin:
        return None
    return {
        "id": admin.get("id"),
        "email": admin.get("email"),
        "name": admin.get("name"),
        "role": admin.get("role"),
        "actorType": admin.get("actor_type", "admin"),
        "status": admin.get("status"),
        "permissions": _json_list(admin.get("permissions")),
        "student_scope": _json_list(admin.get("student_scope")),
        "last_login_at": admin.get("last_login_at"),
    }
