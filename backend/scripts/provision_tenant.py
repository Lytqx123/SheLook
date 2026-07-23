"""Provision one SheLook tenant and its first enterprise administrator.

This module is intentionally a deployment-only command.  It does not expose
an HTTP endpoint and it never derives a tenant or role from an external login
claim.  Run it after database migrations and before the first invited user
signs in through Feishu or enterprise OIDC.

Examples
--------
python -m scripts.provision_tenant \
  --tenant-id acme-prod --slug acme --name "Acme Commerce" \
  --admin-identity-provider feishu --admin-subject "ou_xxxxxxxxx" \
  --admin-display-name "Acme Admin" \
  --confirm

For generic OIDC, ``--admin-subject`` must be the provider's exact ``sub``
claim. The command derives the canonical local membership key, so a raw OIDC
subject can never collide with a Feishu account.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from dataclasses import asdict, dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.core.external_identity import enterprise_member_user_id
from app.core.tenant import tenant_context
from app.db.session import async_session_factory
from app.models.organization import Tenant, TenantMembership, TenantQuota

_TENANT_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,35}")
_TENANT_SLUG_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")


class ProvisioningSafetyError(RuntimeError):
    """A requested bootstrap would conflict with already-managed data."""


@dataclass(frozen=True, slots=True)
class TenantProvisionRequest:
    """Validated, explicit input for the controlled tenant bootstrap command."""

    tenant_id: str
    slug: str
    name: str
    admin_identity_provider: str
    admin_subject: str
    admin_user_id: str
    admin_display_name: str

    @classmethod
    def from_values(
        cls,
        *,
        tenant_id: str,
        slug: str,
        name: str,
        admin_identity_provider: str,
        admin_subject: str,
        admin_display_name: str,
    ) -> TenantProvisionRequest:
        normalized_tenant_id = _required_value("tenant_id", tenant_id, max_length=36)
        if not _TENANT_ID_PATTERN.fullmatch(normalized_tenant_id):
            raise ValueError(
                "tenant_id must use 1-36 ASCII letters, digits, dots, underscores, or hyphens"
            )

        normalized_slug = _required_value("slug", slug, max_length=64)
        if not _TENANT_SLUG_PATTERN.fullmatch(normalized_slug):
            raise ValueError(
                "slug must use lowercase letters, digits, or hyphens and start with a letter or digit"
            )

        normalized_name = _required_value("name", name, max_length=128)
        normalized_provider = _required_value(
            "admin_identity_provider", admin_identity_provider, max_length=16
        ).lower()
        try:
            normalized_admin_user_id = enterprise_member_user_id(
                normalized_provider,
                admin_subject,
                oidc_issuer_url=settings.OIDC_ISSUER_URL,
            )
        except ValueError as exc:
            raise ValueError(f"invalid administrator external identity: {exc}") from exc
        normalized_display_name = _required_value(
            "admin_display_name", admin_display_name, max_length=128
        )
        return cls(
            tenant_id=normalized_tenant_id,
            slug=normalized_slug,
            name=normalized_name,
            admin_identity_provider=normalized_provider,
            admin_subject=admin_subject.strip(),
            admin_user_id=normalized_admin_user_id,
            admin_display_name=normalized_display_name,
        )

    @property
    def identity_provider(self) -> str:
        return self.admin_identity_provider


@dataclass(frozen=True, slots=True)
class TenantProvisionResult:
    """Non-sensitive outcome suitable for deployment logs."""

    tenant_id: str
    slug: str
    identity_provider: str
    member_user_id: str
    dry_run: bool
    tenant_created: bool
    quota_created: bool
    admin_membership_created: bool


def _required_value(field_name: str, value: str, *, max_length: int) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    if len(normalized) > max_length:
        raise ValueError(f"{field_name} must not exceed {max_length} characters")
    return normalized


def _validate_existing_tenant(tenant: Tenant, request: TenantProvisionRequest) -> None:
    if tenant.slug != request.slug:
        raise ProvisioningSafetyError(
            f"tenant_id {request.tenant_id!r} already belongs to slug {tenant.slug!r}; refusing to rewrite it"
        )
    if tenant.name != request.name:
        raise ProvisioningSafetyError(
            f"tenant_id {request.tenant_id!r} already has a different name; refusing to rewrite it"
        )
    if tenant.status != "active":
        raise ProvisioningSafetyError(
            f"tenant_id {request.tenant_id!r} is {tenant.status!r}; activate it through the approved operation first"
        )


def _validate_existing_admin(member: TenantMembership, request: TenantProvisionRequest) -> None:
    if not member.is_active:
        raise ProvisioningSafetyError(
            "the requested administrator already exists but is inactive; refusing to reactivate it"
        )
    if member.role != "admin":
        raise ProvisioningSafetyError(
            "the requested administrator already exists with a non-admin role; refusing to escalate it"
        )
    if "tenant:manage" not in (member.permissions or []):
        raise ProvisioningSafetyError(
            "the requested administrator is missing tenant:manage; refusing to change managed permissions"
        )


async def provision_tenant(
    request: TenantProvisionRequest,
    *,
    dry_run: bool = False,
) -> TenantProvisionResult:
    """Create or safely validate a tenant, quota, and first active admin membership.

    The tenant context is installed *before* the database transaction begins.
    This is important on PostgreSQL: the RLS policy reads ``app.tenant_id`` at
    transaction start, so opening the session outside this scope would be a
    privilege bypass or would fail closed under RLS.

    Re-running the exact command is idempotent.  Existing data is never
    rewritten: mismatched tenant metadata, a non-admin target membership, or a
    tenant that already has a different first member all fail safely.
    """

    try:
        # Tenant itself is deliberately not RLS-scoped, but every tenant-owned
        # table below is accessed in this explicit scope.  Keeping the whole
        # operation in one transaction also prevents a partially bootstrapped
        # tenant when a child insert fails.
        with tenant_context(
            request.tenant_id,
            user_id=request.admin_user_id,
            source="tenant-bootstrap",
        ):
            async with async_session_factory() as session:
                async with session.begin():
                    tenant = await session.get(Tenant, request.tenant_id)
                    tenant_created = tenant is None
                    if tenant is None:
                        slug_owner = await session.scalar(
                            select(Tenant).where(Tenant.slug == request.slug)
                        )
                        if slug_owner is not None:
                            raise ProvisioningSafetyError(
                                f"slug {request.slug!r} is already assigned to tenant_id {slug_owner.id!r}"
                            )
                        if not dry_run:
                            session.add(
                                Tenant(
                                    id=request.tenant_id,
                                    slug=request.slug,
                                    name=request.name,
                                    status="active",
                                )
                            )
                    else:
                        _validate_existing_tenant(tenant, request)

                    quota = await session.get(TenantQuota, request.tenant_id)
                    quota_created = quota is None
                    if quota is None and not dry_run:
                        session.add(TenantQuota(tenant_id=request.tenant_id))

                    membership = await session.scalar(
                        select(TenantMembership).where(
                            TenantMembership.tenant_id == request.tenant_id,
                            TenantMembership.user_id == request.admin_user_id,
                        )
                    )
                    admin_membership_created = membership is None
                    if membership is None:
                        other_membership_id = await session.scalar(
                            select(TenantMembership.id)
                            .where(TenantMembership.tenant_id == request.tenant_id)
                            .limit(1)
                        )
                        if other_membership_id is not None:
                            raise ProvisioningSafetyError(
                                "tenant already has memberships but the requested administrator is absent; "
                                "refusing to infer a new first administrator"
                            )
                        if not dry_run:
                            session.add(
                                TenantMembership(
                                    tenant_id=request.tenant_id,
                                    user_id=request.admin_user_id,
                                    display_name=request.admin_display_name,
                                    role="admin",
                                    permissions=["tenant:manage"],
                                    unit_ids=[],
                                    is_active=True,
                                )
                            )
                    else:
                        _validate_existing_admin(membership, request)

                    if not dry_run:
                        # Surface uniqueness/foreign-key violations while the
                        # transaction and RLS context are still active.
                        await session.flush()
    except IntegrityError as exc:
        raise ProvisioningSafetyError(
            "tenant bootstrap conflicted with concurrent or inconsistent data; inspect it and rerun"
        ) from exc

    return TenantProvisionResult(
        tenant_id=request.tenant_id,
        slug=request.slug,
        identity_provider=request.identity_provider,
        member_user_id=request.admin_user_id,
        dry_run=dry_run,
        tenant_created=tenant_created,
        quota_created=quota_created,
        admin_membership_created=admin_membership_created,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", required=True, help="Stable local tenant identifier (1-36 chars)")
    parser.add_argument("--slug", required=True, help="Stable lowercase tenant slug")
    parser.add_argument("--name", required=True, help="Human-readable tenant name")
    parser.add_argument(
        "--admin-identity-provider",
        required=True,
        choices=("feishu", "oidc"),
        help="Enterprise identity provider for the first administrator",
    )
    parser.add_argument(
        "--admin-subject",
        required=True,
        help="Feishu open_id or the exact raw OIDC sub claim",
    )
    parser.add_argument("--admin-display-name", required=True, help="Initial administrator display name")
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Required before the command can write tenant data",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate current state and print planned changes without writing",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not args.confirm and not args.dry_run:
        parser.error("--confirm is required for writes; use --dry-run for a read-only validation")
    if args.confirm and args.dry_run:
        parser.error("--confirm and --dry-run cannot be used together")

    try:
        request = TenantProvisionRequest.from_values(
            tenant_id=args.tenant_id,
            slug=args.slug,
            name=args.name,
            admin_identity_provider=args.admin_identity_provider,
            admin_subject=args.admin_subject,
            admin_display_name=args.admin_display_name,
        )
        result = asyncio.run(provision_tenant(request, dry_run=args.dry_run))
    except (ProvisioningSafetyError, ValueError) as exc:
        print(f"tenant provisioning refused: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(asdict(result), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
