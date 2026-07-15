from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets


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


def sanitize_admin(admin: dict | None) -> dict | None:
    if not admin:
        return None
    return {
        "id": admin.get("id"),
        "email": admin.get("email"),
        "name": admin.get("name"),
        "role": admin.get("role"),
        "status": admin.get("status"),
        "last_login_at": admin.get("last_login_at"),
    }
