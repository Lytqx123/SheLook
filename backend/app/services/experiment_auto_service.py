"""
A/B 实验自动创建与流量分配服务

1. auto_create_experiments —— 扫描已审核+已预测图片，按商品找预测分接近的两张自动建实验
2. update_traffic_allocation —— UCB 算法动态调整运行中实验的流量比例
3. get_auto_experiment_summary —— 查询自动实验统计

UCB（Upper Confidence Bound）核心思想：
- 探索阶段（曝光少）：置信区间宽，给更多流量探索
- 利用阶段（曝光多）：置信区间窄，按实际 CTR 分配流量
- 公式：UCB_score = avg_ctr + sqrt(2 * ln(N) / n_i)
"""

import math
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.logging import logger
from app.models import (
    ABExperiment,
    DailyMetric,
    ExperimentStatus,
    GeneratedImage,
    ImageScheme,
    PredictionRecord,
    ReviewStatus,
)

# ---- 自动创建实验参数 ----
# 预测 CTR 差距小于此值才创建实验（差距太大说明方案优劣已明确，无需实验）
CTR_DIFF_THRESHOLD = 0.02
# 每商品最多同时运行几个实验
MAX_RUNNING_EXPERIMENTS_PER_PRODUCT = 1
# 实验最小图片数
MIN_IMAGES_FOR_EXPERIMENT = 2

# ---- UCB 流量分配参数 ----
# UCB 需要的最少总曝光次数（低于此值保持 50/50 探索）
MIN_IMPRESSIONS_FOR_UCB = 100
# 流量比例边界（避免极端 0/100 分配）
TRAFFIC_RATIO_MIN = 0.2
TRAFFIC_RATIO_MAX = 0.8


async def auto_create_experiments(db: AsyncSession) -> dict[str, Any]:
    """自动扫描并创建 A/B 实验

    逻辑：
    1. 查所有已审核通过（AUTO_APPROVED）且有预测记录的图片
    2. 按 product_id 分组
    3. 对每商品，找预测 CTR 最接近的两张图片
    4. 检查是否已有运行中实验，无则创建

    Returns:
        {"scanned_products": N, "created": N, "skipped_existing": N, "skipped_insufficient": N, "details": [...]}
    """
    # 查已审核通过 + 有预测记录的图片，关联到商品
    stmt = (
        select(
            GeneratedImage.id.label("image_id"),
            ImageScheme.product_id.label("product_id"),
            PredictionRecord.predicted_ctr.label("predicted_ctr"),
            PredictionRecord.id.label("prediction_id"),
        )
        .select_from(PredictionRecord)
        .join(GeneratedImage, GeneratedImage.id == PredictionRecord.image_id)
        .join(ImageScheme, ImageScheme.id == GeneratedImage.scheme_id)
        .where(
            GeneratedImage.review_status == ReviewStatus.AUTO_APPROVED,
            PredictionRecord.predicted_ctr.isnot(None),
        )
        .order_by(ImageScheme.product_id, PredictionRecord.predicted_ctr.desc())
    )

    rows = (await db.execute(stmt)).all()

    # 按 product_id 分组
    products_map: dict[int, list[dict]] = {}
    for row in rows:
        pid = row.product_id
        if pid not in products_map:
            products_map[pid] = []
        products_map[pid].append({
            "image_id": row.image_id,
            "predicted_ctr": float(row.predicted_ctr),
        })

    created_count = 0
    skipped_existing = 0
    skipped_insufficient = 0
    details = []

    for product_id, images in products_map.items():
        if len(images) < MIN_IMAGES_FOR_EXPERIMENT:
            skipped_insufficient += 1
            continue

        # 检查是否已有运行中的实验
        running_count = (
            await db.execute(
                select(func.count(ABExperiment.id)).where(
                    ABExperiment.product_id == product_id,
                    ABExperiment.status == ExperimentStatus.RUNNING,
                )
            )
        ).scalar() or 0

        if running_count >= MAX_RUNNING_EXPERIMENTS_PER_PRODUCT:
            skipped_existing += 1
            continue

        # 按 CTR 降序排，找相邻两张差距最小的（最有实验价值）
        # images 已按 CTR 降序排
        best_pair = None
        min_diff = float("inf")
        for i in range(len(images) - 1):
            diff = abs(images[i]["predicted_ctr"] - images[i + 1]["predicted_ctr"])
            if diff < min_diff:
                min_diff = diff
                best_pair = (images[i], images[i + 1])

        if not best_pair:
            skipped_insufficient += 1
            continue

        img_a, img_b = best_pair

        # CTR 差距过大则跳过（说明方案优劣已明确）
        if min_diff > CTR_DIFF_THRESHOLD:
            skipped_insufficient += 1
            details.append({
                "product_id": product_id,
                "action": "skipped_diff_too_large",
                "ctr_diff": round(min_diff, 4),
            })
            continue

        # 创建实验
        experiment = ABExperiment(
            product_id=product_id,
            variant_a_image_id=img_a["image_id"],
            variant_b_image_id=img_b["image_id"],
            traffic_ratio=0.5,  # 初始 50/50
            status=ExperimentStatus.RUNNING,
            start_date=datetime.utcnow(),
        )
        db.add(experiment)
        created_count += 1
        details.append({
            "product_id": product_id,
            "action": "created",
            "variant_a_image_id": img_a["image_id"],
            "variant_b_image_id": img_b["image_id"],
            "ctr_a": round(img_a["predicted_ctr"], 4),
            "ctr_b": round(img_b["predicted_ctr"], 4),
            "ctr_diff": round(min_diff, 4),
        })

    await db.commit()

    logger.info(
        "自动实验创建完成",
        scanned_products=len(products_map),
        created=created_count,
        skipped_existing=skipped_existing,
        skipped_insufficient=skipped_insufficient,
    )

    return {
        "scanned_products": len(products_map),
        "created": created_count,
        "skipped_existing": skipped_existing,
        "skipped_insufficient": skipped_insufficient,
        "details": details,
    }


async def update_traffic_allocation(
    db: AsyncSession,
    experiment_id: int,
) -> dict[str, Any]:
    """UCB 算法动态调整实验流量比例

    基于两张变体图片的 daily_metrics 历史数据，计算 UCB 置信区间上界，
    按上界比例分配流量。探索阶段（曝光少）保持均衡，利用阶段（曝光多）偏向胜出方。

    Args:
        db: 异步数据库会话
        experiment_id: 实验 ID

    Returns:
        {"experiment_id": int, "old_ratio": float, "new_ratio": float,
         "ucb_a": float, "ucb_b": float, "method": "ucb"|"default"}
    """
    exp = await db.get(ABExperiment, experiment_id)
    if not exp:
        raise ValueError(f"实验 #{experiment_id} 不存在")

    if exp.status != ExperimentStatus.RUNNING:
        raise ValueError(f"实验 #{experiment_id} 非运行中状态，当前: {exp.status}")

    old_ratio = float(exp.traffic_ratio or 0.5)

    # 聚合两张图的 daily_metrics
    metrics_a = await _aggregate_image_metrics(db, exp.variant_a_image_id)
    metrics_b = await _aggregate_image_metrics(db, exp.variant_b_image_id)

    total_impressions = metrics_a["impressions"] + metrics_b["impressions"]

    # 达到预设样本上限属于自然完成；与人工 stop 的 STOPPED 语义分离。
    if total_impressions >= settings.EXPERIMENT_COMPLETION_IMPRESSIONS:
        from app.services.reward_scorer import calculate_significance

        significance = calculate_significance(metrics_a, metrics_b)
        exp.result_ctr_a = metrics_a["clicks"] / max(metrics_a["impressions"], 1)
        exp.result_ctr_b = metrics_b["clicks"] / max(metrics_b["impressions"], 1)
        exp.p_value = significance.get("p_value")
        exp.winner_image_id = (
            exp.variant_a_image_id
            if significance.get("winner") == "A"
            else exp.variant_b_image_id
            if significance.get("winner") == "B"
            else None
        )
        exp.status = ExperimentStatus.COMPLETED
        exp.end_date = datetime.utcnow()
        await db.commit()
        return {
            "experiment_id": experiment_id,
            "old_ratio": old_ratio,
            "new_ratio": old_ratio,
            "metrics_a": metrics_a,
            "metrics_b": metrics_b,
            "method": "completed_sample_cap",
        }

    # 曝光不足时保持 50/50（探索阶段）
    if total_impressions < MIN_IMPRESSIONS_FOR_UCB:
        new_ratio = 0.5
        method = "default_explore"
    else:
        # UCB 计算
        ctr_a = metrics_a["clicks"] / max(metrics_a["impressions"], 1)
        ctr_b = metrics_b["clicks"] / max(metrics_b["impressions"], 1)

        n = total_impressions
        n_a = max(metrics_a["impressions"], 1)
        n_b = max(metrics_b["impressions"], 1)

        # UCB = avg_ctr + sqrt(2 * ln(N) / n_i)
        ucb_a = ctr_a + math.sqrt(2 * math.log(n) / n_a)
        ucb_b = ctr_b + math.sqrt(2 * math.log(n) / n_b)

        # 流量比例 = UCB_A / (UCB_A + UCB_B)
        total_ucb = ucb_a + ucb_b
        new_ratio = ucb_a / total_ucb if total_ucb > 0 else 0.5

        # 限制在 [0.2, 0.8] 范围内，避免极端分配
        new_ratio = max(TRAFFIC_RATIO_MIN, min(TRAFFIC_RATIO_MAX, new_ratio))
        method = "ucb"

    # 更新实验流量比例
    exp.traffic_ratio = round(new_ratio, 4)
    await db.commit()

    logger.info(
        "流量分配更新",
        experiment_id=experiment_id,
        old_ratio=old_ratio,
        new_ratio=round(new_ratio, 4),
        method=method,
        impressions_a=metrics_a["impressions"],
        impressions_b=metrics_b["impressions"],
    )

    return {
        "experiment_id": experiment_id,
        "old_ratio": round(old_ratio, 4),
        "new_ratio": round(new_ratio, 4),
        "metrics_a": metrics_a,
        "metrics_b": metrics_b,
        "method": method,
    }


async def _aggregate_image_metrics(db: AsyncSession, image_id: int) -> dict[str, int]:
    """聚合单张图片的 daily_metrics 总量"""
    stmt = (
        select(
            func.coalesce(func.sum(DailyMetric.impressions), 0).label("impressions"),
            func.coalesce(func.sum(DailyMetric.clicks), 0).label("clicks"),
        )
        .where(DailyMetric.image_id == image_id)
    )
    row = (await db.execute(stmt)).one()
    return {
        "impressions": int(row.impressions or 0),
        "clicks": int(row.clicks or 0),
    }


async def update_all_running_experiments(db: AsyncSession) -> dict[str, Any]:
    """批量更新所有运行中实验的流量分配

    用于 Celery 定时任务调用。

    Returns:
        {"total_running": N, "updated": N, "skipped": N, "details": [...]}
    """
    stmt = select(ABExperiment).where(ABExperiment.status == ExperimentStatus.RUNNING)
    experiments = (await db.execute(stmt)).scalars().all()

    updated = 0
    skipped = 0
    details = []

    for exp in experiments:
        try:
            result = await update_traffic_allocation(db, exp.id)
            updated += 1
            details.append({
                "experiment_id": exp.id,
                "new_ratio": result["new_ratio"],
                "method": result["method"],
            })
        except Exception as e:
            skipped += 1
            details.append({
                "experiment_id": exp.id,
                "error": str(e),
            })

    logger.info(
        "批量流量分配更新完成",
        total_running=len(experiments),
        updated=updated,
        skipped=skipped,
    )

    return {
        "total_running": len(experiments),
        "updated": updated,
        "skipped": skipped,
        "details": details,
    }


async def get_auto_experiment_summary(db: AsyncSession) -> dict[str, Any]:
    """查询自动实验统计概览

    Returns:
        {"total_experiments": N, "running": N, "completed": N,
         "auto_created_ratio": float, "avg_traffic_ratio": float}
    """
    total = (
        await db.execute(select(func.count(ABExperiment.id)))
    ).scalar() or 0

    running = (
        await db.execute(
            select(func.count(ABExperiment.id)).where(
                ABExperiment.status == ExperimentStatus.RUNNING
            )
        )
    ).scalar() or 0

    completed = (
        await db.execute(
            select(func.count(ABExperiment.id)).where(
                ABExperiment.status == ExperimentStatus.COMPLETED
            )
        )
    ).scalar() or 0

    avg_ratio = (
        await db.execute(
            select(func.avg(ABExperiment.traffic_ratio)).where(
                ABExperiment.status == ExperimentStatus.RUNNING
            )
        )
    ).scalar()

    return {
        "total_experiments": total,
        "running": running,
        "completed": completed,
        "avg_traffic_ratio": round(float(avg_ratio or 0.5), 4),
    }
