"""Prometheus business metrics, aggregated safely across active tenants."""

import asyncio

from sqlalchemy import func, select

from app.config import settings
from app.core.logging import logger
from app.core.tenant import tenant_context

REPORT_INTERVAL_SECONDS = 60
CELERY_QUEUES = ("orchestration", "generation", "model", "analytics")
_last_audit_ids: dict[str, int] = {}


async def _collect_quality_pass_counts(db) -> tuple[int, int, int, int]:
    from app.models.image import GeneratedImage

    total = await db.scalar(select(func.count()).select_from(GeneratedImage))
    if not total:
        return 0, 0, 0, 0
    l1_passed = await db.scalar(
        select(func.count())
        .select_from(GeneratedImage)
        .where(GeneratedImage.overall_score > 0)
    )
    l2_passed = await db.scalar(
        select(func.count())
        .select_from(GeneratedImage)
        .where(GeneratedImage.overall_score >= 60)
    )
    l3_passed = await db.scalar(
        select(func.count())
        .select_from(GeneratedImage)
        .where(GeneratedImage.overall_score >= 75)
    )
    return total, l1_passed or 0, l2_passed or 0, l3_passed or 0


async def _collect_model_prediction_diffs(db) -> tuple[list[float], list[float]]:
    from app.models.prediction import DailyMetric, PredictionRecord

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
    return_diffs: list[float] = []
    for row in return_rows:
        level = row[0].value if row[0] else "low"
        actual = row[1]
        if actual is not None:
            return_diffs.append(abs(level_prob.get(level, 0.1) - actual))
    return ctr_diffs, return_diffs


async def _observe_generation_task_duration(db, tenant_id: str) -> None:
    from app.main import GENERATION_TASK_DURATION
    from app.models.audit_log import AuditLog

    last_audit_id = _last_audit_ids.get(tenant_id)
    if last_audit_id is None:
        max_id = await db.scalar(
            select(func.max(AuditLog.id)).where(AuditLog.operation == "generate")
        )
        _last_audit_ids[tenant_id] = max_id or 0
        logger.info(
            "Generation duration metric initialized",
            tenant_id=tenant_id,
            last_audit_id=max_id or 0,
        )
        return

    rows = await db.execute(
        select(AuditLog.id, AuditLog.model_name, AuditLog.status, AuditLog.duration_ms)
        .where(
            AuditLog.operation == "generate",
            AuditLog.id > last_audit_id,
            AuditLog.duration_ms.isnot(None),
        )
        .order_by(AuditLog.id)
        .limit(500)
    )
    max_id = last_audit_id
    for row in rows:
        GENERATION_TASK_DURATION.labels(
            provider=row.model_name or "unknown", status=row.status or "unknown"
        ).observe(row.duration_ms / 1000.0)
        max_id = max(max_id, row.id)
    _last_audit_ids[tenant_id] = max_id


async def _update_celery_queue_length() -> None:
    import redis.asyncio as aioredis

    from app.main import CELERY_QUEUE_LENGTH

    try:
        redis_client = aioredis.from_url(settings.CELERY_BROKER_URL)
        for queue in CELERY_QUEUES:
            CELERY_QUEUE_LENGTH.labels(queue=queue).set(await redis_client.llen(queue))
        await redis_client.aclose()
    except Exception as exc:
        logger.warning("Celery queue metric collection failed", error=str(exc))


async def _update_all_metrics() -> None:
    from app.db.session import async_session_factory
    from app.main import MODEL_PREDICTION_DRIFT, QUALITY_PASS_RATE
    from app.services.tenant_job_service import get_active_tenant_ids

    try:
        totals = [0, 0, 0, 0]
        ctr_diffs: list[float] = []
        return_diffs: list[float] = []
        for tenant_id in await get_active_tenant_ids():
            with tenant_context(tenant_id, source="metrics_reporter"):
                async with async_session_factory() as db:
                    counts = await _collect_quality_pass_counts(db)
                    totals = [left + right for left, right in zip(totals, counts, strict=True)]
                    tenant_ctr_diffs, tenant_return_diffs = await _collect_model_prediction_diffs(db)
                    ctr_diffs.extend(tenant_ctr_diffs)
                    return_diffs.extend(tenant_return_diffs)
                    await _observe_generation_task_duration(db, tenant_id)

        total, l1_passed, l2_passed, l3_passed = totals
        for layer, passed in (("L1", l1_passed), ("L2", l2_passed), ("L3", l3_passed)):
            QUALITY_PASS_RATE.labels(layer=layer, verdict="auto_approved").set(
                passed / total if total else 0
            )
        if ctr_diffs:
            MODEL_PREDICTION_DRIFT.labels(model_type="ctr").set(
                sum(ctr_diffs) / len(ctr_diffs)
            )
        if return_diffs:
            MODEL_PREDICTION_DRIFT.labels(model_type="return").set(
                sum(return_diffs) / len(return_diffs)
            )
        await _update_celery_queue_length()
    except Exception as exc:
        logger.warning("Business metric collection failed", error=str(exc))


async def metrics_reporter_loop() -> None:
    logger.info("Business metrics reporter started", interval=REPORT_INTERVAL_SECONDS)
    while True:
        try:
            await _update_all_metrics()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Business metrics reporter loop failed", error=str(exc))
        await asyncio.sleep(REPORT_INTERVAL_SECONDS)
