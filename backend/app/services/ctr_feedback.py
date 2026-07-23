"""Write and mature traceable real-CTR evidence without mutating predictions."""

import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enterprise_data import (
    ExternalEntityMapping,
    ModelFeedbackLabel,
    PerformanceFact,
    PredictionSnapshot,
)
from app.services.runtime_settings import get_effective_runtime_setting


class InvalidPerformanceMapping(ValueError):
    """Raised when a submitted performance fact references an invalid mapping."""


def payload_hash(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


async def resolve_performance_mapping(
    db: AsyncSession,
    *,
    tenant_id: str,
    mapping_id: str | None,
    image_id: int | None,
) -> tuple[str | None, int | None, str]:
    """Resolve explicit mapping; no fuzzy matching is permitted for training evidence."""
    if mapping_id is None:
        return (None, image_id, "mapped") if image_id is not None else (None, None, "pending_mapping")
    mapping = await db.scalar(
        select(ExternalEntityMapping).where(
            ExternalEntityMapping.id == mapping_id,
            ExternalEntityMapping.tenant_id == tenant_id,
        )
    )
    if mapping is None:
        raise InvalidPerformanceMapping("关联映射不存在或不属于当前租户")
    if image_id is not None and mapping.image_id is not None and mapping.image_id != image_id:
        raise InvalidPerformanceMapping("提交的图片与外部实体映射中的图片不一致")
    if image_id is not None:
        return mapping.id, image_id, "mapped"
    if mapping.image_id is None:
        return mapping_id, None, "pending_mapping"
    return mapping.id, mapping.image_id, "mapped"


async def create_mature_feedback_labels(
    db: AsyncSession,
    *,
    tenant_id: str,
) -> dict[str, int | float]:
    """Pair snapshots with mature performance facts in a forward-only observation window."""
    minimum_impressions = int(
        (
            await get_effective_runtime_setting(
                db,
                tenant_id=tenant_id,
                setting_key="ctr.minimum_mature_impressions",
            )
        ).value
    )
    snapshots = list(
        (
            await db.execute(
                select(PredictionSnapshot).order_by(PredictionSnapshot.predicted_at.asc())
            )
        ).scalars()
    )
    created = insufficient = missing = 0
    for snapshot in snapshots:
        existing = await db.scalar(
            select(ModelFeedbackLabel.id).where(
                ModelFeedbackLabel.prediction_snapshot_id == snapshot.id,
                ModelFeedbackLabel.label_version == "v1",
            )
        )
        if existing is not None:
            continue
        start = snapshot.predicted_at.date()
        aggregate = (
            await db.execute(
                select(
                    func.sum(PerformanceFact.impressions),
                    func.sum(PerformanceFact.clicks),
                    func.count(PerformanceFact.id),
                    func.max(PerformanceFact.metric_date),
                ).where(
                    PerformanceFact.image_id == snapshot.image_id,
                    PerformanceFact.is_mature.is_(True),
                    PerformanceFact.quality_status == "mapped",
                    PerformanceFact.metric_date >= start,
                )
            )
        ).one()
        impressions = int(aggregate[0] or 0)
        clicks = int(aggregate[1] or 0)
        source_count = int(aggregate[2] or 0)
        end = aggregate[3]
        if source_count == 0 or end is None:
            missing += 1
            continue
        if impressions < minimum_impressions:
            insufficient += 1
            continue
        db.add(
            ModelFeedbackLabel(
                tenant_id=tenant_id,
                prediction_snapshot_id=snapshot.id,
                image_id=snapshot.image_id,
                observation_start=start,
                observation_end=end,
                impressions=impressions,
                clicks=clicks,
                actual_ctr=clicks / impressions,
                source_count=source_count,
                status="mature",
                label_version="v1",
                matured_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )
        created += 1
    eligible = len(snapshots)
    return {
        "eligible_snapshots": eligible,
        "mature_labels_created": created,
        "skipped_insufficient_impressions": insufficient,
        "skipped_missing_performance": missing,
        "coverage_rate": round(created / eligible, 4) if eligible else 0.0,
    }
