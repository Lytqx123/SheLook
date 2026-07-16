"""企业 OIDC/SSO 登录与开发环境本地登录。"""

from fastapi import APIRouter, Depends, HTTPException

from app.config import settings
from app.core.auth import (
    UserInfo,
    begin_oidc_login,
    complete_oidc_login,
    create_access_token,
    require_auth,
)
from app.schemas.auth import (
    AuthConfigResponse,
    LoginRequest,
    OIDCCallbackRequest,
    OIDCLoginResponse,
    TokenResponse,
    UserResponse,
)

router = APIRouter(prefix="/api/auth", tags=["Auth"])


@router.get("/config", response_model=AuthConfigResponse)
async def auth_config() -> AuthConfigResponse:
    return AuthConfigResponse(
        auth_enabled=settings.ENABLE_AUTH,
        mode="oidc" if settings.ENABLE_AUTH else "development",
    )


@router.post("/login", response_model=OIDCLoginResponse)
async def oidc_login() -> OIDCLoginResponse:
    if not settings.ENABLE_AUTH:
        raise HTTPException(status_code=404, detail="OIDC 登录未启用")
    return OIDCLoginResponse(authorization_url=await begin_oidc_login())


@router.post("/callback", response_model=TokenResponse)
async def oidc_callback(body: OIDCCallbackRequest) -> TokenResponse:
    if not settings.ENABLE_AUTH:
        raise HTTPException(status_code=404, detail="OIDC 登录未启用")
    token, user = await complete_oidc_login(body.code, body.state)
    return TokenResponse(
        access_token=token,
        user_id=user.user_id,
        username=user.username,
        role=user.role,
    )


@router.post("/token", response_model=TokenResponse)
async def development_login(body: LoginRequest) -> TokenResponse:
    """本地开发用，生产环境直接 404"""
    if settings.APP_ENV == "production" or settings.ENABLE_AUTH:
        raise HTTPException(status_code=404, detail="本地登录不可用")
    role = body.role or "viewer"
    username = body.username or body.user_id
    return TokenResponse(
        access_token=create_access_token(body.user_id, username, role),
        user_id=body.user_id,
        username=username,
        role=role,
    )


@router.get("/me", response_model=UserResponse)
async def get_me(user: UserInfo = Depends(require_auth)) -> UserResponse:
    return UserResponse(user_id=user.user_id, username=user.username, role=user.role)
