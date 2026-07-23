"""
数据飞轮闭环 —— 线上效果数据回流 → 自动标注 → 模型迭代。
形成"生成→上线→反馈→优化"的闭环。
"""

import ast
import json
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.models import (
    GeneratedImage,
    ImageScheme,
    ModelFeedbackLabel,
    Product,
    ProductEmbedding,
)

# 自动标注分位阈值
POSITIVE_PERCENTILE = 75   # CTR 前 25%
NEGATIVE_PERCENTILE = 25   # CTR 后 25%
HIGH_RETURN_THRESHOLD = 0.10  # 退货率超 10% 标为风险

MIN_TRAINING_SAMPLES = 50


async def aggregate_performance_data(
    db: AsyncSession,
    days: int = 30,
) -> list[dict[str, Any]]:
    """数据回流：聚合每张图片在指定窗口内的累计表现。

    TODO: 关联 product_embeddings 的 CLIP 向量解析用了 ast.literal_eval，
    性能不好，量大了要改成批量 numpy 反序列化。
    """
    cutoff_date = date.today() - timedelta(days=days)

    stmt = (
        select(
            ModelFeedbackLabel.image_id,
            func.sum(ModelFeedbackLabel.impressions).label("total_impressions"),
            func.sum(ModelFeedbackLabel.clicks).label("total_clicks"),
            (
                func.sum(ModelFeedbackLabel.clicks)
                / func.nullif(func.sum(ModelFeedbackLabel.impressions), 0)
            ).label("avg_ctr"),
            literal(0.0).label("avg_cvr"),
            literal(0.0).label("avg_return_rate"),
            literal(0.0).label("total_revenue"),
        )
        .where(
            ModelFeedbackLabel.status == "mature",
            ModelFeedbackLabel.observation_end >= cutoff_date,
        )
        .group_by(ModelFeedbackLabel.image_id)
    )

    rows = (await db.execute(stmt)).all()

    if not rows:
        logger.info("数据回流无数据", days=days)
        return []

    image_ids = [row.image_id for row in rows]

    img_stmt = (
        select(
            GeneratedImage.id,
            GeneratedImage.scheme_id,
            GeneratedImage.market_variant,
            GeneratedImage.quality_scores,
            GeneratedImage.generation_params,
            GeneratedImage.overall_score,
            ImageScheme.product_id,
            Product.category,
            Product.price_range,
        )
        .join(ImageScheme, ImageScheme.id == GeneratedImage.scheme_id)
        .join(Product, Product.id == ImageScheme.product_id)
        .where(GeneratedImage.id.in_(image_ids))
    )

    img_rows = (await db.execute(img_stmt)).all()
    img_map = {r.id: r for r in img_rows}

    product_ids = list({r.product_id for r in img_rows if r.product_id is not None})
    embedding_map: dict[int, list[float]] = {}
    if product_ids:
        emb_stmt = (
            select(ProductEmbedding.product_id, ProductEmbedding.embedding)
            .where(ProductEmbedding.product_id.in_(product_ids))
        )
        emb_rows = (await db.execute(emb_stmt)).all()
        for er in emb_rows:
            if not er.embedding:
                continue
            try:
                vec = json.loads(er.embedding)
                embedding_map[er.product_id] = [float(v) for v in vec]
            except (ValueError, TypeError):
                try:
                    vec = ast.literal_eval(er.embedding)
                    embedding_map[er.product_id] = [float(v) for v in vec]
                except (ValueError, SyntaxError, TypeError):
                    logger.warning("embedding 解析失败", product_id=er.product_id)

    results = []
    for row in rows:
        img = img_map.get(row.image_id)
        if img is None:
            continue

        total_imp = int(row.total_impressions or 0)
        total_clicks = int(row.total_clicks or 0)

        results.append({
            "image_id": row.image_id,
            "scheme_id": img.scheme_id,
            "product_id": img.product_id,
            "category": img.category,
            "market": img.market_variant or "us",
            "price_range": img.price_range or "mid",
            "total_impressions": total_imp,
            "total_clicks": total_clicks,
            "avg_ctr": round(float(row.avg_ctr or 0), 4),
            "avg_cvr": round(float(row.avg_cvr or 0), 4),
            "avg_return_rate": round(float(row.avg_return_rate or 0), 4),
            "total_revenue": round(float(row.total_revenue or 0), 2),
            "quality_scores": img.quality_scores or {},
            "generation_params": img.generation_params or {},
            "overall_score": float(img.overall_score or 0),
            "clip_embedding": embedding_map.get(img.product_id),
        })

    logger.info(
        "数据回流完成",
        days=days,
        images_aggregated=len(results),
        total_impressions=sum(r["total_impressions"] for r in results),
    )

    return results


async def auto_label_samples(
    db: AsyncSession,
    performance_data: list[dict[str, Any]] | None = None,
    days: int = 30,
) -> dict[str, Any]:
    """Build training targets from immutable feedback labels without rewriting predictions."""
    if performance_data is None:
        performance_data = await aggregate_performance_data(db, days)

    if len(performance_data) < 10:
        logger.warning("样本量不足，跳过自动标注", count=len(performance_data))
        return {
            "total_samples": len(performance_data),
            "positive_samples": 0,
            "negative_samples": 0,
            "neutral_samples": len(performance_data),
            "note": "样本量不足，至少需要 10 条",
        }

    ctres = sorted([d["avg_ctr"] for d in performance_data])
    n = len(ctres)
    p25_idx = int(n * 0.25)
    p75_idx = int(n * 0.75)
    ctr_p25 = ctres[p25_idx]
    ctr_p75 = ctres[p75_idx]

    positive = 0
    negative = 0
    neutral = 0
    training_X = []
    training_y_ctr = []
    training_y_hit = []
    training_y_return = []

    for data in performance_data:
        ctr = data["avg_ctr"]

        is_positive = ctr >= ctr_p75
        is_negative = ctr <= ctr_p25

        if is_positive:
            label = 1
            positive += 1
        elif is_negative:
            label = 0
            negative += 1
        else:
            label = 0
            neutral += 1

        features = _build_training_features(data, data.get("clip_embedding"))
        training_X.append(features)
        training_y_ctr.append(ctr)
        training_y_hit.append(float(label))
        training_y_return.append(0)

    logger.info(
        "自动标注完成",
        total=len(performance_data),
        positive=positive,
        negative=negative,
        neutral=neutral,
        ctr_p25=ctr_p25,
        ctr_p75=ctr_p75,
    )

    return {
        "total_samples": len(performance_data),
        "positive_samples": positive,
        "negative_samples": negative,
        "neutral_samples": neutral,
        "ctr_p75": round(ctr_p75, 4),
        "ctr_p25": round(ctr_p25, 4),
        "training_data": {
            "X": training_X,
            "y_ctr": training_y_ctr,
            "y_hit": training_y_hit,
            "y_return": training_y_return,
        },
    }


def _build_training_features(
    data: dict,
    clip_embedding: list[float] | None = None,
) -> list[float]:
    """从效果数据构建训练特征，委托给 predictor.extract_features 保证对齐。"""
    from app.services.predictor import predictor

    quality = data.get("quality_scores", {})
    l2 = quality.get("l2", {}) if isinstance(quality, dict) else {}
    l2_dims = l2.get("dimensions", {}) if isinstance(l2, dict) else {}
    complexity = l2_dims.get("sharpness", 50) / 100.0

    l3 = quality.get("l3", {}) if isinstance(quality, dict) else {}
    color_harmony = l3.get("color_harmony", 0) / 100.0 if isinstance(l3, dict) else 0.0
    color_histogram = [color_harmony, 0.0, 0.0, 0.0, 0.0]

    return predictor.extract_features(
        category=data.get("category", ""),
        price_range=data.get("price_range", "mid"),
        market=data.get("market", "us"),
        color_histogram=color_histogram,
        complexity=complexity,
        similar_ctr_mean=0.02,
        clip_embedding=clip_embedding,
        image_url=None,
    )


async def trigger_model_retraining(
    db: AsyncSession,
    days: int = 30,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """模型迭代：聚合数据 → 标注 → 训练预测器 → 保存新版本。"""
    label_result = await auto_label_samples(db, days=days)

    total_samples = label_result.get("total_samples", 0)
    if total_samples < MIN_TRAINING_SAMPLES:
        logger.info(
            "模型迭代跳过：样本量不足",
            samples=total_samples,
            min_required=MIN_TRAINING_SAMPLES,
        )
        return {
            "status": "skipped",
            "samples": total_samples,
            "model_saved": False,
            "message": f"样本量 {total_samples} 不足，至少需要 {MIN_TRAINING_SAMPLES}",
        }

    training_data = label_result.get("training_data", {})
    X = training_data.get("X", [])
    y_ctr = training_data.get("y_ctr", [])
    y_hit = training_data.get("y_hit", [])
    y_return = training_data.get("y_return", [])

    if len(X) < MIN_TRAINING_SAMPLES:
        return {
            "status": "skipped",
            "samples": len(X),
            "model_saved": False,
            "message": "训练样本不足",
        }

    import asyncio

    import numpy as np

    def _train_sync():
        from app.services.predictor import CTRPredictor

        predictor = CTRPredictor.for_tenant(tenant_id) if tenant_id else CTRPredictor()
        X_arr = np.array(X)
        y_ctr_arr = np.array(y_ctr)
        y_hit_arr = np.array(y_hit)
        y_return_arr = np.array(y_return) if y_return else None

        predictor.train(X_arr, y_ctr_arr, y_hit_arr, y_return_arr)
        predictor.save()

        return {
            "model_saved": True,
            "features_count": len(X_arr),
            "ctr_mean": float(np.mean(y_ctr_arr)),
            "hit_rate": float(np.mean(y_hit_arr)),
        }

    try:
        train_result = await asyncio.to_thread(_train_sync)

        logger.info(
            "模型迭代完成",
            samples=total_samples,
            positive=label_result.get("positive_samples", 0),
            **train_result,
        )

        return {
            "status": "success",
            "samples": total_samples,
            "positive_samples": label_result.get("positive_samples", 0),
            "negative_samples": label_result.get("negative_samples", 0),
            "model_saved": train_result["model_saved"],
            "ctr_mean": round(train_result["ctr_mean"], 4),
            "hit_rate": round(train_result["hit_rate"], 4),
            "message": f"模型训练完成，样本量 {total_samples}",
        }

    except Exception as e:
        logger.error("模型迭代失败", error=str(e))
        return {
            "status": "failed",
            "samples": total_samples,
            "model_saved": False,
            "message": f"训练失败: {e}",
        }
