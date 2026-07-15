"""数据指标 API —— 批量写入 + 导入统计 + 平台同步

所有写入端点需要 X-API-Key 鉴权，使用 secrets.compare_digest 防时序攻击。
"""

import secrets

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.auth import UserInfo, require_auth
from app.core.exceptions import NotFoundError, ValidationError
from app.core.logging import logger
from app.db.session import get_db
from app.models.external_listing import ExternalListingMapping
from app.models.image import GeneratedImage
from app.models.prediction import DailyMetric
from app.schemas.metrics import (
    ExternalListingMappingCreate,
    ExternalListingMappingOut,
    MetricsBatchRequest,
    MetricsBatchResponse,
    MetricsStatsResponse,
    MetricsSyncResponse,
    MetricsUpsertResult,
)

router = APIRouter(prefix="/api/metrics", tags=["Metrics"])


# ============================================================
# API Key 鉴权
# ============================================================

async def verify_metrics_api_key(
    x_api_key: str | None = Header(None, alias="X-API-Key", description="Metrics API Key"),
) -> str:
    """验证 Metrics API Key（使用 secrets.compare_digest 防时序攻击）

    配置项 METRICS_API_KEY 为空时跳过鉴权（仅开发环境）。
    """
    if not settings.METRICS_API_KEY:
        # 开发模式：未配置 API Key 时放行
        return "anonymous"

    if not secrets.compare_digest(x_api_key or "", settings.METRICS_API_KEY):
        logger.warning("Metrics API Key 验证失败")
        raise HTTPException(status_code=401, detail="无效的 API Key")

    return x_api_key or ""


# ============================================================
# 批量写入
# ============================================================

@router.post("/batch", response_model=MetricsBatchResponse)
async def batch_upsert_metrics(
    body: MetricsBatchRequest,
    db: AsyncSession = Depends(get_db),
    api_key: str = Depends(verify_metrics_api_key),
):
    """批量写入指标数据（upsert）

    使用 PostgreSQL INSERT ... ON CONFLICT (image_id, date) DO UPDATE
    实现幂等写入。单次最多 1000 条。

    请求头：
        X-API-Key: <metrics_api_key>

    请求体示例：
        {
            "items": [
                {
                    "image_id": 1,
                    "date": "2026-07-14",
                    "impressions": 5000,
                    "clicks": 150,
                    "ctr": 0.03,
                    "cvr": 0.05,
                    "add_to_cart_rate": 0.12,
                    "return_rate": 0.08,
                    "revenue": 1250.50
                }
            ]
        }
    """
    items = body.items
    total = len(items)
    upserted = 0
    failed = 0
    results: list[MetricsUpsertResult] = []

    for item in items:
        try:
            async with db.begin_nested():
                stmt = pg_insert(DailyMetric).values(
                    image_id=item.image_id,
                    date=item.date,
                    source_platform=item.source_platform,
                    impressions=item.impressions,
                    clicks=item.clicks,
                    ctr=item.ctr,
                    cvr=item.cvr,
                    add_to_cart_rate=item.add_to_cart_rate,
                    return_rate=item.return_rate,
                    revenue=item.revenue,
                ).on_conflict_do_update(
                    constraint="daily_metrics_image_date_platform_key",
                    set_={
                        "impressions": item.impressions,
                        "clicks": item.clicks,
                        "ctr": item.ctr,
                        "cvr": item.cvr,
                        "add_to_cart_rate": item.add_to_cart_rate,
                        "return_rate": item.return_rate,
                        "revenue": item.revenue,
                        "updated_at": func.now(),
                    },
                )

                await db.execute(stmt)
            upserted += 1
            results.append(MetricsUpsertResult(
                image_id=item.image_id,
                date=item.date,
                status="upserted",
            ))

        except Exception as e:
            logger.error(f"指标写入失败 image_id={item.image_id} date={item.date}: {e}")
            failed += 1
            results.append(MetricsUpsertResult(
                image_id=item.image_id,
                date=item.date,
                status="failed",
                error=str(e),
            ))

    await db.commit()

    logger.info("批量指标写入完成", total=total, upserted=upserted, failed=failed)

    return MetricsBatchResponse(
        total=total,
        upserted=upserted,
        failed=failed,
        results=results,
    )


# ============================================================
# 导入统计
# ============================================================

@router.get("/stats", response_model=MetricsStatsResponse)
async def get_metrics_stats(
    db: AsyncSession = Depends(get_db),
    user: UserInfo = Depends(require_auth),
):
    """查询导入统计：总记录数、日期范围、涉及图片数"""
    # 总记录数
    count_stmt = select(func.count(DailyMetric.id))
    total_records = (await db.execute(count_stmt)).scalar() or 0

    if total_records == 0:
        return MetricsStatsResponse(
            total_records=0,
            total_images=0,
        )

    # 涉及图片数
    images_stmt = select(func.count(func.distinct(DailyMetric.image_id)))
    total_images = (await db.execute(images_stmt)).scalar() or 0

    # 日期范围
    range_stmt = select(
        func.min(DailyMetric.date).label("earliest"),
        func.max(DailyMetric.date).label("latest"),
    )
    range_row = (await db.execute(range_stmt)).one_or_none()
    earliest_date = range_row.earliest if range_row else None
    latest_date = range_row.latest if range_row else None

    last_import_at = (await db.execute(select(func.max(DailyMetric.updated_at)))).scalar()

    return MetricsStatsResponse(
        total_records=total_records,
        total_images=total_images,
        earliest_date=earliest_date,
        latest_date=latest_date,
        last_import_at=last_import_at,
    )


# ============================================================
# 平台同步（Phase 2.2）
# ============================================================

@router.post("/sync/{platform}", response_model=MetricsSyncResponse)
async def sync_platform_metrics(
    platform: str,
    date_from: str | None = None,
    date_to: str | None = None,
    db: AsyncSession = Depends(get_db),
    api_key: str = Depends(verify_metrics_api_key),
):
    """手动触发指定平台的数据同步

    从平台 SDK 拉取指标数据后 upsert 到 daily_metrics 表。

    Args:
        platform: 平台标识 (shopee | lazada | amazon)
        date_from: 起始日期 YYYY-MM-DD（默认昨天）
        date_to: 结束日期 YYYY-MM-DD（默认今天）
    """
    from datetime import date, timedelta

    from app.services.metrics_collector import get_collector

    # 校验平台
    valid_platforms = {"shopee", "lazada", "amazon"}
    if platform not in valid_platforms:
        raise ValidationError(f"不支持的平台: {platform}，可选值: {', '.join(sorted(valid_platforms))}")

    # 日期范围
    today = date.today()
    d_from = date.fromisoformat(date_from) if date_from else today - timedelta(days=1)
    d_to = date.fromisoformat(date_to) if date_to else today

    if d_from > d_to:
        raise ValidationError("date_from 不能晚于 date_to")

    date_range_str = f"{d_from.isoformat()} ~ {d_to.isoformat()}"

    try:
        collector = get_collector(platform)
        try:
            raw_items = await collector.fetch_daily_metrics((d_from, d_to))
        finally:
            await collector.close()

        if not raw_items:
            return MetricsSyncResponse(
                platform=platform,
                status="success",
                date_range=date_range_str,
                records_fetched=0,
                message="无新数据",
            )

        external_ids = {item.external_id for item in raw_items}
        mapping_rows = (
            await db.execute(
                select(ExternalListingMapping).where(
                    ExternalListingMapping.platform == platform,
                    ExternalListingMapping.external_id.in_(external_ids),
                )
            )
        ).scalars().all()
        mappings = {row.external_id: row.image_id for row in mapping_rows}

        # 仅使用显式映射写入，绝不再用进程随机 hash 伪造 image_id。
        upserted = 0
        errors: list[str] = []
        for raw in raw_items:
            try:
                image_id = mappings.get(raw.external_id)
                if image_id is None:
                    errors.append(f"缺少 {platform} listing 映射: {raw.external_id}")
                    continue
                mapped = collector.map_to_internal_schema(raw, image_id)
                stmt = pg_insert(DailyMetric).values(
                    image_id=mapped.image_id,
                    date=mapped.date,
                    source_platform=mapped.source_platform,
                    impressions=mapped.impressions,
                    clicks=mapped.clicks,
                    ctr=mapped.ctr,
                    cvr=mapped.cvr,
                    add_to_cart_rate=mapped.add_to_cart_rate,
                    return_rate=mapped.return_rate,
                    revenue=mapped.revenue,
                ).on_conflict_do_update(
                    constraint="daily_metrics_image_date_platform_key",
                    set_={
                        "impressions": mapped.impressions,
                        "clicks": mapped.clicks,
                        "ctr": mapped.ctr,
                        "cvr": mapped.cvr,
                        "add_to_cart_rate": mapped.add_to_cart_rate,
                        "return_rate": mapped.return_rate,
                        "revenue": mapped.revenue,
                        "updated_at": func.now(),
                    },
                )
                await db.execute(stmt)
                upserted += 1
            except Exception as e:
                errors.append(f"写入失败 {raw.external_id}: {e}")

        await db.commit()

        status = "success" if len(errors) == 0 else ("failed" if upserted == 0 else "partial")

        logger.info(
            "平台数据同步完成",
            platform=platform,
            date_range=date_range_str,
            fetched=len(raw_items),
            upserted=upserted,
            errors=len(errors),
        )

        return MetricsSyncResponse(
            platform=platform,
            status=status,
            date_range=date_range_str,
            records_fetched=len(raw_items),
            records_upserted=upserted,
            errors=errors,
        )

    except Exception as e:
        logger.error(f"平台同步失败 platform={platform}: {e}")
        return MetricsSyncResponse(
            platform=platform,
            status="failed",
            date_range=date_range_str,
            errors=[str(e)],
        )


@router.get("/mappings", response_model=list[ExternalListingMappingOut])
async def list_external_mappings(
    platform: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: UserInfo = Depends(require_auth),
):
    query = select(ExternalListingMapping).order_by(ExternalListingMapping.updated_at.desc())
    if platform:
        query = query.where(ExternalListingMapping.platform == platform)
    return (await db.execute(query.limit(1000))).scalars().all()


@router.post("/mappings", response_model=ExternalListingMappingOut)
async def upsert_external_mapping(
    body: ExternalListingMappingCreate,
    db: AsyncSession = Depends(get_db),
    user: UserInfo = Depends(require_auth),
):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可维护平台映射")
    if not (await db.execute(select(GeneratedImage.id).where(GeneratedImage.id == body.image_id))).scalar_one_or_none():
        raise NotFoundError(detail=f"图片 #{body.image_id} 不存在")
    stmt = pg_insert(ExternalListingMapping).values(**body.model_dump()).on_conflict_do_update(
        constraint="uq_external_listing_platform_id",
        set_={"image_id": body.image_id, "updated_at": func.now()},
    ).returning(ExternalListingMapping)
    return (await db.execute(stmt)).scalar_one()


@router.delete("/mappings/{mapping_id}", status_code=204)
async def delete_external_mapping(
    mapping_id: int,
    db: AsyncSession = Depends(get_db),
    user: UserInfo = Depends(require_auth),
):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可维护平台映射")
    mapping = (
        await db.execute(select(ExternalListingMapping).where(ExternalListingMapping.id == mapping_id))
    ).scalar_one_or_none()
    if not mapping:
        raise NotFoundError(detail=f"平台映射 #{mapping_id} 不存在")
    await db.delete(mapping)
