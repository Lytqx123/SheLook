"""数据飞轮闭环 Celery 任务。"""

from app.core.logging import logger
from app.tasks.async_utils import run_async_task
from app.tasks.celery_app import app


@app.task(name="sync_daily_metrics")
def sync_daily_metrics():
    """Mature real CTR feedback labels; predictions remain immutable."""
    from app.db.session import async_session_factory
    from app.services.ctr_feedback import create_mature_feedback_labels

    async def _run_tenant(_tenant_id: str):
        async with async_session_factory() as db:
            result = await create_mature_feedback_labels(db, tenant_id=_tenant_id)
            await db.commit()
            logger.info(
                "真实 CTR 反馈标签刷新完成",
                tenant_id=_tenant_id,
                mature_labels_created=result["mature_labels_created"],
            )
            return result

    async def _run():
        from app.services.tenant_job_service import run_for_active_tenants

        return await run_for_active_tenants(_run_tenant, source="scheduled_flywheel")

    try:
        tenant_results = run_async_task(_run())
        return {
            "status": "success",
            "tenants_processed": len(tenant_results),
            "labels_created": sum(item.get("mature_labels_created", 0) for item in tenant_results.values()),
        }
    except Exception as e:
        logger.error(f"sync_daily_metrics 失败: {e}", exc_info=True)
        raise


@app.task(name="retrain_models")
def retrain_models():
    """模型迭代训练（每周日凌晨 3:00）"""
    from app.db.session import async_session_factory
    from app.services.data_flywheel import trigger_model_retraining

    async def _run_tenant(tenant_id: str):
        async with async_session_factory() as db:
            return await trigger_model_retraining(db, days=30, tenant_id=tenant_id)

    async def _run():
        from app.services.tenant_job_service import run_for_active_tenants

        return await run_for_active_tenants(_run_tenant, source="scheduled_training")

    try:
        results = run_async_task(_run())
        logger.info(f"模型迭代结果: {results}")
        return {"status": "success", "tenants_processed": len(results), "results": results}
    except Exception as e:
        logger.error(f"retrain_models 失败: {e}", exc_info=True)
        raise
