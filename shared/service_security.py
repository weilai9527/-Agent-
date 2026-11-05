"""内部 HTTP 调用使用绑定接收方的短期身份。由可信网关委派用户，各服务独立核验调用方权限、学校及对象归属。"""

import json
import os
import time
from functools import lru_cache
from uuid import uuid4

import jwt
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import HTTPException, Request


TOKEN_LIFETIME = 45
ACTOR_TYPES = {"student", "teacher", "admin", "system"}


def _identifier(value):
    return isinstance(value, str) and 0 < len(value) <= 128 and not any(
        character.isspace() or ord(character) < 32 for character in value
    )


def _scope_list(value):
    return isinstance(value, list) and 0 < len(value) <= 64 and all(
        _identifier(item) and "*" not in item for item in value
    )


@lru_cache(maxsize=64)
def _verification_key(pem):
    key = serialization.load_pem_public_key(pem.encode("ascii"))
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("Trust policy requires an Ed25519 public key")
    return key


def service_headers(audience, *, actor_id, school_id, actor_type, scopes):
    """为唯一指定的接收服务签发新凭据，禁止转发上游令牌。"""
    issuer = os.environ["SERVICE_ID"]
    key_id = os.environ["SERVICE_KEY_ID"]
    if not all(_identifier(v) for v in (issuer, key_id, audience, actor_id, school_id)):
        raise ValueError("Service, audience, key, actor and school identifiers are required")
    if actor_type not in ACTOR_TYPES or not _scope_list(scopes):
        raise ValueError("An explicit actor type and concrete scopes are required")
    now = int(time.time())
    signed = jwt.encode(
        {"iss": issuer, "aud": audience, "sub": actor_id, "school_id": school_id,
         "actor_type": actor_type, "scopes": scopes, "iat": now,
         "exp": now + TOKEN_LIFETIME, "jti": str(uuid4())},
        os.environ["SERVICE_SIGNING_KEY"], algorithm="EdDSA",
        headers={"kid": key_id, "typ": "service+jwt"},
    )
    return {"Authorization": f"Bearer {signed}"}


def _authenticate(token, audience):
    if os.environ.get("SERVICE_ID") != audience:
        raise HTTPException(503, "Service identity is not configured for this audience")
    try:
        policy = json.loads(os.environ["SERVICE_TRUST_POLICY"])
        if not isinstance(policy, dict):
            raise ValueError("Invalid policy")
    except (KeyError, ValueError):
        raise HTTPException(503, "Service trust configuration unavailable") from None

    try:
        header = jwt.get_unverified_header(token)
        if header.get("alg") != "EdDSA" or header.get("typ") != "service+jwt":
            raise ValueError("Unexpected token type")
        # 未验签的字段仅用于选择本地可信公钥，不能用于构造 URL、文件路径或授予用户权限。
        selector = jwt.decode(token, options={"verify_signature": False})
        issuer = selector["iss"]
        peer = policy[issuer]
        key = _verification_key(peer["keys"][header["kid"]])
        claims = jwt.decode(
            token, key, algorithms=["EdDSA"], issuer=issuer, audience=audience,
            options={"strict_aud": True, "require": [
                "iss", "aud", "sub", "school_id", "actor_type", "scopes", "iat", "exp", "jti",
            ]},
        )
        start, end = claims["iat"], claims["exp"]
        if type(start) is not int or type(end) is not int or not 0 < end - start <= TOKEN_LIFETIME:
            raise ValueError("Invalid lifetime")
        if not all(_identifier(claims[name]) for name in ("sub", "iss", "jti", "school_id")):
            raise ValueError("Invalid identity")
        if claims["actor_type"] not in ACTOR_TYPES or not _scope_list(claims["scopes"]):
            raise ValueError("Invalid delegation")
    except (jwt.PyJWTError, KeyError, AttributeError, ValueError, TypeError, OverflowError, UnsupportedAlgorithm):
        raise HTTPException(401, "Invalid service credential") from None
    # 同一领域的 HTTP 进程与 Worker 可共享 issuer，但各自的 kid 只能使用分配给自己的动作。
    # 若启用了逐密钥策略，未列出的密钥、角色或范围必须拒绝，不能退回到领域级并集。
    if "key_grants" in peer:
        try:
            permitted = peer["key_grants"][header["kid"]][audience][claims["actor_type"]]
        except (KeyError, TypeError):
            raise HTTPException(403, "当前进程密钥未获此角色授权") from None
        if not _scope_list(permitted) or not set(claims["scopes"]).issubset(permitted):
            raise HTTPException(403, "当前进程密钥未获此操作授权")
    return peer, claims


def require_service(audience, scope):
    """校验服务令牌及动作；具体对象和教师负责关系仍由数据所有服务核验。"""
    def verify(request: Request):
        auth = request.headers.getlist("authorization")
        if len(auth) != 1 or len(auth[0]) > 8192:
            raise HTTPException(401, "One service credential is required")
        scheme, _, token = auth[0].partition(" ")
        if scheme.lower() != "bearer" or not token or " " in token:
            raise HTTPException(401, "Bearer service credential required")
        peer, claims = _authenticate(token, audience)
        granted = peer.get("grants", {}).get(audience, {}).get(claims["actor_type"], [])
        schools = peer.get("schools", [])
        # 只要令牌携带一个未获授的动作就整体拒绝，防止下游误用多余权限。
        if (not isinstance(schools, list) or claims["school_id"] not in schools
                or not _scope_list(granted) or scope not in claims["scopes"]
                or not set(claims["scopes"]).issubset(granted)):
            raise HTTPException(403, "School or action outside caller grant")
        return {"caller": claims["iss"], "actor_id": claims["sub"],
                "school_id": claims["school_id"], "actor_type": claims["actor_type"],
                "scopes": claims["scopes"]}

    return verify
