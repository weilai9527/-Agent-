import base64
import hashlib
import hmac
import re
import secrets


PASSWORD_KEY_LENGTH = 64


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def normalize_email(email: object) -> str:
    return str(email or "").strip().lower()


def is_valid_email(email: str) -> bool:
    return re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", email or "") is not None


def hash_password(password: str) -> str:
    salt = _b64url_encode(secrets.token_bytes(16))
    derived_key = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt.encode("utf-8"),
        n=16384,
        r=8,
        p=1,
        dklen=PASSWORD_KEY_LENGTH,
    )
    return f"scrypt${salt}${_b64url_encode(derived_key)}"


def verify_password(password: str, stored_hash: str) -> bool:
    parts = str(stored_hash or "").split("$")
    if len(parts) != 3:
        return False

    algorithm, salt, key = parts
    if algorithm != "scrypt" or not salt or not key:
        return False

    stored_key = _b64url_decode(key)
    derived_key = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt.encode("utf-8"),
        n=16384,
        r=8,
        p=1,
        dklen=len(stored_key),
    )
    return hmac.compare_digest(stored_key, derived_key)


def create_token() -> str:
    return _b64url_encode(secrets.token_bytes(32))


def hash_token(token: str) -> str:
    return _b64url_encode(hashlib.sha256(str(token).encode("utf-8")).digest())


def sanitize_user(user: dict | None) -> dict | None:
    if not user:
        return None

    return {
        "id": user["id"],
        "email": user["email"],
        "name": user["name"],
        "status": user["status"],
        "createdAt": user["created_at"],
        "lastLoginAt": user["last_login_at"],
    }
