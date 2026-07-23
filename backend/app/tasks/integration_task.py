"""Asynchronous, tenant-scoped provider synchronization tasks."""

from datetime import UTC, datetime

from app.core.logging import logger
from app.tasks.async_utils import run_async_task
from app.tasks.celery_app import app


@app.task(name="sync_dianxiaomi_connection")
def sync_dianxiaomi_connection(tenant_id: str, run_id: str) -> dict:
    """Run one connection sync; external requests are gated by the vendor contract."""
    from app.core.tenant import tenant_context
    from app.db.session import async_session_factory
    from app.models.integration import DianxiaomiConnection, IntegrationSyncRun
    from app.services.commerce_facts import upsert_commerce_fact
    from app.services.dianxiaomi_adapter import ProviderContractUnavailable, get_dianxiaomi_adapter

    async def _run() -> dict:
        with tenant_context(tenant_id, source="dianxiaomi_sync"):
            async with async_session_factory() as db:
                run = await db.get(IntegrationSyncRun, run_id)
                if run is None:
                    return {"status": "missing", "run_id": run_id}
                connection = await db.get(DianxiaomiConnection, run.connection_id)
                if connection is None or connection.status == "disabled":
                    run.status = "cancelled"
                    run.error_message = "连接不存在或已停用"
                    run.completed_at = datetime.now(UTC).replace(tzinfo=None)
                    await db.commit()
                    return {"status": run.status, "run_id": run_id}
                run.status = "running"
                await db.flush()
                try:
                    adapter = get_dianxiaomi_adapter()
                    received = applied = 0
                    async for record in adapter.fetch(
                        connection,
                        scopes=list(run.requested_scopes or connection.sync_scopes or []),
                        cursor=run.cursor_before,
                    ):
                        received += 1
                        applied += int(
                            await upsert_commerce_fact(
                                db,
                                tenant_id=tenant_id,
                                provider="dianxiaomi",
                                connection_key=connection.id,
                                sync_run_id=run.id,
                                record=record,
                            )
                        )
                    run.records_received = received
                    run.records_applied = applied
                    run.status = "succeeded"
                    connection.last_sync_status = "succeeded"
                    connection.last_sync_error = None
                except ProviderContractUnavailable as exc:
                    run.status = "awaiting_provider_contract"
                    run.error_message = str(exc)
                    connection.last_sync_status = run.status
                    connection.last_sync_error = str(exc)
                except Exception as exc:  # pragma: no cover - defensive worker boundary
                    run.status = "failed"
                    run.error_message = str(exc)
                    connection.last_sync_status = "failed"
                    connection.last_sync_error = str(exc)
                    logger.exception("店小秘同步失败", run_id=run_id, connection_id=connection.id)
                finally:
                    now = datetime.now(UTC).replace(tzinfo=None)
                    run.completed_at = now
                    connection.last_sync_at = now
                    await db.commit()
                return {"status": run.status, "run_id": run_id, "records_applied": run.records_applied}

    return run_async_task(_run())
