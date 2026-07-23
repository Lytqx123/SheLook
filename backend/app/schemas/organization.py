"""企业组织管理请求与响应模型。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

OrganizationUnitType = Literal["brand", "store", "department", "team"]
TenantRole = Literal["admin", "operator", "reviewer", "analyst", "supplier", "viewer"]
EnterpriseIdentityProvider = Literal["feishu", "oidc"]


class TenantContextResponse(BaseModel):
    tenant_id: str
    tenant_name: str
    user_id: str
    username: str
    role: str
    permissions: list[str] = Field(default_factory=list)
    unit_ids: list[str] = Field(default_factory=list)


class OrganizationUnitCreate(BaseModel):
    unit_type: OrganizationUnitType
    name: str = Field(min_length=1, max_length=128)
    parent_id: str | None = Field(None, max_length=36)
    external_ref: str | None = Field(None, max_length=128)


class OrganizationUnitResponse(OrganizationUnitCreate):
    id: str
    tenant_id: str
    is_active: bool
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TenantMemberUpsert(BaseModel):
    user_id: str = Field(min_length=1, max_length=128)
    display_name: str | None = Field(None, max_length=128)
    role: TenantRole = "viewer"
    permissions: list[str] = Field(default_factory=list, max_length=100)
    unit_ids: list[str] = Field(default_factory=list, max_length=100)
    is_active: bool = True


class TenantMemberInvite(BaseModel):
    """Create a member from an explicit external identity, never a raw local key."""

    identity_provider: EnterpriseIdentityProvider
    external_subject: str = Field(min_length=1, max_length=1_024)
    display_name: str | None = Field(None, max_length=128)
    role: TenantRole = "viewer"
    permissions: list[str] = Field(default_factory=list, max_length=100)
    unit_ids: list[str] = Field(default_factory=list, max_length=100)
    is_active: bool = True


class TenantMemberResponse(TenantMemberUpsert):
    id: str
    tenant_id: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TenantQuotaUpdate(BaseModel):
    api_requests_per_minute: int = Field(ge=1, le=100_000)
    generation_concurrency: int = Field(ge=0, le=10_000)
    monthly_generation_limit: int | None = Field(None, ge=0)
    storage_limit_bytes: int | None = Field(None, ge=0)
    monthly_budget_cents: int | None = Field(None, ge=0)


class TenantQuotaResponse(TenantQuotaUpdate):
    tenant_id: str
    updated_at: datetime | None = None


class TenantFeatureFlagUpdate(BaseModel):
    enabled: bool
    rollout_note: str | None = Field(None, max_length=1_000)


class TenantFeatureFlagResponse(TenantFeatureFlagUpdate):
    tenant_id: str
    flag_key: str
    updated_by: str | None = None
    updated_at: datetime | None = None
