"""阶段一：运行治理基础能力回归测试。"""

import pytest

from app.config import Settings, settings
from app.core.middleware import get_metric_route_label
from app.main import _validate_production_security, app


def test_database_pool_has_bounded_timeouts() -> None:
    assert settings.DATABASE_POOL_SIZE > 0
    assert settings.DATABASE_MAX_OVERFLOW >= 0
    assert settings.DATABASE_POOL_TIMEOUT_SECONDS > 0
    assert settings.DATABASE_STATEMENT_TIMEOUT_MS > 0


def test_list_settings_accept_json_and_comma_delimited_environment_values(monkeypatch) -> None:
    """Compose and direct deployments may use either documented list format."""
    monkeypatch.setenv("CORS_ORIGINS", '["https://console.shelook.test","https://api.shelook.test"]')
    monkeypatch.setenv("TRUSTED_PROXY_HOSTS", "127.0.0.1,::1,nginx")
    monkeypatch.setenv("IMAGE_FETCH_ALLOWED_HOSTS", "placehold.co,storage.googleapis.com")
    monkeypatch.setenv("FEISHU_ALLOWED_TENANT_KEYS", "tenant-a,tenant-b")

    configured = Settings(_env_file=None)

    assert configured.CORS_ORIGINS == [
        "https://console.shelook.test",
        "https://api.shelook.test",
    ]
    assert configured.TRUSTED_PROXY_HOSTS == ["127.0.0.1", "::1", "nginx"]
    assert configured.IMAGE_FETCH_ALLOWED_HOSTS == ["placehold.co", "storage.googleapis.com"]
    assert configured.FEISHU_ALLOWED_TENANT_KEYS == ["tenant-a", "tenant-b"]
    assert settings.DATABASE_LOCK_TIMEOUT_MS > 0


def test_metric_route_label_uses_route_template() -> None:
    class Route:
        path = "/api/images/{image_id}"

    assert get_metric_route_label({"route": Route()}) == "/api/images/{image_id}"
    assert get_metric_route_label({"path": "/api/images/123"}) == "unmatched"


def test_middleware_order_keeps_request_context_and_cors_outermost() -> None:
    names = [middleware.cls.__name__ for middleware in app.user_middleware]
    assert names[:6] == [
        "CORSMiddleware",
        "SecurityHeadersMiddleware",
        "RequestIDMiddleware",
        "RequestTimingMiddleware",
        "PrometheusMetricsMiddleware",
        "AuthorizationMiddleware",
    ]
    assert names[6] == "RateLimitMiddleware"


def test_production_requires_a_distinct_integration_credential_root_key(monkeypatch) -> None:
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "SECRET_KEY", "production-session-root")
    monkeypatch.setattr(settings, "MINIO_ACCESS_KEY", "production-storage-user")
    monkeypatch.setattr(settings, "MINIO_SECRET_KEY", "production-storage-secret")
    monkeypatch.setattr(settings, "INTEGRATION_CREDENTIALS_ENCRYPTION_KEY", "")

    with pytest.raises(RuntimeError, match="INTEGRATION_CREDENTIALS_ENCRYPTION_KEY"):
        _validate_production_security()

    monkeypatch.setattr(
        settings,
        "INTEGRATION_CREDENTIALS_ENCRYPTION_KEY",
        "production-session-root",
    )
    with pytest.raises(RuntimeError, match="必须与 SECRET_KEY 独立"):
        _validate_production_security()
