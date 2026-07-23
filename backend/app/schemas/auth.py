"""认证相关 Pydantic 模型。"""

from typing import Literal

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    """仅开发/测试环境可用的本地身份。"""
    user_id: str = Field(..., min_length=1, max_length=128)
    username: str | None = None
    role: str | None = Field(
        None, pattern="^(admin|operator|reviewer|analyst|supplier|viewer)$"
    )
    tenant_id: str = Field("default", min_length=1, max_length=36)
    permissions: list[str] = Field(default_factory=list, max_length=100)
    unit_ids: list[str] = Field(default_factory=list, max_length=100)


class OIDCCallbackRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=4096)
    state: str = Field(..., min_length=1, max_length=512)


class OIDCLoginResponse(BaseModel):
    authorization_url: str


class LoginMethodResponse(BaseModel):
    """A login method that is safe for the client to render."""

    id: Literal["development_account", "feishu", "enterprise_sso"]
    label: str
    login_path: str


class AuthConfigResponse(BaseModel):
    auth_enabled: bool
    mode: str
    login_methods: list[LoginMethodResponse] = Field(default_factory=list)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    username: str
    role: str
    tenant_id: str
    permissions: list[str] = Field(default_factory=list)
    unit_ids: list[str] = Field(default_factory=list)


class UserResponse(BaseModel):
    user_id: str
    username: str
    role: str
    tenant_id: str
    permissions: list[str] = Field(default_factory=list)
    unit_ids: list[str] = Field(default_factory=list)
