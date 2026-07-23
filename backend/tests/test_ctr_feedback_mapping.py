"""Regression coverage for explicit, tenant-safe real-CTR mapping resolution."""

import asyncio
from types import SimpleNamespace

import pytest

from app.services.ctr_feedback import InvalidPerformanceMapping, resolve_performance_mapping


def test_unknown_or_cross_tenant_mapping_is_rejected() -> None:
    db = SimpleNamespace(scalar=lambda _statement: None)

    async def scalar(_statement):
        return None

    db.scalar = scalar
    with pytest.raises(InvalidPerformanceMapping, match="不属于当前租户"):
        asyncio.run(
            resolve_performance_mapping(
                db,
                tenant_id="tenant-a",
                mapping_id="mapping-from-another-tenant",
                image_id=None,
            )
        )


def test_mapping_and_explicit_image_must_agree() -> None:
    async def scalar(_statement):
        return SimpleNamespace(id="mapping-a", image_id=9)

    db = SimpleNamespace(scalar=scalar)
    with pytest.raises(InvalidPerformanceMapping, match="不一致"):
        asyncio.run(
            resolve_performance_mapping(
                db,
                tenant_id="tenant-a",
                mapping_id="mapping-a",
                image_id=10,
            )
        )


def test_current_tenant_mapping_resolves_its_image() -> None:
    async def scalar(_statement):
        return SimpleNamespace(id="mapping-a", image_id=9)

    db = SimpleNamespace(scalar=scalar)
    assert asyncio.run(
        resolve_performance_mapping(
            db,
            tenant_id="tenant-a",
            mapping_id="mapping-a",
            image_id=None,
        )
    ) == ("mapping-a", 9, "mapped")
