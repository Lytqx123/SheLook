"""认证相关 Pydantic 模型。"""

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    """仅开发/测试环境可用的本地身份。"""

    user_id: str = Field(..., min_length=1, max_length=128)
    username: str | None = None
    role: str | None = Field(None, pattern="^(admin|viewer)$")


class OIDCCallbackRequest(BaseModel):
    code: str = Field(..., min_length=1)
    state: str = Field(..., min_length=1)


class OIDCLoginResponse(BaseModel):
    authorization_url: str


class AuthConfigResponse(BaseModel):
    auth_enabled: bool
    mode: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    username: str
    role: str


class UserResponse(BaseModel):
    user_id: str
    username: str
    role: str
