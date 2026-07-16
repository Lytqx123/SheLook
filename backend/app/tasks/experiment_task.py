"""A/B 实验自动管理 Celery 任务。"""

import asyncio

from app.core.logging import logger
from app.tasks.celery_app import app


@app.task(name="auto_create_experiments_task")
def auto_create_experiments_task():
    """每日自动扫描并创建 A/B 实验"""
    from app.db.session import async_session_factory
    from app.services.experiment_auto_service import auto_create_experiments

    async def _run():
        async with async_session_factory() as db:
            result = await auto_create_experiments(db)
            logger.info(
                "自动实验创建任务完成",
                scanned=result["scanned_products"],
                created=result["created"],
            )
            return result

    return asyncio.run(_run())


@app.task(name="update_traffic_allocation_task")
def update_traffic_allocation_task():
    """每日 UCB 流量分配更新"""
    from app.db.session import async_session_factory
    from app.services.experiment_auto_service import update_all_running_experiments

    async def _run():
        async with async_session_factory() as db:
            result = await update_all_running_experiments(db)
            logger.info(
                "流量分配更新任务完成",
                total=result["total_running"],
                updated=result["updated"],
            )
            return result

    return asyncio.run(_run())
