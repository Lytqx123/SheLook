"""按租户分批上线控制与 AI 成本预留记录。"""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin


class UsageStatus(StrEnum):
    RESERVED = "reserved"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TenantFeatureFlag(TenantScopedMixin, Base):
    """租户级功能开关，用于试点、灰度和紧急熔断。"""

    __tablename__ = "tenant_feature_flags"
    __table_args__ = (
        UniqueConstraint("tenant_id", "flag_key", name="uq_tenant_feature_flag"),
        Index("ix_tenant_feature_flags_tenant_enabled", "tenant_id", "enabled"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    flag_key: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    rollout_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class AIUsageRecord(TenantScopedMixin, Base):
    """提交 AI 任务时预留预算，避免并发请求突破租户成本上限。"""

    __tablename__ = "ai_usage_records"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_ai_usage_idempotency"),
        Index("ix_ai_usage_tenant_created_status", "tenant_id", "created_at", "status"),
        Index("ix_ai_usage_workflow_task", "workflow_task_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workflow_task_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    reserved_cost_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    actual_cost_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[UsageStatus] = mapped_column(
        String(16), nullable=False, server_default=UsageStatus.RESERVED.value
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    settled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
