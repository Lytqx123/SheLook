"""Short-lived, tenant-scoped cache for expensive dashboard aggregates."""

import hashlib
import json

import redis.asyncio as aioredis

from app.config import settings
from app.core.logging import logger

_redis: aioredis.Redis | None = None
_CACHE_PREFIX = "dashboard:summary:v1"


def _cache_key(
    *, tenant_id: str, market: str | None, category: str | None, runtime_config_version: int
) -> str:
    scope = json.dumps(
        {
            "tenant_id": tenant_id,
            "market": market,
            "category": category,
            "runtime_config_version": runtime_config_version,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"{_CACHE_PREFIX}:{hashlib.sha256(scope.encode()).hexdigest()}"


async def _get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.REDIS_URL, encoding="utf-8", decode_responses=True)
    return _redis


async def get_summary_cache(
    *, tenant_id: str, market: str | None, category: str | None, runtime_config_version: int
) -> dict | None:
    """Return a cached summary when enabled; cache failures never block reads."""
    if settings.DASHBOARD_SUMMARY_CACHE_TTL_SECONDS <= 0:
        return None
    try:
        value = await (await _get_redis()).get(
            _cache_key(
                tenant_id=tenant_id,
                market=market,
                category=category,
                runtime_config_version=runtime_config_version,
            )
        )
        return json.loads(value) if value else None
    except Exception as exc:
        logger.warning("Dashboard summary cache read failed", error=str(exc))
        return None


async def set_summary_cache(
    *,
    tenant_id: str,
    market: str | None,
    category: str | None,
    runtime_config_version: int,
    payload: dict,
) -> None:
    """Store a short-lived entry without turning Redis into a read dependency."""
    ttl = settings.DASHBOARD_SUMMARY_CACHE_TTL_SECONDS
    if ttl <= 0:
        return
    try:
        await (await _get_redis()).setex(
            _cache_key(
                tenant_id=tenant_id,
                market=market,
                category=category,
                runtime_config_version=runtime_config_version,
            ),
            ttl,
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        )
    except Exception as exc:
        logger.warning("Dashboard summary cache write failed", error=str(exc))
