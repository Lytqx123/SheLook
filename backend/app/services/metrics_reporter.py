"""业务指标上报器 —— 在被 Prometheus 抓取的 backend 进程内更新自定义指标

为什么在 backend 而非 celery worker？
  Prometheus 抓取的是 backend:8000/metrics。prometheus_client 的指标是进程内的，
  celery worker 进程中设置的 Gauge 在 backend 的 /metrics 不可见。
  因此所有业务指标必须在 backend 进程内更新。

通过 lifespan 启动的 asyncio 后台任务，每 60s 从 DB / Redis / audit_log 拉取数据，
更新以下指标：
  - shelook_quality_pass_rate             (Gauge, layer+verdict)
  - shelook_model_prediction_drift        (Gauge, model_type)
  - shelook_generation_task_duration_seconds (Histogram, provider+status)
  - shelook_celery_queue_length           (Gauge, queue)
"""

import asyncio

from sqlalchemy import func, select

from app.config import settings
from app.core.logging import logger

# 跟踪已观察的审计日志 ID，避免重复 observe 同一条生成耗时
# None 表示尚未初始化（首次运行时跳过历史数据，仅观察启动后的新记录）
_last_audit_id: int | None = None

REPORT_INTERVAL_SECONDS = 60


async def _update_quality_pass_rate(db) -> None:
    """质检通过率（按 L1/L2/L3 层级）

    L1 合规层通过率：overall_score > 0 的比例（L1 失败时流水线提前返回 overall_score=0）
    L2 质量层通过率：overall_score >= 60 的比例（达到 manual_pending 阈值）
    L3 审美层通过率：overall_score >= 75 的比例（达到 auto_approved 阈值）
    """
    from app.main import QUALITY_PASS_RATE
    from app.models.image import GeneratedImage

    total = await db.scalar(select(func.count()).select_from(GeneratedImage))
    if not total:
        return

    l1_passed = await db.scalar(
        select(func.count()).select_from(GeneratedImage)
        .where(GeneratedImage.overall_score > 0)
    )
    l2_passed = await db.scalar(
        select(func.count()).select_from(GeneratedImage)
        .where(GeneratedImage.overall_score >= 60)
    )
    l3_passed = await db.scalar(
        select(func.count()).select_from(GeneratedImage)
        .where(GeneratedImage.overall_score >= 75)
    )

    QUALITY_PASS_RATE.labels(layer="L1", verdict="auto_approved").set(
        (l1_passed or 0) / total
    )
    QUALITY_PASS_RATE.labels(layer="L2", verdict="auto_approved").set(
        (l2_passed or 0) / total
    )
    QUALITY_PASS_RATE.labels(layer="L3", verdict="auto_approved").set(
        (l3_passed or 0) / total
    )


async def _update_celery_queue_length() -> None:
    """Celery 队列深度（从 Redis 直接读取 list 长度，比 inspect 更快更稳定）"""
    import redis.asyncio as aioredis

    from app.main import CELERY_QUEUE_LENGTH

    try:
        r = aioredis.from_url(settings.CELERY_BROKER_URL)
        # Celery 默认队列为 "celery"
        length = await r.llen("celery")
        await r.aclose()
        CELERY_QUEUE_LENGTH.labels(queue="celery").set(length)
    except Exception as e:
        logger.warning("Celery 队列长度采集失败", error=str(e))


async def _update_model_prediction_drift(db) -> None:
    """模型预测漂移（MAE）：预测值 vs 实际值的平均绝对误差

    ctr:    |predicted_ctr - actual_ctr|，actual_ctr = sum(clicks)/sum(impressions)
    return: |退货风险等级概率映射 - actual return_rate|
    hit:    缺乏实际爆款标签，暂不计算（仪表盘对应面板无数据）
    """
    from app.main import MODEL_PREDICTION_DRIFT
    from app.models.prediction import DailyMetric, PredictionRecord

    # ---- CTR 漂移 ----
    ctr_rows = await db.execute(
        select(
            PredictionRecord.predicted_ctr,
            (
                func.sum(DailyMetric.clicks) * 1.0
                / func.nullif(func.sum(DailyMetric.impressions), 0)
            ).label("actual_ctr"),
        )
        .join(DailyMetric, DailyMetric.image_id == PredictionRecord.image_id)
        .where(PredictionRecord.predicted_ctr.isnot(None))
        .group_by(PredictionRecord.id, PredictionRecord.predicted_ctr)
    )
    ctr_diffs = [
        abs(row[0] - row[1])
        for row in ctr_rows
        if row[0] is not None and row[1] is not None
    ]
    if ctr_diffs:
        MODEL_PREDICTION_DRIFT.labels(model_type="ctr").set(
            sum(ctr_diffs) / len(ctr_diffs)
        )

    # ---- Return 漂移（退货风险等级 → 概率映射）----
    level_prob = {"low": 0.1, "medium": 0.3, "high": 0.7}
    return_rows = await db.execute(
        select(
            PredictionRecord.return_risk_level,
            func.avg(DailyMetric.return_rate).label("actual_return"),
        )
        .join(DailyMetric, DailyMetric.image_id == PredictionRecord.image_id)
        .where(PredictionRecord.return_risk_level.isnot(None))
        .where(DailyMetric.return_rate.isnot(None))
        .group_by(PredictionRecord.id, PredictionRecord.return_risk_level)
    )
    return_diffs = []
    for row in return_rows:
        level = row[0].value if row[0] else "low"
        prob = level_prob.get(level, 0.1)
        actual = row[1]
        if actual is not None:
            return_diffs.append(abs(prob - actual))
    if return_diffs:
        MODEL_PREDICTION_DRIFT.labels(model_type="return").set(
            sum(return_diffs) / len(return_diffs)
        )


async def _update_generation_task_duration(db) -> None:
    """生图任务耗时（从 audit_log 增量观察，每条只 observe 一次）

    首次运行时跳过历史数据（_last_audit_id 初始化为当前最大 ID），
    仅观察 backend 启动后的新生成记录，避免重启时重复 observe 历史数据。
    """
    global _last_audit_id
    from app.main import GENERATION_TASK_DURATION
    from app.models.audit_log import AuditLog

    # 首次运行：初始化为当前最大 ID，跳过历史数据
    if _last_audit_id is None:
        max_id = await db.scalar(
            select(func.max(AuditLog.id)).where(AuditLog.operation == "generate")
        )
        _last_audit_id = max_id or 0
        logger.info("生图耗时指标初始化", last_audit_id=_last_audit_id)
        return

    rows = await db.execute(
        select(
            AuditLog.id,
            AuditLog.model_name,
            AuditLog.status,
            AuditLog.duration_ms,
        )
        .where(
            AuditLog.operation == "generate",
            AuditLog.id > _last_audit_id,
            AuditLog.duration_ms.isnot(None),
        )
        .order_by(AuditLog.id)
        .limit(500)
    )
    max_id = _last_audit_id
    for row in rows:
        provider = row.model_name or "unknown"
        status = row.status or "unknown"
        GENERATION_TASK_DURATION.labels(provider=provider, status=status).observe(
            row.duration_ms / 1000.0
        )
        if row.id > max_id:
            max_id = row.id
    _last_audit_id = max_id


async def _update_all_metrics() -> None:
    """采集并更新全部业务指标"""
    from app.db.session import async_session_factory

    try:
        async with async_session_factory() as db:
            await _update_quality_pass_rate(db)
            await _update_model_prediction_drift(db)
            await _update_generation_task_duration(db)
        await _update_celery_queue_length()
    except Exception as e:
        logger.warning("业务指标采集失败", error=str(e))


async def metrics_reporter_loop() -> None:
    """业务指标上报循环（由 lifespan 启动，应用关闭时取消）"""
    logger.info("业务指标上报器已启动", interval=REPORT_INTERVAL_SECONDS)
    while True:
        try:
            await _update_all_metrics()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("指标上报循环异常", error=str(e))
        await asyncio.sleep(REPORT_INTERVAL_SECONDS)
