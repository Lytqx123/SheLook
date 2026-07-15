"""IP 级 API 速率限制中间件 —— 基于 Redis 滑动窗口

用法（在 main.py 中）：
  from app.core.rate_limit import RateLimitMiddleware
  app.add_middleware(RateLimitMiddleware, redis_url=settings.REDIS_URL)
"""

import secrets
import time

import redis.asyncio as aioredis
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import settings
from app.core.logging import logger


class RateLimitMiddleware:
    """基于 Redis 滑动窗口的 IP 速率限制中间件

    ASGI 原生中间件，不依赖 BaseHTTPMiddleware，避免与背景任务冲突。
    """

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

        # 跳过健康检查和 metrics 端点
        path = request.url.path
        if path in ("/api/health", "/api/health/ready", "/metrics"):
            await self.app(scope, receive, send)
            return

        # 获取客户端 IP
        client_ip = self._get_client_ip(request)

        # 滑动窗口限流
        is_limited, remaining = await self._check_rate_limit(client_ip)

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
                    "RateLimit-Limit": str(self._max_requests),
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
                    [b"ratelimit-limit", str(self._max_requests).encode("ascii")],
                    [b"ratelimit-remaining", str(remaining).encode("ascii")],
                    [b"ratelimit-reset", str(self._window).encode("ascii")],
                ])
            await send(message)

        await self.app(scope, receive, send_wrapper)

    def _get_client_ip(self, request: Request) -> str:
        """获取真实客户端 IP"""
        host = request.client.host if request.client else "unknown"
        if host in settings.TRUSTED_PROXY_HOSTS:
            forwarded = request.headers.get("X-Forwarded-For")
            if forwarded:
                return forwarded.split(",")[0].strip()
            real_ip = request.headers.get("X-Real-IP")
            if real_ip:
                return real_ip
        return host

    async def _check_rate_limit(self, client_ip: str) -> tuple[bool, int]:
        """滑动窗口算法：检查是否超过限制

        Returns:
            (是否限流, 剩余配额)
        """
        try:
            redis = await self._get_redis()
            now = time.time()
            window_start = now - self._window
            key = f"rate_limit:{client_ip}"

            member = f"{now}:{secrets.token_hex(6)}"
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
                self._max_requests,
                now,
                member,
                self._window * 2,
            )
            return bool(result[0]), max(0, int(result[1]))
        except Exception as e:
            logger.error("速率限制检查失败，放行请求", error=str(e))
            return False, self._max_requests
