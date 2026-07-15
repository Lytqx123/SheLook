"""
数据飞轮闭环 Celery 任务

两个定时任务：
- sync_daily_metrics  每天凌晨 2:00 数据回流 + 自动标注
- retrain_models      每周日凌晨 3:00 模型迭代

Celery 任务本身是同步的，内部通过 asyncio.run 调用异步服务层。
"""

import asyncio

from app.core.logging import logger
from app.tasks.celery_app import app


@app.task(name="sync_daily_metrics")
def sync_daily_metrics():
    """每日数据回流 + 自动标注

    流程：
    1. 从 daily_metrics 聚合近 30 天的效果数据
    2. 按 CTR 分位数自动标注正/负样本
    3. 标注结果写入 prediction_records
    """
    from app.db.session import async_session_factory
    from app.services.data_flywheel import aggregate_performance_data, auto_label_samples

    async def _run():
        async with async_session_factory() as db:
            # 1. 数据回流
            perf_data = await aggregate_performance_data(db, days=30)
            logger.info(f"数据回流: {len(perf_data)} 张图片")

            # 2. 自动标注
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
        raise  # 重新抛出异常，让 Celery 处理重试


@app.task(name="retrain_models")
def retrain_models():
    """模型迭代训练

    流程：
    1. 数据回流 + 自动标注（获取训练数据）
    2. 训练 CTRPredictor（GBDT + 退货分类器 v2）
    3. 保存模型到 models/ctr_predictor_YYYYMMDD.pkl（版本化，保留最近 4 版）

    调度：每周日凌晨 3:00
    """
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
        raise  # 重新抛出异常，让 Celery 处理重试
