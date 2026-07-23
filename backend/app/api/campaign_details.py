"""Read-model assembly for campaign details, decisions, and timelines."""

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.campaign_common import (
    _campaign_response,
    _enum_value,
    _insight_response,
    _resource_ids,
)
from app.models.campaign import CampaignInsight, CampaignStatus, VisualOperationCampaign
from app.models.experiment import ABExperiment, ExperimentStatus
from app.models.image import GeneratedImage, ImageScheme, ReviewStatus
from app.models.prediction import DailyMetric, PredictionRecord
from app.models.product import Product
from app.models.review import ReviewRecord
from app.schemas.campaign import (
    CampaignActionItem,
    CampaignDecisionSummary,
    CampaignDetailResponse,
    CampaignExperimentSummary,
    CampaignImageSummary,
    CampaignProductSummary,
    CampaignTimelineItem,
)


async def _load_product_summary(
    db: AsyncSession,
    campaign: VisualOperationCampaign,
) -> CampaignProductSummary | None:
    if campaign.product_id is None:
        return None
    product = await db.scalar(
        select(Product).where(
            Product.id == campaign.product_id,
            Product.tenant_id == campaign.tenant_id,
        )
    )
    if product is None:
        return None
    return CampaignProductSummary(
        id=product.id,
        sku_code=product.sku_code,
        title=product.title,
        category=product.category,
        status=_enum_value(product.status) or "draft",
    )


def _campaign_image_filter(campaign: VisualOperationCampaign):
    """Return a portable image filter; explicit links take precedence."""
    image_ids = _resource_ids(campaign.image_ids)
    scheme_ids = _resource_ids(campaign.scheme_ids)
    if image_ids or scheme_ids:
        conditions = []
        if image_ids:
            conditions.append(GeneratedImage.id.in_(image_ids))
        if scheme_ids:
            conditions.append(GeneratedImage.scheme_id.in_(scheme_ids))
        return or_(*conditions)
    if campaign.product_id is not None:
        return ImageScheme.product_id == campaign.product_id
    return None


async def _load_campaign_images(
    db: AsyncSession,
    campaign: VisualOperationCampaign,
) -> list[GeneratedImage]:
    asset_filter = _campaign_image_filter(campaign)
    if asset_filter is None:
        return []
    result = await db.execute(
        select(GeneratedImage)
        .join(ImageScheme, GeneratedImage.scheme_id == ImageScheme.id)
        .where(
            asset_filter,
            GeneratedImage.tenant_id == campaign.tenant_id,
            ImageScheme.tenant_id == campaign.tenant_id,
        )
        .order_by(GeneratedImage.created_at.desc())
        .limit(300)
    )
    return list(result.scalars())


async def _load_campaign_experiments(
    db: AsyncSession,
    campaign: VisualOperationCampaign,
) -> list[ABExperiment]:
    experiment_ids = _resource_ids(campaign.experiment_ids)
    if experiment_ids:
        filter_clause = ABExperiment.id.in_(experiment_ids)
    elif campaign.product_id is not None:
        filter_clause = ABExperiment.product_id == campaign.product_id
    else:
        return []
    result = await db.execute(
        select(ABExperiment)
        .where(filter_clause, ABExperiment.tenant_id == campaign.tenant_id)
        .order_by(ABExperiment.created_at.desc())
        .limit(100)
    )
    return list(result.scalars())


async def _load_latest_predictions(
    db: AsyncSession,
    campaign: VisualOperationCampaign,
    image_ids: list[int],
) -> dict[int, PredictionRecord]:
    if not image_ids:
        return {}
    rows = (
        await db.execute(
            select(PredictionRecord)
            .where(
                PredictionRecord.image_id.in_(image_ids),
                PredictionRecord.tenant_id == campaign.tenant_id,
            )
            .order_by(PredictionRecord.image_id, PredictionRecord.predicted_at.desc())
        )
    ).scalars()
    latest: dict[int, PredictionRecord] = {}
    for record in rows:
        latest.setdefault(record.image_id, record)
    return latest


async def _load_latest_reviews(
    db: AsyncSession,
    campaign: VisualOperationCampaign,
    image_ids: list[int],
) -> dict[int, ReviewRecord]:
    if not image_ids:
        return {}
    rows = (
        await db.execute(
            select(ReviewRecord)
            .where(
                ReviewRecord.image_id.in_(image_ids),
                ReviewRecord.tenant_id == campaign.tenant_id,
            )
            .order_by(ReviewRecord.image_id, ReviewRecord.created_at.desc())
        )
    ).scalars()
    latest: dict[int, ReviewRecord] = {}
    for record in rows:
        latest.setdefault(record.image_id, record)
    return latest


async def load_insights(
    db: AsyncSession,
    campaign: VisualOperationCampaign,
    *,
    limit: int = 100,
) -> list[CampaignInsight]:
    result = await db.execute(
        select(CampaignInsight)
        .where(
            CampaignInsight.campaign_id == campaign.id,
            CampaignInsight.tenant_id == campaign.tenant_id,
        )
        .order_by(CampaignInsight.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars())


async def _metric_totals(
    db: AsyncSession,
    campaign: VisualOperationCampaign,
    image_ids: list[int],
) -> tuple[int, int, float]:
    if not image_ids:
        return 0, 0, 0.0
    row = (
        await db.execute(
            select(
                func.coalesce(func.sum(DailyMetric.impressions), 0).label("impressions"),
                func.coalesce(func.sum(DailyMetric.clicks), 0).label("clicks"),
                func.coalesce(func.sum(DailyMetric.revenue), 0).label("revenue"),
            ).where(
                DailyMetric.image_id.in_(image_ids),
                DailyMetric.tenant_id == campaign.tenant_id,
            )
        )
    ).one()
    return int(row.impressions or 0), int(row.clicks or 0), float(row.revenue or 0)


def _action_items(
    campaign: VisualOperationCampaign,
    *,
    image_count: int,
    pending_review_count: int,
    predicted_image_count: int,
    approved_image_count: int,
    experiment_count: int,
) -> list[CampaignActionItem]:
    actions: list[CampaignActionItem] = []
    if campaign.recommended_action:
        recommendation = campaign.recommended_action
        if isinstance(recommendation, dict):
            rationale = str(
                recommendation.get("description")
                or recommendation.get("rationale")
                or recommendation.get("label")
                or "系统建议优先推进当前活动。"
            )
        else:
            rationale = str(recommendation)
        actions.append(
            CampaignActionItem(
                id="campaign-recommended-action",
                priority="high",
                action_type="campaign_recommendation",
                title="执行当前经营建议",
                rationale=rationale,
                entity_type="campaign",
                entity_id=campaign.id,
            )
        )
    if campaign.status == CampaignStatus.DRAFT.value:
        actions.append(
            CampaignActionItem(
                id="start-campaign",
                priority="high",
                action_type="start_campaign",
                title="确认目标后启动活动",
                rationale="活动仍处于草稿状态，尚未进入可跟踪的经营流程。",
                entity_type="campaign",
                entity_id=campaign.id,
            )
        )
    if image_count == 0:
        actions.append(
            CampaignActionItem(
                id="create-creative",
                priority="high",
                action_type="create_creative",
                title="生成或关联候选素材",
                rationale="当前活动没有可用于审核和效果判断的视觉素材。",
                entity_type="campaign",
                entity_id=campaign.id,
            )
        )
    if pending_review_count:
        actions.append(
            CampaignActionItem(
                id="complete-review",
                priority="high",
                action_type="complete_review",
                title=f"处理 {pending_review_count} 个待审核素材",
                rationale="未完成质量门禁的素材不应进入后续预测或投放实验。",
                entity_type="review_queue",
            )
        )
    if image_count and predicted_image_count < image_count:
        actions.append(
            CampaignActionItem(
                id="run-prediction",
                priority="medium",
                action_type="run_prediction",
                title="补齐素材效果预测",
                rationale="尚有素材没有 CTR、爆款潜力或退货风险预测，无法做可解释筛选。",
                entity_type="campaign",
                entity_id=campaign.id,
            )
        )
    if approved_image_count >= 2 and experiment_count == 0:
        actions.append(
            CampaignActionItem(
                id="create-experiment",
                priority="medium",
                action_type="create_experiment",
                title="为通过审核的候选素材创建 A/B 实验",
                rationale="至少已有两份合格素材，可以用真实流量验证预测与视觉策略。",
                entity_type="experiment",
            )
        )
    if campaign.status == CampaignStatus.COMPLETED.value:
        actions.append(
            CampaignActionItem(
                id="record-learning",
                priority="medium",
                action_type="record_learning",
                title="沉淀本次活动学习记录",
                rationale="将有效策略、风险和经营结果写入学习记录，供下一次推荐复用。",
                entity_type="campaign",
                entity_id=campaign.id,
            )
        )
    return actions


def _timeline_sort_key(item: CampaignTimelineItem) -> float:
    return item.occurred_at.timestamp() if item.occurred_at else 0.0


async def build_campaign_detail(
    db: AsyncSession,
    campaign: VisualOperationCampaign,
) -> CampaignDetailResponse:
    product, images, experiments, insights = await _load_detail_sources(db, campaign)
    image_ids = [image.id for image in images]
    latest_predictions, latest_reviews = await _load_decision_records(db, campaign, image_ids)
    impressions, clicks, revenue = await _metric_totals(db, campaign, image_ids)

    pending_count = sum(image.review_status == ReviewStatus.MANUAL_PENDING for image in images)
    approved_count = sum(image.review_status == ReviewStatus.AUTO_APPROVED for image in images)
    rejected_count = sum(image.review_status == ReviewStatus.REJECTED for image in images)
    predicted_values = [
        record.predicted_ctr
        for record in latest_predictions.values()
        if record.predicted_ctr is not None
    ]
    hit_values = [
        record.predicted_hit_probability
        for record in latest_predictions.values()
        if record.predicted_hit_probability is not None
    ]

    average_predicted_ctr = (
        (sum(predicted_values) / len(predicted_values)) if predicted_values else None
    )
    realized_ctr = (clicks / impressions) if impressions else None
    running_experiment_count = sum(
        experiment.status == ExperimentStatus.RUNNING for experiment in experiments
    )
    summary = CampaignDecisionSummary(
        product=product,
        images=[
            CampaignImageSummary(
                id=image.id,
                scheme_id=image.scheme_id,
                image_url=image.image_url,
                generation_status=image.generation_status,
                review_status=_enum_value(image.review_status) or "manual_pending",
                overall_score=image.overall_score,
                market_variant=image.market_variant,
                created_at=image.created_at,
            )
            for image in images
        ],
        experiments=[
            CampaignExperimentSummary(
                id=experiment.id,
                status=_enum_value(experiment.status),
                variant_a_image_id=experiment.variant_a_image_id,
                variant_b_image_id=experiment.variant_b_image_id,
                winner_image_id=experiment.winner_image_id,
                result_ctr_a=experiment.result_ctr_a,
                result_ctr_b=experiment.result_ctr_b,
                p_value=experiment.p_value,
                start_date=experiment.start_date,
                end_date=experiment.end_date,
            )
            for experiment in experiments
        ],
        image_count=len(images),
        pending_review_count=pending_count,
        approved_image_count=approved_count,
        rejected_image_count=rejected_count,
        predicted_image_count=len(latest_predictions),
        average_predicted_ctr=average_predicted_ctr,
        average_hit_probability=(sum(hit_values) / len(hit_values)) if hit_values else None,
        total_impressions=impressions,
        total_clicks=clicks,
        realized_ctr=realized_ctr,
        total_images=len(images),
        approved_images=approved_count,
        pending_reviews=pending_count,
        prediction_count=len(latest_predictions),
        experiments_total=len(experiments),
        experiments_running=running_experiment_count,
        avg_predicted_ctr=average_predicted_ctr,
        avg_actual_ctr=realized_ctr,
        total_revenue=revenue,
        action_items=_action_items(
            campaign,
            image_count=len(images),
            pending_review_count=pending_count,
            predicted_image_count=len(latest_predictions),
            approved_image_count=approved_count,
            experiment_count=len(experiments),
        ),
    )
    timeline = _build_timeline(
        campaign=campaign,
        images=images,
        predictions=latest_predictions,
        reviews=latest_reviews,
        experiments=experiments,
        insights=insights,
    )
    return CampaignDetailResponse(
        campaign=_campaign_response(campaign),
        summary=summary,
        timeline=timeline,
        insights=[_insight_response(insight) for insight in insights],
    )


async def _load_detail_sources(
    db: AsyncSession,
    campaign: VisualOperationCampaign,
) -> tuple[
    CampaignProductSummary | None,
    list[GeneratedImage],
    list[ABExperiment],
    list[CampaignInsight],
]:
    # Independent reads make the query portable between SQLite and PostgreSQL;
    # they also avoid JSON-specific joins for the resource ID arrays.
    product = await _load_product_summary(db, campaign)
    images = await _load_campaign_images(db, campaign)
    experiments = await _load_campaign_experiments(db, campaign)
    insights = await load_insights(db, campaign)
    return product, images, experiments, insights


async def _load_decision_records(
    db: AsyncSession,
    campaign: VisualOperationCampaign,
    image_ids: list[int],
) -> tuple[dict[int, PredictionRecord], dict[int, ReviewRecord]]:
    predictions = await _load_latest_predictions(db, campaign, image_ids)
    reviews = await _load_latest_reviews(db, campaign, image_ids)
    return predictions, reviews


def _build_timeline(
    *,
    campaign: VisualOperationCampaign,
    images: list[GeneratedImage],
    predictions: dict[int, PredictionRecord],
    reviews: dict[int, ReviewRecord],
    experiments: list[ABExperiment],
    insights: list[CampaignInsight],
) -> list[CampaignTimelineItem]:
    timeline = [
        CampaignTimelineItem(
            id=f"campaign:{campaign.id}:created",
            event_type="campaign_created",
            title="创建视觉运营活动",
            occurred_at=campaign.created_at,
            entity_type="campaign",
            entity_id=campaign.id,
            status=campaign.status,
            detail={"stage": campaign.current_stage, "market": campaign.market},
        )
    ]
    for image in images:
        timeline.append(
            CampaignTimelineItem(
                id=f"image:{image.id}:generated",
                event_type="image_generated",
                title="生成候选视觉素材",
                occurred_at=image.created_at,
                entity_type="image",
                entity_id=str(image.id),
                status=image.generation_status,
                detail={
                    "scheme_id": image.scheme_id,
                    "review_status": _enum_value(image.review_status),
                    "overall_score": image.overall_score,
                },
            )
        )
    for image_id, prediction in predictions.items():
        timeline.append(
            CampaignTimelineItem(
                id=f"prediction:{prediction.id}",
                event_type="prediction_completed",
                title="完成素材效果预测",
                occurred_at=prediction.predicted_at,
                entity_type="image",
                entity_id=str(image_id),
                status="completed",
                detail={
                    "predicted_ctr": prediction.predicted_ctr,
                    "hit_probability": prediction.predicted_hit_probability,
                    "return_risk_level": _enum_value(prediction.return_risk_level),
                },
            )
        )
    for image_id, review in reviews.items():
        timeline.append(
            CampaignTimelineItem(
                id=f"review:{review.id}",
                event_type="review_decided",
                title="完成人工质量审核",
                occurred_at=review.created_at,
                entity_type="image",
                entity_id=str(image_id),
                status=_enum_value(review.action),
                detail={
                    "reason": review.reason,
                    "problem_dimensions": review.problem_dimensions or {},
                },
            )
        )
    for experiment in experiments:
        occurred_at = experiment.end_date or experiment.start_date or experiment.created_at
        timeline.append(
            CampaignTimelineItem(
                id=f"experiment:{experiment.id}",
                event_type="experiment_completed"
                if experiment.status in {ExperimentStatus.COMPLETED, ExperimentStatus.STOPPED}
                else "experiment_started",
                title="A/B 实验结果已更新" if experiment.end_date else "启动 A/B 实验",
                occurred_at=occurred_at,
                entity_type="experiment",
                entity_id=str(experiment.id),
                status=_enum_value(experiment.status),
                detail={
                    "winner_image_id": experiment.winner_image_id,
                    "result_ctr_a": experiment.result_ctr_a,
                    "result_ctr_b": experiment.result_ctr_b,
                    "p_value": experiment.p_value,
                },
            )
        )
    for insight in insights:
        timeline.append(
            CampaignTimelineItem(
                id=f"insight:{insight.id}",
                event_type="campaign_insight_recorded",
                title=insight.title,
                occurred_at=insight.created_at,
                entity_type="insight",
                entity_id=insight.id,
                status=insight.status,
                detail={
                    "insight_type": insight.insight_type,
                    "confidence": insight.confidence,
                    "source_type": insight.source_type,
                    "source_id": insight.source_id,
                },
            )
        )
    descriptions = {
        "campaign_created": "已建立活动目标、市场范围和后续经营链路。",
        "image_generated": "候选素材已进入质量审核和效果判断链路。",
        "prediction_completed": "已生成 CTR、爆款潜力和风险相关判断。",
        "review_decided": "质量门禁结果已写入活动决策记录。",
        "experiment_started": "已开始通过真实流量验证候选方案。",
        "experiment_completed": "实验结果已更新，可用于复盘和后续策略选择。",
        "campaign_insight_recorded": "已沉淀为下次活动可复用的学习记录。",
    }
    for item in timeline:
        item.type = item.event_type
        item.metadata = dict(item.detail)
        item.description = descriptions.get(item.event_type, item.title)
    timeline.sort(key=_timeline_sort_key, reverse=True)
    return timeline[:100]
