"""Regression checks for the controlled first-tenant-admin bootstrap input."""

import pytest

from app.config import settings
from app.core.external_identity import oidc_member_user_id
from app.models.organization import Tenant, TenantMembership
from scripts.migrate_oidc_membership import LegacyOIDCMembershipRequest
from scripts.provision_tenant import (
    ProvisioningSafetyError,
    TenantProvisionRequest,
    _validate_existing_admin,
    _validate_existing_tenant,
)


def _request(**overrides: str) -> TenantProvisionRequest:
    values = {
        "tenant_id": "acme-prod",
        "slug": "acme",
        "name": "Acme Commerce",
        "admin_identity_provider": "feishu",
        "admin_subject": "ou_abc123",
        "admin_display_name": "Acme Admin",
    }
    values.update(overrides)
    return TenantProvisionRequest.from_values(**values)


def test_bootstrap_request_keeps_feishu_identity_in_login_format() -> None:
    request = _request()

    assert request.admin_user_id == "feishu:ou_abc123"
    assert request.identity_provider == "feishu"


def test_bootstrap_request_scopes_raw_oidc_subject_to_issuer(monkeypatch) -> None:
    monkeypatch.setattr(settings, "OIDC_ISSUER_URL", "https://id.example.com")
    request = _request(
        admin_identity_provider="oidc",
        admin_subject="00u1example subject",
    )

    assert request.admin_user_id == oidc_member_user_id(
        "https://id.example.com", "00u1example subject"
    )
    assert request.identity_provider == "oidc"


@pytest.mark.parametrize(
    "admin_subject",
    ("", "not a valid open id", "contains:extra-separator"),
)
def test_bootstrap_request_rejects_invalid_feishu_identity(admin_subject: str) -> None:
    with pytest.raises(ValueError):
        _request(admin_subject=admin_subject)


def test_existing_tenant_metadata_is_not_rewritten() -> None:
    tenant = Tenant(id="acme-prod", slug="acme-other", name="Acme Commerce", status="active")

    with pytest.raises(ProvisioningSafetyError, match="refusing to rewrite"):
        _validate_existing_tenant(tenant, _request())


def test_existing_admin_must_retain_explicit_management_permission() -> None:
    member = TenantMembership(
        tenant_id="acme-prod",
        user_id="feishu:ou_abc123",
        display_name="Acme Admin",
        role="admin",
        permissions=[],
        unit_ids=[],
        is_active=True,
    )

    with pytest.raises(ProvisioningSafetyError, match="tenant:manage"):
        _validate_existing_admin(member, _request())


def test_legacy_oidc_migration_requires_configured_issuer(monkeypatch) -> None:
    monkeypatch.setattr(settings, "OIDC_ISSUER_URL", "https://id.example.com")

    request = LegacyOIDCMembershipRequest.from_values(
        tenant_id="acme-prod", raw_subject="legacy-user"
    )

    assert request.raw_subject == "legacy-user"
    assert request.canonical_user_id == oidc_member_user_id(
        "https://id.example.com", "legacy-user"
    )
