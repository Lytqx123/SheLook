"""Offline coverage for immediate member-session revocation."""

import asyncio
import time
from typing import Any

import jwt
import pytest
from fastapi import HTTPException
from starlette.requests import HTTPConnection

from app.api.organization import upsert_tenant_member
from app.config import settings
from app.core.auth import (
    UserInfo,
    _member_session_revocation_key,
    close_session_revocation_redis,
    create_access_token,
    get_current_user,
    is_member_session_token_active,
    revoke_member_sessions,
)
from app.db.session import get_db
from app.models.organization import TenantMembership
from app.schemas.organization import TenantMemberUpsert


class InMemoryRedis:
    """Small async Redis stand-in that exercises the revocation contract."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.closed = False

    async def eval(
        self,
        _script: str,
        key_count: int,
        key: str,
        marker: str,
        ttl_seconds: str,
    ) -> int:
        assert key_count == 1
        previous = self.values.get(key)
        if previous is None or int(previous) < int(marker):
            self.values[key] = marker
        self.ttls[key] = int(ttl_seconds)
        return 1

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def aclose(self) -> None:
        self.closed = True


class UnavailableRedis:
    async def eval(self, *_args: Any) -> int:
        raise OSError("offline")

    async def get(self, _key: str) -> str | None:
        raise OSError("offline")

    async def aclose(self) -> None:
        return None


@pytest.fixture(autouse=True)
def reset_revocation_redis_pool() -> None:
    """Keep monkeypatched Redis clients isolated across synchronous test loops."""
    asyncio.run(close_session_revocation_redis())
    yield
    asyncio.run(close_session_revocation_redis())


def _connection(token: str) -> HTTPConnection:
    return HTTPConnection(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/products",
            "query_string": b"",
            "headers": [(b"authorization", f"Bearer {token}".encode("ascii"))],
        }
    )


def _signed_token(*, iat_ms: int, tenant_id: str = "tenant-a", user_id: str = "user-a") -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "sub": user_id,
            "username": "Member",
            "role": "viewer",
            "tenant_id": tenant_id,
            "permissions": [],
            "unit_ids": [],
            "iss": "shelook",
            "aud": "shelook-api",
            "iat": now,
            "iat_ms": iat_ms,
            "exp": now + 3600,
        },
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )


def test_access_token_embeds_a_millisecond_issue_timestamp() -> None:
    token = create_access_token("member-a", tenant_id="tenant-a")

    payload = jwt.decode(
        token,
        settings.JWT_SECRET,
        algorithms=[settings.JWT_ALGORITHM],
        audience="shelook-api",
        issuer="shelook",
    )

    assert isinstance(payload["iat_ms"], int)
    assert payload["iat_ms"] >= payload["iat"] * 1000


def test_redis_revocation_key_is_opaque() -> None:
    key = _member_session_revocation_key("tenant-acme", "member@example.com")

    assert key.startswith("auth:member-session-revoked:v1:")
    assert "tenant-acme" not in key
    assert "member@example.com" not in key


def test_revocation_checks_reuse_one_bounded_redis_pool(monkeypatch) -> None:
    redis = InMemoryRedis()
    calls: list[dict[str, object]] = []

    def from_url(*_args: object, **kwargs: object) -> InMemoryRedis:
        calls.append(kwargs)
        return redis

    monkeypatch.setattr(settings, "ENABLE_AUTH", True)
    monkeypatch.setattr("app.core.auth.aioredis.from_url", from_url)

    asyncio.run(revoke_member_sessions("tenant-a", "user-a"))
    assert asyncio.run(is_member_session_token_active("tenant-a", "user-a", 0)) is False

    assert len(calls) == 1
    assert calls[0]["socket_connect_timeout"] == settings.AUTH_REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS
    assert calls[0]["socket_timeout"] == settings.AUTH_REDIS_SOCKET_TIMEOUT_SECONDS
    assert calls[0]["max_connections"] == settings.AUTH_REDIS_MAX_CONNECTIONS


def test_member_revocation_rejects_prior_jwt_and_allows_newer_jwt(monkeypatch) -> None:
    redis = InMemoryRedis()
    monkeypatch.setattr(settings, "ENABLE_AUTH", True)
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr("app.core.auth.aioredis.from_url", lambda *_args, **_kwargs: redis)

    marker_ms = asyncio.run(revoke_member_sessions("tenant-a", "user-a"))
    assert marker_ms is not None
    assert redis.ttls[_member_session_revocation_key("tenant-a", "user-a")] >= 24 * 60 * 60

    revoked_user = asyncio.run(
        get_current_user(_connection(_signed_token(iat_ms=marker_ms - 1)))
    )
    active_user = asyncio.run(
        get_current_user(_connection(_signed_token(iat_ms=marker_ms + 1)))
    )

    assert revoked_user is None
    assert active_user is not None
    assert active_user.user_id == "user-a"


def test_production_fails_closed_when_revocation_store_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ENABLE_AUTH", True)
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(
        "app.core.auth.aioredis.from_url", lambda *_args, **_kwargs: UnavailableRedis()
    )

    user = asyncio.run(get_current_user(_connection(create_access_token("member-a"))))

    assert user is None


def test_production_backoff_avoids_repeated_redis_attempts(monkeypatch) -> None:
    calls = 0

    def unavailable_factory(*_args: object, **_kwargs: object) -> UnavailableRedis:
        nonlocal calls
        calls += 1
        return UnavailableRedis()

    monkeypatch.setattr(settings, "ENABLE_AUTH", True)
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr("app.core.auth.aioredis.from_url", unavailable_factory)

    assert asyncio.run(is_member_session_token_active("tenant-a", "member-a", 1)) is False
    assert asyncio.run(is_member_session_token_active("tenant-a", "member-a", 1)) is False

    assert calls == 1


def test_production_refuses_member_change_when_revocation_store_is_unavailable(
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "ENABLE_AUTH", True)
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(
        "app.core.auth.aioredis.from_url", lambda *_args, **_kwargs: UnavailableRedis()
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(revoke_member_sessions("tenant-a", "member-a"))

    assert exc_info.value.status_code == 503


def test_development_preserves_login_when_revocation_store_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ENABLE_AUTH", True)
    monkeypatch.setattr(settings, "APP_ENV", "development")
    monkeypatch.setattr(
        "app.core.auth.aioredis.from_url", lambda *_args, **_kwargs: UnavailableRedis()
    )

    user = asyncio.run(get_current_user(_connection(create_access_token("member-a"))))

    assert user is not None
    assert user.user_id == "member-a"


class _ScalarResult:
    def __init__(self, value: TenantMembership | None) -> None:
        self.value = value

    def scalar_one_or_none(self) -> TenantMembership | None:
        return self.value


class MemberSession:
    """Minimal transactional session used to assert get_db rollback behavior."""

    def __init__(self, member: TenantMembership) -> None:
        self.member = member
        self.flushed = False
        self.refreshed = False
        self.committed = False
        self.rolled_back = False

    async def __aenter__(self) -> "MemberSession":
        return self

    async def __aexit__(self, *_args: Any) -> None:
        return None

    async def execute(self, _statement: Any) -> _ScalarResult:
        return _ScalarResult(self.member)

    async def flush(self) -> None:
        self.flushed = True

    async def refresh(self, _member: TenantMembership) -> None:
        self.refreshed = True

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


def test_failed_production_revocation_rolls_back_member_change(monkeypatch) -> None:
    member = TenantMembership(
        tenant_id="tenant-a",
        user_id="member-a",
        display_name="Member",
        role="viewer",
        permissions=[],
        unit_ids=[],
        is_active=True,
    )
    session = MemberSession(member)

    async def fail_revoke(*_args: Any, **_kwargs: Any) -> None:
        raise HTTPException(status_code=503, detail="revocation unavailable")

    monkeypatch.setattr("app.api.organization.revoke_member_sessions", fail_revoke)
    monkeypatch.setattr("app.db.session.async_session_factory", lambda: session)

    async def run_change() -> None:
        db_generator = get_db()
        db = await anext(db_generator)
        try:
            await upsert_tenant_member(
                "member-a",
                TenantMemberUpsert(
                    user_id="member-a",
                    display_name="Member",
                    role="reviewer",
                    permissions=["review:decide"],
                    unit_ids=["team-1"],
                    is_active=True,
                ),
                UserInfo(user_id="admin-a", role="admin", tenant_id="tenant-a"),
                db,
            )
        except HTTPException as exc:
            with pytest.raises(HTTPException):
                await db_generator.athrow(type(exc), exc, exc.__traceback__)

    asyncio.run(run_change())

    assert session.flushed is True
    assert session.refreshed is True
    assert session.rolled_back is True
    assert session.committed is False
