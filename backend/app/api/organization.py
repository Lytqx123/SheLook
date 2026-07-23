"""企业组织、成员和配额管理接口。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.auth import UserInfo, has_permission, require_auth, revoke_member_sessions
from app.core.external_identity import enterprise_member_user_id
from app.db.session import get_db
from app.models.organization import OrganizationUnit, Tenant, TenantMembership, TenantQuota
from app.models.release_control import TenantFeatureFlag
from app.schemas.organization import (
    OrganizationUnitCreate,
    OrganizationUnitResponse,
    TenantContextResponse,
    TenantFeatureFlagResponse,
    TenantFeatureFlagUpdate,
    TenantMemberInvite,
    TenantMemberResponse,
    TenantMemberUpsert,
    TenantQuotaResponse,
    TenantQuotaUpdate,
)
from app.services.feature_flags import DEFAULT_FEATURE_FLAGS

router = APIRouter(prefix="/api/organization", tags=["Organization"])


async def require_tenant_admin(user: UserInfo = Depends(require_auth)) -> UserInfo:
    if not (has_permission(user, "tenant:manage") or user.role == "admin"):
        raise HTTPException(status_code=403, detail="需要租户管理员权限")
    return user


def _unit_response(unit: OrganizationUnit) -> OrganizationUnitResponse:
    return OrganizationUnitResponse(
        id=unit.id,
        tenant_id=unit.tenant_id,
        unit_type=unit.unit_type,
        name=unit.name,
        parent_id=unit.parent_id,
        external_ref=unit.external_ref,
        is_active=unit.is_active,
        created_at=unit.created_at,
        updated_at=unit.updated_at,
    )


def _member_response(member: TenantMembership) -> TenantMemberResponse:
    return TenantMemberResponse(
        id=member.id,
        tenant_id=member.tenant_id,
        user_id=member.user_id,
        display_name=member.display_name,
        role=member.role,
        permissions=member.permissions or [],
        unit_ids=member.unit_ids or [],
        is_active=member.is_active,
        created_at=member.created_at,
        updated_at=member.updated_at,
    )


def _quota_response(quota: TenantQuota) -> TenantQuotaResponse:
    return TenantQuotaResponse(
        tenant_id=quota.tenant_id,
        api_requests_per_minute=quota.api_requests_per_minute,
        generation_concurrency=quota.generation_concurrency,
        monthly_generation_limit=quota.monthly_generation_limit,
        storage_limit_bytes=quota.storage_limit_bytes,
        monthly_budget_cents=quota.monthly_budget_cents,
        updated_at=quota.updated_at,
    )


def _feature_flag_response(flag: TenantFeatureFlag) -> TenantFeatureFlagResponse:
    return TenantFeatureFlagResponse(
        tenant_id=flag.tenant_id,
        flag_key=flag.flag_key,
        enabled=flag.enabled,
        rollout_note=flag.rollout_note,
        updated_by=flag.updated_by,
        updated_at=flag.updated_at,
    )


@router.get("/context", response_model=TenantContextResponse)
async def get_current_tenant_context(
    user: UserInfo = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> TenantContextResponse:
    tenant = await db.get(Tenant, user.tenant_id)
    if tenant is None or tenant.status != "active":
        raise HTTPException(status_code=403, detail="当前租户不存在或已停用")
    return TenantContextResponse(
        tenant_id=user.tenant_id,
        tenant_name=tenant.name,
        user_id=user.user_id,
        username=user.username,
        role=user.role,
        permissions=list(user.permissions),
        unit_ids=list(user.unit_ids),
    )


@router.get("/units", response_model=list[OrganizationUnitResponse])
async def list_organization_units(
    user: UserInfo = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> list[OrganizationUnitResponse]:
    result = await db.execute(
        select(OrganizationUnit)
        .where(OrganizationUnit.tenant_id == user.tenant_id)
        .order_by(OrganizationUnit.unit_type, OrganizationUnit.name)
    )
    return [_unit_response(unit) for unit in result.scalars()]


@router.post("/units", response_model=OrganizationUnitResponse, status_code=201)
async def create_organization_unit(
    body: OrganizationUnitCreate,
    user: UserInfo = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_db),
) -> OrganizationUnitResponse:
    if body.parent_id:
        parent = await db.get(OrganizationUnit, body.parent_id)
        if parent is None or parent.tenant_id != user.tenant_id:
            raise HTTPException(status_code=422, detail="父级组织单元不存在或不属于当前租户")

    unit = OrganizationUnit(tenant_id=user.tenant_id, **body.model_dump())
    db.add(unit)
    await db.flush()
    await db.refresh(unit)
    return _unit_response(unit)


@router.get("/members", response_model=list[TenantMemberResponse])
async def list_tenant_members(
    user: UserInfo = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_db),
) -> list[TenantMemberResponse]:
    result = await db.execute(
        select(TenantMembership)
        .where(TenantMembership.tenant_id == user.tenant_id)
        .order_by(TenantMembership.user_id)
    )
    return [_member_response(member) for member in result.scalars()]


@router.post("/members", response_model=TenantMemberResponse, status_code=201)
async def invite_tenant_member(
    body: TenantMemberInvite,
    user: UserInfo = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_db),
) -> TenantMemberResponse:
    """Invite a provider-scoped enterprise identity into the current tenant."""
    try:
        member_user_id = enterprise_member_user_id(
            body.identity_provider,
            body.external_subject,
            oidc_issuer_url=settings.OIDC_ISSUER_URL,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    existing = await db.scalar(
        select(TenantMembership).where(
            TenantMembership.tenant_id == user.tenant_id,
            TenantMembership.user_id == member_user_id,
        )
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="该企业身份已在当前租户中")

    member = TenantMembership(
        tenant_id=user.tenant_id,
        user_id=member_user_id,
        display_name=body.display_name,
        role=body.role,
        permissions=body.permissions,
        unit_ids=body.unit_ids,
        is_active=body.is_active,
    )
    db.add(member)
    await db.flush()
    await db.refresh(member)
    await revoke_member_sessions(user.tenant_id, member.user_id, reason="membership_created")
    return _member_response(member)


@router.put("/members/{member_user_id}", response_model=TenantMemberResponse)
async def upsert_tenant_member(
    member_user_id: str,
    body: TenantMemberUpsert,
    user: UserInfo = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_db),
) -> TenantMemberResponse:
    if member_user_id != body.user_id:
        raise HTTPException(status_code=422, detail="路径用户与请求体 user_id 必须一致")
    result = await db.execute(
        select(TenantMembership).where(
            TenantMembership.tenant_id == user.tenant_id,
            TenantMembership.user_id == member_user_id,
        )
    )
    member = result.scalar_one_or_none()
    if member is None:
        raise HTTPException(
            status_code=404,
            detail="成员不存在；请通过 POST /api/organization/members 使用身份源邀请成员",
        )

    change_reason: str | None = None
    for field, value in body.model_dump().items():
        if getattr(member, field) != value:
            change_reason = "membership_changed"
        setattr(member, field, value)
    await db.flush()
    await db.refresh(member)
    if change_reason:
        # Redis is intentionally updated before get_db commits. A production
        # Redis failure raises here and get_db rolls this membership write back;
        # a later database commit failure can only cause a safe extra re-login.
        await revoke_member_sessions(
            user.tenant_id,
            member.user_id,
            reason=change_reason,
        )
    return _member_response(member)


@router.get("/quota", response_model=TenantQuotaResponse)
async def get_tenant_quota(
    user: UserInfo = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_db),
) -> TenantQuotaResponse:
    quota = await db.get(TenantQuota, user.tenant_id)
    if quota is None:
        quota = TenantQuota(tenant_id=user.tenant_id)
        db.add(quota)
        await db.flush()
        await db.refresh(quota)
    return _quota_response(quota)


@router.put("/quota", response_model=TenantQuotaResponse)
async def update_tenant_quota(
    body: TenantQuotaUpdate,
    user: UserInfo = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_db),
) -> TenantQuotaResponse:
    quota = await db.get(TenantQuota, user.tenant_id)
    if quota is None:
        quota = TenantQuota(tenant_id=user.tenant_id, **body.model_dump())
        db.add(quota)
    else:
        for field, value in body.model_dump().items():
            setattr(quota, field, value)
    await db.flush()
    await db.refresh(quota)
    return _quota_response(quota)


@router.get("/feature-flags", response_model=list[TenantFeatureFlagResponse])
async def list_tenant_feature_flags(
    user: UserInfo = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_db),
) -> list[TenantFeatureFlagResponse]:
    result = await db.execute(
        select(TenantFeatureFlag)
        .where(TenantFeatureFlag.tenant_id == user.tenant_id)
        .order_by(TenantFeatureFlag.flag_key)
    )
    configured = {flag.flag_key: flag for flag in result.scalars()}
    flags = list(configured.values())
    for flag_key, enabled in DEFAULT_FEATURE_FLAGS.items():
        if flag_key not in configured:
            flags.append(
                TenantFeatureFlag(
                    tenant_id=user.tenant_id,
                    flag_key=flag_key,
                    enabled=enabled,
                    rollout_note="platform default",
                )
            )
    return [_feature_flag_response(flag) for flag in sorted(flags, key=lambda item: item.flag_key)]


@router.put("/feature-flags/{flag_key}", response_model=TenantFeatureFlagResponse)
async def update_tenant_feature_flag(
    flag_key: str,
    body: TenantFeatureFlagUpdate,
    user: UserInfo = Depends(require_tenant_admin),
    db: AsyncSession = Depends(get_db),
) -> TenantFeatureFlagResponse:
    if flag_key not in DEFAULT_FEATURE_FLAGS:
        raise HTTPException(status_code=422, detail="未知或不可管理的功能开关")
    flag = await db.scalar(
        select(TenantFeatureFlag).where(
            TenantFeatureFlag.tenant_id == user.tenant_id,
            TenantFeatureFlag.flag_key == flag_key,
        )
    )
    if flag is None:
        flag = TenantFeatureFlag(
            tenant_id=user.tenant_id,
            flag_key=flag_key,
            enabled=body.enabled,
            rollout_note=body.rollout_note,
            updated_by=user.user_id,
        )
        db.add(flag)
    else:
        flag.enabled = body.enabled
        flag.rollout_note = body.rollout_note
        flag.updated_by = user.user_id
    await db.flush()
    await db.refresh(flag)
    return _feature_flag_response(flag)
