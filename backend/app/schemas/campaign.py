"""Request and response contracts for visual-operation campaigns."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.campaign import (
    CampaignInsightStatus,
    CampaignInsightType,
    CampaignStage,
    CampaignStatus,
)


def _validate_resource_ids(value: list[int] | None) -> list[int] | None:
    if value is None:
        return value
    if any(resource_id < 1 for resource_id in value):
        raise ValueError("关联资源 ID 必须为正整数")
    if len(value) != len(set(value)):
        raise ValueError("关联资源 ID 不能重复")
    return value


class CampaignCreateRequest(BaseModel):
    """Create a campaign around a product, market and business objective."""

    name: str = Field(..., min_length=1, max_length=160)
    product_id: int | None = Field(None, ge=1)
    market: str | None = Field(None, max_length=64)
    objective: str | None = Field(None, max_length=2_000)
    objective_metric: str | None = Field(None, max_length=64)
    target_value: float | None = None
    status: CampaignStatus = CampaignStatus.DRAFT
    current_stage: CampaignStage = CampaignStage.BRIEF
    # ``plan_id`` is retained as a convenient alias for a primary visual scheme.
    plan_id: int | None = Field(None, ge=1)
    scheme_ids: list[int] | None = Field(None, max_length=100)
    image_ids: list[int] | None = Field(None, max_length=300)
    experiment_ids: list[int] | None = Field(None, max_length=100)
    description: str | None = Field(None, max_length=2_000)
    recommended_action: dict[str, Any] | str | None = None
    next_step: str | None = Field(None, max_length=2_000)
    owner_id: str | None = Field(None, max_length=128)

    @field_validator("scheme_ids", "image_ids", "experiment_ids")
    @classmethod
    def validate_resource_ids(cls, value: list[int] | None) -> list[int] | None:
        return _validate_resource_ids(value)

    @model_validator(mode="after")
    def include_primary_plan(self) -> "CampaignCreateRequest":
        if self.plan_id is not None:
            scheme_ids = list(self.scheme_ids or [])
            if self.plan_id not in scheme_ids:
                scheme_ids.insert(0, self.plan_id)
            self.scheme_ids = scheme_ids
        return self


class CampaignUpdateRequest(BaseModel):
    """Partial campaign update; linked-resource lists replace their prior value."""

    name: str | None = Field(None, min_length=1, max_length=160)
    product_id: int | None = Field(None, ge=1)
    market: str | None = Field(None, max_length=64)
    objective: str | None = Field(None, max_length=2_000)
    objective_metric: str | None = Field(None, max_length=64)
    target_value: float | None = None
    status: CampaignStatus | None = None
    current_stage: CampaignStage | None = None
    plan_id: int | None = Field(None, ge=1)
    scheme_ids: list[int] | None = Field(None, max_length=100)
    image_ids: list[int] | None = Field(None, max_length=300)
    experiment_ids: list[int] | None = Field(None, max_length=100)
    description: str | None = Field(None, max_length=2_000)
    recommended_action: dict[str, Any] | str | None = None
    next_step: str | None = Field(None, max_length=2_000)
    owner_id: str | None = Field(None, max_length=128)

    @field_validator("scheme_ids", "image_ids", "experiment_ids")
    @classmethod
    def validate_resource_ids(cls, value: list[int] | None) -> list[int] | None:
        return _validate_resource_ids(value)

    @model_validator(mode="after")
    def include_primary_plan(self) -> "CampaignUpdateRequest":
        if self.plan_id is not None:
            scheme_ids = list(self.scheme_ids or [])
            if self.plan_id not in scheme_ids:
                scheme_ids.insert(0, self.plan_id)
            self.scheme_ids = scheme_ids
        return self


class CampaignStatusUpdateRequest(BaseModel):
    status: CampaignStatus
    current_stage: CampaignStage | None = None
    next_step: str | None = Field(None, max_length=2_000)


class CampaignResponse(BaseModel):
    id: str
    tenant_id: str
    name: str
    product_id: int | None = None
    market: str | None = None
    objective: str | None = None
    description: str | None = None
    objective_metric: str | None = None
    target_value: float | None = None
    status: CampaignStatus
    current_stage: CampaignStage
    plan_id: int | None = None
    scheme_ids: list[int] = Field(default_factory=list)
    image_ids: list[int] = Field(default_factory=list)
    experiment_ids: list[int] = Field(default_factory=list)
    recommended_action: dict[str, Any] | None = None
    next_step: str | None = None
    owner_id: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class CampaignListResponse(BaseModel):
    items: list[CampaignResponse]
    total: int
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)


class CampaignProductSummary(BaseModel):
    id: int
    sku_code: str
    title: str
    category: str
    status: str


class CampaignImageSummary(BaseModel):
    id: int
    scheme_id: int
    image_url: str | None = None
    generation_status: str
    review_status: str
    overall_score: float | None = None
    market_variant: str | None = None
    created_at: datetime | None = None


class CampaignExperimentSummary(BaseModel):
    id: int
    status: str | None = None
    variant_a_image_id: int
    variant_b_image_id: int
    winner_image_id: int | None = None
    result_ctr_a: float | None = None
    result_ctr_b: float | None = None
    p_value: float | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None


class CampaignActionItem(BaseModel):
    id: str
    priority: str
    action_type: str
    title: str
    rationale: str
    entity_type: str | None = None
    entity_id: str | None = None


class CampaignDecisionSummary(BaseModel):
    product: CampaignProductSummary | None = None
    images: list[CampaignImageSummary] = Field(default_factory=list)
    experiments: list[CampaignExperimentSummary] = Field(default_factory=list)
    image_count: int = 0
    pending_review_count: int = 0
    approved_image_count: int = 0
    rejected_image_count: int = 0
    predicted_image_count: int = 0
    average_predicted_ctr: float | None = None
    average_hit_probability: float | None = None
    total_impressions: int = 0
    total_clicks: int = 0
    realized_ctr: float | None = None
    # Stable product-facing names used by the activity workbench.
    total_images: int = 0
    approved_images: int = 0
    pending_reviews: int = 0
    prediction_count: int = 0
    experiments_total: int = 0
    experiments_running: int = 0
    avg_predicted_ctr: float | None = None
    avg_actual_ctr: float | None = None
    total_revenue: float | None = None
    action_items: list[CampaignActionItem] = Field(default_factory=list)


class CampaignTimelineItem(BaseModel):
    id: str
    event_type: str
    type: str | None = None
    title: str
    description: str | None = None
    occurred_at: datetime | None = None
    entity_type: str | None = None
    entity_id: str | None = None
    status: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CampaignInsightCreateRequest(BaseModel):
    insight_type: CampaignInsightType = CampaignInsightType.LEARNING
    title: str = Field(..., min_length=1, max_length=255)
    summary: str | None = Field(None, max_length=4_000)
    source_type: str | None = Field(None, max_length=64)
    source_id: str | None = Field(None, max_length=64)
    confidence: float | None = Field(None, ge=0, le=1)
    metric_snapshot: dict[str, Any] | None = None
    evidence: dict[str, Any] | None = None
    recommended_action: str | None = Field(None, max_length=2_000)
    status: CampaignInsightStatus = CampaignInsightStatus.OBSERVED


class CampaignInsightResponse(BaseModel):
    id: str
    campaign_id: str
    tenant_id: str
    insight_type: CampaignInsightType
    title: str
    summary: str = ""
    source_type: str | None = None
    source_id: str | None = None
    confidence: float | None = None
    metric_snapshot: dict[str, Any] | None = None
    evidence: dict[str, Any] | None = None
    recommended_action: str | None = None
    status: CampaignInsightStatus
    created_by: str | None = None
    created_at: datetime


class CampaignInsightListResponse(BaseModel):
    items: list[CampaignInsightResponse]
    total: int


class CampaignDetailResponse(BaseModel):
    campaign: CampaignResponse
    summary: CampaignDecisionSummary
    timeline: list[CampaignTimelineItem] = Field(default_factory=list)
    insights: list[CampaignInsightResponse] = Field(default_factory=list)
