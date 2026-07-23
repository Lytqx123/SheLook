"""Regression coverage for issues found during the enterprise-readiness audit."""

import asyncio

from app.config import settings
from app.core.auth import create_access_token
from app.core.tenant import tenant_context
from app.services.pgvector_store import PgvectorStore
from app.services.predictor import CTRPredictor


def test_viewer_cannot_mutate_products_through_a_protected_router(client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "ENABLE_AUTH", True)
    token = create_access_token("viewer-1", "Viewer", "viewer", tenant_id="default")

    response = client.post(
        "/api/products",
        headers={"Authorization": f"Bearer {token}"},
        json={"sku_code": "blocked-write", "title": "Blocked"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "missing permission: product:write"


def test_prometheus_endpoint_requires_a_key_when_one_is_configured(client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "METRICS_API_KEY", "monitoring-key")

    denied = client.get("/metrics")
    assert denied.status_code == 401
    assert denied.headers["x-content-type-options"] == "nosniff"
    assert client.get("/metrics", headers={"X-Metrics-Key": "monitoring-key"}).status_code == 200


def test_tenant_model_artifacts_use_distinct_path_safe_directories() -> None:
    first = CTRPredictor.for_tenant("tenant-a")
    second = CTRPredictor.for_tenant("tenant-b")

    assert first.model_dir != second.model_dir
    assert first.model_dir.parent.name == "tenants"
    assert second.model_dir.parent.name == "tenants"


def test_vector_upsert_carries_the_explicit_tenant_id() -> None:
    class Session:
        def __init__(self) -> None:
            self.params = None
            self.committed = False

        async def execute(self, _statement, params):
            self.params = params

        async def commit(self) -> None:
            self.committed = True

    session = Session()
    with tenant_context("tenant-vector"):
        result = asyncio.run(PgvectorStore(session).insert(17, [0.1, 0.2], "test-model"))

    assert result is True
    assert session.params["tenant_id"] == "tenant-vector"
    assert session.committed is True
