"""企业租户、组织单元、成员与配额模型。"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _new_id() -> str:
    return str(uuid4())


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, server_default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class OrganizationUnit(Base):
    __tablename__ = "organization_units"
    __table_args__ = (UniqueConstraint("tenant_id", "unit_type", "name", name="uq_org_unit_scope"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    parent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("organization_units.id", ondelete="SET NULL"), nullable=True, index=True
    )
    unit_type: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    external_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class TenantMembership(Base):
    __tablename__ = "tenant_memberships"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id", name="uq_tenant_membership_user"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False, server_default="viewer")
    permissions: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    unit_ids: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class TenantQuota(Base):
    __tablename__ = "tenant_quotas"

    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    api_requests_per_minute: Mapped[int] = mapped_column(Integer, nullable=False, server_default="600")
    generation_concurrency: Mapped[int] = mapped_column(Integer, nullable=False, server_default="4")
    monthly_generation_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    storage_limit_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    monthly_budget_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )
