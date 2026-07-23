"""Helpers for scheduled jobs that must execute once per active tenant."""

from collections.abc import Awaitable, Callable

from sqlalchemy import select

from app.core.tenant import tenant_context
from app.db.session import async_session_factory
from app.models.organization import Tenant


async def get_active_tenant_ids() -> list[str]:
    """Return active tenant IDs without relying on the request-default tenant."""
    async with async_session_factory() as db:
        result = await db.execute(
            select(Tenant.id).where(Tenant.status == "active").order_by(Tenant.id)
        )
        return list(result.scalars().all())


async def run_for_active_tenants(
    operation: Callable[[str], Awaitable[dict]],
    *,
    source: str,
) -> dict[str, dict]:
    """Run an async operation in a fresh, explicit tenant context for every tenant."""
    results: dict[str, dict] = {}
    for tenant_id in await get_active_tenant_ids():
        with tenant_context(tenant_id, source=source):
            results[tenant_id] = await operation(tenant_id)
    return results
