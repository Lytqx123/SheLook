"""Campaign HTTP routes.

The route surface remains here for stable imports and URLs; validation and
detail-read assembly live in focused sibling modules.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.campaign_common import (
    _apply_status_stage,
    _campaign_response,
    _get_campaign_or_404,
    _insight_response,
    _normalise_recommended_action,
    _resource_ids,
    _utcnow_naive,
    _validate_campaign_links,
    _validate_status_transition,
    require_campaign_operator,
    require_campaign_reader,
)
from app.api.campaign_details import (
    build_campaign_detail as _campaign_detail,
)
from app.api.campaign_details import (
    load_insights as _load_insights,
)
from app.core.auth import UserInfo
from app.db.session import get_db
from app.models.campaign import (
    CampaignInsight,
    CampaignStage,
    CampaignStatus,
    VisualOperationCampaign,
)
from app.schemas.campaign import (
    CampaignCreateRequest,
    CampaignDetailResponse,
    CampaignInsightCreateRequest,
    CampaignInsightResponse,
    CampaignListResponse,
    CampaignResponse,
    CampaignStatusUpdateRequest,
    CampaignUpdateRequest,
)

# `/api/v1` is the stable endpoint family for new product workflows. The
# unversioned router remains a compatibility alias for existing `/api/*` clients.
router = APIRouter(prefix="/api/v1/campaigns", tags=["Campaigns"])
compat_router = APIRouter(prefix="/api/campaigns", tags=["Campaigns"])


@compat_router.get("", response_model=CampaignListResponse)
@router.get("", response_model=CampaignListResponse)
async def list_campaigns(
    status: CampaignStatus | None = None,
    product_id: int | None = Query(default=None, ge=1),
    market: str | None = Query(default=None, max_length=64),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: UserInfo = Depends(require_campaign_reader),
    db: AsyncSession = Depends(get_db),
) -> CampaignListResponse:
    filters = [VisualOperationCampaign.tenant_id == user.tenant_id]
    if status is not None:
        filters.append(VisualOperationCampaign.status == status.value)
    if product_id is not None:
        filters.append(VisualOperationCampaign.product_id == product_id)
    if market:
        filters.append(VisualOperationCampaign.market == market)

    total = await db.scalar(
        select(func.count()).select_from(VisualOperationCampaign).where(*filters)
    )
    result = await db.execute(
        select(VisualOperationCampaign)
        .where(*filters)
        .order_by(
            VisualOperationCampaign.updated_at.desc(), VisualOperationCampaign.created_at.desc()
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return CampaignListResponse(
        items=[_campaign_response(campaign) for campaign in result.scalars()],
        total=total or 0,
        page=page,
        page_size=page_size,
    )


@compat_router.post("", response_model=CampaignResponse, status_code=201)
@router.post("", response_model=CampaignResponse, status_code=201)
async def create_campaign(
    body: CampaignCreateRequest,
    user: UserInfo = Depends(require_campaign_operator),
    db: AsyncSession = Depends(get_db),
) -> CampaignResponse:
    scheme_ids = _resource_ids(body.scheme_ids)
    image_ids = _resource_ids(body.image_ids)
    experiment_ids = _resource_ids(body.experiment_ids)
    product_id = await _validate_campaign_links(
        db,
        tenant_id=user.tenant_id,
        product_id=body.product_id,
        scheme_ids=scheme_ids,
        image_ids=image_ids,
        experiment_ids=experiment_ids,
    )
    now = _utcnow_naive()
    campaign = VisualOperationCampaign(
        tenant_id=user.tenant_id,
        name=body.name.strip(),
        product_id=product_id,
        market=body.market.strip() if body.market else None,
        objective=body.objective.strip() if body.objective else None,
        description=body.description.strip() if body.description else None,
        objective_metric=body.objective_metric.strip() if body.objective_metric else None,
        target_value=body.target_value,
        status=body.status.value,
        current_stage=body.current_stage.value,
        scheme_ids=scheme_ids or None,
        image_ids=image_ids or None,
        experiment_ids=experiment_ids or None,
        recommended_action=_normalise_recommended_action(body.recommended_action),
        next_step=body.next_step.strip() if body.next_step else None,
        owner_id=body.owner_id or user.user_id,
        started_at=now if body.status == CampaignStatus.IN_PROGRESS else None,
        completed_at=now if body.status == CampaignStatus.COMPLETED else None,
    )
    if body.status == CampaignStatus.COMPLETED and body.current_stage == CampaignStage.BRIEF:
        campaign.current_stage = CampaignStage.LEARNING.value
    elif body.current_stage == CampaignStage.BRIEF:
        _apply_status_stage(campaign, body.status)
    db.add(campaign)
    await db.flush()
    await db.refresh(campaign)
    return _campaign_response(campaign)


@compat_router.get("/{campaign_id}", response_model=CampaignDetailResponse)
@router.get("/{campaign_id}", response_model=CampaignDetailResponse)
async def get_campaign(
    campaign_id: str,
    user: UserInfo = Depends(require_campaign_reader),
    db: AsyncSession = Depends(get_db),
) -> CampaignDetailResponse:
    campaign = await _get_campaign_or_404(db, campaign_id, user.tenant_id)
    return await _campaign_detail(db, campaign)


@compat_router.patch("/{campaign_id}", response_model=CampaignResponse)
@router.patch("/{campaign_id}", response_model=CampaignResponse)
async def update_campaign(
    campaign_id: str,
    body: CampaignUpdateRequest,
    user: UserInfo = Depends(require_campaign_operator),
    db: AsyncSession = Depends(get_db),
) -> CampaignResponse:
    campaign = await _get_campaign_or_404(db, campaign_id, user.tenant_id)
    fields_set = body.model_fields_set
    scheme_ids = (
        _resource_ids(body.scheme_ids)
        if "scheme_ids" in fields_set
        else _resource_ids(campaign.scheme_ids)
    )
    image_ids = (
        _resource_ids(body.image_ids)
        if "image_ids" in fields_set
        else _resource_ids(campaign.image_ids)
    )
    experiment_ids = (
        _resource_ids(body.experiment_ids)
        if "experiment_ids" in fields_set
        else _resource_ids(campaign.experiment_ids)
    )
    if "plan_id" in fields_set and body.plan_id is not None and body.plan_id not in scheme_ids:
        scheme_ids.insert(0, body.plan_id)
    requested_product_id = body.product_id if "product_id" in fields_set else campaign.product_id
    product_id = await _validate_campaign_links(
        db,
        tenant_id=user.tenant_id,
        product_id=requested_product_id,
        scheme_ids=scheme_ids,
        image_ids=image_ids,
        experiment_ids=experiment_ids,
    )

    if body.status is not None:
        current_status = CampaignStatus(campaign.status)
        _validate_status_transition(current_status, body.status)
        campaign.status = body.status.value
        now = _utcnow_naive()
        if body.status == CampaignStatus.IN_PROGRESS and campaign.started_at is None:
            campaign.started_at = now
        if body.status == CampaignStatus.COMPLETED:
            campaign.completed_at = now
            if body.current_stage is None:
                campaign.current_stage = CampaignStage.LEARNING.value
        elif body.current_stage is None:
            _apply_status_stage(campaign, body.status)

    for field in (
        "name",
        "market",
        "objective",
        "description",
        "objective_metric",
        "target_value",
        "current_stage",
        "recommended_action",
        "next_step",
        "owner_id",
    ):
        if field not in fields_set:
            continue
        value = getattr(body, field)
        if isinstance(value, str):
            value = value.strip() or None
        if field == "recommended_action":
            value = _normalise_recommended_action(value)
        if field == "current_stage" and value is not None:
            value = value.value
        if field == "name" and value is None:
            raise HTTPException(status_code=422, detail="活动名称不能为空")
        setattr(campaign, field, value)

    campaign.product_id = product_id
    if "scheme_ids" in fields_set or "plan_id" in fields_set:
        campaign.scheme_ids = scheme_ids or None
    if "image_ids" in fields_set:
        campaign.image_ids = image_ids or None
    if "experiment_ids" in fields_set:
        campaign.experiment_ids = experiment_ids or None
    await db.flush()
    await db.refresh(campaign)
    return _campaign_response(campaign)


@compat_router.patch("/{campaign_id}/status", response_model=CampaignResponse)
@router.patch("/{campaign_id}/status", response_model=CampaignResponse)
async def update_campaign_status(
    campaign_id: str,
    body: CampaignStatusUpdateRequest,
    user: UserInfo = Depends(require_campaign_operator),
    db: AsyncSession = Depends(get_db),
) -> CampaignResponse:
    campaign = await _get_campaign_or_404(db, campaign_id, user.tenant_id)
    _validate_status_transition(CampaignStatus(campaign.status), body.status)
    campaign.status = body.status.value
    now = _utcnow_naive()
    if body.status == CampaignStatus.IN_PROGRESS and campaign.started_at is None:
        campaign.started_at = now
    if body.status == CampaignStatus.COMPLETED:
        campaign.completed_at = now
        campaign.current_stage = (body.current_stage or CampaignStage.LEARNING).value
    elif body.current_stage is not None:
        campaign.current_stage = body.current_stage.value
    else:
        _apply_status_stage(campaign, body.status)
    if body.next_step is not None:
        campaign.next_step = body.next_step.strip() or None
    await db.flush()
    await db.refresh(campaign)
    return _campaign_response(campaign)


@compat_router.get("/{campaign_id}/insights", response_model=list[CampaignInsightResponse])
@router.get("/{campaign_id}/insights", response_model=list[CampaignInsightResponse])
async def list_campaign_insights(
    campaign_id: str,
    user: UserInfo = Depends(require_campaign_reader),
    db: AsyncSession = Depends(get_db),
) -> list[CampaignInsightResponse]:
    campaign = await _get_campaign_or_404(db, campaign_id, user.tenant_id)
    insights = await _load_insights(db, campaign)
    return [_insight_response(insight) for insight in insights]


@compat_router.post(
    "/{campaign_id}/insights", response_model=CampaignInsightResponse, status_code=201
)
@router.post("/{campaign_id}/insights", response_model=CampaignInsightResponse, status_code=201)
async def create_campaign_insight(
    campaign_id: str,
    body: CampaignInsightCreateRequest,
    user: UserInfo = Depends(require_campaign_operator),
    db: AsyncSession = Depends(get_db),
) -> CampaignInsightResponse:
    campaign = await _get_campaign_or_404(db, campaign_id, user.tenant_id)
    insight = CampaignInsight(
        tenant_id=user.tenant_id,
        campaign_id=campaign.id,
        insight_type=body.insight_type.value,
        title=body.title.strip(),
        summary=body.summary.strip() if body.summary else None,
        source_type=body.source_type.strip() if body.source_type else None,
        source_id=body.source_id.strip() if body.source_id else None,
        confidence=body.confidence,
        metric_snapshot=body.metric_snapshot or body.evidence,
        recommended_action=body.recommended_action.strip() if body.recommended_action else None,
        status=body.status.value,
        created_by=user.user_id,
    )
    db.add(insight)
    await db.flush()
    await db.refresh(insight)
    return _insight_response(insight)
