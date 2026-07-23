"""Enterprise SSO, Feishu OAuth, and development-only local login."""

import secrets
from urllib.parse import parse_qs, urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.auth import (
    UserInfo,
    begin_feishu_login,
    begin_oidc_login,
    complete_enterprise_login,
    create_access_token,
    is_feishu_login_configured,
    is_oidc_login_configured,
    require_auth,
)
from app.db.session import get_db
from app.schemas.auth import (
    AuthConfigResponse,
    LoginMethodResponse,
    LoginRequest,
    OIDCCallbackRequest,
    OIDCLoginResponse,
    TokenResponse,
    UserResponse,
)

router = APIRouter(prefix="/api/auth", tags=["Auth"])
_LOGIN_STATE_COOKIE_NAME = "shelook_login_state"
_LOGIN_STATE_COOKIE_PATH = "/api/auth"
_LOGIN_STATE_TTL_SECONDS = 600


def _token_response(token: str, user: UserInfo) -> TokenResponse:
    return TokenResponse(
        access_token=token,
        user_id=user.user_id,
        username=user.username,
        role=user.role,
        tenant_id=user.tenant_id,
        permissions=list(user.permissions),
        unit_ids=list(user.unit_ids),
    )


def _authorization_state(authorization_url: str) -> str:
    states = parse_qs(urlparse(authorization_url).query).get("state", [])
    if len(states) != 1 or not states[0]:
        raise RuntimeError("企业登录提供方未返回有效 state")
    return states[0]


def _set_login_state_cookie(response: Response, authorization_url: str) -> None:
    """Bind the server-side one-time state to the browser that began login."""
    response.set_cookie(
        key=_LOGIN_STATE_COOKIE_NAME,
        value=_authorization_state(authorization_url),
        max_age=_LOGIN_STATE_TTL_SECONDS,
        httponly=True,
        secure=settings.APP_ENV.lower() == "production",
        samesite="lax",
        path=_LOGIN_STATE_COOKIE_PATH,
    )


def _require_login_state_cookie(request: Request, state: str) -> None:
    cookie_state = request.cookies.get(_LOGIN_STATE_COOKIE_NAME)
    if not cookie_state or not secrets.compare_digest(cookie_state, state):
        raise HTTPException(status_code=400, detail="企业登录 state 与浏览器会话不匹配")


def _clear_login_state_cookie(response: Response) -> None:
    response.delete_cookie(
        key=_LOGIN_STATE_COOKIE_NAME,
        path=_LOGIN_STATE_COOKIE_PATH,
        secure=settings.APP_ENV.lower() == "production",
        httponly=True,
        samesite="lax",
    )


@router.get("/config", response_model=AuthConfigResponse)
async def auth_config() -> AuthConfigResponse:
    login_methods: list[LoginMethodResponse] = []
    if not settings.ENABLE_AUTH and settings.APP_ENV.lower() != "production":
        login_methods.append(
            LoginMethodResponse(
                id="development_account", label="账号登录（开发环境）", login_path="/api/auth/token"
            )
        )
    if settings.ENABLE_AUTH and is_feishu_login_configured():
        login_methods.append(
            LoginMethodResponse(id="feishu", label="飞书登录", login_path="/api/auth/feishu/login")
        )
    if settings.ENABLE_AUTH and is_oidc_login_configured():
        login_methods.append(
            LoginMethodResponse(
                id="enterprise_sso", label="企业 SSO", login_path="/api/auth/login"
            )
        )
    return AuthConfigResponse(
        auth_enabled=settings.ENABLE_AUTH,
        mode="enterprise" if settings.ENABLE_AUTH else "development",
        login_methods=login_methods,
    )


@router.post("/login", response_model=OIDCLoginResponse)
async def oidc_login(response: Response) -> OIDCLoginResponse:
    if not settings.ENABLE_AUTH or not is_oidc_login_configured():
        raise HTTPException(status_code=404, detail="企业 SSO 未启用")
    authorization_url = await begin_oidc_login()
    _set_login_state_cookie(response, authorization_url)
    return OIDCLoginResponse(authorization_url=authorization_url)


@router.post("/feishu/login", response_model=OIDCLoginResponse)
async def feishu_login(response: Response) -> OIDCLoginResponse:
    if not settings.ENABLE_AUTH or not is_feishu_login_configured():
        raise HTTPException(status_code=404, detail="飞书登录未启用")
    authorization_url = await begin_feishu_login()
    _set_login_state_cookie(response, authorization_url)
    return OIDCLoginResponse(authorization_url=authorization_url)


@router.post("/callback", response_model=TokenResponse)
async def oidc_callback(
    body: OIDCCallbackRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    if not settings.ENABLE_AUTH:
        raise HTTPException(status_code=404, detail="企业登录未启用")
    _require_login_state_cookie(request, body.state)
    token, user = await complete_enterprise_login(body.code, body.state, db)
    _clear_login_state_cookie(response)
    return _token_response(token, user)


@router.post("/token", response_model=TokenResponse)
async def development_login(body: LoginRequest) -> TokenResponse:
    """本地开发用，生产环境直接 404"""
    if settings.APP_ENV == "production" or settings.ENABLE_AUTH:
        raise HTTPException(status_code=404, detail="本地登录不可用")
    role = body.role or "viewer"
    username = body.username or body.user_id
    return TokenResponse(
        access_token=create_access_token(
            body.user_id,
            username,
            role,
            tenant_id=body.tenant_id,
            permissions=tuple(body.permissions),
            unit_ids=tuple(body.unit_ids),
        ),
        user_id=body.user_id,
        username=username,
        role=role,
        tenant_id=body.tenant_id,
        permissions=body.permissions,
        unit_ids=body.unit_ids,
    )


@router.get("/me", response_model=UserResponse)
async def get_me(user: UserInfo = Depends(require_auth)) -> UserResponse:
    return UserResponse(
        user_id=user.user_id,
        username=user.username,
        role=user.role,
        tenant_id=user.tenant_id,
        permissions=list(user.permissions),
        unit_ids=list(user.unit_ids),
    )
