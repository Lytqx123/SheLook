"""Visual-operation campaign and reusable learning-record models.

A campaign is the user-facing aggregate that connects a product, market goal,
creative assets and the decisions made around them.  The linked asset IDs are
kept as JSON lists intentionally: existing image, scheme and experiment tables
remain the systems of record, while a campaign can evolve without introducing
three additional join tables during the first rollout.
"""

from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin


def _new_id() -> str:
    return str(uuid4())


class CampaignStatus(StrEnum):
    """Lifecycle states for a visual-operation campaign."""

    DRAFT = "draft"
    IN_PROGRESS = "in_progress"
    WAITING_REVIEW = "waiting_review"
    EXPERIMENTING = "experimenting"
    LEARNING = "learning"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class CampaignStage(StrEnum):
    """The current business step; independent from the campaign lifecycle."""

    BRIEF = "brief"
    STRATEGY = "strategy"
    PRODUCTION = "production"
    REVIEW = "review"
    PREDICTION = "prediction"
    EXPERIMENT = "experiment"
    LEARNING = "learning"


class CampaignInsightType(StrEnum):
    """Classifies knowledge that should be reused by a later campaign."""

    DECISION = "decision"
    STRATEGY_VALIDATED = "strategy_validated"
    STRATEGY_REJECTED = "strategy_rejected"
    RECOMMENDATION_UPDATE = "recommendation_update"
    PERFORMANCE = "performance"
    QUALITY = "quality"
    EXPERIMENT = "experiment"
    LEARNING = "learning"
    RISK = "risk"


class CampaignInsightStatus(StrEnum):
    """Signals whether a learning is observed, validated, or superseded."""

    OBSERVED = "observed"
    VALIDATED = "validated"
    SUPERSEDED = "superseded"


class VisualOperationCampaign(TenantScopedMixin, Base):
    """A visual operation campaign spanning creation, review, and learning."""

    __tablename__ = "visual_operation_campaigns"
    __table_args__ = (
        Index(
            "ix_visual_operation_campaigns_tenant_status_updated",
            "tenant_id",
            "status",
            "updated_at",
        ),
        Index(
            "ix_visual_operation_campaigns_tenant_product",
            "tenant_id",
            "product_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    product_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("products.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    market: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    objective: Mapped[str | None] = mapped_column(Text, nullable=True)
    objective_metric: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=CampaignStatus.DRAFT.value, index=True
    )
    current_stage: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=CampaignStage.BRIEF.value, index=True
    )
    # These fields intentionally reference existing resources without claiming
    # ownership.  The API validates every supplied ID under the current tenant.
    scheme_ids: Mapped[list[int] | None] = mapped_column(JSON, nullable=True)
    image_ids: Mapped[list[int] | None] = mapped_column(JSON, nullable=True)
    experiment_ids: Mapped[list[int] | None] = mapped_column(JSON, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommended_action: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    next_step: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<VisualOperationCampaign {self.id} {self.status}>"


class CampaignInsight(TenantScopedMixin, Base):
    """A traceable decision or learning that can feed the next campaign."""

    __tablename__ = "campaign_insights"
    __table_args__ = (
        Index(
            "ix_campaign_insights_tenant_campaign_created",
            "tenant_id",
            "campaign_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    campaign_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("visual_operation_campaigns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    insight_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    metric_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    recommended_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=CampaignInsightStatus.OBSERVED.value
    )
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<CampaignInsight {self.id} campaign={self.campaign_id}>"
