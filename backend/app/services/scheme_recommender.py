"""
三维度方案推荐引擎

融合三个维度生成差异化方案推荐：
1. 同品类历史最优 —— 查同品类中历史 CTR 最高的方案风格
2. 跨品类风格迁移趋势 —— 发现近期在多品类表现上升的风格
3. 市场本地化偏好 —— 按目标市场过滤风格偏好

每个推荐结果附带可解释的量化理由。
"""

from typing import Any

from sqlalchemy import Float, cast, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.models import (
    DailyMetric,
    GeneratedImage,
    ImageScheme,
    Product,
    ReviewStatus,
)

# 三维度权重（可按业务调参）
WEIGHT_SAME_CATEGORY = 0.45
WEIGHT_CROSS_CATEGORY = 0.25
WEIGHT_MARKET = 0.30

# 聚合时要求的最小曝光量，低于此值视为样本不足不参与排序
MIN_IMPRESSIONS = 200


async def _dim1_same_category_best(
    db: AsyncSession, category: str, top_k: int = 5
) -> list[dict]:
    """维度一：同品类历史 CTR 最优方案

    SQL 逻辑：
      SELECT scheme_name, style_tags,
             SUM(dm.clicks) / NULLIF(SUM(dm.impressions), 0) as avg_ctr,
             SUM(dm.impressions) as total_imp
      FROM image_schemes ish
      JOIN generated_images gi ON gi.scheme_id = ish.id
      JOIN daily_metrics dm ON dm.image_id = gi.id
      JOIN products p ON p.id = ish.product_id
      WHERE p.category = :category
        AND gi.review_status = 'auto_approved'
      GROUP BY scheme_name, style_tags
      HAVING SUM(dm.impressions) >= :min_imp
      ORDER BY avg_ctr DESC
      LIMIT :top_k
    """
    stmt = (
        select(
            ImageScheme.id,
            ImageScheme.scheme_name,
            ImageScheme.style_tags,
            (
                cast(func.sum(DailyMetric.clicks), Float)
                / func.nullif(func.sum(DailyMetric.impressions), 0)
            ).label("avg_ctr"),
            func.sum(DailyMetric.impressions).label("total_impressions"),
            func.avg(DailyMetric.cvr).label("avg_cvr"),
        )
        .join(GeneratedImage, GeneratedImage.scheme_id == ImageScheme.id)
        .join(DailyMetric, DailyMetric.image_id == GeneratedImage.id)
        .join(Product, Product.id == ImageScheme.product_id)
        .where(
            Product.category == category,
            GeneratedImage.review_status == ReviewStatus.AUTO_APPROVED,
        )
        .group_by(ImageScheme.id)
        .having(func.sum(DailyMetric.impressions) >= MIN_IMPRESSIONS)
        .order_by(desc("avg_ctr"))
        .limit(top_k)
    )

    rows = (await db.execute(stmt)).all()

    return [
        {
            "scheme_id": row.id,
            "scheme_name": row.scheme_name,
            "style_tags": row.style_tags or {},
            "avg_ctr": round(float(row.avg_ctr or 0), 4),
            "avg_cvr": round(float(row.avg_cvr or 0), 4),
            "total_impressions": int(row.total_impressions or 0),
            "dimension": "same_category",
        }
        for row in rows
    ]


async def _dim2_cross_category_trending(
    db: AsyncSession, category: str, top_k: int = 5
) -> list[dict]:
    """维度二：跨品类风格迁移趋势

    找出在"其他品类"中近期 CTR 表现优秀、但尚未在本品类大量使用的风格。
    核心思路：风格在 A 品类火了，很可能迁移到 B 品类也有效。

    SQL 逻辑：
      SELECT scheme_name, style_tags,
             SUM(dm.clicks) / NULLIF(SUM(dm.impressions), 0) as avg_ctr,
             COUNT(DISTINCT p.category) as category_count
      FROM image_schemes ish
      JOIN generated_images gi ON gi.scheme_id = ish.id
      JOIN daily_metrics dm ON dm.image_id = gi.id
      JOIN products p ON p.id = ish.product_id
      WHERE p.category != :category          -- 排除当前品类
        AND gi.review_status = 'auto_approved'
      GROUP BY scheme_name, style_tags
      HAVING SUM(dm.impressions) >= :min_imp
      ORDER BY avg_ctr DESC
      LIMIT :top_k
    """
    stmt = (
        select(
            ImageScheme.id,
            ImageScheme.scheme_name,
            ImageScheme.style_tags,
            (
                cast(func.sum(DailyMetric.clicks), Float)
                / func.nullif(func.sum(DailyMetric.impressions), 0)
            ).label("avg_ctr"),
            func.sum(DailyMetric.impressions).label("total_impressions"),
            func.count(Product.category.distinct()).label("category_count"),
        )
        .join(GeneratedImage, GeneratedImage.scheme_id == ImageScheme.id)
        .join(DailyMetric, DailyMetric.image_id == GeneratedImage.id)
        .join(Product, Product.id == ImageScheme.product_id)
        .where(
            Product.category != category,
            GeneratedImage.review_status == ReviewStatus.AUTO_APPROVED,
        )
        .group_by(ImageScheme.id)
        .having(func.sum(DailyMetric.impressions) >= MIN_IMPRESSIONS)
        .order_by(desc("avg_ctr"))
        .limit(top_k)
    )

    rows = (await db.execute(stmt)).all()

    return [
        {
            "scheme_id": row.id,
            "scheme_name": row.scheme_name,
            "style_tags": row.style_tags or {},
            "avg_ctr": round(float(row.avg_ctr or 0), 4),
            "total_impressions": int(row.total_impressions or 0),
            "category_count": int(row.category_count or 0),
            "dimension": "cross_category",
        }
        for row in rows
    ]


async def _dim3_market_preference(
    db: AsyncSession, market: str, top_k: int = 5
) -> list[dict]:
    """维度三：市场本地化偏好

    按目标市场过滤，找出该市场 CTR 表现最好的风格。
    同一风格在不同市场的表现差异很大（如欧美偏好街拍、中东偏好保守场景）。

    SQL 逻辑：
      SELECT scheme_name, style_tags,
             SUM(dm.clicks) / NULLIF(SUM(dm.impressions), 0) as avg_ctr,
             AVG(dm.return_rate) as avg_return_rate
      FROM image_schemes ish
      JOIN generated_images gi ON gi.scheme_id = ish.id
      JOIN daily_metrics dm ON dm.image_id = gi.id
      WHERE gi.market_variant = :market
        AND gi.review_status = 'auto_approved'
      GROUP BY scheme_name, style_tags
      HAVING SUM(dm.impressions) >= :min_imp
      ORDER BY avg_ctr DESC
      LIMIT :top_k
    """
    stmt = (
        select(
            ImageScheme.id,
            ImageScheme.scheme_name,
            ImageScheme.style_tags,
            (
                cast(func.sum(DailyMetric.clicks), Float)
                / func.nullif(func.sum(DailyMetric.impressions), 0)
            ).label("avg_ctr"),
            func.sum(DailyMetric.impressions).label("total_impressions"),
            func.avg(DailyMetric.return_rate).label("avg_return_rate"),
        )
        .join(GeneratedImage, GeneratedImage.scheme_id == ImageScheme.id)
        .join(DailyMetric, DailyMetric.image_id == GeneratedImage.id)
        .where(
            GeneratedImage.market_variant == market,
            GeneratedImage.review_status == ReviewStatus.AUTO_APPROVED,
        )
        .group_by(ImageScheme.id)
        .having(func.sum(DailyMetric.impressions) >= MIN_IMPRESSIONS)
        .order_by(desc("avg_ctr"))
        .limit(top_k)
    )

    rows = (await db.execute(stmt)).all()

    return [
        {
            "scheme_id": row.id,
            "scheme_name": row.scheme_name,
            "style_tags": row.style_tags or {},
            "avg_ctr": round(float(row.avg_ctr or 0), 4),
            "avg_return_rate": round(float(row.avg_return_rate or 0), 4),
            "total_impressions": int(row.total_impressions or 0),
            "dimension": "market",
        }
        for row in rows
    ]


def _build_reason(dim: str, item: dict, category: str, market: str) -> str:
    """为每个推荐生成可解释的量化理由"""
    ctr = item.get("avg_ctr", 0)
    ctr_pct = f"{ctr * 100:.2f}%"

    if dim == "same_category":
        return (
            f"该风格在{category}品类历史 CTR 均值 {ctr_pct}，"
            f"样本量 {item['total_impressions']} 次曝光"
        )
    elif dim == "cross_category":
        return (
            f"该风格在 {item['category_count']} 个其他品类均表现优异（CTR {ctr_pct}），"
            f"具备跨品类迁移潜力"
        )
    elif dim == "market":
        ret = item.get("avg_return_rate", 0)
        return (
            f"该风格在{market}市场 CTR {ctr_pct}，"
            f"退货率 {ret * 100:.1f}%，符合本地化审美偏好"
        )
    return ""


async def recommend_schemes(
    db: AsyncSession,
    category: str,
    market: str,
    top_k: int = 5,
) -> dict[str, Any]:
    """三维度融合方案推荐主入口

    Args:
        db: 异步数据库会话
        category: 商品品类（如"连衣裙"）
        market: 目标市场（如"us"/"eu"/"me"/"seasia"）
        top_k: 每个维度返回的方案数

    Returns:
        {
            "recommendations": [
                {
                    "scheme_name": "...",
                    "style_tags": {...},
                    "recommendation_score": float,   # 0-1 归一化
                    "dimension": "same_category|cross_category|market",
                    "reason": "可解释的量化理由",
                    "metrics": {...}
                }
            ],
            "weights": {"same_category": 0.45, "cross_category": 0.25, "market": 0.30},
            "source": "three_dim_fusion",
        }
    """
    # 顺序查三个维度（AsyncSession 不支持并发使用）
    dim1 = await _dim1_same_category_best(db, category, top_k)
    dim2 = await _dim2_cross_category_trending(db, category, top_k)
    dim3 = await _dim3_market_preference(db, market, top_k)

    # 找全局最高 CTR 用于归一化
    all_ctrs = [i["avg_ctr"] for i in dim1 + dim2 + dim3 if i["avg_ctr"] > 0]
    max_ctr = max(all_ctrs) if all_ctrs else 0.05

    # 融合：每个方案按来源维度加权
    seen: dict[str, dict] = {}
    weight_map = {
        "same_category": WEIGHT_SAME_CATEGORY,
        "cross_category": WEIGHT_CROSS_CATEGORY,
        "market": WEIGHT_MARKET,
    }

    for dim_name, items in [
        ("same_category", dim1),
        ("cross_category", dim2),
        ("market", dim3),
    ]:
        for item in items:
            scheme_id = item["scheme_id"]
            # 归一化 CTR 到 0-1
            norm_ctr = item["avg_ctr"] / max_ctr if max_ctr > 0 else 0
            # 加权得分
            score = norm_ctr * weight_map[dim_name]

            if scheme_id not in seen:
                seen[scheme_id] = {
                    "scheme_id": scheme_id,
                    "scheme_name": item["scheme_name"],
                    "style_tags": item["style_tags"],
                    "recommendation_score": round(score, 4),
                    "dimensions": [dim_name],
                    "reason": _build_reason(dim_name, item, category, market),
                    "metrics": {
                        "avg_ctr": item["avg_ctr"],
                        "total_impressions": item["total_impressions"],
                    },
                }
            else:
                # 方案在多个维度都出现，累加得分
                existing = seen[scheme_id]
                existing["recommendation_score"] = round(
                    existing["recommendation_score"] + score, 4
                )
                existing["dimensions"].append(dim_name)
                # 补充该维度的理由
                extra_reason = _build_reason(dim_name, item, category, market)
                existing["reason"] += f"；{extra_reason}"

                # 补充指标
                if dim_name == "cross_category":
                    existing["metrics"]["category_count"] = item.get("category_count", 0)
                if dim_name == "market":
                    existing["metrics"]["avg_return_rate"] = item.get("avg_return_rate", 0)

    # 按融合得分排序
    recommendations = sorted(
        seen.values(),
        key=lambda x: x["recommendation_score"],
        reverse=True,
    )[:top_k]

    logger.info(
        "三维度方案推荐完成",
        category=category,
        market=market,
        dim1_count=len(dim1),
        dim2_count=len(dim2),
        dim3_count=len(dim3),
        final_count=len(recommendations),
    )

    return {
        "recommendations": recommendations,
        "weights": {
            "same_category": WEIGHT_SAME_CATEGORY,
            "cross_category": WEIGHT_CROSS_CATEGORY,
            "market": WEIGHT_MARKET,
        },
        "source": "three_dim_fusion",
    }
