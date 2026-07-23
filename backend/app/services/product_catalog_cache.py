"""Tenant-scoped cache for the product list read model."""

import hashlib
import json

import redis.asyncio as aioredis

from app.config import settings
from app.core.logging import logger

_redis: aioredis.Redis | None = None
_CACHE_PREFIX = "catalog:products:v1"


async def _get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.REDIS_URL, encoding="utf-8", decode_responses=True)
    return _redis


def _version_key(tenant_id: str) -> str:
    return f"{_CACHE_PREFIX}:version:{tenant_id}"


async def _tenant_version(tenant_id: str) -> str:
    value = await (await _get_redis()).get(_version_key(tenant_id))
    return value or "0"


def _cache_key(
    *, tenant_id: str, version: str, page: int, page_size: int, category: str | None, status: str | None
) -> str:
    scope = json.dumps(
        {
            "tenant_id": tenant_id,
            "version": version,
            "page": page,
            "page_size": page_size,
            "category": category,
            "status": status,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"{_CACHE_PREFIX}:{hashlib.sha256(scope.encode()).hexdigest()}"


async def get_product_list_cache(
    *, tenant_id: str, page: int, page_size: int, category: str | None, status: str | None
) -> dict | None:
    if settings.PRODUCT_LIST_CACHE_TTL_SECONDS <= 0:
        return None
    try:
        version = await _tenant_version(tenant_id)
        value = await (await _get_redis()).get(
            _cache_key(
                tenant_id=tenant_id,
                version=version,
                page=page,
                page_size=page_size,
                category=category,
                status=status,
            )
        )
        return json.loads(value) if value else None
    except Exception as exc:
        logger.warning("Product list cache read failed", error=str(exc))
        return None


async def set_product_list_cache(
    *, tenant_id: str, page: int, page_size: int, category: str | None, status: str | None, payload: dict
) -> None:
    ttl = settings.PRODUCT_LIST_CACHE_TTL_SECONDS
    if ttl <= 0:
        return
    try:
        version = await _tenant_version(tenant_id)
        await (await _get_redis()).setex(
            _cache_key(
                tenant_id=tenant_id,
                version=version,
                page=page,
                page_size=page_size,
                category=category,
                status=status,
            ),
            ttl,
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        )
    except Exception as exc:
        logger.warning("Product list cache write failed", error=str(exc))


async def invalidate_product_list_cache(tenant_id: str) -> None:
    """Advance a tenant version after a committed catalog write."""
    if settings.PRODUCT_LIST_CACHE_TTL_SECONDS <= 0:
        return
    try:
        redis = await _get_redis()
        await redis.incr(_version_key(tenant_id))
        await redis.expire(_version_key(tenant_id), settings.PRODUCT_LIST_CACHE_TTL_SECONDS * 12)
    except Exception as exc:
        logger.warning("Product list cache invalidation failed", error=str(exc))
