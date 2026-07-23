"""可靠异步任务与 Outbox 事件模型。"""

from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import JSON, DateTime, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin


def _new_event_id() -> str:
    return str(uuid4())


class WorkflowTaskStatus(StrEnum):
    CREATED = "created"
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_EXTERNAL = "waiting_external"
    WAITING_HUMAN = "waiting_human"
    RETRYING = "retrying"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class OutboxStatus(StrEnum):
    PENDING = "pending"
    PUBLISHED = "published"
    FAILED = "failed"


class WorkflowTask(TenantScopedMixin, Base):
    __tablename__ = "workflow_tasks"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_workflow_task_idempotency"),
        Index("ix_workflow_tasks_tenant_status", "tenant_id", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_event_id)
    task_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    status: Mapped[WorkflowTaskStatus] = mapped_column(
        String(32), nullable=False, server_default=WorkflowTaskStatus.CREATED.value, index=True
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default="100")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="3")
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class OutboxEvent(TenantScopedMixin, Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        UniqueConstraint("tenant_id", "event_key", name="uq_outbox_event_key"),
        Index("ix_outbox_events_pending", "status", "available_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_event_id)
    event_key: Mapped[str] = mapped_column(String(160), nullable=False)
    event_type: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    aggregate_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[OutboxStatus] = mapped_column(
        String(16), nullable=False, server_default=OutboxStatus.PENDING.value, index=True
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    available_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
