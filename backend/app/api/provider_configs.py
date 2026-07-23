"""Administrator API for encrypted, tenant-scoped external provider settings."""

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserInfo, has_permission, require_auth
from app.db.session import get_db
from app.models.audit_log import AuditLog
from app.models.provider_config import ProviderConfig
from app.schemas.provider_config import (
    ProviderConfigResponse,
    ProviderConfigUpsert,
    ProviderConfigValidationResponse,
    ProviderFieldResponse,
    ProviderId,
)
from app.services.integration_credentials import (
    CredentialCipherError,
    decrypt_credentials,
    encrypt_credentials,
)
from app.services.provider_config_service import (
    PROVIDER_DEFINITIONS,
    get_provider_config,
    normalize_provider_credentials,
    normalize_provider_settings,
    provider_status,
)

router = APIRouter(prefix="/api/provider-configs", tags=["Provider configuration"])


async def require_provider_config_manager(user: UserInfo = Depends(require_auth)) -> UserInfo:
    if not (user.role == "admin" or has_permission(user, "tenant:manage")):
        raise HTTPException(status_code=403, detail="需要租户外部服务配置权限")
    return user


def _response(config: ProviderConfig | None, provider: ProviderId) -> ProviderConfigResponse:
    definition = PROVIDER_DEFINITIONS[provider]
    return ProviderConfigResponse(
        provider=provider,
        display_name=definition.display_name,
        capabilities=list(definition.capabilities),
        credential_fields=[
            ProviderFieldResponse(
                key=field.key,
                label=field.label,
                placeholder=field.placeholder,
                required=field.required,
            )
            for field in definition.credential_fields
        ],
        config_fields=[
            ProviderFieldResponse(
                key=field.key,
                label=field.label,
                placeholder=field.placeholder,
                required=field.required,
            )
            for field in definition.config_fields
        ],
        enabled=bool(config.enabled) if config is not None else False,
        status=provider_status(config),
        config={str(key): str(value) for key, value in (config.config_json or {}).items()} if config else {},
        credentials_configured=bool(config and config.credentials_encrypted),
        credentials_fingerprint=((config.credentials_fingerprint or "")[:12] or None) if config else None,
        config_version=config.config_version if config else 0,
        updated_by=config.updated_by if config else None,
        updated_at=config.updated_at if config else None,
    )


def _audit(db: AsyncSession, *, tenant_id: str, provider: str, action: str, user_id: str) -> None:
    db.add(
        AuditLog(
            tenant_id=tenant_id,
            request_id=str(uuid4()),
            operation="provider_config",
            model_name=provider,
            generation_params={"provider": provider, "action": action, "actor_id": user_id},
            status="success",
        )
    )


@router.get("", response_model=list[ProviderConfigResponse])
async def list_provider_configs(
    user: UserInfo = Depends(require_provider_config_manager),
    db: AsyncSession = Depends(get_db),
) -> list[ProviderConfigResponse]:
    return [
        _response(await get_provider_config(db, provider, user.tenant_id), provider)  # type: ignore[arg-type]
        for provider in PROVIDER_DEFINITIONS
    ]


@router.put("/{provider}", response_model=ProviderConfigResponse)
async def upsert_provider_config(
    provider: ProviderId,
    body: ProviderConfigUpsert,
    user: UserInfo = Depends(require_provider_config_manager),
    db: AsyncSession = Depends(get_db),
) -> ProviderConfigResponse:
    try:
        safe_config = normalize_provider_settings(provider, body.config)
        credentials = (
            normalize_provider_credentials(provider, body.credentials)
            if body.credentials is not None
            else None
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    config = await get_provider_config(db, provider, user.tenant_id)
    if config is None:
        config = ProviderConfig(
            tenant_id=user.tenant_id,
            provider=provider,
            enabled=body.enabled,
            config_json=safe_config or None,
            status="incomplete",
            created_by=user.user_id,
            updated_by=user.user_id,
        )
        db.add(config)
        action = "created"
    else:
        config.enabled = body.enabled
        config.config_json = safe_config or None
        config.config_version += 1
        config.updated_by = user.user_id
        action = "updated"

    if credentials is not None:
        try:
            ciphertext, fingerprint = encrypt_credentials(credentials)
        except CredentialCipherError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        config.credentials_encrypted = ciphertext
        config.credentials_fingerprint = fingerprint

    config.status = provider_status(config)
    _audit(db, tenant_id=user.tenant_id, provider=provider, action=action, user_id=user.user_id)
    await db.flush()
    await db.refresh(config)
    return _response(config, provider)


@router.post("/{provider}/validate", response_model=ProviderConfigValidationResponse)
async def validate_provider_config(
    provider: ProviderId,
    user: UserInfo = Depends(require_provider_config_manager),
    db: AsyncSession = Depends(get_db),
) -> ProviderConfigValidationResponse:
    config = await get_provider_config(db, provider, user.tenant_id)
    if config is None or not config.credentials_encrypted:
        return ProviderConfigValidationResponse(
            provider=provider,
            status="incomplete",
            message="请先保存完整的 API 凭据。",
            config_version=config.config_version if config else 0,
        )
    try:
        normalize_provider_credentials(provider, decrypt_credentials(config.credentials_encrypted))
    except (CredentialCipherError, ValueError) as exc:
        config.status = "incomplete"
        await db.flush()
        return ProviderConfigValidationResponse(
            provider=provider,
            status="incomplete",
            message=str(exc),
            config_version=config.config_version,
        )
    config.status = provider_status(config)
    _audit(db, tenant_id=user.tenant_id, provider=provider, action="validated", user_id=user.user_id)
    await db.flush()
    return ProviderConfigValidationResponse(
        provider=provider,
        status=provider_status(config),
        message="加密凭据与配置结构校验通过；不会把密钥返回给浏览器。",
        config_version=config.config_version,
    )


@router.delete("/{provider}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider_config(
    provider: ProviderId,
    user: UserInfo = Depends(require_provider_config_manager),
    db: AsyncSession = Depends(get_db),
) -> Response:
    config = await get_provider_config(db, provider, user.tenant_id)
    if config is None:
        raise HTTPException(status_code=404, detail="该服务尚未配置")
    _audit(db, tenant_id=user.tenant_id, provider=provider, action="deleted", user_id=user.user_id)
    await db.delete(config)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
