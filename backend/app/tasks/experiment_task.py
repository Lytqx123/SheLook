"""A/B 实验自动管理 Celery 任务。"""

from app.core.logging import logger
from app.tasks.async_utils import run_async_task
from app.tasks.celery_app import app


@app.task(name="auto_create_experiments_task")
def auto_create_experiments_task():
    """每日自动扫描并创建 A/B 实验"""
    from app.db.session import async_session_factory
    from app.services.experiment_auto_service import auto_create_experiments

    async def _run_tenant(_tenant_id: str):
        async with async_session_factory() as db:
            result = await auto_create_experiments(db)
            logger.info(
                "自动实验创建任务完成",
                scanned=result["scanned_products"],
                created=result["created"],
            )
            return result

    async def _run():
        from app.services.tenant_job_service import run_for_active_tenants

        return await run_for_active_tenants(_run_tenant, source="scheduled_experiment")

    results = run_async_task(_run())
    return {
        "tenants_processed": len(results),
        "scanned_products": sum(item["scanned_products"] for item in results.values()),
        "created": sum(item["created"] for item in results.values()),
    }


@app.task(name="update_traffic_allocation_task")
def update_traffic_allocation_task():
    """每日 UCB 流量分配更新"""
    from app.db.session import async_session_factory
    from app.services.experiment_auto_service import update_all_running_experiments

    async def _run_tenant(_tenant_id: str):
        async with async_session_factory() as db:
            result = await update_all_running_experiments(db)
            logger.info(
                "流量分配更新任务完成",
                total=result["total_running"],
                updated=result["updated"],
            )
            return result

    async def _run():
        from app.services.tenant_job_service import run_for_active_tenants

        return await run_for_active_tenants(_run_tenant, source="scheduled_experiment")

    results = run_async_task(_run())
    return {
        "tenants_processed": len(results),
        "total_running": sum(item["total_running"] for item in results.values()),
        "updated": sum(item["updated"] for item in results.values()),
    }
