"""Tenant-scoped, write-only configuration for external business providers."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, DateTime, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin


def _new_id() -> str:
    return str(uuid4())


class ProviderConfig(TenantScopedMixin, Base):
    """Encrypted credentials and safe, tenant-managed provider settings.

    Only non-secret values are stored in ``config_json``.  Credentials are
    encrypted before persistence and are deliberately absent from all API
    response schemas and audit records.
    """

    __tablename__ = "provider_configs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "provider", name="uq_provider_config_tenant_provider"),
        Index("ix_provider_configs_tenant_status", "tenant_id", "status"),
        Index("ix_provider_configs_tenant_updated", "tenant_id", "updated_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(nullable=False, server_default="true")
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="incomplete")
    config_json: Mapped[dict[str, str] | None] = mapped_column(JSON, nullable=True)
    credentials_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    credentials_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    config_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )
