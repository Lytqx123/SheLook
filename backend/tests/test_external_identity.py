"""Regression coverage for provider-scoped external membership keys."""

import pytest

from app.core.external_identity import (
    enterprise_member_user_id,
    feishu_member_user_id,
    oidc_member_user_id,
)


def test_oidc_subject_is_scoped_to_its_issuer_and_cannot_match_feishu() -> None:
    subject = "feishu:ou_same_string"

    issuer_a = oidc_member_user_id("https://id-a.example.com", subject)
    issuer_b = oidc_member_user_id("https://id-b.example.com", subject)
    feishu = feishu_member_user_id("ou_same_string")

    assert issuer_a.startswith("oidc:")
    assert issuer_a != issuer_b
    assert issuer_a != feishu
    assert issuer_b != feishu


def test_provider_scoped_key_is_stable_and_does_not_store_raw_oidc_subject() -> None:
    subject = "00u1-example-subject"

    first = enterprise_member_user_id(
        "oidc", subject, oidc_issuer_url="https://id.example.com/"
    )
    second = enterprise_member_user_id(
        "oidc", subject, oidc_issuer_url="https://id.example.com"
    )

    assert first == second
    assert subject not in first


def test_unknown_provider_and_invalid_feishu_open_id_are_rejected() -> None:
    with pytest.raises(ValueError):
        enterprise_member_user_id("unknown", "subject", oidc_issuer_url="https://id.example.com")
    with pytest.raises(ValueError):
        feishu_member_user_id("invalid open id")
