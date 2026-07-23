"""IP 级速率限制，Redis 滑动窗口实现"""

import secrets
import time

import redis.asyncio as aioredis
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import settings
from app.core.logging import logger


class RateLimitMiddleware:
    """ASGI 原生限流中间件，不依赖 BaseHTTPMiddleware"""

    def __init__(self, app: ASGIApp, redis_url: str | None = None) -> None:
        self.app = app
        self._redis_url = redis_url or settings.REDIS_URL
        self._redis: aioredis.Redis | None = None
        self._enabled = settings.RATE_LIMIT_ENABLED
        self._max_requests = settings.RATE_LIMIT_REQUESTS
        self._window = settings.RATE_LIMIT_WINDOW

    async def _get_redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.from_url(
                self._redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
        return self._redis

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self._enabled:
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)

        # 健康检查不限制
        path = request.url.path
        if path in ("/api/health", "/api/health/live", "/api/health/ready", "/metrics"):
            await self.app(scope, receive, send)
            return

        client_ip = self._get_client_ip(request)
        user = scope.get("state", {}).get("user")
        tenant_id = getattr(user, "tenant_id", None)
        request_limit = await self._get_request_limit(tenant_id)
        rate_limit_key = f"rate_limit:{tenant_id or 'anonymous'}:{client_ip}"

        is_limited, remaining = await self._check_rate_limit(rate_limit_key, request_limit)

        if is_limited:
            logger.warning(
                "请求被限流",
                client_ip=client_ip,
                path=path,
            )
            response = JSONResponse(
                status_code=429,
                content={"detail": "请求过于频繁，请稍后重试"},
                headers={
                    "Retry-After": str(self._window),
                    "RateLimit-Limit": str(request_limit),
                    "RateLimit-Remaining": "0",
                    "RateLimit-Reset": str(self._window),
                },
            )
            await response(scope, receive, send)
            return

        async def send_wrapper(message: dict) -> None:
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                headers.extend([
                    [b"ratelimit-limit", str(request_limit).encode("ascii")],
                    [b"ratelimit-remaining", str(remaining).encode("ascii")],
                    [b"ratelimit-reset", str(self._window).encode("ascii")],
                ])
            await send(message)

        await self.app(scope, receive, send_wrapper)

    def _get_client_ip(self, request: Request) -> str:
        """拿真实 IP，注意代理穿透"""
        host = request.client.host if request.client else "unknown"
        if host in settings.TRUSTED_PROXY_HOSTS:
            forwarded = request.headers.get("X-Forwarded-For")
            if forwarded:
                return forwarded.split(",")[0].strip()
            real_ip = request.headers.get("X-Real-IP")
            if real_ip:
                return real_ip
        return host

    async def _get_request_limit(self, tenant_id: str | None) -> int:
        """Read and briefly cache the tenant's request quota; fall back safely to global policy."""
        if not tenant_id:
            return self._max_requests
        cache_key = f"tenant_quota:rpm:{tenant_id}"
        try:
            redis = await self._get_redis()
            cached = await redis.get(cache_key)
            if cached is not None:
                return max(1, int(cached))

            from app.db.session import async_session_factory
            from app.models.organization import TenantQuota

            async with async_session_factory() as db:
                quota = await db.get(TenantQuota, tenant_id)
            limit = quota.api_requests_per_minute if quota else self._max_requests
            await redis.set(cache_key, limit, ex=60)
            return max(1, int(limit))
        except Exception as exc:
            logger.warning("Tenant rate-limit quota lookup failed", tenant_id=tenant_id, error=str(exc))
            return self._max_requests

    async def _check_rate_limit(self, key: str, max_requests: int) -> tuple[bool, int]:
        """滑动窗口限流。返回 (是否触发限流, 剩余配额)"""
        try:
            redis = await self._get_redis()
            now = time.time()
            window_start = now - self._window
            member = f"{now}:{secrets.token_hex(6)}"
            # TODO: 这个 Lua 脚本后面可以考虑抽成常量或者放到配置里
            script = """
            redis.call('ZREMRANGEBYSCORE', KEYS[1], 0, ARGV[1])
            local count = redis.call('ZCARD', KEYS[1])
            if count >= tonumber(ARGV[2]) then
                return {1, 0}
            end
            redis.call('ZADD', KEYS[1], ARGV[3], ARGV[4])
            redis.call('EXPIRE', KEYS[1], ARGV[5])
            return {0, tonumber(ARGV[2]) - count - 1}
            """
            result = await redis.eval(
                script,
                1,
                key,
                window_start,
                max_requests,
                now,
                member,
                self._window * 2,
            )
            return bool(result[0]), max(0, int(result[1]))
        except Exception as e:
            # Redis 挂了就放行，别把正常流量拦了
            logger.error("速率限制检查失败，放行请求", error=str(e))
            return False, max_requests
