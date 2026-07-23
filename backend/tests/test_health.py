"""健康检查端点测试"""

import asyncio
from unittest import mock

from starlette.requests import Request

from app.main import unhandled_exception_handler


def test_health_check(client) -> None:
    """基础健康检查应返回 200"""
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "version" in data


def test_liveness_check_is_dependency_free(client) -> None:
    """存活探针不依赖数据库、Redis 或对象存储。"""
    response = client.get("/api/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "alive"


def test_request_id_is_validated_and_returned(client) -> None:
    response = client.get("/api/health/live", headers={"X-Request-ID": "release-20260718"})
    assert response.status_code == 200
    assert response.headers["x-request-id"] == "release-20260718"
    assert response.headers["x-audit-trace-id"] == "release-20260718"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"


def test_readiness_check(client) -> None:
    """所有关键依赖可用时就绪检查返回 200。"""
    connection = mock.AsyncMock()
    engine = mock.Mock()
    engine.connect = mock.AsyncMock(return_value=connection)
    with (
        mock.patch("app.db.session.engine", engine),
        mock.patch("app.services.storage_service.get_minio_client") as minio_factory,
    ):
        minio_factory.return_value.list_buckets.return_value = []
        response = client.get("/api/health/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["checks"] == {"database": "ok", "redis": "ok", "minio": "ok"}


def test_readiness_returns_503_when_dependency_fails(client) -> None:
    """任一关键依赖失败时返回 503。"""
    engine = mock.Mock()
    engine.connect = mock.AsyncMock(side_effect=RuntimeError("database unavailable"))
    with (
        mock.patch("app.db.session.engine", engine),
        mock.patch("app.services.storage_service.get_minio_client") as minio_factory,
    ):
        minio_factory.return_value.list_buckets.return_value = []
        response = client.get("/api/health/ready")
    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "not_ready"
    assert data["checks"]["database"] == "unavailable"


def test_auth_token_endpoint(client) -> None:
    """登录端点应返回 JWT token"""
    response = client.post(
        "/api/auth/token",
        json={"user_id": "test-user", "username": "test", "role": "viewer"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["user_id"] == "test-user"
    assert data["tenant_id"] == "default"


def test_auth_me_endpoint(client) -> None:
    """获取当前用户信息（测试环境跳过认证）"""
    response = client.get("/api/auth/me")
    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == "dev-user"
    assert data["role"] == "admin"
    assert data["tenant_id"] == "default"


def test_rate_limit_bypass_health(client) -> None:
    """健康检查端点不应被限流"""
    for _ in range(10):
        response = client.get("/api/health")
        assert response.status_code == 200


def test_unhandled_errors_retain_security_and_audit_headers() -> None:
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": [], "state": {"request_id": "failure-trace"}})
    response = asyncio.run(unhandled_exception_handler(request, RuntimeError("boom")))

    assert response.status_code == 500
    assert response.headers["x-request-id"] == "failure-trace"
    assert response.headers["x-audit-trace-id"] == "failure-trace"
    assert response.headers["x-content-type-options"] == "nosniff"
