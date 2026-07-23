"""Tenant-admin APIs for explicit external mappings and real CTR facts."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.integrations import require_integration_manager
from app.core.auth import UserInfo
from app.db.session import get_db
from app.models.enterprise_data import (
    CommerceFact,
    ExternalEntityMapping,
    ModelFeedbackLabel,
    PerformanceFact,
)
from app.models.image import GeneratedImage
from app.models.product import Product
from app.schemas.enterprise_data import (
    CTRFeedbackSummary,
    EnterpriseDataQualitySummary,
    ExternalEntityMappingResponse,
    ExternalEntityMappingUpsert,
    PerformanceFactBatch,
    PerformanceFactBatchResponse,
)
from app.services.ctr_feedback import (
    InvalidPerformanceMapping,
    create_mature_feedback_labels,
    payload_hash,
    resolve_performance_mapping,
)

router = APIRouter(prefix="/api/enterprise-data", tags=["Enterprise data"])


def _mapping_response(mapping: ExternalEntityMapping) -> ExternalEntityMappingResponse:
    return ExternalEntityMappingResponse(
        id=mapping.id,
        provider=mapping.provider,
        connection_key=mapping.connection_key,
        entity_type=mapping.entity_type,
        external_id=mapping.external_id,
        shop_reference=mapping.shop_reference,
        marketplace=mapping.marketplace,
        external_sku=mapping.external_sku,
        product_id=mapping.product_id,
        image_id=mapping.image_id,
        mapping_method=mapping.mapping_method,
        metadata=mapping.metadata_json,
        status=mapping.status,
        created_by=mapping.created_by,
        updated_by=mapping.updated_by,
        created_at=mapping.created_at,
        updated_at=mapping.updated_at,
    )


@router.get("/mappings", response_model=list[ExternalEntityMappingResponse])
async def list_entity_mappings(
    provider: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: UserInfo = Depends(require_integration_manager),
) -> list[ExternalEntityMappingResponse]:
    query = select(ExternalEntityMapping).order_by(ExternalEntityMapping.updated_at.desc())
    if provider:
        query = query.where(ExternalEntityMapping.provider == provider)
    mappings = (await db.execute(query.limit(1_000))).scalars()
    return [_mapping_response(mapping) for mapping in mappings]


@router.get("/quality", response_model=EnterpriseDataQualitySummary)
async def get_enterprise_data_quality(
    db: AsyncSession = Depends(get_db),
    _user: UserInfo = Depends(require_integration_manager),
) -> EnterpriseDataQualitySummary:
    """Compact operational view: missing mappings never masquerade as usable CTR evidence."""
    async def count(model, *conditions) -> int:
        return int((await db.scalar(select(func.count()).select_from(model).where(*conditions))) or 0)

    return EnterpriseDataQualitySummary(
        mappings_total=await count(ExternalEntityMapping),
        mappings_pending=await count(ExternalEntityMapping, ExternalEntityMapping.status != "mapped"),
        commerce_facts_total=await count(CommerceFact),
        performance_facts_total=await count(PerformanceFact),
        performance_facts_pending_mapping=await count(
            PerformanceFact, PerformanceFact.quality_status != "mapped"
        ),
        performance_facts_mature=await count(
            PerformanceFact,
            PerformanceFact.quality_status == "mapped",
            PerformanceFact.is_mature.is_(True),
        ),
        feedback_labels_total=await count(ModelFeedbackLabel),
    )


@router.put("/mappings", response_model=ExternalEntityMappingResponse)
async def upsert_entity_mapping(
    body: ExternalEntityMappingUpsert,
    db: AsyncSession = Depends(get_db),
    user: UserInfo = Depends(require_integration_manager),
) -> ExternalEntityMappingResponse:
    if body.product_id is not None and await db.get(Product, body.product_id) is None:
        raise HTTPException(status_code=422, detail="关联商品不存在或不属于当前租户")
    if body.image_id is not None and await db.get(GeneratedImage, body.image_id) is None:
        raise HTTPException(status_code=422, detail="关联图片不存在或不属于当前租户")
    mapping = await db.scalar(
        select(ExternalEntityMapping).where(
            ExternalEntityMapping.provider == body.provider,
            ExternalEntityMapping.connection_key == body.connection_key,
            ExternalEntityMapping.entity_type == body.entity_type,
            ExternalEntityMapping.external_id == body.external_id,
        )
    )
    payload = body.model_dump(by_alias=False)
    if mapping is None:
        mapping = ExternalEntityMapping(
            tenant_id=user.tenant_id,
            provider=payload["provider"],
            connection_key=payload["connection_key"],
            entity_type=payload["entity_type"],
            external_id=payload["external_id"],
            shop_reference=payload["shop_reference"],
            marketplace=payload["marketplace"],
            external_sku=payload["external_sku"],
            product_id=payload["product_id"],
            image_id=payload["image_id"],
            mapping_method=payload["mapping_method"],
            metadata_json=payload["metadata"],
            status="mapped" if payload["image_id"] else "pending_mapping",
            created_by=user.user_id,
            updated_by=user.user_id,
        )
        db.add(mapping)
    else:
        for source, target in (
            ("shop_reference", "shop_reference"), ("marketplace", "marketplace"),
            ("external_sku", "external_sku"), ("product_id", "product_id"),
            ("image_id", "image_id"), ("mapping_method", "mapping_method"),
            ("metadata", "metadata_json"),
        ):
            setattr(mapping, target, payload[source])
        mapping.status = "mapped" if mapping.image_id else "pending_mapping"
        mapping.updated_by = user.user_id
    await db.flush()
    await db.refresh(mapping)
    return _mapping_response(mapping)


@router.post("/performance-facts/batch", response_model=PerformanceFactBatchResponse)
async def import_performance_facts(
    body: PerformanceFactBatch,
    db: AsyncSession = Depends(get_db),
    user: UserInfo = Depends(require_integration_manager),
) -> PerformanceFactBatchResponse:
    upserted = pending_mapping = mature = 0
    now = datetime.now(UTC).replace(tzinfo=None)
    for item in body.items:
        try:
            mapping_id, image_id, quality_status = await resolve_performance_mapping(
                db,
                tenant_id=user.tenant_id,
                mapping_id=item.mapping_id,
                image_id=item.image_id,
            )
        except InvalidPerformanceMapping as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if image_id is not None and await db.get(GeneratedImage, image_id) is None:
            raise HTTPException(status_code=422, detail=f"图片 #{image_id} 不存在或不属于当前租户")
        item_data = item.model_dump(mode="json")
        is_mature = item.data_mature_at is not None and item.data_mature_at <= now
        existing = await db.scalar(
            select(PerformanceFact).where(
                PerformanceFact.source_name == item.source_name,
                PerformanceFact.source_record_id == item.source_record_id,
            )
        )
        values = {
            "metric_date": item.metric_date,
            "shop_reference": item.shop_reference,
            "marketplace": item.marketplace,
            "external_listing_id": item.external_listing_id,
            "mapping_id": mapping_id,
            "image_id": image_id,
            "impressions": item.impressions,
            "clicks": item.clicks,
            "orders": item.orders,
            "revenue": item.revenue,
            "currency": item.currency,
            "source_updated_at": item.source_updated_at,
            "data_mature_at": item.data_mature_at,
            "is_mature": is_mature,
            "quality_status": quality_status,
            "metric_definition_version": item.metric_definition_version,
            "source_payload_hash": payload_hash(item_data),
        }
        if existing is None:
            db.add(PerformanceFact(tenant_id=user.tenant_id, source_name=item.source_name, source_record_id=item.source_record_id, **values))
        else:
            for field, value in values.items():
                setattr(existing, field, value)
        upserted += 1
        pending_mapping += int(quality_status != "mapped")
        mature += int(is_mature and quality_status == "mapped")
    return PerformanceFactBatchResponse(
        total=len(body.items), upserted=upserted, pending_mapping=pending_mapping, mature=mature
    )


@router.post("/ctr-feedback/refresh", response_model=CTRFeedbackSummary)
async def refresh_ctr_feedback_labels(
    db: AsyncSession = Depends(get_db),
    user: UserInfo = Depends(require_integration_manager),
) -> CTRFeedbackSummary:
    result = await create_mature_feedback_labels(db, tenant_id=user.tenant_id)
    return CTRFeedbackSummary(**result)
