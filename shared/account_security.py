"""身份域凭据算法。仅处理内存中的密码、随机令牌与标识，不加载数据库或部署配置。"""
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


def normalize_student_no(value: object) -> str:
    return str(value or "").strip().upper()


def is_valid_student_no(value: str) -> bool:
    return re.match(r"^[0-9A-Z_-]{3,40}$", value or "") is not None


def hash_password(password: str) -> str:
    """学生账号继续写入 64 字节 scrypt 摘要，验证时也接受历史 32 字节摘要。"""
    return _derive(password, PASSWORD_KEY_LENGTH)


def hash_staff_password(password: str) -> str:
    """职员账号仍写入原 32 字节格式，迁移不要求用户重新设置密码。"""
    return _derive(password, 32)


def _derive(password: str, length: int) -> str:
    salt = _b64url_encode(secrets.token_bytes(16))
    derived_key = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt.encode("utf-8"),
        n=16384,
        r=8,
        p=1,
        dklen=length,
    )
    return f"scrypt${salt}${_b64url_encode(derived_key)}"


def verify_password(password: str, stored_hash: str) -> bool:
    parts = str(stored_hash or "").split("$")
    if len(parts) != 3:
        return False

    algorithm, salt, key = parts
    if algorithm != "scrypt" or not salt or not key:
        return False

    try:
        stored_key = _b64url_decode(key)
    except (ValueError, UnicodeError):
        return False
    # 管理端导入密码使用 32 字节派生密钥，候选人端使用 64 字节。校验密码前先排除损坏或截断的摘要。
    if len(stored_key) not in (32, PASSWORD_KEY_LENGTH):
        return False
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


def hash_staff_token(token: object) -> str:
    """职员会话表以十六进制保存摘要，与学生历史会话的 URL 安全编码区分。"""
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


def hash_student_token(token: str) -> str:
    return _b64url_encode(hashlib.sha256(str(token).encode("utf-8")).digest())


WEAK_PASSWORDS = {
    "12345678", "123456789", "1234567890", "123456", "1234567", "password", "password1",
    "passw0rd", "qwertyui", "qwerty123", "abc12345", "a1234567", "11111111", "00000000",
    "88888888", "66666666", "12341234", "11223344", "1qaz2wsx", "iloveyou", "admin123",
    "student", "student123", "test1234", "abcd1234", "asdf1234", "woaini1314", "5201314520",
}

_SEQUENCES = ("0123456789", "9876543210", "abcdefghijklmnopqrstuvwxyz", "zyxwvutsrqponmlkjihgfedcba")


def _is_weak_password(password: str) -> bool:
    lowered = password.strip().lower()
    if not lowered:
        return True
    if lowered in WEAK_PASSWORDS:
        return True
    if len(set(lowered)) == 1:
        return True
    for sequence in _SEQUENCES:
        for start in range(len(sequence) - len(lowered) + 1):
            if lowered == sequence[start:start + len(lowered)]:
                return True
    return False


def validate_new_password(password: str, confirmation: str | None = None) -> str | None:
    if len(password) < 8:
        return "密码至少需要 8 位。"
    if len(password) > 256:
        return "密码不能超过 256 位。"
    if _is_weak_password(password):
        return "密码过于简单，请勿使用连续数字、重复字符或常见弱口令。"
    if confirmation is not None and password != confirmation:
        return "两次输入的密码不一致。"
    return None
