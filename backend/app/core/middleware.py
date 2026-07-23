"""
FastAPI 中间件集合，全用纯 ASGI 实现，避免 BaseHTTPMiddleware 的 Content-Length 坑。
"""

import secrets
import time
import uuid
from contextvars import ContextVar
from re import compile as re_compile

import structlog
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import settings
from app.core.logging import logger
from app.core.tenant import clear_tenant_context

# 请求级别的 request_id，全局可拿
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
_REQUEST_ID_PATTERN = re_compile(r"^[A-Za-z0-9._-]{1,128}$")


def _get_request_id(scope: Scope) -> str:
    """只回显安全的关联 ID，避免把任意请求头写进响应与日志。"""
    for key, value in scope.get("headers", []):
        if key in {b"x-request-id", b"x-correlation-id"}:
            candidate = value.decode("ascii", errors="ignore").strip()
            if _REQUEST_ID_PATTERN.fullmatch(candidate):
                return candidate
    return uuid.uuid4().hex


def get_metric_route_label(scope: Scope) -> str:
    """返回稳定的路由模板，避免把资源 ID 写成 Prometheus 高基数标签。"""
    route = scope.get("route")
    route_path = getattr(route, "path", None) or getattr(route, "path_format", None)
    if isinstance(route_path, str):
        return route_path
    return "unmatched"


class RequestIDMiddleware:
    """给每个请求塞一个 request_id，响应头里也带回去"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _get_request_id(scope)
        request_id_token = request_id_var.set(request_id)
        structlog.contextvars.bind_contextvars(request_id=request_id)
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

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            request_id_var.reset(request_id_token)
            structlog.contextvars.unbind_contextvars("request_id")
            clear_tenant_context()


class RequestTimingMiddleware:
    """请求耗时 + 结构化日志"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if scope.get("path") == "/metrics":
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


class SecurityHeadersMiddleware:
    """Provide browser-safe headers even when the API is reached without Nginx."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: dict) -> None:
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                headers.extend([
                    [b"x-content-type-options", b"nosniff"],
                    [b"x-frame-options", b"DENY"],
                    [b"referrer-policy", b"strict-origin-when-cross-origin"],
                    [b"permissions-policy", b"camera=(), microphone=(), geolocation=()"],
                ])
            await send(message)

        await self.app(scope, receive, send_wrapper)


class AuthorizationMiddleware:
    """Enforce role permissions consistently before protected API handlers run."""

    @staticmethod
    def _required_permission(scope: Scope) -> str | None:
        path = str(scope.get("path", ""))
        method = str(scope.get("method", "GET")).upper()
        if method == "OPTIONS" or not path.startswith("/api/"):
            return None
        if path.startswith(("/api/health", "/api/auth", "/api/metrics", "/api/organization", "/api/workflows")):
            return None
        if path.startswith("/api/products"):
            return "product:read" if method == "GET" else "product:write"
        if path.startswith("/api/schemes"):
            return "product:read"
        if path.startswith("/api/generation"):
            return "product:read" if method == "GET" or scope["type"] == "websocket" else "generation:run"
        if path.startswith("/api/review"):
            return "review:read" if method == "GET" else "review:decide"
        if path.startswith("/api/prediction"):
            return "model:manage" if path.endswith("/rollback") else "analytics:read"
        if path.startswith("/api/experiments"):
            return "experiment:read" if method == "GET" else "experiment:manage"
        if path.startswith(("/api/dashboard", "/api/fairness", "/api/clustering")):
            return "analytics:read"
        if path.startswith("/api/flywheel"):
            return "model:manage"
        if path.startswith("/api/audit"):
            return "audit:read"
        if path.startswith("/api/supplier"):
            return "supplier:read" if method == "GET" else "supplier:write"
        if path.startswith("/api/video"):
            return "product:read" if method == "GET" else "generation:run"
        return None

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = str(scope.get("path", ""))
        if path == "/metrics" and settings.METRICS_API_KEY:
            headers = dict(scope.get("headers", []))
            provided = headers.get(b"x-metrics-key", b"").decode("utf-8", errors="ignore")
            if not provided:
                authorization = headers.get(b"authorization", b"").decode(
                    "utf-8", errors="ignore"
                )
                scheme, _, token = authorization.partition(" ")
                provided = token if scheme.lower() == "bearer" else ""
            if not secrets.compare_digest(provided, settings.METRICS_API_KEY):
                if scope["type"] == "http":
                    from starlette.responses import JSONResponse

                    await JSONResponse({"detail": "invalid metrics key"}, status_code=401)(scope, receive, send)
                return

        permission = self._required_permission(scope)
        if permission is None or scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return

        from starlette.requests import HTTPConnection

        from app.core.auth import get_current_user, has_permission

        user = await get_current_user(HTTPConnection(scope))
        if user is not None and not has_permission(user, permission):
            if scope["type"] == "http":
                from starlette.responses import JSONResponse

                await JSONResponse(
                    {"detail": f"missing permission: {permission}"}, status_code=403
                )(scope, receive, send)
            else:
                await send({"type": "websocket.close", "code": 4403})
            clear_tenant_context()
            return

        try:
            await self.app(scope, receive, send)
        finally:
            clear_tenant_context()


class PrometheusMetricsMiddleware:
    """Prometheus 请求计数 / 延迟"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        from app.main import ACTIVE_REQUESTS, REQUEST_COUNT, REQUEST_LATENCY

        ACTIVE_REQUESTS.inc()
        method = scope.get("method", "-")
        scope.get("path", "-")
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
            route = get_metric_route_label(scope)
            REQUEST_COUNT.labels(method=method, route=route, status=status_code).inc()
            REQUEST_LATENCY.labels(
                method=method, route=route
            ).observe(elapsed)


def register_middleware(app: ASGIApp) -> None:
    app.add_middleware(AuthorizationMiddleware)
    app.add_middleware(PrometheusMetricsMiddleware)
    app.add_middleware(RequestTimingMiddleware)
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    # CORS 在 main.py 单独配，得最先执行
