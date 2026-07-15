"""
效果归因服务 —— 剥离混杂因素，量化视觉方案的增量贡献

支持：
1. 整体 Lift + Z-test（calculate_lift / calculate_p_value / generate_attribution_report）
2. 多维度下钻归因（dimension_breakdown）—— 按 market/category/date 分组重算 Lift
"""

from typing import Any

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger

# 支持的下钻维度
SUPPORTED_DIMENSIONS = ("market", "category", "date")


def calculate_lift(
    variant_ctr: float,
    control_ctr: float,
) -> dict:
    """
    计算视觉方案的 Lift 值

    Args:
        variant_ctr: 实验组 CTR
        control_ctr: 对照组 CTR

    Returns:
        {"lift_pct": 15.2, "direction": "positive"}
    """
    if control_ctr <= 0:
        return {"lift_pct": 0, "direction": "neutral", "error": "control_ctr is zero"}

    lift = ((variant_ctr - control_ctr) / control_ctr) * 100

    return {
        "lift_pct": round(float(lift), 1),
        "direction": "positive" if lift > 0 else ("negative" if lift < 0 else "neutral"),
    }


def calculate_p_value(
    variant_impressions: int,
    variant_clicks: int,
    control_impressions: int,
    control_clicks: int,
) -> float:
    """
    简化的 A/B 检验 p-value 计算（Z-test for proportions）
    """
    if variant_impressions <= 0 or control_impressions <= 0:
        return 1.0

    p1 = variant_clicks / variant_impressions
    p2 = control_clicks / control_impressions

    # 合并比例
    p_pool = (variant_clicks + control_clicks) / (variant_impressions + control_impressions)

    # 标准误
    se = np.sqrt(p_pool * (1 - p_pool) * (1 / variant_impressions + 1 / control_impressions))

    if se == 0:
        return 1.0

    z = (p1 - p2) / se

    # 双边检验 p-value（简化：使用正态近似）
    from math import erfc, sqrt

    p_value = float(erfc(abs(z) / sqrt(2)))

    return round(p_value, 4)


def generate_attribution_report(
    image_id: int,
    variant_metrics: dict,
    control_metrics: dict,
) -> dict:
    """
    生成效果归因报告

    Args:
        image_id: 图片 ID
        variant_metrics: 实验组指标 {"impressions": N, "clicks": N, "conversions": N, "returns": N}
        control_metrics: 对照组指标

    Returns:
        归因报告
    """
    variant_ctr = variant_metrics["clicks"] / max(variant_metrics["impressions"], 1)
    control_ctr = control_metrics["clicks"] / max(control_metrics["impressions"], 1)
    variant_cvr = variant_metrics.get("conversions", 0) / max(variant_metrics["clicks"], 1)
    control_cvr = control_metrics.get("conversions", 0) / max(control_metrics["clicks"], 1)

    ctr_lift = calculate_lift(variant_ctr, control_ctr)
    cvr_lift = calculate_lift(variant_cvr, control_cvr)

    p_value = calculate_p_value(
        variant_metrics["impressions"],
        variant_metrics["clicks"],
        control_metrics["impressions"],
        control_metrics["clicks"],
    )

    is_significant = p_value < 0.05

    return {
        "image_id": image_id,
        "variant_ctr": round(float(variant_ctr), 4),
        "control_ctr": round(float(control_ctr), 4),
        "ctr_lift": ctr_lift,
        "cvr_lift": cvr_lift,
        "p_value": p_value,
        "is_significant": is_significant,
        "recommendation": (
            "推广此方案" if ctr_lift["direction"] == "positive" and is_significant
            else "继续观察" if not is_significant
            else "考虑替换方案"
        ),
    }


# ============ 多维度下钻归因 ============


async def _query_variant_metrics_by_dimension(
    db: AsyncSession,
    image_id: int,
    dimension: str,
) -> dict[str, dict[str, int]]:
    """查单个变体图片按维度的聚合指标

    Args:
        db: 异步数据库会话
        image_id: 变体图片 ID
        dimension: 下钻维度 market/category/date

    Returns:
        {dim_value: {"impressions": N, "clicks": N}, ...}
    """
    from app.models import DailyMetric, GeneratedImage, ImageScheme, Product

    if dimension == "market":
        # 按 market_variant 分组（同一张图只有一个 market，但保持聚合一致性）
        stmt = (
            select(
                GeneratedImage.market_variant.label("dim_value"),
                func.sum(DailyMetric.impressions).label("impressions"),
                func.sum(DailyMetric.clicks).label("clicks"),
            )
            .select_from(DailyMetric)
            .join(GeneratedImage, GeneratedImage.id == DailyMetric.image_id)
            .where(DailyMetric.image_id == image_id)
            .group_by(GeneratedImage.market_variant)
        )
    elif dimension == "category":
        # 关联到 Product.category
        stmt = (
            select(
                Product.category.label("dim_value"),
                func.sum(DailyMetric.impressions).label("impressions"),
                func.sum(DailyMetric.clicks).label("clicks"),
            )
            .select_from(DailyMetric)
            .join(GeneratedImage, GeneratedImage.id == DailyMetric.image_id)
            .join(ImageScheme, ImageScheme.id == GeneratedImage.scheme_id)
            .join(Product, Product.id == ImageScheme.product_id)
            .where(DailyMetric.image_id == image_id)
            .group_by(Product.category)
        )
    elif dimension == "date":
        # 按日期分组
        stmt = (
            select(
                DailyMetric.date.label("dim_value"),
                func.sum(DailyMetric.impressions).label("impressions"),
                func.sum(DailyMetric.clicks).label("clicks"),
            )
            .select_from(DailyMetric)
            .where(DailyMetric.image_id == image_id)
            .group_by(DailyMetric.date)
        )
    else:
        raise ValueError(f"不支持的下钻维度: {dimension}，可选: {SUPPORTED_DIMENSIONS}")

    rows = (await db.execute(stmt)).all()
    return {
        str(row.dim_value): {
            "impressions": int(row.impressions or 0),
            "clicks": int(row.clicks or 0),
        }
        for row in rows
    }


async def dimension_breakdown(
    db: AsyncSession,
    experiment_id: int,
    dimension: str,
) -> dict[str, Any]:
    """多维度下钻归因分析

    对指定实验按维度（market/category/date）切片，重算每个切片内
    variant A vs variant B 的 Lift + Z-test p-value。

    场景举例：
    - dimension=date：看 Lift 随时间的变化趋势，判断效果是否稳定
    - dimension=market：看不同市场中 A/B 谁更优（跨市场实验时有意义）
    - dimension=category：单实验同品类时退化为单行，跨品类聚合时才有差异

    Args:
        db: 异步数据库会话
        experiment_id: A/B 实验 ID
        dimension: 下钻维度 market/category/date

    Returns:
        {
            "experiment_id": int,
            "dimension": str,
            "breakdown": [
                {
                    "dimension_value": str,
                    "variant_a": {"impressions": N, "clicks": N, "ctr": float},
                    "variant_b": {"impressions": N, "clicks": N, "ctr": float},
                    "lift_pct": float,
                    "direction": "positive"|"negative"|"neutral",
                    "p_value": float,
                    "is_significant": bool,
                }
            ]
        }
    """
    from app.models import ABExperiment

    if dimension not in SUPPORTED_DIMENSIONS:
        raise ValueError(
            f"不支持的维度: {dimension}，可选: {SUPPORTED_DIMENSIONS}"
        )

    # 查实验
    exp = await db.get(ABExperiment, experiment_id)
    if not exp:
        raise ValueError(f"实验 #{experiment_id} 不存在")

    # 分别查 A 和 B 按维度的聚合指标
    metrics_a = await _query_variant_metrics_by_dimension(
        db, exp.variant_a_image_id, dimension
    )
    metrics_b = await _query_variant_metrics_by_dimension(
        db, exp.variant_b_image_id, dimension
    )

    # 合并所有维度值
    all_dim_values = set(metrics_a.keys()) | set(metrics_b.keys())

    breakdown = []
    for dim_value in sorted(all_dim_values):
        a = metrics_a.get(dim_value, {"impressions": 0, "clicks": 0})
        b = metrics_b.get(dim_value, {"impressions": 0, "clicks": 0})

        # 跳过两边都没数据的维度值
        if a["impressions"] == 0 and b["impressions"] == 0:
            continue

        ctr_a = a["clicks"] / max(a["impressions"], 1)
        ctr_b = b["clicks"] / max(b["impressions"], 1)

        # A 相对 B 的 Lift（A=实验组，B=对照组）
        lift = calculate_lift(ctr_a, ctr_b)
        p_value = calculate_p_value(
            a["impressions"], a["clicks"],
            b["impressions"], b["clicks"],
        )

        breakdown.append({
            "dimension_value": dim_value,
            "variant_a": {
                "impressions": a["impressions"],
                "clicks": a["clicks"],
                "ctr": round(ctr_a, 4),
            },
            "variant_b": {
                "impressions": b["impressions"],
                "clicks": b["clicks"],
                "ctr": round(ctr_b, 4),
            },
            "lift_pct": lift["lift_pct"],
            "direction": lift["direction"],
            "p_value": p_value,
            "is_significant": p_value < 0.05,
        })

    logger.info(
        "维度下钻归因完成",
        experiment_id=experiment_id,
        dimension=dimension,
        slices=len(breakdown),
    )

    return {
        "experiment_id": experiment_id,
        "dimension": dimension,
        "breakdown": breakdown,
    }
