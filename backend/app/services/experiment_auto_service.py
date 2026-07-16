"""
A/B 实验自动创建与 UCB 流量分配。
auto_create_experiments 扫描已审核图片找预测分接近的两张建实验，
update_traffic_allocation 用 UCB 算法动态调整流量比例。
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

# 自动实验参数
CTR_DIFF_THRESHOLD = 0.02  # 预测 CTR 差距小于此值才建实验
MAX_RUNNING_EXPERIMENTS_PER_PRODUCT = 1
MIN_IMAGES_FOR_EXPERIMENT = 2

# UCB 参数
MIN_IMPRESSIONS_FOR_UCB = 100
TRAFFIC_RATIO_MIN = 0.2
TRAFFIC_RATIO_MAX = 0.8


async def auto_create_experiments(db: AsyncSession) -> dict[str, Any]:
    """扫描已审核通过的图片，按商品找预测 CTR 最接近的两张创建 A/B 实验。"""
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

        # 找相邻两张 CTR 差距最小的
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

        if min_diff > CTR_DIFF_THRESHOLD:
            skipped_insufficient += 1
            details.append({
                "product_id": product_id,
                "action": "skipped_diff_too_large",
                "ctr_diff": round(min_diff, 4),
            })
            continue

        experiment = ABExperiment(
            product_id=product_id,
            variant_a_image_id=img_a["image_id"],
            variant_b_image_id=img_b["image_id"],
            traffic_ratio=0.5,
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
    """UCB 算法动态调整流量比例。
    
    探索阶段（曝光 < 100）保持 50/50，利用阶段按 UCB 上界分配。
    FIXME: 达到样本上限自动结束的逻辑跟 stop_experiment 的 STOPPED 语义有重叠。
    """
    exp = await db.get(ABExperiment, experiment_id)
    if not exp:
        raise ValueError(f"实验 #{experiment_id} 不存在")

    if exp.status != ExperimentStatus.RUNNING:
        raise ValueError(f"实验 #{experiment_id} 非运行中状态，当前: {exp.status}")

    old_ratio = float(exp.traffic_ratio or 0.5)

    metrics_a = await _aggregate_image_metrics(db, exp.variant_a_image_id)
    metrics_b = await _aggregate_image_metrics(db, exp.variant_b_image_id)

    total_impressions = metrics_a["impressions"] + metrics_b["impressions"]

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

    if total_impressions < MIN_IMPRESSIONS_FOR_UCB:
        new_ratio = 0.5
        method = "default_explore"
    else:
        ctr_a = metrics_a["clicks"] / max(metrics_a["impressions"], 1)
        ctr_b = metrics_b["clicks"] / max(metrics_b["impressions"], 1)

        n = total_impressions
        n_a = max(metrics_a["impressions"], 1)
        n_b = max(metrics_b["impressions"], 1)

        ucb_a = ctr_a + math.sqrt(2 * math.log(n) / n_a)
        ucb_b = ctr_b + math.sqrt(2 * math.log(n) / n_b)

        total_ucb = ucb_a + ucb_b
        new_ratio = ucb_a / total_ucb if total_ucb > 0 else 0.5
        new_ratio = max(TRAFFIC_RATIO_MIN, min(TRAFFIC_RATIO_MAX, new_ratio))
        method = "ucb"

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
    """批量更新所有运行中实验的流量分配（Celery 定时任务）。"""
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
    """查询自动实验统计概览。"""
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
