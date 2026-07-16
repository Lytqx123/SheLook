"""数据飞轮闭环 Celery 任务。"""

import asyncio

from app.core.logging import logger
from app.tasks.celery_app import app


@app.task(name="sync_daily_metrics")
def sync_daily_metrics():
    """每日数据回流 + 自动标注"""
    from app.db.session import async_session_factory
    from app.services.data_flywheel import aggregate_performance_data, auto_label_samples

    async def _run():
        async with async_session_factory() as db:
            perf_data = await aggregate_performance_data(db, days=30)
            logger.info(f"数据回流: {len(perf_data)} 张图片")

            result = await auto_label_samples(db, performance_data=perf_data, days=30)
            logger.info(
                f"自动标注: 正样本 {result['positive_samples']}, "
                f"负样本 {result['negative_samples']}, "
                f"高退货 {result.get('high_return_samples', 0)}"
            )
            return result

    try:
        result = asyncio.run(_run())
        return {
            "status": "success",
            "images_processed": result.get("total_samples", 0),
            "positive_samples": result.get("positive_samples", 0),
            "negative_samples": result.get("negative_samples", 0),
        }
    except Exception as e:
        logger.error(f"sync_daily_metrics 失败: {e}", exc_info=True)
        raise


@app.task(name="retrain_models")
def retrain_models():
    """模型迭代训练（每周日凌晨 3:00）"""
    from app.db.session import async_session_factory
    from app.services.data_flywheel import trigger_model_retraining

    async def _run():
        async with async_session_factory() as db:
            return await trigger_model_retraining(db, days=30)

    try:
        result = asyncio.run(_run())
        logger.info(f"模型迭代结果: {result}")
        return result
    except Exception as e:
        logger.error(f"retrain_models 失败: {e}", exc_info=True)
        raise
