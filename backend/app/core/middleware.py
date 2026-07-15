"""
FastAPI 中间件集合
使用纯 ASGI 中间件替代 BaseHTTPMiddleware，避免
"Response content longer than Content-Length" 错误。
"""

import time
import uuid
from contextvars import ContextVar

import structlog
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.logging import logger

# 请求级别的 request_id（可在任意位置通过 contextvars 获取）
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


class RequestIDMiddleware:
    """统一请求 ID、审计 trace ID 与响应耗时头。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # 从请求头提取或生成 request_id
        req_headers = scope.get("headers", [])
        request_id = "-"
        for key, value in req_headers:
            if key == b"x-request-id":
                request_id = value.decode("ascii", errors="replace")
                break
        if request_id == "-":
            request_id = str(uuid.uuid4())[:8]

        request_id = request_id[:128]
        request_id_var.set(request_id)
        scope.setdefault("state", {})["request_id"] = request_id
        scope["state"]["audit_trace_id"] = request_id
        rid_bytes = request_id.encode("ascii")
        started_at = time.monotonic()

        async def send_wrapper(message: dict) -> None:
            if message["type"] == "http.response.start":
                headers = message.get("headers", [])
                headers.append([b"x-request-id", rid_bytes])
                headers.append([b"x-audit-trace-id", rid_bytes])
                duration = str(int((time.monotonic() - started_at) * 1000)).encode("ascii")
                headers.append([b"x-request-duration-ms", duration])
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)


class RequestTimingMiddleware:
    """请求耗时记录 + 结构化日志（纯 ASGI 实现）"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.monotonic()
        status_code = 0

        async def send_wrapper(message: dict) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 0)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            elapsed_ms = round((time.monotonic() - start) * 1000, 2)

            path = scope.get("path", "-")
            method = scope.get("method", "-")

            structlog.contextvars.bind_contextvars(
                method=method,
                path=path,
                status=status_code,
                duration_ms=f"{elapsed_ms:.2f}",
            )

            if status_code >= 500:
                logger.error("请求处理异常")
            elif status_code >= 400:
                logger.warning("请求处理警告")
            else:
                logger.info("请求处理完成")

            structlog.contextvars.clear_contextvars()


class PrometheusMetricsMiddleware:
    """Prometheus 请求计数/延迟中间件（纯 ASGI 实现）"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        from app.main import ACTIVE_REQUESTS, REQUEST_COUNT, REQUEST_LATENCY

        ACTIVE_REQUESTS.inc()
        method = scope.get("method", "-")
        path = scope.get("path", "-")
        start = time.monotonic()
        status_code = "500"

        async def send_wrapper(message: dict) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = str(message.get("status", 500))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            ACTIVE_REQUESTS.dec()
            elapsed = time.monotonic() - start
            REQUEST_COUNT.labels(method=method, endpoint=path, status=status_code).inc()
            REQUEST_LATENCY.labels(
                method=method, endpoint=path
            ).observe(elapsed)


def register_middleware(app: ASGIApp) -> None:
    """注册全局中间件"""
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(RequestTimingMiddleware)
    app.add_middleware(PrometheusMetricsMiddleware)
    # 注意：CORS 中间件由 main.py 单独配置，优先级最高
