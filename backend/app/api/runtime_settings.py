"""Tenant-admin API for allow-listed business runtime settings."""

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.integrations import require_integration_manager
from app.core.auth import UserInfo
from app.db.session import get_db
from app.models.audit_log import AuditLog
from app.schemas.runtime_setting import (
    RuntimeSettingResponse,
    RuntimeSettingRevisionResponse,
    RuntimeSettingUpdate,
)
from app.services.runtime_settings import (
    EffectiveRuntimeSetting,
    RuntimeSettingError,
    list_effective_runtime_settings,
    list_runtime_setting_revisions,
    reset_runtime_setting,
    set_runtime_setting,
)

router = APIRouter(prefix="/api/runtime-settings", tags=["Runtime settings"])


def _response(setting: EffectiveRuntimeSetting) -> RuntimeSettingResponse:
    return RuntimeSettingResponse(
        key=setting.spec.key,
        label=setting.spec.label,
        description=setting.spec.description,
        value_type=setting.spec.value_type,
        default_value=setting.spec.default,
        value=setting.value,
        is_overridden=setting.is_overridden,
        version=setting.version,
        updated_by=setting.updated_by,
        updated_at=setting.updated_at,
    )


def _audit(db: AsyncSession, *, tenant_id: str, setting_key: str, action: str, actor_id: str) -> None:
    db.add(
        AuditLog(
            tenant_id=tenant_id,
            request_id=str(uuid4()),
            operation="runtime_setting",
            model_name="runtime_setting",
            generation_params={"setting_key": setting_key, "action": action, "actor_id": actor_id},
            status="success",
        )
    )


@router.get("", response_model=list[RuntimeSettingResponse])
async def list_runtime_settings(
    user: UserInfo = Depends(require_integration_manager),
    db: AsyncSession = Depends(get_db),
) -> list[RuntimeSettingResponse]:
    settings = await list_effective_runtime_settings(db, tenant_id=user.tenant_id)
    return [_response(setting) for setting in settings]


@router.put("/{setting_key}", response_model=RuntimeSettingResponse)
async def update_runtime_setting(
    setting_key: str,
    body: RuntimeSettingUpdate,
    user: UserInfo = Depends(require_integration_manager),
    db: AsyncSession = Depends(get_db),
) -> RuntimeSettingResponse:
    try:
        setting = await set_runtime_setting(
            db,
            tenant_id=user.tenant_id,
            setting_key=setting_key,
            value=body.value,
            actor_id=user.user_id,
        )
    except RuntimeSettingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _audit(
        db,
        tenant_id=user.tenant_id,
        setting_key=setting_key,
        action="updated",
        actor_id=user.user_id,
    )
    return _response(setting)


@router.post("/{setting_key}/reset", response_model=RuntimeSettingResponse)
async def reset_runtime_setting_to_default(
    setting_key: str,
    user: UserInfo = Depends(require_integration_manager),
    db: AsyncSession = Depends(get_db),
) -> RuntimeSettingResponse:
    try:
        setting = await reset_runtime_setting(
            db,
            tenant_id=user.tenant_id,
            setting_key=setting_key,
            actor_id=user.user_id,
        )
    except RuntimeSettingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _audit(
        db,
        tenant_id=user.tenant_id,
        setting_key=setting_key,
        action="reset_to_default",
        actor_id=user.user_id,
    )
    return _response(setting)


@router.get("/{setting_key}/history", response_model=list[RuntimeSettingRevisionResponse])
async def get_runtime_setting_history(
    setting_key: str,
    user: UserInfo = Depends(require_integration_manager),
    db: AsyncSession = Depends(get_db),
) -> list[RuntimeSettingRevisionResponse]:
    try:
        revisions = await list_runtime_setting_revisions(
            db, tenant_id=user.tenant_id, setting_key=setting_key
        )
    except RuntimeSettingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return [
        RuntimeSettingRevisionResponse(
            key=revision.setting_key,
            version=revision.version,
            value=revision.value_json,
            action=revision.action,
            changed_by=revision.changed_by,
            created_at=revision.created_at,
        )
        for revision in revisions
    ]
