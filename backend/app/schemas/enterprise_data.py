"""API contracts for mappings, commerce facts and real CTR evidence."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

EntityType = Literal["product", "listing", "inventory", "order", "fulfillment", "creative"]


class ExternalEntityMappingUpsert(BaseModel):
    provider: str = Field(min_length=1, max_length=32)
    connection_key: str = Field(default="manual", min_length=1, max_length=64)
    entity_type: EntityType
    external_id: str = Field(min_length=1, max_length=255)
    shop_reference: str | None = Field(default=None, max_length=128)
    marketplace: str | None = Field(default=None, max_length=64)
    external_sku: str | None = Field(default=None, max_length=255)
    product_id: int | None = Field(default=None, ge=1)
    image_id: int | None = Field(default=None, ge=1)
    mapping_method: Literal["manual", "suggested", "imported"] = "manual"
    metadata: dict | None = None

    @field_validator("provider", "connection_key", "external_id")
    @classmethod
    def normalize_required(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("字段不能为空白")
        return normalized


class ExternalEntityMappingResponse(ExternalEntityMappingUpsert):
    id: str
    status: str
    created_by: str | None = None
    updated_by: str | None = None
    created_at: datetime
    updated_at: datetime


class PerformanceFactInput(BaseModel):
    source_name: str = Field(min_length=1, max_length=64)
    source_record_id: str = Field(min_length=1, max_length=255)
    metric_date: date
    shop_reference: str | None = Field(default=None, max_length=128)
    marketplace: str | None = Field(default=None, max_length=64)
    external_listing_id: str | None = Field(default=None, max_length=255)
    mapping_id: str | None = Field(default=None, max_length=36)
    image_id: int | None = Field(default=None, ge=1)
    impressions: int = Field(ge=0)
    clicks: int = Field(ge=0)
    orders: int | None = Field(default=None, ge=0)
    revenue: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=8)
    source_updated_at: datetime | None = None
    data_mature_at: datetime | None = None
    metric_definition_version: str = Field(default="v1", min_length=1, max_length=32)

    @model_validator(mode="after")
    def validate_clicks(self) -> "PerformanceFactInput":
        if self.clicks > self.impressions:
            raise ValueError("clicks 不能大于 impressions")
        if self.impressions == 0 and self.clicks:
            raise ValueError("曝光为 0 时点击必须为 0")
        return self


class PerformanceFactBatch(BaseModel):
    items: list[PerformanceFactInput] = Field(min_length=1, max_length=1_000)


class PerformanceFactBatchResponse(BaseModel):
    total: int
    upserted: int
    pending_mapping: int
    mature: int


class CTRFeedbackSummary(BaseModel):
    eligible_snapshots: int
    mature_labels_created: int
    skipped_insufficient_impressions: int
    skipped_missing_performance: int
    coverage_rate: float


class EnterpriseDataQualitySummary(BaseModel):
    mappings_total: int
    mappings_pending: int
    commerce_facts_total: int
    performance_facts_total: int
    performance_facts_pending_mapping: int
    performance_facts_mature: int
    feedback_labels_total: int
