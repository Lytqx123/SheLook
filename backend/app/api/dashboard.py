"""运营看板 API —— 总览 / CTR 趋势 / 市场对比 / 风格洞察"""

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, literal, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.core.tenant import get_current_tenant_id
from app.db.session import get_db
from app.models.enterprise_data import PerformanceFact
from app.models.image import GeneratedImage, ImageScheme, ReviewStatus
from app.models.prediction import DailyMetric, PredictionRecord
from app.models.product import Product
from app.services.dashboard_cache import get_summary_cache, set_summary_cache
from app.services.runtime_settings import get_effective_runtime_setting

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])


def _build_filtered_query(market: str | None, category: str | None):
    """构建带 market/category 筛选的 GeneratedImage 基础查询

    market 直接滤 GeneratedImage.market_variant，
    category 需要 JOIN ImageScheme → Product。
    """
    query = select(GeneratedImage)
    if market:
        query = query.where(GeneratedImage.market_variant == market)
    if category:
        query = query.join(ImageScheme, ImageScheme.id == GeneratedImage.scheme_id
                          ).join(Product, Product.id == ImageScheme.product_id
                                 ).where(Product.category == category)
    return query


@router.get("/summary")
async def get_summary(
    request: Request,
    db: AsyncSession = Depends(get_db),
    market: str | None = None,
    category: str | None = None,
):
    """运营总览 —— 累计指标，可筛 market / category"""
    tenant_id = get_current_tenant_id()
    ctr_baseline_setting = await get_effective_runtime_setting(
        db, tenant_id=tenant_id, setting_key="ctr.dashboard_baseline"
    )
    ctr_baseline = float(ctr_baseline_setting.value)
    cached = await get_summary_cache(
        tenant_id=tenant_id,
        market=market,
        category=category,
        runtime_config_version=ctr_baseline_setting.version,
    )
    if cached is not None:
        return cached

    base_query = _build_filtered_query(market, category)
    total_images = (await db.execute(
        select(func.count()).select_from(base_query.subquery())
    )).scalar() or 0

    approved_query = _build_filtered_query(market, category).where(
        GeneratedImage.review_status == ReviewStatus.AUTO_APPROVED
    )
    approved = (await db.execute(
        select(func.count()).select_from(approved_query.subquery())
    )).scalar() or 0

    # 待审数（给 manual_review_rate 用）
    manual_pending_query = _build_filtered_query(market, category).where(
        GeneratedImage.review_status == ReviewStatus.MANUAL_PENDING
    )
    manual_pending = (await db.execute(
        select(func.count()).select_from(manual_pending_query.subquery())
    )).scalar() or 0

    # 优先使用来源可追溯、已映射的真实效果事实；旧 DailyMetric 只作为兼容回退。
    metrics_query = select(
        func.sum(PerformanceFact.impressions),
        func.sum(PerformanceFact.clicks),
        literal(None),
        literal(None),
        func.sum(PerformanceFact.revenue),
    ).where(PerformanceFact.quality_status == "mapped")
    if market or category:
        metrics_query = metrics_query.join(
            GeneratedImage, GeneratedImage.id == PerformanceFact.image_id
        )
        if market:
            metrics_query = metrics_query.where(GeneratedImage.market_variant == market)
        if category:
            metrics_query = metrics_query.join(
                ImageScheme, ImageScheme.id == GeneratedImage.scheme_id
            ).join(Product, Product.id == ImageScheme.product_id
                   ).where(Product.category == category)

    row = (await db.execute(metrics_query)).one_or_none()
    if not int(row[0] or 0):
        metrics_query = select(
            func.sum(DailyMetric.impressions),
            func.sum(DailyMetric.clicks),
            (
                func.sum(DailyMetric.cvr * DailyMetric.clicks)
                / func.nullif(func.sum(DailyMetric.clicks), 0)
            ),
            func.avg(DailyMetric.return_rate),
            func.sum(DailyMetric.revenue),
        )
        if market or category:
            metrics_query = metrics_query.join(
                GeneratedImage, GeneratedImage.id == DailyMetric.image_id
            )
            if market:
                metrics_query = metrics_query.where(GeneratedImage.market_variant == market)
            if category:
                metrics_query = metrics_query.join(
                    ImageScheme, ImageScheme.id == GeneratedImage.scheme_id
                ).join(Product, Product.id == ImageScheme.product_id).where(
                    Product.category == category
                )
        row = (await db.execute(metrics_query)).one_or_none()
    total_impressions = int(row[0] or 0)
    total_clicks = int(row[1] or 0)
    avg_ctr = round(total_clicks / total_impressions, 4) if total_impressions else 0.0
    avg_cvr = round(float(row[2] or 0), 4)
    avg_return_rate = round(float(row[3] or 0), 4)
    total_revenue = round(float(row[4] or 0), 2)

    # 跟租户运行时配置基线的偏差，不是 A/B 实验 lift，别搞混
    ctr_vs_baseline = (
        round((avg_ctr - ctr_baseline) / ctr_baseline * 100, 2)
        if ctr_baseline > 0 and total_impressions > 0
        else None
    )

    # 高 CTR 预测命中率（简化：predicted_ctr > 0.05 算高）
    high_ctr_prediction_share = None
    try:
        hit_total = (await db.execute(select(func.count()).select_from(PredictionRecord))).scalar() or 0
        if hit_total > 0:
            hit_correct = (await db.execute(
                select(func.count()).select_from(PredictionRecord).where(
                    PredictionRecord.predicted_ctr > 0.05
                )
            )).scalar() or 0
            high_ctr_prediction_share = round(hit_correct / hit_total, 4)
    except Exception as error:
        logger.warning("高 CTR 预测占比统计失败", error=str(error))

    payload = {
        "total_generated": total_images,
        "total_approved": approved,
        "approval_rate": round(approved / total_images, 2) if total_images > 0 else 0,
        "total_impressions": total_impressions,
        "total_clicks": total_clicks,
        "avg_ctr": avg_ctr,
        "avg_cvr": avg_cvr,
        "avg_return_rate": avg_return_rate,
        "total_revenue": total_revenue,
        "ctr_vs_baseline_percent": ctr_vs_baseline,
        "ctr_baseline": ctr_baseline,
        "ctr_baseline_config_version": ctr_baseline_setting.version,
        "ctr_auc": None,
        "high_ctr_prediction_share": high_ctr_prediction_share,
        "manual_review_rate": round(manual_pending / total_images, 4) if total_images > 0 else 0,
        "filters": {"market": market, "category": category},
    }
    await set_summary_cache(
        tenant_id=tenant_id,
        market=market,
        category=category,
        runtime_config_version=ctr_baseline_setting.version,
        payload=payload,
    )
    return payload


@router.get("/ctr_trend")
async def get_ctr_trend(
    request: Request,
    db: AsyncSession = Depends(get_db),
    days: int = Query(30, ge=1, le=365),
):
    """最近 N 天的每日 CTR 曲线"""
    from datetime import date, timedelta
    today = date.today()
    start = today - timedelta(days=days)

    result = await db.execute(
        select(
            DailyMetric.date,
            func.sum(DailyMetric.clicks)
            / func.nullif(func.sum(DailyMetric.impressions), 0),
        )
        .where(DailyMetric.date >= start)
        .group_by(DailyMetric.date)
        .order_by(DailyMetric.date)
    )
    rows = result.all()

    return {
        "days": days,
        "data": [
            {"date": r[0].isoformat() if hasattr(r[0], "isoformat") else str(r[0]), "avg_ctr": round(float(r[1] or 0), 4)}
            for r in rows
        ],
    }


@router.get("/market_comparison")
async def get_market_comparison(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """市场维度的 CTR / CVR 对比"""
    result = await db.execute(
        select(
            GeneratedImage.market_variant,
            func.count(func.distinct(GeneratedImage.id)).label("total"),
            (
                func.sum(DailyMetric.clicks)
                / func.nullif(func.sum(DailyMetric.impressions), 0)
            ).label("avg_ctr"),
            (
                func.sum(DailyMetric.cvr * DailyMetric.clicks)
                / func.nullif(func.sum(DailyMetric.clicks), 0)
            ).label("avg_cvr"),
            func.sum(DailyMetric.impressions).label("total_impressions"),
        )
        .outerjoin(DailyMetric, DailyMetric.image_id == GeneratedImage.id)
        .group_by(GeneratedImage.market_variant)
    )
    rows = result.all()

    return {
        "markets": [
            {
                "market": r[0] or "unknown",
                "total_images": r[1],
                "avg_ctr": round(float(r[2] or 0), 4),
                "avg_cvr": round(float(r[3] or 0), 4),
                "total_impressions": int(r[4] or 0),
            }
            for r in rows
        ],
    }


@router.get("/style_insight")
async def get_style_insight(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """从全部当前租户的 image_schemes.style_tags 聚合 Top 20 风格标签。"""
    from app.models.image import ImageScheme
    if db.bind and db.bind.dialect.name == "postgresql":
        rows = (
            await db.execute(
                text("""
                    WITH raw_tags AS (
                        SELECT CASE
                            WHEN jsonb_typeof(tag_entry.value) = 'array'
                                THEN array_item.value #>> '{}'
                            WHEN jsonb_typeof(tag_entry.value) IN ('string', 'number', 'boolean')
                                THEN tag_entry.value #>> '{}'
                            ELSE NULL
                        END AS tag
                        FROM image_schemes AS scheme
                        CROSS JOIN LATERAL jsonb_each(
                            COALESCE(scheme.style_tags::jsonb, '{}'::jsonb)
                        ) AS tag_entry(key, value)
                        LEFT JOIN LATERAL jsonb_array_elements(
                            CASE WHEN jsonb_typeof(tag_entry.value) = 'array'
                                THEN tag_entry.value ELSE '[]'::jsonb END
                        ) AS array_item(value) ON true
                        WHERE scheme.tenant_id = :tenant_id
                    ), tag_counts AS (
                        SELECT tag, COUNT(*) AS count
                        FROM raw_tags
                        WHERE tag IS NOT NULL AND tag <> ''
                        GROUP BY tag
                    )
                    SELECT tag, count, COUNT(*) OVER () AS total_tags
                    FROM tag_counts
                    ORDER BY count DESC, tag ASC
                    LIMIT 20
                """),
                {"tenant_id": get_current_tenant_id()},
            )
        ).all()
        return {
            "insights": [{"tag": row.tag, "count": row.count} for row in rows],
            "total_tags": int(rows[0].total_tags) if rows else 0,
        }

    result = await db.execute(
        select(ImageScheme.style_tags)
    )
    rows = result.scalars().all()

    # 统计标签频次
    tag_counts: dict[str, int] = {}
    for tags in rows:
        if not tags:
            continue
        for _tag_key, tag_value in (tags if isinstance(tags, dict) else {}).items():
            if isinstance(tag_value, list):
                for item in tag_value:
                    tag_counts[str(item)] = tag_counts.get(str(item), 0) + 1
            else:
                tag_counts[str(tag_value)] = tag_counts.get(str(tag_value), 0) + 1

    # 排序取 Top 20
    top_tags = sorted(tag_counts.items(), key=lambda item: (-item[1], item[0]))[:20]

    return {
        "insights": [{"tag": tag, "count": count} for tag, count in top_tags],
        "total_tags": len(tag_counts),
    }
