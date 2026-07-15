"""应用 JWT 与企业 OpenID Connect 认证。"""

import asyncio
import base64
import hashlib
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
import redis.asyncio as aioredis
from fastapi import HTTPException
from jwt import PyJWKClient
from starlette.requests import HTTPConnection

from app.config import settings
from app.core.logging import logger

_discovery_cache: tuple[float, dict[str, Any]] | None = None


def is_auth_enabled() -> bool:
    return settings.ENABLE_AUTH


@dataclass(slots=True)
class UserInfo:
    user_id: str
    username: str = ""
    role: str = "viewer"


def _bearer_token(connection: HTTPConnection) -> str | None:
    authorization = connection.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() == "bearer" and token:
        return token
    if connection.scope.get("type") == "websocket":
        return connection.query_params.get("token")
    return None


async def get_current_user(connection: HTTPConnection) -> UserInfo | None:
    """读取应用 JWT；仅开发/测试环境允许关闭认证。"""
    if not is_auth_enabled():
        return UserInfo(user_id="dev-user", username="developer", role="admin")

    token = _bearer_token(connection)
    if not token:
        return None
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
            audience="shelook-api",
            issuer="shelook",
        )
    except jwt.PyJWTError as exc:
        logger.debug("应用 JWT 无效", error=str(exc))
        return None

    user = UserInfo(
        user_id=str(payload.get("sub", "")),
        username=str(payload.get("username", "")),
        role=str(payload.get("role", "viewer")),
    )
    connection.scope.setdefault("state", {})["user"] = user
    return user


async def require_auth(connection: HTTPConnection) -> UserInfo:
    user = await get_current_user(connection)
    if user is None:
        raise HTTPException(
            status_code=401,
            detail="未认证或 token 已过期，请重新登录",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def create_access_token(
    user_id: str,
    username: str = "",
    role: str = "viewer",
    expires_hours: int | None = None,
) -> str:
    now = int(time.time())
    expires = expires_hours if expires_hours is not None else settings.JWT_EXPIRE_HOURS
    return jwt.encode(
        {
            "sub": user_id,
            "username": username,
            "role": role,
            "iss": "shelook",
            "aud": "shelook-api",
            "iat": now,
            "exp": now + expires * 3600,
        },
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )


def _require_oidc_config() -> None:
    missing = [
        name
        for name in ("OIDC_ISSUER_URL", "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET")
        if not getattr(settings, name)
    ]
    if missing:
        raise HTTPException(status_code=503, detail=f"OIDC 配置不完整: {', '.join(missing)}")


async def get_oidc_metadata() -> dict[str, Any]:
    """读取并短时缓存 Provider Discovery 文档。"""
    global _discovery_cache
    _require_oidc_config()
    if _discovery_cache and _discovery_cache[0] > time.monotonic():
        return _discovery_cache[1]

    issuer = settings.OIDC_ISSUER_URL.rstrip("/")
    async with httpx.AsyncClient(timeout=settings.OIDC_HTTP_TIMEOUT_SECONDS) as client:
        response = await client.get(f"{issuer}/.well-known/openid-configuration")
        response.raise_for_status()
        metadata = response.json()
    if metadata.get("issuer", "").rstrip("/") != issuer:
        raise HTTPException(status_code=503, detail="OIDC Discovery issuer 不匹配")
    for field in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        if not metadata.get(field):
            raise HTTPException(status_code=503, detail=f"OIDC Discovery 缺少 {field}")
    _discovery_cache = (time.monotonic() + 3600, metadata)
    return metadata


async def begin_oidc_login() -> str:
    metadata = await get_oidc_metadata()
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")
    session = {"nonce": nonce, "code_verifier": verifier, "created_at": int(time.time())}
    redis = aioredis.from_url(settings.REDIS_URL, encoding="utf-8", decode_responses=True)
    try:
        await redis.setex(f"oidc:state:{state}", 600, json.dumps(session))
    finally:
        await redis.aclose()

    params = {
        "response_type": "code",
        "client_id": settings.OIDC_CLIENT_ID,
        "redirect_uri": settings.OIDC_REDIRECT_URI,
        "scope": settings.OIDC_SCOPES,
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return f"{metadata['authorization_endpoint']}?{urlencode(params)}"


def _role_from_claims(claims: dict[str, Any]) -> str:
    raw_roles = claims.get(settings.OIDC_ROLE_CLAIM, [])
    if isinstance(raw_roles, str):
        roles = {raw_roles}
    elif isinstance(raw_roles, list):
        roles = {str(role) for role in raw_roles}
    else:
        roles = set()
    return "admin" if roles.intersection(settings.OIDC_ADMIN_ROLES) else "viewer"


async def complete_oidc_login(code: str, state: str) -> tuple[str, UserInfo]:
    """一次性消费 state，交换 code，并完整验证 ID Token。"""
    metadata = await get_oidc_metadata()
    redis = aioredis.from_url(settings.REDIS_URL, encoding="utf-8", decode_responses=True)
    try:
        raw_session = await redis.getdel(f"oidc:state:{state}")
    finally:
        await redis.aclose()
    if not raw_session:
        raise HTTPException(status_code=400, detail="OIDC state 无效或已过期")
    session = json.loads(raw_session)

    async with httpx.AsyncClient(timeout=settings.OIDC_HTTP_TIMEOUT_SECONDS) as client:
        response = await client.post(
            metadata["token_endpoint"],
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.OIDC_REDIRECT_URI,
                "client_id": settings.OIDC_CLIENT_ID,
                "client_secret": settings.OIDC_CLIENT_SECRET,
                "code_verifier": session["code_verifier"],
            },
        )
        response.raise_for_status()
        token_response = response.json()
    id_token = token_response.get("id_token")
    if not id_token:
        raise HTTPException(status_code=401, detail="OIDC 响应缺少 ID Token")

    def _decode() -> dict[str, Any]:
        signing_key = PyJWKClient(metadata["jwks_uri"]).get_signing_key_from_jwt(id_token)
        return jwt.decode(
            id_token,
            signing_key.key,
            algorithms=metadata.get("id_token_signing_alg_values_supported", ["RS256"]),
            audience=settings.OIDC_AUDIENCE or settings.OIDC_CLIENT_ID,
            issuer=metadata["issuer"],
        )

    try:
        claims = await asyncio.to_thread(_decode)
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="OIDC ID Token 验证失败") from exc
    if not secrets.compare_digest(str(claims.get("nonce", "")), session["nonce"]):
        raise HTTPException(status_code=401, detail="OIDC nonce 验证失败")

    user = UserInfo(
        user_id=str(claims["sub"]),
        username=str(claims.get("preferred_username") or claims.get("email") or claims["sub"]),
        role=_role_from_claims(claims),
    )
    return create_access_token(user.user_id, user.username, user.role), user
