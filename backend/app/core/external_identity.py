"""Stable, provider-scoped local identifiers for external enterprise identities."""

from __future__ import annotations

import hashlib
import re

MAX_EXTERNAL_SUBJECT_LENGTH = 1_024
_FEISHU_OPEN_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,120}")


def normalize_external_subject(value: str, *, max_length: int = MAX_EXTERNAL_SUBJECT_LENGTH) -> str:
    """Keep signed provider subjects opaque while rejecting unsafe control data."""
    subject = str(value).strip()
    if not subject:
        raise ValueError("external identity subject must not be empty")
    if len(subject) > max_length:
        raise ValueError(f"external identity subject must not exceed {max_length} characters")
    if any(ord(char) < 32 for char in subject):
        raise ValueError("external identity subject must not contain control characters")
    return subject


def feishu_member_user_id(open_id: str) -> str:
    """Build the canonical local key for one Feishu open_id."""
    normalized_open_id = normalize_external_subject(open_id, max_length=120)
    if not _FEISHU_OPEN_ID_PATTERN.fullmatch(normalized_open_id):
        raise ValueError("Feishu open_id has an unsupported format")
    return f"feishu:{normalized_open_id}"


def oidc_member_user_id(issuer_url: str, subject: str) -> str:
    """Build an opaque local OIDC key scoped to both issuer and subject.

    Hashing the pair prevents a generic OIDC `sub` from colliding with a
    Feishu key (or a subject from another OIDC issuer) while keeping the local
    membership column bounded and avoiding persistence of the raw subject.
    """
    issuer = str(issuer_url).strip().rstrip("/")
    if not issuer:
        raise ValueError("OIDC issuer must be configured before inviting members")
    normalized_subject = normalize_external_subject(subject)
    digest = hashlib.sha256(f"{issuer}\x1f{normalized_subject}".encode()).hexdigest()
    return f"oidc:{digest}"


def enterprise_member_user_id(
    provider: str,
    subject: str,
    *,
    oidc_issuer_url: str,
) -> str:
    """Return the only local key accepted for an external provider identity."""
    normalized_provider = provider.strip().lower()
    if normalized_provider == "feishu":
        return feishu_member_user_id(subject)
    if normalized_provider == "oidc":
        return oidc_member_user_id(oidc_issuer_url, subject)
    raise ValueError("identity provider must be feishu or oidc")
