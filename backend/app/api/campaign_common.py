"""Shared validation, authorization, and serialization for campaign routes."""

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserInfo, has_permission, require_auth
from app.models.campaign import (
    CampaignInsight,
    CampaignInsightStatus,
    CampaignInsightType,
    CampaignStage,
    CampaignStatus,
    VisualOperationCampaign,
)
from app.models.experiment import ABExperiment
from app.models.image import GeneratedImage, ImageScheme
from app.models.product import Product
from app.schemas.campaign import CampaignInsightResponse, CampaignResponse

_STATUS_TRANSITIONS: dict[CampaignStatus, set[CampaignStatus]] = {
    CampaignStatus.DRAFT: {
        CampaignStatus.IN_PROGRESS,
        CampaignStatus.WAITING_REVIEW,
        CampaignStatus.EXPERIMENTING,
        CampaignStatus.LEARNING,
        CampaignStatus.COMPLETED,
        CampaignStatus.ARCHIVED,
    },
    CampaignStatus.IN_PROGRESS: {
        CampaignStatus.WAITING_REVIEW,
        CampaignStatus.EXPERIMENTING,
        CampaignStatus.LEARNING,
        CampaignStatus.COMPLETED,
        CampaignStatus.ARCHIVED,
    },
    CampaignStatus.WAITING_REVIEW: {
        CampaignStatus.IN_PROGRESS,
        CampaignStatus.EXPERIMENTING,
        CampaignStatus.LEARNING,
        CampaignStatus.COMPLETED,
        CampaignStatus.ARCHIVED,
    },
    CampaignStatus.EXPERIMENTING: {
        CampaignStatus.IN_PROGRESS,
        CampaignStatus.LEARNING,
        CampaignStatus.COMPLETED,
        CampaignStatus.ARCHIVED,
    },
    CampaignStatus.LEARNING: {
        CampaignStatus.IN_PROGRESS,
        CampaignStatus.COMPLETED,
        CampaignStatus.ARCHIVED,
    },
    CampaignStatus.COMPLETED: {CampaignStatus.ARCHIVED},
    CampaignStatus.ARCHIVED: set(),
}

_STATUS_DEFAULT_STAGES: dict[CampaignStatus, CampaignStage] = {
    CampaignStatus.WAITING_REVIEW: CampaignStage.REVIEW,
    CampaignStatus.EXPERIMENTING: CampaignStage.EXPERIMENT,
    CampaignStatus.LEARNING: CampaignStage.LEARNING,
    CampaignStatus.COMPLETED: CampaignStage.LEARNING,
}


def _enum_value(value: object | None) -> str | None:
    if value is None:
        return None
    return getattr(value, "value", str(value))


def _normalise_recommended_action(value: dict[str, Any] | str | None) -> dict[str, Any] | None:
    """Keep old text recommendations usable while serving a UI action object."""
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return {"label": "执行建议", "description": text} if text else None
    return value


def _utcnow_naive() -> datetime:
    """Use the repository's existing timezone-naive database convention."""
    return datetime.now(UTC).replace(tzinfo=None)


def _campaign_response(campaign: VisualOperationCampaign) -> CampaignResponse:
    scheme_ids = [int(value) for value in (campaign.scheme_ids or [])]
    return CampaignResponse(
        id=campaign.id,
        tenant_id=campaign.tenant_id,
        name=campaign.name,
        product_id=campaign.product_id,
        market=campaign.market,
        objective=campaign.objective,
        description=campaign.description,
        objective_metric=campaign.objective_metric,
        target_value=campaign.target_value,
        status=CampaignStatus(campaign.status),
        current_stage=CampaignStage(campaign.current_stage),
        plan_id=scheme_ids[0] if scheme_ids else None,
        scheme_ids=scheme_ids,
        image_ids=[int(value) for value in (campaign.image_ids or [])],
        experiment_ids=[int(value) for value in (campaign.experiment_ids or [])],
        recommended_action=_normalise_recommended_action(campaign.recommended_action),
        next_step=campaign.next_step,
        owner_id=campaign.owner_id,
        started_at=campaign.started_at,
        completed_at=campaign.completed_at,
        created_at=campaign.created_at,
        updated_at=campaign.updated_at,
    )


def _insight_response(insight: CampaignInsight) -> CampaignInsightResponse:
    return CampaignInsightResponse(
        id=insight.id,
        campaign_id=insight.campaign_id,
        tenant_id=insight.tenant_id,
        insight_type=CampaignInsightType(insight.insight_type),
        title=insight.title,
        summary=insight.summary or "",
        source_type=insight.source_type,
        source_id=insight.source_id,
        confidence=insight.confidence,
        metric_snapshot=insight.metric_snapshot,
        evidence=insight.metric_snapshot,
        recommended_action=insight.recommended_action,
        status=CampaignInsightStatus(insight.status),
        created_by=insight.created_by,
        created_at=insight.created_at,
    )


async def require_campaign_reader(user: UserInfo = Depends(require_auth)) -> UserInfo:
    if not (
        user.role == "admin"
        or has_permission(user, "campaign:read")
        or has_permission(user, "product:read")
        or has_permission(user, "analytics:read")
        or has_permission(user, "review:read")
    ):
        raise HTTPException(status_code=403, detail="需要视觉运营活动查看权限")
    return user


async def require_campaign_operator(user: UserInfo = Depends(require_auth)) -> UserInfo:
    if not (
        user.role == "admin"
        or has_permission(user, "campaign:manage")
        or has_permission(user, "product:write")
        or has_permission(user, "generation:run")
        or has_permission(user, "experiment:manage")
    ):
        raise HTTPException(status_code=403, detail="需要视觉运营活动操作权限")
    return user


async def _get_campaign_or_404(
    db: AsyncSession,
    campaign_id: str,
    tenant_id: str,
) -> VisualOperationCampaign:
    campaign = await db.scalar(
        select(VisualOperationCampaign).where(
            VisualOperationCampaign.id == campaign_id,
            VisualOperationCampaign.tenant_id == tenant_id,
        )
    )
    if campaign is None:
        raise HTTPException(status_code=404, detail="视觉运营活动不存在")
    return campaign


def _resource_ids(values: Iterable[int] | None) -> list[int]:
    return [int(value) for value in (values or [])]


async def _validate_campaign_links(
    db: AsyncSession,
    *,
    tenant_id: str,
    product_id: int | None,
    scheme_ids: Iterable[int] | None,
    image_ids: Iterable[int] | None,
    experiment_ids: Iterable[int] | None,
) -> int | None:
    """Verify every linked record belongs to this tenant and one product."""
    resolved_product_ids: set[int] = set()
    if product_id is not None:
        product = await db.scalar(
            select(Product.id).where(Product.id == product_id, Product.tenant_id == tenant_id)
        )
        if product is None:
            raise HTTPException(status_code=422, detail="关联商品不存在或不属于当前租户")
        resolved_product_ids.add(product_id)

    scheme_id_list = _resource_ids(scheme_ids)
    if scheme_id_list:
        rows = (
            await db.execute(
                select(ImageScheme.id, ImageScheme.product_id).where(
                    ImageScheme.id.in_(scheme_id_list),
                    ImageScheme.tenant_id == tenant_id,
                )
            )
        ).all()
        found_ids = {int(row.id) for row in rows}
        missing_ids = sorted(set(scheme_id_list) - found_ids)
        if missing_ids:
            raise HTTPException(status_code=422, detail="关联视觉方案不存在或不属于当前租户")
        resolved_product_ids.update(int(row.product_id) for row in rows)

    image_id_list = _resource_ids(image_ids)
    if image_id_list:
        rows = (
            await db.execute(
                select(GeneratedImage.id, ImageScheme.product_id)
                .join(ImageScheme, GeneratedImage.scheme_id == ImageScheme.id)
                .where(
                    GeneratedImage.id.in_(image_id_list),
                    GeneratedImage.tenant_id == tenant_id,
                    ImageScheme.tenant_id == tenant_id,
                )
            )
        ).all()
        found_ids = {int(row.id) for row in rows}
        missing_ids = sorted(set(image_id_list) - found_ids)
        if missing_ids:
            raise HTTPException(status_code=422, detail="关联图片不存在或不属于当前租户")
        resolved_product_ids.update(int(row.product_id) for row in rows)

    experiment_id_list = _resource_ids(experiment_ids)
    if experiment_id_list:
        rows = (
            await db.execute(
                select(ABExperiment.id, ABExperiment.product_id).where(
                    ABExperiment.id.in_(experiment_id_list),
                    ABExperiment.tenant_id == tenant_id,
                )
            )
        ).all()
        found_ids = {int(row.id) for row in rows}
        missing_ids = sorted(set(experiment_id_list) - found_ids)
        if missing_ids:
            raise HTTPException(status_code=422, detail="关联实验不存在或不属于当前租户")
        resolved_product_ids.update(int(row.product_id) for row in rows)

    if len(resolved_product_ids) > 1:
        raise HTTPException(
            status_code=422, detail="活动关联的商品、方案、图片和实验必须属于同一商品"
        )
    return next(iter(resolved_product_ids), None)


def _validate_status_transition(
    current: CampaignStatus,
    desired: CampaignStatus,
) -> None:
    if current == desired:
        return
    if desired not in _STATUS_TRANSITIONS[current]:
        raise HTTPException(
            status_code=409,
            detail=f"活动状态不能从 {current.value} 变更为 {desired.value}",
        )


def _apply_status_stage(campaign: VisualOperationCampaign, status: CampaignStatus) -> None:
    """Advance the visible workbench stage when a lifecycle state implies one."""
    stage = _STATUS_DEFAULT_STAGES.get(status)
    if stage is not None:
        campaign.current_stage = stage.value
