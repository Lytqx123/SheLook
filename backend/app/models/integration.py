"""Tenant-scoped third-party integration connections and sync history."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin


def _new_id() -> str:
    return str(uuid4())


class DianxiaomiConnection(TenantScopedMixin, Base):
    """A write-only credentialed Dianxiaomi integration connection.

    ``credentials_encrypted`` is intentionally not exposed through schemas or
    logs. The provider contract is configured per connection because official
    access can differ by merchant entitlement and deployment environment.
    """

    __tablename__ = "dianxiaomi_connections"
    __table_args__ = (
        Index("ix_dianxiaomi_connections_tenant_status", "tenant_id", "status"),
        Index("ix_dianxiaomi_connections_tenant_updated", "tenant_id", "updated_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    merchant_reference: Mapped[str | None] = mapped_column(String(128), nullable=True)
    api_base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    shop_references: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    sync_scopes: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    sync_interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default="360")
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="draft")
    credentials_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    credentials_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    config_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_sync_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class IntegrationSyncRun(TenantScopedMixin, Base):
    """Auditable integration sync attempt; no source payload is retained here."""

    __tablename__ = "integration_sync_runs"
    __table_args__ = (
        Index("ix_integration_sync_runs_connection_started", "connection_id", "started_at"),
        Index("ix_integration_sync_runs_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    connection_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("dianxiaomi_connections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    trigger: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    requested_scopes: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    config_version: Mapped[int] = mapped_column(Integer, nullable=False)
    records_received: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    records_applied: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    cursor_before: Mapped[str | None] = mapped_column(Text, nullable=True)
    cursor_after: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
