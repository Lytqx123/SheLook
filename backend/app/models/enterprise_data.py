"""Canonical external business facts and CTR feedback evidence."""

from datetime import date, datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin


def _new_id() -> str:
    return str(uuid4())


class ExternalEntityMapping(TenantScopedMixin, Base):
    """Explicit bridge from a provider entity to internal business entities."""

    __tablename__ = "external_entity_mappings"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "provider", "connection_key", "entity_type", "external_id",
            name="uq_external_entity_mapping_identity",
        ),
        Index("ix_external_entity_mappings_tenant_status", "tenant_id", "status"),
        Index("ix_external_entity_mappings_image", "tenant_id", "image_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    connection_key: Mapped[str] = mapped_column(String(64), nullable=False, server_default="manual")
    shop_reference: Mapped[str | None] = mapped_column(String(128), nullable=True)
    marketplace: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    external_sku: Mapped[str | None] = mapped_column(String(255), nullable=True)
    product_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("products.id", ondelete="SET NULL"), nullable=True, index=True
    )
    image_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("generated_images.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="mapped")
    mapping_method: Mapped[str] = mapped_column(String(32), nullable=False, server_default="manual")
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class CommerceFact(TenantScopedMixin, Base):
    """Current canonical state for product/listing/inventory/order/fulfillment facts."""

    __tablename__ = "commerce_facts"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "provider", "connection_key", "entity_type", "external_id",
            name="uq_commerce_fact_identity",
        ),
        Index("ix_commerce_facts_tenant_type_updated", "tenant_id", "entity_type", "source_updated_at"),
        Index("ix_commerce_facts_tenant_run", "tenant_id", "sync_run_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    connection_key: Mapped[str] = mapped_column(String(64), nullable=False)
    sync_run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("integration_sync_runs.id", ondelete="SET NULL"), nullable=True
    )
    shop_reference: Mapped[str | None] = mapped_column(String(128), nullable=True)
    marketplace: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class PerformanceFact(TenantScopedMixin, Base):
    """Source-attributed exposure and click facts.  CTR is always derived."""

    __tablename__ = "performance_facts"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "source_name", "source_record_id", name="uq_performance_fact_source_record"
        ),
        Index("ix_performance_facts_tenant_image_date", "tenant_id", "image_id", "metric_date"),
        Index("ix_performance_facts_tenant_maturity", "tenant_id", "is_mature", "metric_date"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    source_name: Mapped[str] = mapped_column(String(64), nullable=False)
    source_record_id: Mapped[str] = mapped_column(String(255), nullable=False)
    metric_date: Mapped[date] = mapped_column(Date, nullable=False)
    shop_reference: Mapped[str | None] = mapped_column(String(128), nullable=True)
    marketplace: Mapped[str | None] = mapped_column(String(64), nullable=True)
    external_listing_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mapping_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("external_entity_mappings.id", ondelete="SET NULL"), nullable=True
    )
    image_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("generated_images.id", ondelete="SET NULL"), nullable=True
    )
    impressions: Mapped[int] = mapped_column(Integer, nullable=False)
    clicks: Mapped[int] = mapped_column(Integer, nullable=False)
    orders: Mapped[int | None] = mapped_column(Integer, nullable=True)
    revenue: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    data_mature_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_mature: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    quality_status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="pending_mapping")
    metric_definition_version: Mapped[str] = mapped_column(String(32), nullable=False, server_default="v1")
    source_payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class PredictionSnapshot(TenantScopedMixin, Base):
    """Immutable evidence of what the model predicted at one point in time."""

    __tablename__ = "prediction_snapshots"
    __table_args__ = (
        UniqueConstraint("tenant_id", "prediction_record_id", name="uq_prediction_snapshot_record"),
        Index("ix_prediction_snapshots_tenant_image_time", "tenant_id", "image_id", "predicted_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    prediction_record_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("prediction_records.id", ondelete="CASCADE"), nullable=False
    )
    image_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("generated_images.id", ondelete="CASCADE"), nullable=False
    )
    predicted_ctr: Mapped[float | None] = mapped_column(Float, nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    feature_version: Mapped[str] = mapped_column(String(64), nullable=False, server_default="v1")
    entity_snapshot_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    predicted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())


class ModelFeedbackLabel(TenantScopedMixin, Base):
    """Mature, source-traceable actual CTR label for a prediction snapshot."""

    __tablename__ = "model_feedback_labels"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "prediction_snapshot_id", "label_version",
            name="uq_feedback_label_snapshot_version",
        ),
        Index("ix_model_feedback_labels_tenant_status", "tenant_id", "status", "matured_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    prediction_snapshot_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("prediction_snapshots.id", ondelete="CASCADE"), nullable=False
    )
    image_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("generated_images.id", ondelete="CASCADE"), nullable=False
    )
    observation_start: Mapped[date] = mapped_column(Date, nullable=False)
    observation_end: Mapped[date] = mapped_column(Date, nullable=False)
    impressions: Mapped[int] = mapped_column(Integer, nullable=False)
    clicks: Mapped[int] = mapped_column(Integer, nullable=False)
    actual_ctr: Mapped[float] = mapped_column(Float, nullable=False)
    source_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="mature")
    label_version: Mapped[str] = mapped_column(String(32), nullable=False, server_default="v1")
    matured_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
