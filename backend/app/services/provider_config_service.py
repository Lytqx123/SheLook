"""Definitions, encryption boundaries and runtime lookup for external providers."""

from dataclasses import dataclass
from typing import Final
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.core.tenant import get_current_tenant_id
from app.models.provider_config import ProviderConfig
from app.services.integration_credentials import CredentialCipherError, decrypt_credentials


@dataclass(frozen=True, slots=True)
class ProviderField:
    key: str
    label: str
    placeholder: str | None = None
    required: bool = True


@dataclass(frozen=True, slots=True)
class ProviderDefinition:
    provider: str
    display_name: str
    capabilities: tuple[str, ...]
    credential_fields: tuple[ProviderField, ...]
    credential_groups: tuple[tuple[str, ...], ...]
    config_fields: tuple[ProviderField, ...] = ()


@dataclass(frozen=True, slots=True)
class ProviderRuntimeConfig:
    provider: str
    credentials: dict[str, str]
    config: dict[str, str]
    version: int


PROVIDER_DEFINITIONS: Final[dict[str, ProviderDefinition]] = {
    "kling": ProviderDefinition(
        provider="kling",
        display_name="Kling AI",
        capabilities=("视频生成",),
        credential_fields=(
            ProviderField("api_key", "API Key", "单一 API Key 认证"),
            ProviderField("access_key", "Access Key", "国际版 JWT 认证", required=False),
            ProviderField("secret_key", "Secret Key", "国际版 JWT 认证", required=False),
        ),
        credential_groups=(("api_key",), ("access_key", "secret_key")),
        config_fields=(
            ProviderField("api_base_url", "API 基础地址", "https://api.klingai.com/v1", required=False),
        ),
    ),
    "runway": ProviderDefinition(
        provider="runway",
        display_name="Runway",
        capabilities=("视频生成",),
        credential_fields=(ProviderField("api_key", "API Key"),),
        credential_groups=(("api_key",),),
        config_fields=(
            ProviderField("api_base_url", "API 基础地址", "https://api.runwayml.com/v1", required=False),
        ),
    ),
    "replicate": ProviderDefinition(
        provider="replicate",
        display_name="Replicate",
        capabilities=("图片生成",),
        credential_fields=(ProviderField("api_token", "API Token"),),
        credential_groups=(("api_token",),),
    ),
    "gemini": ProviderDefinition(
        provider="gemini",
        display_name="Google Gemini",
        capabilities=("图片生成", "AI 审核"),
        credential_fields=(ProviderField("api_key", "API Key"),),
        credential_groups=(("api_key",),),
        config_fields=(
            ProviderField("api_base_url", "API 基础地址", "留空使用 Google 默认地址", required=False),
        ),
    ),
    "shopee": ProviderDefinition(
        provider="shopee",
        display_name="Shopee Open Platform",
        capabilities=("指标同步",),
        credential_fields=(
            ProviderField("partner_id", "Partner ID"),
            ProviderField("partner_key", "Partner Key"),
            ProviderField("shop_id", "Shop ID"),
            ProviderField("access_token", "Access Token"),
        ),
        credential_groups=(("partner_id", "partner_key", "shop_id", "access_token"),),
        config_fields=(ProviderField("region", "站点区域", "sg / my / th / tw / id / vn / ph / br / mx"),),
    ),
    "amazon": ProviderDefinition(
        provider="amazon",
        display_name="Amazon SP-API",
        capabilities=("指标同步",),
        credential_fields=(
            ProviderField("client_id", "LWA Client ID"),
            ProviderField("client_secret", "LWA Client Secret"),
            ProviderField("refresh_token", "LWA Refresh Token"),
        ),
        credential_groups=(("client_id", "client_secret", "refresh_token"),),
        config_fields=(
            ProviderField("region", "API 区域", "na / eu / fe"),
            ProviderField("marketplace_id", "Marketplace ID", "例如 ATVPDKIKX0DER"),
        ),
    ),
}


def get_provider_definition(provider: str) -> ProviderDefinition:
    definition = PROVIDER_DEFINITIONS.get(provider)
    if definition is None:
        raise ValueError(f"不支持的外部服务提供商: {provider}")
    return definition


def _normalize_settings(definition: ProviderDefinition, config: dict[str, str]) -> dict[str, str]:
    allowed = {field.key for field in definition.config_fields}
    unexpected = set(config) - allowed
    if unexpected:
        raise ValueError(f"{definition.display_name} 不支持配置字段: {', '.join(sorted(unexpected))}")
    normalized = {key: value.strip() for key, value in config.items() if value.strip()}
    for key in ("api_base_url",):
        if key not in normalized:
            continue
        parsed = urlparse(normalized[key])
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("API 基础地址必须是 HTTPS URL")
        normalized[key] = normalized[key].rstrip("/")
    if definition.provider == "shopee" and "region" in normalized:
        allowed_regions = {"sg", "my", "th", "tw", "id", "vn", "ph", "br", "mx"}
        normalized["region"] = normalized["region"].lower()
        if normalized["region"] not in allowed_regions:
            raise ValueError("Shopee 区域必须是 sg、my、th、tw、id、vn、ph、br 或 mx")
    if definition.provider == "amazon" and "region" in normalized:
        normalized["region"] = normalized["region"].lower()
        if normalized["region"] not in {"na", "eu", "fe"}:
            raise ValueError("Amazon API 区域必须是 na、eu 或 fe")
    return normalized


def normalize_provider_credentials(provider: str, credentials: dict[str, str]) -> dict[str, str]:
    """Validate a complete credential replacement without retaining plaintext."""
    definition = get_provider_definition(provider)
    allowed = {field.key for field in definition.credential_fields}
    unexpected = set(credentials) - allowed
    if unexpected:
        raise ValueError(f"{definition.display_name} 不支持凭据字段: {', '.join(sorted(unexpected))}")
    normalized = {key: value.strip() for key, value in credentials.items() if value.strip()}
    if not any(all(normalized.get(key) for key in group) for group in definition.credential_groups):
        readable_groups = " 或 ".join(" + ".join(group) for group in definition.credential_groups)
        raise ValueError(f"{definition.display_name} 凭据不完整，需要填写 {readable_groups}")
    return normalized


def normalize_provider_settings(provider: str, config: dict[str, str]) -> dict[str, str]:
    return _normalize_settings(get_provider_definition(provider), config)


def provider_status(config: ProviderConfig | None) -> str:
    if config is None:
        return "incomplete"
    if not config.enabled:
        return "disabled"
    if not config.credentials_encrypted:
        return "incomplete"
    return "configured"


async def get_provider_config(
    db: AsyncSession,
    provider: str,
    tenant_id: str | None = None,
) -> ProviderConfig | None:
    return await db.scalar(
        select(ProviderConfig).where(
            ProviderConfig.provider == provider,
            ProviderConfig.tenant_id == (tenant_id or get_current_tenant_id()),
        )
    )


async def resolve_provider_runtime_config(
    db: AsyncSession,
    provider: str,
    tenant_id: str | None = None,
) -> ProviderRuntimeConfig | None:
    """Decrypt an enabled config only inside a backend runtime request/task."""
    config = await get_provider_config(db, provider, tenant_id)
    if provider_status(config) != "configured" or config is None:
        return None
    try:
        credentials = decrypt_credentials(config.credentials_encrypted or "")
    except CredentialCipherError as exc:
        logger.warning("外部服务凭据无法解密", provider=provider, error=str(exc))
        return None
    return ProviderRuntimeConfig(
        provider=provider,
        credentials=credentials,
        config={str(key): str(value) for key, value in (config.config_json or {}).items()},
        version=config.config_version,
    )
