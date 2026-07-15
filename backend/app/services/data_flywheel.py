"""
数据飞轮闭环服务

将线上效果数据回流为训练样本，自动标注正/负样本，
定期触发模型迭代，形成"生成→上线→反馈→优化"的闭环。

核心流程：
1. aggregate_performance_data()  数据回流
   从 daily_metrics 聚合每张图片的累计表现
2. auto_label_samples()          自动标注
   按 CTR 分位数标注正/负样本，按退货率标注风险样本
3. trigger_model_retraining()    模型迭代
   用标注数据训练 predictor，保存新版本
"""

import ast
import hashlib
import json
from datetime import date, timedelta
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.models import (
    DailyMetric,
    GeneratedImage,
    ImageScheme,
    PredictionRecord,
    Product,
    ProductEmbedding,
    ReturnRiskLevel,
)

# 自动标注的分位阈值
POSITIVE_PERCENTILE = 75   # CTR 前 25% 标为正样本
NEGATIVE_PERCENTILE = 25   # CTR 后 25% 标为负样本
HIGH_RETURN_THRESHOLD = 0.10  # 退货率超过 10% 标为风险样本

# 最小样本量，低于此值不触发训练
MIN_TRAINING_SAMPLES = 50


async def aggregate_performance_data(
    db: AsyncSession,
    days: int = 30,
) -> list[dict[str, Any]]:
    """数据回流：聚合线上效果数据

    从 daily_metrics 聚合每张图片在指定时间窗口内的累计表现，
    关联 generated_images 获取图片属性，关联 products 获取商品品类/市场。

    Args:
        db: 异步数据库会话
        days: 回溯天数（默认 30 天）

    Returns:
        [
            {
                "image_id": int,
                "scheme_id": int,
                "product_id": int,
                "category": str,
                "market": str,
                "price_range": str,
                "total_impressions": int,
                "total_clicks": int,
                "avg_ctr": float,
                "avg_cvr": float,
                "avg_return_rate": float,
                "total_revenue": float,
                "quality_scores": dict,
                "generation_params": dict,
            },
            ...
        ]
    """
    cutoff_date = date.today() - timedelta(days=days)

    # 聚合每张图片的指标
    stmt = (
        select(
            DailyMetric.image_id,
            func.sum(DailyMetric.impressions).label("total_impressions"),
            func.sum(DailyMetric.clicks).label("total_clicks"),
            (
                func.sum(DailyMetric.clicks)
                / func.nullif(func.sum(DailyMetric.impressions), 0)
            ).label("avg_ctr"),
            func.avg(DailyMetric.cvr).label("avg_cvr"),
            func.avg(DailyMetric.return_rate).label("avg_return_rate"),
            func.sum(DailyMetric.revenue).label("total_revenue"),
        )
        .where(DailyMetric.date >= cutoff_date)
        .group_by(DailyMetric.image_id)
    )

    rows = (await db.execute(stmt)).all()

    if not rows:
        logger.info("数据回流无数据", days=days)
        return []

    # 收集所有 image_id 用于批量查图片信息
    image_ids = [row.image_id for row in rows]

    # 查图片+方案+商品信息
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

    # 查 product_embeddings：按 product_id 批量获取 CLIP embedding
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
            # embedding 字段存的是 "[0.1,0.2,...]" 字符串，解析为 list[float]
            try:
                vec = ast.literal_eval(er.embedding)
                embedding_map[er.product_id] = [float(v) for v in vec]
            except (ValueError, SyntaxError):
                # 兼容 JSON 格式
                try:
                    vec = json.loads(er.embedding)
                    embedding_map[er.product_id] = [float(v) for v in vec]
                except (ValueError, TypeError):
                    logger.warning("embedding 解析失败", product_id=er.product_id)

    # 组装结果
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
    """自动标注正/负样本

    根据效果数据自动标注：
    - CTR > P75 → 正样本（label=1），标记为"爆款候选"
    - CTR < P25 → 负样本（label=0），标记为"效果不佳"
    - return_rate > 10% → 负样本（label=0），标记为"高退货风险"

    标注结果写入 prediction_records 表（复用该表存储反馈标注）。

    Args:
        db: 异步数据库会话
        performance_data: 预聚合的效果数据（未提供时自动调用 aggregate）
        days: 回溯天数

    Returns:
        {
            "total_samples": int,
            "positive_samples": int,
            "negative_samples": int,
            "neutral_samples": int,
            "high_return_samples": int,
            "ctr_p75": float,
            "ctr_p25": float,
            "training_data": {"X": [...], "y_ctr": [...], "y_hit": [...]},
        }
    """
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

    # 计算 CTR 分位数
    ctres = sorted([d["avg_ctr"] for d in performance_data])
    n = len(ctres)
    p25_idx = int(n * 0.25)
    p75_idx = int(n * 0.75)
    ctr_p25 = ctres[p25_idx]
    ctr_p75 = ctres[p75_idx]

    positive = 0
    negative = 0
    neutral = 0
    high_return = 0

    # 准备训练数据
    training_X = []
    training_y_ctr = []
    training_y_hit = []
    training_y_return = []

    # 提取 image_ids（用于并发锁和清理旧标注）
    image_ids = [d["image_id"] for d in performance_data]

    # 使用 PostgreSQL 事务级 advisory lock 防止并发标注冲突
    # 同一批 image_ids 的标注操作串行化，避免 DELETE+INSERT 竞态丢数据
    lock_digest = hashlib.sha256(
        ",".join(str(image_id) for image_id in sorted(image_ids)).encode("ascii")
    ).digest()
    lock_key = int.from_bytes(lock_digest[:4], byteorder="big") & 0x7FFFFFFF
    lock_result = await db.execute(
        select(func.pg_try_advisory_xact_lock(lock_key))
    )
    if not lock_result.scalar():
        logger.warning("标注锁冲突，跳过本批次", image_count=len(image_ids))
        return {
            "total_samples": len(performance_data),
            "positive_samples": 0,
            "negative_samples": 0,
            "neutral_samples": len(performance_data),
            "note": "并发标注冲突，请稍后重试",
        }

    # 清理旧的反馈标注（同一批 image_id）
    # 只删除反馈标注（ctr_confidence_interval 含 "source": "actual"），
    # 保留模型预测记录（ctr_confidence_interval 格式为 {"lower": ..., "upper": ...}）
    await db.execute(
        PredictionRecord.__table__.delete().where(
            and_(
                PredictionRecord.image_id.in_(image_ids),
                PredictionRecord.ctr_confidence_interval["source"].as_string() == "actual",
            )
        )
    )

    for data in performance_data:
        ctr = data["avg_ctr"]
        return_rate = data["avg_return_rate"]

        # 标注逻辑
        is_positive = ctr >= ctr_p75
        is_negative = ctr <= ctr_p25
        is_high_return = return_rate > HIGH_RETURN_THRESHOLD

        if is_positive:
            label = 1
            positive += 1
        elif is_negative or is_high_return:
            label = 0
            negative += 1
        else:
            label = 0  # 中间样本标为 0，不进入正样本
            neutral += 1

        if is_high_return:
            high_return += 1

        # 写入 prediction_records 作为反馈标注
        risk_level = ReturnRiskLevel.HIGH if is_high_return else (
            ReturnRiskLevel.LOW if is_positive else ReturnRiskLevel.MEDIUM
        )

        record = PredictionRecord(
            image_id=data["image_id"],
            predicted_ctr=ctr,
            ctr_confidence_interval={"source": "actual", "p25": ctr_p25, "p75": ctr_p75},
            predicted_hit_probability=float(label),
            return_risk_level=risk_level,
        )
        db.add(record)

        # 构建训练特征（手工特征 + CLIP embedding 融合）
        features = _build_training_features(data, data.get("clip_embedding"))
        training_X.append(features)
        training_y_ctr.append(ctr)
        training_y_hit.append(float(label))
        # 退货标签：return_rate > 8% 标记为高风险（label=1）
        training_y_return.append(1 if return_rate > 0.08 else 0)

    await db.commit()

    logger.info(
        "自动标注完成",
        total=len(performance_data),
        positive=positive,
        negative=negative,
        neutral=neutral,
        high_return=high_return,
        ctr_p25=ctr_p25,
        ctr_p75=ctr_p75,
    )

    return {
        "total_samples": len(performance_data),
        "positive_samples": positive,
        "negative_samples": negative,
        "neutral_samples": neutral,
        "high_return_samples": high_return,
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
    """从效果数据构建训练特征

    委托给 predictor.extract_features 确保训练/推理特征完全对齐。
    回流数据中无 image_url，视觉特征（拍摄角度/模特数量等 12 维）使用默认值。
    """
    from app.services.predictor import predictor

    # 从 quality_scores 提取 complexity 和 color_histogram
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
        # 线上推理尚未接入“相似商品 CTR”查询，训练时也必须使用同一默认值，
        # 否则把当前样本真实 CTR 同时作为特征和标签会造成直接目标泄漏。
        similar_ctr_mean=0.02,
        clip_embedding=clip_embedding,
        image_url=None,  # 回流数据无 image_url，视觉特征用默认值
    )


async def trigger_model_retraining(
    db: AsyncSession,
    days: int = 30,
) -> dict[str, Any]:
    """模型迭代：用回流数据重新训练预测模型

    流程：
    1. 聚合效果数据
    2. 自动标注正/负样本
    3. 训练 CTRPredictor
    4. 保存新版本

    Args:
        db: 异步数据库会话
        days: 回溯天数

    Returns:
        {
            "status": "success|skipped|failed",
            "samples": int,
            "positive_samples": int,
            "model_saved": bool,
            "message": str,
        }
    """
    # 1. 数据回流 + 自动标注
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

    # 2. 训练模型（在线程池中执行，避免阻塞事件循环）
    import asyncio

    import numpy as np

    def _train_sync():
        from app.services.predictor import CTRPredictor

        predictor = CTRPredictor()
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
