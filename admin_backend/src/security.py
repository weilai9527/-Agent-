from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets

from cryptography.fernet import Fernet, InvalidToken


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def normalize_email(value: object) -> str:
    return str(value or "").strip().lower()


def is_valid_email(value: str) -> bool:
    return re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", value or "") is not None


def hash_password(password: str) -> str:
    salt = _b64url_encode(secrets.token_bytes(16))
    derived_key = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt.encode("ascii"),
        n=2**14,
        r=8,
        p=1,
        dklen=32,
    )
    return f"scrypt${salt}${_b64url_encode(derived_key)}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, salt, encoded_key = stored_hash.split("$", 2)
        if algorithm != "scrypt":
            return False
        expected_key = _b64url_decode(encoded_key)
        derived_key = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt.encode("ascii"),
            n=2**14,
            r=8,
            p=1,
            dklen=len(expected_key),
        )
    except (TypeError, ValueError):
        return False
    return hmac.compare_digest(expected_key, derived_key)


def create_token() -> str:
    return _b64url_encode(secrets.token_bytes(32))


def hash_token(token: object) -> str:
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


TEMP_PASSWORD_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"


def generate_temporary_password(length: int = 12) -> str:
    """Generate a print-friendly, per-student password without ambiguous glyphs."""
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
        "status": admin.get("status"),
        "permissions": _json_list(admin.get("permissions")),
        "student_scope": _json_list(admin.get("student_scope")),
        "last_login_at": admin.get("last_login_at"),
    }
