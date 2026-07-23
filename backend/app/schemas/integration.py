"""Request and response contracts for tenant-managed ERP integrations."""

from datetime import datetime
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, model_validator

DianxiaomiScope = Literal["products", "listings", "inventory", "orders", "fulfillment"]


class DianxiaomiCredentialsInput(BaseModel):
    """Write-only provider credential fields; never included in a response."""

    api_key: str | None = Field(default=None, min_length=1, max_length=512)
    api_secret: str | None = Field(default=None, min_length=1, max_length=2048)
    access_token: str | None = Field(default=None, min_length=1, max_length=4096)

    @model_validator(mode="after")
    def require_at_least_one_value(self) -> "DianxiaomiCredentialsInput":
        if not any((self.api_key, self.api_secret, self.access_token)):
            raise ValueError("至少填写一个店小秘授权凭据字段")
        return self


class DianxiaomiConnectionCreate(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=128)
    merchant_reference: str | None = Field(default=None, max_length=128)
    api_base_url: str | None = Field(default=None, max_length=512)
    shop_references: list[str] = Field(default_factory=list, max_length=100)
    sync_scopes: list[DianxiaomiScope] = Field(
        default_factory=lambda: ["products", "listings", "inventory", "orders", "fulfillment"]
    )
    sync_interval_minutes: int = Field(default=360, ge=15, le=1440)
    credentials: DianxiaomiCredentialsInput

    @field_validator("api_base_url")
    @classmethod
    def require_https_api_url(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        parsed = urlparse(value.strip())
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("API 地址必须是 HTTPS URL")
        return value.strip().rstrip("/")

    @field_validator("display_name", "merchant_reference")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("字段不能为空白")
        return normalized

    @field_validator("shop_references")
    @classmethod
    def normalize_shop_references(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item.strip() for item in value if item.strip()))


class DianxiaomiConnectionUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=128)
    merchant_reference: str | None = Field(default=None, max_length=128)
    api_base_url: str | None = Field(default=None, max_length=512)
    shop_references: list[str] | None = Field(default=None, max_length=100)
    sync_scopes: list[DianxiaomiScope] | None = None
    sync_interval_minutes: int | None = Field(default=None, ge=15, le=1440)
    credentials: DianxiaomiCredentialsInput | None = None
    enabled: bool | None = None

    @field_validator("api_base_url")
    @classmethod
    def require_https_api_url(cls, value: str | None) -> str | None:
        return DianxiaomiConnectionCreate.require_https_api_url(value)

    @field_validator("display_name", "merchant_reference")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        return DianxiaomiConnectionCreate.normalize_text(value)

    @field_validator("shop_references")
    @classmethod
    def normalize_shop_references(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return DianxiaomiConnectionCreate.normalize_shop_references(value)


class DianxiaomiConnectionResponse(BaseModel):
    id: str
    tenant_id: str
    display_name: str
    merchant_reference: str | None
    api_base_url: str | None
    shop_references: list[str]
    sync_scopes: list[DianxiaomiScope]
    sync_interval_minutes: int
    status: str
    credentials_configured: bool
    credentials_fingerprint: str | None
    config_version: int
    last_sync_at: datetime | None
    last_sync_status: str | None
    last_sync_error: str | None
    created_at: datetime
    updated_at: datetime


class DianxiaomiConfigCheckResponse(BaseModel):
    connection_id: str
    status: Literal["ready_for_vendor_validation", "incomplete"]
    message: str
    config_version: int


class IntegrationSyncRunResponse(BaseModel):
    id: str
    connection_id: str
    trigger: str
    status: str
    requested_scopes: list[str]
    config_version: int
    records_received: int
    records_applied: int
    error_message: str | None
    cursor_before: str | None = None
    cursor_after: str | None = None
    started_at: datetime
    completed_at: datetime | None


class IntegrationSyncStartResponse(BaseModel):
    run_id: str
    status: str
    message: str
