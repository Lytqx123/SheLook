"""Tenant-scoped, versioned business runtime settings."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin


def _new_id() -> str:
    return str(uuid4())


class RuntimeSetting(TenantScopedMixin, Base):
    """The active override for an allow-listed business setting.

    This table deliberately contains no bootstrap infrastructure secrets.  A
    missing row means that the deployment-provided default remains effective.
    """

    __tablename__ = "runtime_settings"
    __table_args__ = (
        UniqueConstraint("tenant_id", "setting_key", name="uq_runtime_setting_tenant_key"),
        Index("ix_runtime_settings_tenant_updated", "tenant_id", "updated_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    setting_key: Mapped[str] = mapped_column(String(128), nullable=False)
    value_json: Mapped[int | float] = mapped_column(JSON, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    updated_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class RuntimeSettingRevision(TenantScopedMixin, Base):
    """Append-only history for setting changes and rollbacks."""

    __tablename__ = "runtime_setting_revisions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "setting_key",
            "version",
            name="uq_runtime_setting_revision_tenant_key_version",
        ),
        Index("ix_runtime_setting_revisions_tenant_key_created", "tenant_id", "setting_key", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    setting_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("runtime_settings.id", ondelete="SET NULL"), nullable=True
    )
    setting_key: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    value_json: Mapped[int | float | None] = mapped_column(JSON, nullable=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    changed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
