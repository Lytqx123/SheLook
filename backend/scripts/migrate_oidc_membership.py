"""Re-key one legacy raw-sub OIDC membership without an unsafe login fallback.

Older deployments that created memberships before provider-scoped OIDC keys
must run this controlled command once per invited OIDC user.  The login path
does not fall back to raw `sub` values, because doing so would reintroduce
cross-provider account confusion.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict, dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.core.auth import revoke_member_sessions
from app.core.external_identity import normalize_external_subject, oidc_member_user_id
from app.core.tenant import tenant_context
from app.db.session import async_session_factory
from app.models.organization import TenantMembership


class LegacyOIDCMembershipError(RuntimeError):
    """The explicit migration cannot safely update the requested membership."""


@dataclass(frozen=True, slots=True)
class LegacyOIDCMembershipRequest:
    tenant_id: str
    raw_subject: str
    canonical_user_id: str

    @classmethod
    def from_values(cls, *, tenant_id: str, raw_subject: str) -> LegacyOIDCMembershipRequest:
        normalized_tenant_id = tenant_id.strip()
        if not normalized_tenant_id or len(normalized_tenant_id) > 36:
            raise ValueError("tenant_id must contain 1-36 characters")
        normalized_subject = normalize_external_subject(raw_subject)
        canonical_user_id = oidc_member_user_id(
            settings.OIDC_ISSUER_URL,
            normalized_subject,
        )
        return cls(
            tenant_id=normalized_tenant_id,
            raw_subject=normalized_subject,
            canonical_user_id=canonical_user_id,
        )


@dataclass(frozen=True, slots=True)
class LegacyOIDCMembershipResult:
    tenant_id: str
    member_user_id: str
    dry_run: bool
    migrated: bool


async def migrate_legacy_oidc_membership(
    request: LegacyOIDCMembershipRequest,
    *,
    dry_run: bool = False,
) -> LegacyOIDCMembershipResult:
    """Atomically replace an explicitly confirmed raw subject with its canonical key."""
    try:
        with tenant_context(request.tenant_id, source="legacy-oidc-membership-migration"):
            async with async_session_factory() as session:
                async with session.begin():
                    legacy_member = await session.scalar(
                        select(TenantMembership).where(
                            TenantMembership.tenant_id == request.tenant_id,
                            TenantMembership.user_id == request.raw_subject,
                        )
                    )
                    if legacy_member is None:
                        raise LegacyOIDCMembershipError(
                            "no legacy raw-sub membership exists for the explicitly supplied subject"
                        )
                    canonical_member = await session.scalar(
                        select(TenantMembership).where(
                            TenantMembership.tenant_id == request.tenant_id,
                            TenantMembership.user_id == request.canonical_user_id,
                        )
                    )
                    if canonical_member is not None:
                        raise LegacyOIDCMembershipError(
                            "the canonical OIDC membership already exists; refusing to merge members"
                        )

                    if not dry_run:
                        # Revoke before commit so a production Redis outage rolls
                        # the key change back instead of leaving a legacy token live.
                        await revoke_member_sessions(
                            request.tenant_id,
                            request.raw_subject,
                            reason="legacy_oidc_identity_rekey",
                        )
                        legacy_member.user_id = request.canonical_user_id
                        await session.flush()
    except IntegrityError as exc:
        raise LegacyOIDCMembershipError(
            "legacy OIDC membership migration conflicted with concurrent data; inspect and retry"
        ) from exc

    return LegacyOIDCMembershipResult(
        tenant_id=request.tenant_id,
        member_user_id=request.canonical_user_id,
        dry_run=dry_run,
        migrated=not dry_run,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument(
        "--raw-subject",
        required=True,
        help="The exact legacy raw OIDC sub currently stored in tenant_memberships.user_id",
    )
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not args.confirm and not args.dry_run:
        parser.error("--confirm is required for writes; use --dry-run for validation")
    if args.confirm and args.dry_run:
        parser.error("--confirm and --dry-run cannot be used together")

    try:
        request = LegacyOIDCMembershipRequest.from_values(
            tenant_id=args.tenant_id,
            raw_subject=args.raw_subject,
        )
        result = asyncio.run(migrate_legacy_oidc_membership(request, dry_run=args.dry_run))
    except (LegacyOIDCMembershipError, ValueError) as exc:
        print(f"legacy OIDC membership migration refused: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(asdict(result), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
