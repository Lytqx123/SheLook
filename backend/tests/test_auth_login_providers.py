"""Regression coverage for the client-safe enterprise login provider contract."""

import asyncio
import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import HTTPException
from starlette.responses import Response

from app import main
from app.api import auth as auth_api
from app.config import settings
from app.core import auth


def _configure_feishu(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ENABLE_AUTH", True)
    monkeypatch.setattr(settings, "FEISHU_APP_ID", "cli_test")
    monkeypatch.setattr(settings, "FEISHU_APP_SECRET", "server-only-secret")
    monkeypatch.setattr(settings, "FEISHU_REDIRECT_URI", "https://app.example.com/login/callback")
    monkeypatch.setattr(settings, "FEISHU_SCOPES", "auth:user.id:read")
    monkeypatch.setattr(settings, "FEISHU_TENANT_KEY_MAP", {"tenant-key": "tenant-local"})
    monkeypatch.setattr(settings, "FEISHU_ALLOWED_TENANT_KEYS", [])


def _disable_feishu(monkeypatch) -> None:
    monkeypatch.setattr(settings, "FEISHU_APP_ID", "")
    monkeypatch.setattr(settings, "FEISHU_APP_SECRET", "")
    monkeypatch.setattr(settings, "FEISHU_REDIRECT_URI", "")
    monkeypatch.setattr(settings, "FEISHU_TENANT_KEY_MAP", {})
    monkeypatch.setattr(settings, "FEISHU_ALLOWED_TENANT_KEYS", [])


def _configure_oidc(monkeypatch) -> None:
    monkeypatch.setattr(settings, "OIDC_ISSUER_URL", "https://id.example.com")
    monkeypatch.setattr(settings, "OIDC_CLIENT_ID", "oidc-client")
    monkeypatch.setattr(settings, "OIDC_CLIENT_SECRET", "oidc-server-secret")


def _disable_oidc(monkeypatch) -> None:
    monkeypatch.setattr(settings, "OIDC_ISSUER_URL", "")
    monkeypatch.setattr(settings, "OIDC_CLIENT_ID", "")
    monkeypatch.setattr(settings, "OIDC_CLIENT_SECRET", "")


def test_auth_config_lists_only_available_login_methods(client, monkeypatch) -> None:
    _disable_feishu(monkeypatch)
    _disable_oidc(monkeypatch)
    monkeypatch.setattr(settings, "ENABLE_AUTH", False)
    monkeypatch.setattr(settings, "APP_ENV", "development")

    development = client.get("/api/auth/config")
    assert development.status_code == 200
    assert development.json() == {
        "auth_enabled": False,
        "mode": "development",
        "login_methods": [
            {
                "id": "development_account",
                "label": "账号登录（开发环境）",
                "login_path": "/api/auth/token",
            }
        ],
    }

    _configure_feishu(monkeypatch)
    _disable_oidc(monkeypatch)
    enterprise = client.get("/api/auth/config")
    assert enterprise.status_code == 200
    body = enterprise.json()
    assert body["auth_enabled"] is True
    assert body["mode"] == "enterprise"
    assert body["login_methods"] == [
        {"id": "feishu", "label": "飞书登录", "login_path": "/api/auth/feishu/login"}
    ]
    assert "server-only-secret" not in json.dumps(body)


def test_provider_readiness_requires_credentials_and_a_tenant_boundary(monkeypatch) -> None:
    _disable_feishu(monkeypatch)
    _disable_oidc(monkeypatch)
    assert auth.is_feishu_login_configured() is False
    assert auth.is_oidc_login_configured() is False

    _configure_oidc(monkeypatch)
    assert auth.is_oidc_login_configured() is True

    monkeypatch.setattr(settings, "FEISHU_APP_ID", "cli_test")
    monkeypatch.setattr(settings, "FEISHU_APP_SECRET", "server-only-secret")
    monkeypatch.setattr(settings, "FEISHU_REDIRECT_URI", "https://app.example.com/login/callback")
    assert auth.is_feishu_login_configured() is False
    monkeypatch.setattr(settings, "FEISHU_ALLOWED_TENANT_KEYS", ["approved-company"])
    assert auth.is_feishu_login_configured() is True


def test_production_rejects_non_https_external_login_urls(monkeypatch) -> None:
    _configure_oidc(monkeypatch)
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "ENABLE_AUTH", True)
    monkeypatch.setattr(settings, "OIDC_ISSUER_URL", "http://id.example.com")
    monkeypatch.setattr(settings, "OIDC_REDIRECT_URI", "http://app.example.com/login/callback")

    with pytest.raises(RuntimeError, match="OIDC_ISSUER_URL 必须使用 HTTPS"):
        main._validate_production_security()


def test_login_state_cookie_is_httponly_lax_and_secure_in_production(monkeypatch) -> None:
    authorization_url = "https://provider.example/authorize?state=feishu.one-time-state"
    response = Response()
    monkeypatch.setattr(settings, "APP_ENV", "development")
    auth_api._set_login_state_cookie(response, authorization_url)
    development_cookie = response.headers["set-cookie"].lower()
    assert "httponly" in development_cookie
    assert "samesite=lax" in development_cookie
    assert "max-age=600" in development_cookie
    assert "secure" not in development_cookie

    response = Response()
    monkeypatch.setattr(settings, "APP_ENV", "production")
    auth_api._set_login_state_cookie(response, authorization_url)
    assert "secure" in response.headers["set-cookie"].lower()


def test_starting_feishu_login_binds_state_to_the_browser(client, monkeypatch) -> None:
    _configure_feishu(monkeypatch)

    async def fake_begin_feishu_login() -> str:
        return "https://accounts.feishu.cn/open-apis/authen/v1/authorize?state=feishu.one-time-state"

    monkeypatch.setattr(auth_api, "begin_feishu_login", fake_begin_feishu_login)
    response = client.post("/api/auth/feishu/login")

    assert response.status_code == 200
    assert response.json()["authorization_url"].endswith("state=feishu.one-time-state")
    set_cookie = response.headers["set-cookie"].lower()
    assert "shelook_login_state=feishu.one-time-state" in set_cookie
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie


def test_shared_callback_rejects_unbound_state_and_clears_bound_state(client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "ENABLE_AUTH", True)
    completed: list[tuple[str, str]] = []
    expected_user = auth.UserInfo(
        user_id="feishu:open-id",
        username="Invited member",
        role="viewer",
        tenant_id="tenant-local",
    )

    async def fake_complete_enterprise_login(code: str, state: str, _db):
        completed.append((code, state))
        return "signed-token", expected_user

    monkeypatch.setattr(auth_api, "complete_enterprise_login", fake_complete_enterprise_login)

    denied = client.post(
        "/api/auth/callback", json={"code": "code", "state": "feishu.one-time-state"}
    )
    assert denied.status_code == 400
    assert completed == []

    mismatch = client.post(
        "/api/auth/callback",
        json={"code": "code", "state": "feishu.one-time-state"},
        headers={"Cookie": "shelook_login_state=feishu.different-state"},
    )
    assert mismatch.status_code == 400
    assert completed == []

    accepted = client.post(
        "/api/auth/callback",
        json={"code": "code", "state": "feishu.one-time-state"},
        headers={"Cookie": "shelook_login_state=feishu.one-time-state"},
    )
    assert accepted.status_code == 200
    assert accepted.json()["access_token"] == "signed-token"
    assert completed == [("code", "feishu.one-time-state")]
    assert "max-age=0" in accepted.headers["set-cookie"].lower()


def test_feishu_authorization_uses_state_namespace_and_no_client_secret(mock_redis, monkeypatch) -> None:
    _configure_feishu(monkeypatch)

    authorization_url = asyncio.run(auth.begin_feishu_login())
    parsed = urlparse(authorization_url)
    query = parse_qs(parsed.query)

    assert parsed.scheme == "https"
    assert parsed.netloc == "accounts.feishu.cn"
    assert parsed.path == "/open-apis/authen/v1/authorize"
    assert query["client_id"] == ["cli_test"]
    assert query["redirect_uri"] == ["https://app.example.com/login/callback"]
    assert query["scope"] == ["auth:user.id:read"]
    assert query["state"][0].startswith("feishu.")
    assert "server-only-secret" not in authorization_url

    state_key, ttl, raw_session = mock_redis.setex.await_args.args
    assert state_key == f"auth:state:feishu:{query['state'][0]}"
    assert ttl == 600
    session = json.loads(raw_session)
    assert session["provider"] == "feishu"
    assert isinstance(session["created_at"], int)


def test_external_tenant_values_cannot_select_local_tenants(monkeypatch) -> None:
    monkeypatch.setattr(settings, "DEFAULT_TENANT_ID", "default")
    monkeypatch.setattr(settings, "FEISHU_TENANT_KEY_MAP", {"known": "tenant-a"})
    monkeypatch.setattr(settings, "FEISHU_ALLOWED_TENANT_KEYS", ["single-tenant-company"])

    assert auth._resolve_feishu_tenant("known") == "tenant-a"
    with pytest.raises(HTTPException, match="未获准"):
        auth._resolve_feishu_tenant("single-tenant-company")
    with pytest.raises(HTTPException, match="未获准"):
        auth._resolve_feishu_tenant("attacker-controlled")
    monkeypatch.setattr(settings, "FEISHU_TENANT_KEY_MAP", {})
    assert auth._resolve_feishu_tenant("single-tenant-company") == "default"

    monkeypatch.setattr(settings, "OIDC_TENANT_CLAIM", "organization")
    monkeypatch.setattr(settings, "OIDC_TENANT_CLAIM_MAP", {})
    assert auth._resolve_oidc_tenant({"organization": "untrusted-idp-value"}) == "default"
    monkeypatch.setattr(settings, "OIDC_TENANT_CLAIM_MAP", {"idp-tenant": "tenant-b"})
    assert auth._resolve_oidc_tenant({"organization": "idp-tenant"}) == "tenant-b"
    with pytest.raises(HTTPException, match="未获准"):
        auth._resolve_oidc_tenant({"organization": "another-idp-value"})
    with pytest.raises(HTTPException, match="未获准"):
        auth._resolve_oidc_tenant({})


def test_active_local_membership_controls_role_and_permissions() -> None:
    membership = SimpleNamespace(
        role="operator",
        display_name="Local member name",
        permissions=["custom:approve"],
        unit_ids=["unit-1"],
    )

    class FakeDatabase:
        async def get(self, model, tenant_id):
            assert model.__name__ == "Tenant"
            assert tenant_id == "tenant-local"
            return SimpleNamespace(status="active")

        async def scalar(self, statement):
            assert statement is not None
            return membership

    user = asyncio.run(
        auth._load_active_tenant_member(
            FakeDatabase(),
            tenant_id="tenant-local",
            user_id="feishu:open-id",
            display_name="Feishu name",
        )
    )

    assert user.user_id == "feishu:open-id"
    assert user.username == "Feishu name"
    assert user.role == "operator"
    assert user.permissions == ("custom:approve",)
    assert user.unit_ids == ("unit-1",)


def test_uninvited_external_member_is_rejected() -> None:
    class FakeDatabase:
        async def get(self, _model, _tenant_id):
            return SimpleNamespace(status="active")

        async def scalar(self, _statement):
            return None

    with pytest.raises(HTTPException, match="尚未获邀") as error:
        asyncio.run(
            auth._load_active_tenant_member(
                FakeDatabase(),
                tenant_id="tenant-local",
                user_id="external-user",
                display_name="External user",
            )
        )
    assert error.value.status_code == 403


def test_shared_callback_dispatches_by_state_namespace(monkeypatch) -> None:
    expected_user = auth.UserInfo(user_id="feishu:open-id", tenant_id="tenant-local")

    async def fake_feishu_callback(code: str, state: str, db):
        assert code == "code"
        assert state == "feishu.one-time-state"
        assert db == "db-session"
        return "token", expected_user

    monkeypatch.setattr(auth, "complete_feishu_login", fake_feishu_callback)
    token, user = asyncio.run(
        auth.complete_enterprise_login("code", "feishu.one-time-state", "db-session")
    )

    assert token == "token"
    assert user is expected_user


def test_feishu_callback_uses_verified_profile_and_local_membership(mock_redis, monkeypatch) -> None:
    _configure_feishu(monkeypatch)
    mock_redis.getdel.return_value = json.dumps({"provider": "feishu"})
    requests: list[tuple[str, str, dict]] = []

    class FakeResponse:
        def __init__(self, payload: dict) -> None:
            self.payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return self.payload

    class FakeFeishuClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> None:
            return None

        async def post(self, url: str, **kwargs):
            requests.append(("post", url, kwargs))
            return FakeResponse({"code": 0, "access_token": "provider-token"})

        async def get(self, url: str, **kwargs):
            requests.append(("get", url, kwargs))
            return FakeResponse(
                {
                    "code": 0,
                    "data": {
                        "open_id": "open-id",
                        "tenant_key": "tenant-key",
                        "name": "飞书成员",
                    },
                }
            )

    class FakeDatabase:
        async def get(self, _model, _tenant_id):
            return SimpleNamespace(status="active")

        async def scalar(self, _statement):
            return SimpleNamespace(
                role="reviewer",
                display_name="已邀请成员",
                permissions=["review:decide"],
                unit_ids=["review-team"],
            )

    monkeypatch.setattr(auth.httpx, "AsyncClient", lambda **_kwargs: FakeFeishuClient())
    token, user = asyncio.run(
        auth.complete_feishu_login("authorization-code", "feishu.valid-state", FakeDatabase())
    )

    assert token
    assert user.user_id == "feishu:open-id"
    assert user.role == "reviewer"
    assert user.permissions == ("review:decide",)
    assert requests[0][1] == "https://open.feishu.cn/open-apis/authen/v2/oauth/token"
    assert requests[0][2]["json"]["client_secret"] == "server-only-secret"
    assert requests[1][2]["headers"]["Authorization"] == "Bearer provider-token"
