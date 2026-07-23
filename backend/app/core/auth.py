"""Application JWT, enterprise OIDC SSO, and Feishu OAuth login."""

import asyncio
import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode, urlparse

import httpx
import jwt
import redis.asyncio as aioredis
from fastapi import HTTPException
from jwt import PyJWKClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import HTTPConnection

from app.config import settings
from app.core.external_identity import (
    feishu_member_user_id,
    normalize_external_subject,
    oidc_member_user_id,
)
from app.core.logging import logger
from app.core.tenant import set_tenant_context, tenant_context
from app.models.organization import Tenant, TenantMembership

# 缓存 discovery 文档，一小时过期
_discovery_cache: tuple[float, dict[str, Any]] | None = None
_LOGIN_STATE_TTL_SECONDS = 600
_FEISHU_AUTHORIZE_ENDPOINT = "https://accounts.feishu.cn/open-apis/authen/v1/authorize"
_FEISHU_TOKEN_ENDPOINT = "https://open.feishu.cn/open-apis/authen/v2/oauth/token"
_FEISHU_USER_INFO_ENDPOINT = "https://open.feishu.cn/open-apis/authen/v1/user_info"
_SESSION_REVOCATION_KEY_PREFIX = "auth:member-session-revoked:v1"
_MIN_SESSION_REVOCATION_TTL_SECONDS = 24 * 60 * 60
_SESSION_REVOCATION_SET_SCRIPT = """
local current = redis.call("GET", KEYS[1])
local current_marker = tonumber(current)
local new_marker = tonumber(ARGV[1])
if not current_marker or current_marker < new_marker then
    redis.call("SET", KEYS[1], ARGV[1], "EX", ARGV[2])
else
    redis.call("EXPIRE", KEYS[1], ARGV[2])
end
return 1
"""
_session_revocation_redis: aioredis.Redis | None = None
_session_revocation_redis_lock: asyncio.Lock | None = None
_session_revocation_circuit_until = 0.0


def is_auth_enabled() -> bool:
    return settings.ENABLE_AUTH


def is_oidc_login_configured() -> bool:
    """Return whether generic enterprise OIDC has every required credential."""
    return all(
        getattr(settings, name).strip()
        for name in ("OIDC_ISSUER_URL", "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET")
    )


def is_feishu_login_configured() -> bool:
    """Return whether the Feishu provider can run without a tenant bypass."""
    has_credentials = all(
        getattr(settings, name).strip()
        for name in ("FEISHU_APP_ID", "FEISHU_APP_SECRET", "FEISHU_REDIRECT_URI")
    )
    return has_credentials and bool(
        settings.FEISHU_TENANT_KEY_MAP or settings.FEISHU_ALLOWED_TENANT_KEYS
    )


def _local_tenant_id(value: str) -> str:
    """Validate a locally configured tenant identifier before opening a DB scope."""
    tenant_id = value.strip()
    if not tenant_id or len(tenant_id) > 36:
        raise HTTPException(status_code=503, detail="企业登录租户映射配置无效")
    return tenant_id


def _external_user_id(value: str, *, detail: str, max_length: int = 1_024) -> str:
    try:
        return normalize_external_subject(value, max_length=max_length)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=detail) from exc


def _is_https_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.netloc)


def _session_subject_digest(tenant_id: str, user_id: str) -> str:
    """Create a stable opaque subject identifier for Redis keys and logs."""
    subject = f"{tenant_id}\x1f{user_id}".encode()
    return hmac.new(settings.JWT_SECRET.encode(), subject, hashlib.sha256).hexdigest()


def _member_session_revocation_key(tenant_id: str, user_id: str) -> str:
    """Keep tenant and member identifiers out of Redis key names."""
    return f"{_SESSION_REVOCATION_KEY_PREFIX}:{_session_subject_digest(tenant_id, user_id)}"


def _session_revocation_ttl_seconds() -> int:
    """Retain a marker for at least the configured maximum JWT lifetime."""
    return max(
        _MIN_SESSION_REVOCATION_TTL_SECONDS,
        max(1, int(settings.JWT_EXPIRE_HOURS)) * 60 * 60,
    )


def _session_revocation_store_is_required() -> bool:
    """Production fails closed; local development remains usable without Redis."""
    return settings.APP_ENV.lower() == "production"


def _session_revocation_circuit_open() -> bool:
    return time.monotonic() < _session_revocation_circuit_until


def _trip_session_revocation_circuit() -> None:
    global _session_revocation_circuit_until
    _session_revocation_circuit_until = max(
        _session_revocation_circuit_until,
        time.monotonic() + max(0.1, settings.AUTH_REDIS_FAILURE_BACKOFF_SECONDS),
    )


def _restore_session_revocation_circuit() -> None:
    global _session_revocation_circuit_until
    _session_revocation_circuit_until = 0.0


async def _get_session_revocation_redis() -> aioredis.Redis:
    """Reuse one Redis connection pool per API worker for hot-path checks."""
    global _session_revocation_redis, _session_revocation_redis_lock
    if _session_revocation_redis is not None:
        return _session_revocation_redis
    if _session_revocation_redis_lock is None:
        _session_revocation_redis_lock = asyncio.Lock()

    async with _session_revocation_redis_lock:
        if _session_revocation_redis is None:
            _session_revocation_redis = aioredis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=settings.AUTH_REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS,
                socket_timeout=settings.AUTH_REDIS_SOCKET_TIMEOUT_SECONDS,
                max_connections=settings.AUTH_REDIS_MAX_CONNECTIONS,
                health_check_interval=30,
            )
    return _session_revocation_redis


async def close_session_revocation_redis() -> None:
    """Release the API worker's revocation connection pool at shutdown."""
    global _session_revocation_redis, _session_revocation_redis_lock
    redis_client = _session_revocation_redis
    _session_revocation_redis = None
    _session_revocation_redis_lock = None
    _restore_session_revocation_circuit()
    if redis_client is None:
        return
    try:
        await redis_client.aclose()
    except Exception as exc:  # pragma: no cover - connection cleanup best effort
        logger.warning(
            "成员会话撤销 Redis 连接关闭失败",
            operation="member_session_revocation",
            error_type=type(exc).__name__,
        )


async def revoke_member_sessions(
    tenant_id: str,
    user_id: str,
    *,
    reason: str = "membership_changed",
) -> int | None:
    """Invalidate a member's existing JWTs without persisting token material.

    The marker is deliberately written before the surrounding database
    transaction commits. If Redis is unavailable in production, raising here
    makes ``get_db`` roll the membership transaction back. A rare database
    commit failure after a successful marker write can only force a harmless
    re-login; it can never retain stale permissions.
    """
    if not is_auth_enabled():
        return None

    if _session_revocation_circuit_open():
        if _session_revocation_store_is_required():
            raise HTTPException(
                status_code=503,
                detail="会话撤销服务暂不可用，成员变更未保存",
            )
        return None

    marker_ms = time.time_ns() // 1_000_000
    ttl_seconds = _session_revocation_ttl_seconds()
    subject_digest = _session_subject_digest(tenant_id, user_id)
    try:
        redis_client = await _get_session_revocation_redis()
        # Preserve the latest marker during concurrent member updates and
        # refresh its TTL without exposing the raw subject in Redis.
        await redis_client.eval(
            _SESSION_REVOCATION_SET_SCRIPT,
            1,
            _member_session_revocation_key(tenant_id, user_id),
            str(marker_ms),
            str(ttl_seconds),
        )
    except Exception as exc:
        _trip_session_revocation_circuit()
        logger.error(
            "成员会话撤销写入失败",
            operation="member_session_revoke",
            reason=reason,
            subject_fingerprint=subject_digest[:12],
            error_type=type(exc).__name__,
        )
        if _session_revocation_store_is_required():
            raise HTTPException(
                status_code=503,
                detail="会话撤销服务暂不可用，成员变更未保存",
            ) from exc
        return None

    _restore_session_revocation_circuit()

    logger.info(
        "成员会话已撤销",
        operation="member_session_revoke",
        reason=reason,
        subject_fingerprint=subject_digest[:12],
        marker_ms=marker_ms,
        ttl_seconds=ttl_seconds,
    )
    return marker_ms


def _jwt_iat_ms(payload: dict[str, Any]) -> int | None:
    """Read the millisecond issue timestamp required for revocation checks."""
    raw_iat_ms = payload.get("iat_ms")
    if isinstance(raw_iat_ms, bool):
        return None
    try:
        iat_ms = int(raw_iat_ms)
    except (TypeError, ValueError):
        return None
    return iat_ms if iat_ms > 0 else None


async def is_member_session_token_active(
    tenant_id: str,
    user_id: str,
    token_iat_ms: int,
) -> bool:
    """Perform the constant-time Redis revocation lookup for one JWT."""
    if _session_revocation_circuit_open():
        return not _session_revocation_store_is_required()

    subject_digest = _session_subject_digest(tenant_id, user_id)
    try:
        redis_client = await _get_session_revocation_redis()
        raw_marker = await redis_client.get(
            _member_session_revocation_key(tenant_id, user_id)
        )
    except Exception as exc:
        _trip_session_revocation_circuit()
        logger.error(
            "成员会话撤销读取失败",
            operation="member_session_check",
            subject_fingerprint=subject_digest[:12],
            error_type=type(exc).__name__,
        )
        # A production request must never fall back to stale authorization.
        return not _session_revocation_store_is_required()

    _restore_session_revocation_circuit()

    if raw_marker is None:
        return True
    try:
        revoked_after_ms = int(raw_marker)
    except (TypeError, ValueError):
        logger.error(
            "成员会话撤销标记无效",
            operation="member_session_check",
            subject_fingerprint=subject_digest[:12],
        )
        return not _session_revocation_store_is_required()

    if token_iat_ms <= revoked_after_ms:
        logger.info(
            "已拒绝撤销前签发的成员会话",
            operation="member_session_rejected",
            subject_fingerprint=subject_digest[:12],
        )
        return False
    return True


@dataclass(slots=True)
class UserInfo:
    user_id: str
    username: str = ""
    role: str = "viewer"
    tenant_id: str = settings.DEFAULT_TENANT_ID
    permissions: tuple[str, ...] = ()
    unit_ids: tuple[str, ...] = ()


ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "admin": frozenset({"*"}),
    "operator": frozenset({
        "product:read", "product:write", "generation:run", "review:read",
        "analytics:read", "experiment:read", "experiment:manage",
        "supplier:read", "supplier:write",
    }),
    "reviewer": frozenset({"product:read", "review:read", "review:decide"}),
    "analyst": frozenset({"product:read", "analytics:read", "experiment:read", "supplier:read"}),
    "supplier": frozenset({"product:read", "supplier:read", "supplier:write"}),
    "viewer": frozenset({"product:read", "review:read", "analytics:read"}),
}


def has_permission(user: UserInfo, permission: str) -> bool:
    granted = set(ROLE_PERMISSIONS.get(user.role, ROLE_PERMISSIONS["viewer"]))
    granted.update(user.permissions)
    return "*" in granted or permission in granted


def _bearer_token(connection: HTTPConnection) -> str | None:
    authorization = connection.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() == "bearer" and token:
        return token
    if connection.scope.get("type") == "websocket":
        return connection.query_params.get("token")
    return None


def _development_tenant_id(connection: HTTPConnection) -> str:
    """Allow explicit tenant simulation only when authentication is disabled in dev/test."""
    candidate = connection.headers.get("X-Tenant-ID", "").strip()
    if settings.APP_ENV.lower() in {"development", "test"} and 0 < len(candidate) <= 36:
        return candidate
    return settings.DEFAULT_TENANT_ID


async def get_current_user(connection: HTTPConnection) -> UserInfo | None:
    """解析 JWT，认证关闭时直接返回 dev-user"""
    existing_user = connection.scope.get("state", {}).get("user")
    if isinstance(existing_user, UserInfo):
        return existing_user
    if not is_auth_enabled():
        user = UserInfo(
            user_id="dev-user",
            username="developer",
            role="admin",
            tenant_id=_development_tenant_id(connection),
        )
        set_tenant_context(user.tenant_id, user_id=user.user_id)
        connection.scope.setdefault("state", {})["user"] = user
        return user

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

    user_id = str(payload.get("sub", "")).strip()
    tenant_id = str(payload.get("tenant_id") or settings.DEFAULT_TENANT_ID).strip()
    token_iat_ms = _jwt_iat_ms(payload)
    if not user_id or not tenant_id or token_iat_ms is None:
        logger.warning(
            "应用 JWT 缺少成员会话撤销所需声明",
            operation="member_session_check",
        )
        return None
    if not await is_member_session_token_active(tenant_id, user_id, token_iat_ms):
        return None

    user = UserInfo(
        user_id=user_id,
        username=str(payload.get("username", "")),
        role=str(payload.get("role", "viewer")),
        tenant_id=tenant_id,
        permissions=tuple(str(value) for value in payload.get("permissions", []) if value),
        unit_ids=tuple(str(value) for value in payload.get("unit_ids", []) if value),
    )
    set_tenant_context(user.tenant_id, user_id=user.user_id)
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
    tenant_id: str = settings.DEFAULT_TENANT_ID,
    permissions: tuple[str, ...] = (),
    unit_ids: tuple[str, ...] = (),
    expires_hours: int | None = None,
) -> str:
    now = int(time.time())
    now_ms = time.time_ns() // 1_000_000
    configured_max_hours = max(1, int(settings.JWT_EXPIRE_HOURS))
    expires = expires_hours if expires_hours is not None else configured_max_hours
    if not 0 < expires <= configured_max_hours:
        raise ValueError("expires_hours must be positive and no greater than JWT_EXPIRE_HOURS")
    return jwt.encode(
        {
            "sub": user_id,
            "username": username,
            "role": role,
            "tenant_id": tenant_id,
            "permissions": list(permissions),
            "unit_ids": list(unit_ids),
            "iss": "shelook",
            "aud": "shelook-api",
            "iat": now,
            "iat_ms": now_ms,
            "exp": now + expires * 3600,
        },
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )


def _require_oidc_config() -> None:
    if is_oidc_login_configured():
        return
    missing = [
        name
        for name in ("OIDC_ISSUER_URL", "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET")
        if not getattr(settings, name)
    ]
    if missing:
        raise HTTPException(status_code=503, detail=f"OIDC 配置不完整: {', '.join(missing)}")


async def get_oidc_metadata() -> dict[str, Any]:
    """拉取 Provider Discovery 文档，带一小时缓存"""
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
        if settings.APP_ENV.lower() == "production" and not _is_https_url(
            str(metadata[field])
        ):
            raise HTTPException(status_code=503, detail=f"OIDC Discovery 的 {field} 必须使用 HTTPS")
    _discovery_cache = (time.monotonic() + 3600, metadata)
    return metadata


async def begin_oidc_login() -> str:
    metadata = await get_oidc_metadata()
    state = f"oidc.{secrets.token_urlsafe(32)}"
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")
    session = {
        "provider": "oidc",
        "nonce": nonce,
        "code_verifier": verifier,
        "created_at": int(time.time()),
    }
    redis = aioredis.from_url(settings.REDIS_URL, encoding="utf-8", decode_responses=True)
    try:
        await redis.setex(
            f"auth:state:oidc:{state}", _LOGIN_STATE_TTL_SECONDS, json.dumps(session)
        )
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


def _resolve_oidc_tenant(claims: dict[str, Any]) -> str:
    """Resolve an IdP tenant claim only through the local allowlisted map.

    A single-tenant deployment deliberately ignores an unconfigured IdP tenant
    claim and uses DEFAULT_TENANT_ID. A multi-tenant deployment must provide a
    map; an IdP never gets to choose a local tenant identifier directly.
    """
    external_tenant = str(claims.get(settings.OIDC_TENANT_CLAIM) or "").strip()
    if settings.OIDC_TENANT_CLAIM_MAP:
        mapped_tenant = settings.OIDC_TENANT_CLAIM_MAP.get(external_tenant)
        if mapped_tenant:
            return _local_tenant_id(mapped_tenant)
        raise HTTPException(status_code=403, detail="当前企业身份未获准访问 SheLook")
    return _local_tenant_id(settings.DEFAULT_TENANT_ID)


async def complete_oidc_login(
    code: str, state: str, db: AsyncSession
) -> tuple[str, UserInfo]:
    """用 code + state 换 token，验证 ID Token，返回 JWT + 用户信息"""
    if state.startswith("feishu."):
        raise HTTPException(status_code=400, detail="登录回调提供方与 state 不匹配")
    metadata = await get_oidc_metadata()
    redis = aioredis.from_url(settings.REDIS_URL, encoding="utf-8", decode_responses=True)
    try:
        raw_session = await redis.getdel(f"auth:state:oidc:{state}")
        # Keep callbacks already in progress during a rolling release valid.
        if not raw_session:
            raw_session = await redis.getdel(f"oidc:state:{state}")
    finally:
        await redis.aclose()
    if not raw_session:
        raise HTTPException(status_code=400, detail="OIDC state 无效或已过期")
    session = json.loads(raw_session)
    if session.get("provider") not in (None, "oidc"):
        raise HTTPException(status_code=400, detail="登录回调提供方与 state 不匹配")

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

    external_subject = _external_user_id(
        str(claims.get("sub") or ""), detail="OIDC 身份未返回可用用户标识"
    )
    try:
        member_user_id = oidc_member_user_id(settings.OIDC_ISSUER_URL, external_subject)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="OIDC 本地身份映射配置无效") from exc
    tenant_id = _resolve_oidc_tenant(claims)
    user = await _load_active_tenant_member(
        db,
        tenant_id=tenant_id,
        user_id=member_user_id,
        display_name=str(
            claims.get("preferred_username") or claims.get("email") or external_subject
        ).strip(),
    )
    return (
        create_access_token(
            user.user_id,
            user.username,
            user.role,
            tenant_id=user.tenant_id,
            permissions=user.permissions,
            unit_ids=user.unit_ids,
        ),
        user,
    )


def _require_feishu_config() -> None:
    """Fail closed when an OAuth client or tenant boundary is incomplete."""
    if not is_feishu_login_configured():
        raise HTTPException(status_code=503, detail="飞书登录配置不完整")


def _resolve_feishu_tenant(tenant_key: str) -> str:
    """Map a verified Feishu tenant key to a locally approved tenant only."""
    normalized_key = tenant_key.strip()
    if not normalized_key:
        raise HTTPException(status_code=403, detail="飞书账号未返回企业标识")

    if settings.FEISHU_TENANT_KEY_MAP:
        mapped_tenant = settings.FEISHU_TENANT_KEY_MAP.get(normalized_key)
        if mapped_tenant:
            return _local_tenant_id(mapped_tenant)
        raise HTTPException(status_code=403, detail="当前飞书企业未获准访问 SheLook")
    # An allowlist is only valid for the one configured default tenant. A
    # multi-tenant deployment must use FEISHU_TENANT_KEY_MAP exclusively.
    if normalized_key in set(settings.FEISHU_ALLOWED_TENANT_KEYS):
        return _local_tenant_id(settings.DEFAULT_TENANT_ID)
    raise HTTPException(status_code=403, detail="当前飞书企业未获准访问 SheLook")


async def begin_feishu_login() -> str:
    """Start a Feishu OAuth authorization-code flow with one-time Redis state."""
    _require_feishu_config()
    state = f"feishu.{secrets.token_urlsafe(32)}"
    session = {"provider": "feishu", "created_at": int(time.time())}
    redis = aioredis.from_url(settings.REDIS_URL, encoding="utf-8", decode_responses=True)
    try:
        await redis.setex(
            f"auth:state:feishu:{state}", _LOGIN_STATE_TTL_SECONDS, json.dumps(session)
        )
    finally:
        await redis.aclose()

    params = {
        "client_id": settings.FEISHU_APP_ID,
        "redirect_uri": settings.FEISHU_REDIRECT_URI,
        "state": state,
        "scope": settings.FEISHU_SCOPES,
    }
    return f"{_FEISHU_AUTHORIZE_ENDPOINT}?{urlencode(params)}"


async def _consume_feishu_state(state: str) -> None:
    if not state.startswith("feishu."):
        raise HTTPException(status_code=400, detail="登录回调提供方与 state 不匹配")
    redis = aioredis.from_url(settings.REDIS_URL, encoding="utf-8", decode_responses=True)
    try:
        raw_session = await redis.getdel(f"auth:state:feishu:{state}")
    finally:
        await redis.aclose()
    if not raw_session:
        raise HTTPException(status_code=400, detail="飞书 state 无效或已过期")
    try:
        session = json.loads(raw_session)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="飞书登录会话无效") from exc
    if session.get("provider") != "feishu":
        raise HTTPException(status_code=400, detail="登录回调提供方与 state 不匹配")


def _feishu_payload_data(payload: dict[str, Any], *, detail: str) -> dict[str, Any]:
    """Handle the documented Feishu envelope without leaking provider details."""
    result_code = payload.get("code", 0)
    if result_code not in (0, "0", None):
        logger.warning("飞书 OAuth 请求被拒绝", provider_code=str(result_code))
        raise HTTPException(status_code=401, detail=detail)
    data = payload.get("data")
    if data is None:
        return payload
    if not isinstance(data, dict):
        raise HTTPException(status_code=503, detail="飞书认证服务响应异常")
    return data


async def _fetch_feishu_user_info(code: str) -> dict[str, Any]:
    """Exchange a code server-side and fetch the current Feishu user profile."""
    try:
        async with httpx.AsyncClient(timeout=settings.OIDC_HTTP_TIMEOUT_SECONDS) as client:
            token_response = await client.post(
                _FEISHU_TOKEN_ENDPOINT,
                headers={"Content-Type": "application/json; charset=utf-8"},
                json={
                    "grant_type": "authorization_code",
                    "client_id": settings.FEISHU_APP_ID,
                    "client_secret": settings.FEISHU_APP_SECRET,
                    "code": code,
                    "redirect_uri": settings.FEISHU_REDIRECT_URI,
                },
            )
            token_response.raise_for_status()
            token_payload = _feishu_payload_data(
                token_response.json(), detail="飞书授权无效或已过期"
            )
            access_token = str(token_payload.get("access_token") or "").strip()
            if not access_token:
                raise HTTPException(status_code=401, detail="飞书授权无效或已过期")

            user_info_response = await client.get(
                _FEISHU_USER_INFO_ENDPOINT,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json; charset=utf-8",
                },
            )
            user_info_response.raise_for_status()
            user_info = _feishu_payload_data(
                user_info_response.json(), detail="无法获取飞书账号信息"
            )
    except HTTPException:
        raise
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("飞书认证服务请求失败", error=str(exc))
        raise HTTPException(status_code=503, detail="飞书认证服务暂不可用") from exc

    return user_info


async def _load_active_tenant_member(
    db: AsyncSession,
    *,
    tenant_id: str,
    user_id: str,
    display_name: str,
) -> UserInfo:
    """Require local membership; external authentication is not an invitation."""
    with tenant_context(tenant_id, user_id=user_id, source="enterprise_login"):
        tenant = await db.get(Tenant, tenant_id)
        if tenant is None or tenant.status != "active":
            raise HTTPException(status_code=403, detail="当前 SheLook 租户不可用")
        membership = await db.scalar(
            select(TenantMembership).where(
                TenantMembership.tenant_id == tenant_id,
                TenantMembership.user_id == user_id,
                TenantMembership.is_active.is_(True),
            )
        )
    if membership is None:
        raise HTTPException(status_code=403, detail="当前企业账号尚未获邀加入 SheLook")

    role = membership.role if membership.role in ROLE_PERMISSIONS else "viewer"
    return UserInfo(
        user_id=user_id,
        username=display_name or membership.display_name or user_id,
        role=role,
        tenant_id=tenant_id,
        permissions=tuple(str(value) for value in membership.permissions or [] if value),
        unit_ids=tuple(str(value) for value in membership.unit_ids or [] if value),
    )


async def complete_feishu_login(
    code: str, state: str, db: AsyncSession
) -> tuple[str, UserInfo]:
    """Finish Feishu OAuth and issue a SheLook JWT for an invited tenant member."""
    _require_feishu_config()
    await _consume_feishu_state(state)
    profile = await _fetch_feishu_user_info(code)

    open_id = _external_user_id(
        str(profile.get("open_id") or ""), detail="飞书账号未返回可用用户标识", max_length=120
    )
    tenant_key = str(profile.get("tenant_key") or "").strip()
    tenant_id = _resolve_feishu_tenant(tenant_key)
    try:
        user_id = feishu_member_user_id(open_id)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="飞书账号未返回可用用户标识") from exc
    display_name = str(profile.get("name") or profile.get("en_name") or "").strip()
    user = await _load_active_tenant_member(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        display_name=display_name,
    )
    return (
        create_access_token(
            user.user_id,
            user.username,
            user.role,
            tenant_id=user.tenant_id,
            permissions=user.permissions,
            unit_ids=user.unit_ids,
        ),
        user,
    )


async def complete_enterprise_login(
    code: str, state: str, db: AsyncSession
) -> tuple[str, UserInfo]:
    """Dispatch the shared frontend callback by its one-time state namespace."""
    if state.startswith("feishu."):
        return await complete_feishu_login(code, state, db)
    return await complete_oidc_login(code, state, db)
