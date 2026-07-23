"""Contracts for Web-managed external provider configuration."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

ProviderId = Literal["kling", "runway", "replicate", "gemini", "shopee", "amazon"]


class ProviderFieldResponse(BaseModel):
    """A safe field definition used to render the administrator form."""

    key: str
    label: str
    placeholder: str | None = None
    required: bool = True


class ProviderConfigUpsert(BaseModel):
    """Credentials are write-only and replace the previous encrypted bundle."""

    enabled: bool = True
    config: dict[str, str] = Field(default_factory=dict)
    credentials: dict[str, str] | None = None

    @field_validator("config", "credentials")
    @classmethod
    def normalize_map(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        if value is None:
            return None
        normalized: dict[str, str] = {}
        for key, item in value.items():
            normalized_key = str(key).strip()
            normalized_value = str(item).strip()
            if not normalized_key:
                raise ValueError("配置字段名不能为空")
            if not normalized_value:
                continue
            if len(normalized_value) > 4096:
                raise ValueError(f"配置字段 {normalized_key} 超过长度限制")
            normalized[normalized_key] = normalized_value
        return normalized


class ProviderConfigResponse(BaseModel):
    provider: ProviderId
    display_name: str
    capabilities: list[str]
    credential_fields: list[ProviderFieldResponse]
    config_fields: list[ProviderFieldResponse]
    enabled: bool
    status: str
    config: dict[str, str]
    credentials_configured: bool
    credentials_fingerprint: str | None = None
    config_version: int
    updated_by: str | None = None
    updated_at: datetime | None = None


class ProviderConfigValidationResponse(BaseModel):
    provider: ProviderId
    status: Literal["configured", "incomplete", "disabled"]
    message: str
    config_version: int
