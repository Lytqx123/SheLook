"""Regression coverage for Web-managed external provider credential validation."""

import pytest

from app.services.provider_config_service import (
    PROVIDER_DEFINITIONS,
    normalize_provider_credentials,
    normalize_provider_settings,
)


def test_all_web_managed_provider_definitions_have_credential_contracts() -> None:
    assert {"kling", "runway", "replicate", "gemini", "shopee", "amazon"}.issubset(
        PROVIDER_DEFINITIONS
    )
    assert all(definition.credential_groups for definition in PROVIDER_DEFINITIONS.values())


def test_kling_accepts_api_key_or_complete_jwt_pair() -> None:
    assert normalize_provider_credentials("kling", {"api_key": "key"}) == {"api_key": "key"}
    assert normalize_provider_credentials(
        "kling", {"access_key": "access", "secret_key": "secret"}
    ) == {"access_key": "access", "secret_key": "secret"}
    with pytest.raises(ValueError, match="凭据不完整"):
        normalize_provider_credentials("kling", {"access_key": "access"})


def test_provider_settings_reject_unknown_fields_and_invalid_urls() -> None:
    with pytest.raises(ValueError, match="不支持配置字段"):
        normalize_provider_settings("runway", {"token": "not-a-setting"})
    with pytest.raises(ValueError, match="HTTPS URL"):
        normalize_provider_settings("gemini", {"api_base_url": "http://insecure.example"})
    assert normalize_provider_settings(
        "amazon", {"region": "EU", "marketplace_id": "A1PA6795UKMFR9"}
    ) == {"region": "eu", "marketplace_id": "A1PA6795UKMFR9"}
