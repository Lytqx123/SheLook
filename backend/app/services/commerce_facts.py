"""Idempotent application of provider records to canonical commerce facts."""

import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enterprise_data import CommerceFact
from app.services.dianxiaomi_adapter import ProviderFact


def _hash_payload(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


async def upsert_commerce_fact(
    db: AsyncSession,
    *,
    tenant_id: str,
    provider: str,
    connection_key: str,
    sync_run_id: str,
    record: ProviderFact,
) -> bool:
    """Return true when a canonical current-state fact was inserted or changed."""
    fact = await db.scalar(
        select(CommerceFact).where(
            CommerceFact.provider == provider,
            CommerceFact.connection_key == connection_key,
            CommerceFact.entity_type == record.scope,
            CommerceFact.external_id == record.external_id,
        )
    )
    digest = _hash_payload(record.payload)
    now = datetime.now(UTC).replace(tzinfo=None)
    if fact is None:
        db.add(
            CommerceFact(
                tenant_id=tenant_id,
                provider=provider,
                connection_key=connection_key,
                sync_run_id=sync_run_id,
                shop_reference=record.shop_reference,
                marketplace=record.marketplace,
                entity_type=record.scope,
                external_id=record.external_id,
                source_updated_at=record.source_updated_at,
                occurred_at=record.occurred_at,
                payload_json=record.payload,
                payload_hash=digest,
                is_deleted=record.deleted,
                last_seen_at=now,
            )
        )
        return True
    changed = fact.payload_hash != digest or fact.is_deleted != record.deleted
    fact.sync_run_id = sync_run_id
    fact.shop_reference = record.shop_reference
    fact.marketplace = record.marketplace
    fact.source_updated_at = record.source_updated_at
    fact.occurred_at = record.occurred_at
    fact.payload_json = record.payload
    fact.payload_hash = digest
    fact.is_deleted = record.deleted
    fact.last_seen_at = now
    return changed
