"""学校使用独立的 Ed25519 密钥签发证书，服务身份和链账户分别管理。

CREDENTIALS_PUBLIC_KEYS_JSON 按学校和密钥编号保存 SPKI 格式的 PEM 公钥。
CREDENTIALS_SIGNING_KEYS_JSON 按学校保存活动密钥编号 kid 和 PKCS8 格式的 PEM 私钥 private_key。
只读验真进程只需配置公钥，轮换签发密钥时应保留仍受信任的历史公钥。
"""

import base64
import json
import os

from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


class SigningConfigurationError(RuntimeError):
    """签发或验真进程无法使用本地配置的学校密钥。"""


def _setting(name):
    try:
        value = json.loads(os.environ[name])
        if not isinstance(value, dict):
            raise ValueError
        return value
    except (KeyError, ValueError):
        raise SigningConfigurationError(f"Invalid or missing {name}") from None


def _identifier(value):
    return isinstance(value, str) and 0 < len(value) <= 128 and not any(
        char.isspace() or ord(char) < 32 for char in value
    )


def _message(school_id, payload, kid):
    if (not _identifier(school_id) or not _identifier(kid)
            or not isinstance(payload, dict) or payload.get("school_id") != school_id):
        raise ValueError("Invalid credential identity")
    # 将证书格式、密钥编号、学校和全部声明纳入签名，隔离服务令牌与链交易的用途。
    envelope = {"format": "teaching-credential/v1", "kid": kid, "payload": payload}
    return json.dumps(envelope, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _trusted_key(school_id, kid):
    school = _setting("CREDENTIALS_PUBLIC_KEYS_JSON").get(school_id, {})
    if not isinstance(school, dict):
        raise SigningConfigurationError("Invalid school public key map")
    if kid not in school:
        return None
    try:
        key = serialization.load_pem_public_key(school[kid].encode("ascii"))
        if not isinstance(key, Ed25519PublicKey):
            raise ValueError
        return key
    except (AttributeError, ValueError, TypeError, UnsupportedAlgorithm):
        raise SigningConfigurationError("Invalid school public key") from None


def sign_payload(school_id: str, payload: dict) -> tuple[str, str]:
    """返回学校当前密钥编号及省略填充的 Base64URL 签名。"""
    try:
        active = _setting("CREDENTIALS_SIGNING_KEYS_JSON")[school_id]
        kid = active["kid"]
        if not _identifier(kid):
            raise ValueError
        key = serialization.load_pem_private_key(active["private_key"].encode("ascii"), password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError
    except (KeyError, AttributeError, TypeError, ValueError, UnsupportedAlgorithm):
        raise SigningConfigurationError("School signing key unavailable") from None
    trusted = _trusted_key(school_id, kid)
    raw = (serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    if trusted is None or trusted.public_bytes(*raw) != key.public_key().public_bytes(*raw):
        raise SigningConfigurationError("School signing key does not match trust configuration")
    signature = key.sign(_message(school_id, payload, kid))
    return kid, base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")


def verify_payload(school_id: str, payload: dict, kid: str, signature: str) -> bool:
    """仅使用本地学校公钥验签，信任配置损坏时抛出异常。"""
    if not isinstance(signature, str) or len(signature) != 86:  # Ed25519 签名固定为 64 字节。
        return False
    try:
        message = _message(school_id, payload, kid)
        raw = base64.b64decode(signature + "==", altchars=b"-_", validate=True)
        if base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii") != signature:
            return False
        trusted = _trusted_key(school_id, kid)
        if trusted is None:
            return False
        trusted.verify(raw, message)
    except (ValueError, TypeError, InvalidSignature):
        return False
    return True
