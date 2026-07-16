"""
公平性约束服务 —— 肤色调分布分析与冷启动策略。
用 CLIP Zero-shot 评估生成图片的肤色多样性，防 AI 偏见。
"""

import asyncio
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.logging import logger
from app.services.embedding_service import compute_similarity, encode_image, encode_text

# 肤色分类标签
SKIN_TONE_LABELS = [
    "light skin tone person",
    "medium skin tone person",
    "dark skin tone person",
    "no person",
]

MARKET_DEMOGRAPHICS = settings.FAIRNESS_MARKET_BASELINES

DEVIATION_THRESHOLD = settings.FAIRNESS_DEVIATION_THRESHOLD
SKIN_TONE_KEYS = {"light", "medium", "dark", "no_person"}


def _distribution_metrics(distribution: dict[str, int], market: str | None) -> dict:
    """计算分布指标：比例 / 预期 / 偏差 / 告警。"""
    comparable_total = sum(
        distribution.get(key, 0) for key in ("light", "medium", "dark", "no_person")
    )
    ratios = {
        key: distribution.get(key, 0) / comparable_total if comparable_total else 0
        for key in ("light", "medium", "dark")
    }
    demo = MARKET_DEMOGRAPHICS.get(market or "default", MARKET_DEMOGRAPHICS["default"])
    deviations = {
        key: abs(ratios[key] - demo[key]) for key in ("light", "medium", "dark")
    }
    return {
        "ratios": ratios,
        "expected_demographics": demo,
        "baseline_source": settings.FAIRNESS_BASELINE_SOURCE,
        "deviations": deviations,
        "fairness_alert": max(deviations.values(), default=0) > DEVIATION_THRESHOLD,
    }


async def _classify_skin_tone(image_path: str) -> str:
    """CLIP Zero-shot 肤色分类。
    
    这段 AI 写的，对"no person"的区分度有时候不太行。
    """
    try:
        image_vector = await asyncio.to_thread(encode_image, image_path)
    except Exception as e:
        logger.warning(f"图片编码失败 {image_path}: {e}")
        return "unknown"

    label_vectors = []
    for label in SKIN_TONE_LABELS:
        try:
            vec = await asyncio.to_thread(encode_text, label)
            label_vectors.append(vec)
        except Exception as e:
            logger.warning(f"文本编码失败 '{label}': {e}")
            return "unknown"

    best_label = None
    best_score = -1.0
    for label, vec in zip(SKIN_TONE_LABELS, label_vectors, strict=False):
        score = compute_similarity(image_vector, vec)
        if score > best_score:
            best_score = score
            best_label = label

    mapping = {
        "light skin tone person": "light",
        "medium skin tone person": "medium",
        "dark skin tone person": "dark",
        "no person": "no_person",
    }
    return mapping.get(best_label, "unknown")


async def _classify_images(db: AsyncSession, images: list) -> list[str]:
    """复用持久化标签，限制单次 CLIP 推理量。"""
    from app.services.storage_service import resolve_image_url

    labels: list[str] = []
    fresh_classifications = 0
    updated = False
    for image in images:
        quality = image.quality_scores if isinstance(image.quality_scores, dict) else {}
        cached = quality.get("skin_tone")
        if cached in SKIN_TONE_KEYS:
            labels.append(cached)
            continue
        if fresh_classifications >= settings.FAIRNESS_MAX_CLASSIFICATIONS_PER_REQUEST:
            labels.append("unknown")
            continue

        label = await _classify_skin_tone(await resolve_image_url(image))
        fresh_classifications += 1
        labels.append(label)
        if label in SKIN_TONE_KEYS:
            image.quality_scores = {**quality, "skin_tone": label}
            updated = True

    if updated:
        await db.commit()
    return labels


async def detect_skin_tone_distribution(
    db: AsyncSession,
    market: str | None = None,
    category: str | None = None,
) -> dict:
    """分析所有生成图片的肤色分布，超过偏差阈值触发告警。"""
    from app.models.image import GeneratedImage, ImageScheme
    from app.models.product import Product

    query = (
        select(GeneratedImage)
        .join(ImageScheme, GeneratedImage.scheme_id == ImageScheme.id)
        .join(Product, ImageScheme.product_id == Product.id)
        .where(GeneratedImage.image_url != "")
    )

    if market:
        query = query.where(GeneratedImage.market_variant == market)
    if category:
        query = query.where(Product.category == category)

    result = await db.execute(query)
    images = result.scalars().all()

    if not images:
        demo = MARKET_DEMOGRAPHICS.get(market or "default", MARKET_DEMOGRAPHICS["default"])
        return {
            "total_images": 0,
            "distribution": {"light": 0, "medium": 0, "dark": 0, "no_person": 0, "unknown": 0},
            "fairness_alert": False,
            "alert_details": None,
            "recommendation": "尚未生成足够图片，无法评估分布。建议先生成至少 20 张图片后再检查。",
            "expected_demographics": demo,
            "baseline_source": settings.FAIRNESS_BASELINE_SOURCE,
        }

    distribution = {"light": 0, "medium": 0, "dark": 0, "no_person": 0, "unknown": 0}
    for label in await _classify_images(db, images):
        distribution[label] = distribution.get(label, 0) + 1

    total = sum(distribution.values())

    metrics = _distribution_metrics(distribution, market)
    ratios = metrics["ratios"]
    demo = metrics["expected_demographics"]
    deviations = metrics["deviations"]
    most_biased = max(deviations, key=deviations.get)

    fairness_alert = metrics["fairness_alert"]

    alert_details = None
    recommendation = "当前肤色分布与目标市场人口统计基本匹配，无需调整。"

    if fairness_alert:
        tone_display = {"light": "浅肤色", "medium": "中等肤色", "dark": "深肤色"}
        alert_details = (
            f"{tone_display[most_biased]}图片占比 {ratios[most_biased]:.1%}，"
            f"与目标市场预期 {demo[most_biased]:.1%} 之间偏差 {deviations[most_biased]:.1%}，"
            f"超过 {DEVIATION_THRESHOLD:.0%} 阈值。"
        )
        if ratios[most_biased] > demo[most_biased]:
            recommendation = (
                f"建议提高 {[k for k in tone_display if k != most_biased][0]} 和/或 "
                f"{[k for k in tone_display if k != most_biased][1]} 肤色模特图片的生成比例，"
                f"补充相应市场参考图素材。"
            )
        else:
            recommendation = (
                f"建议增加 {tone_display[most_biased]} 肤色内容的生成数量，"
                f"可通过调整 Prompt 或增加该肤色参考图来改善。"
            )

    logger.info(
        "肤色分布分析完成",
        total=total,
        distribution=distribution,
        fairness_alert=fairness_alert,
        market=market,
    )

    return {
        "total_images": total,
        "distribution": distribution,
        "fairness_alert": fairness_alert,
        "alert_details": alert_details,
        "recommendation": recommendation,
        "expected_demographics": demo,
        "baseline_source": settings.FAIRNESS_BASELINE_SOURCE,
        "deviations": deviations,
    }


async def check_fairness_for_scheme(
    db: AsyncSession,
    scheme_id: int,
) -> dict:
    """检查指定方案是否通过公平性约束。"""
    from app.models.image import ImageScheme

    scheme_result = await db.execute(
        select(ImageScheme).where(ImageScheme.id == scheme_id)
    )
    scheme = scheme_result.scalar_one_or_none()

    if not scheme:
        return {
            "scheme_id": scheme_id,
            "market": None,
            "passes_fairness": True,
            "current_distribution": {},
            "details": f"方案 #{scheme_id} 不存在",
        }

    from app.models.image import GeneratedImage

    images_result = await db.execute(
        select(GeneratedImage).where(
            GeneratedImage.scheme_id == scheme_id,
            GeneratedImage.image_url != "",
        )
    )
    images = images_result.scalars().all()

    if not images:
        return {
            "scheme_id": scheme_id,
            "market": images[0].market_variant if images else None,
            "passes_fairness": True,
            "current_distribution": {},
            "details": "该方案尚未生成任何已完成的图片。",
        }

    market = images[0].market_variant

    distribution_result = await detect_skin_tone_distribution(
        db, market=market
    )

    return {
        "scheme_id": scheme_id,
        "market": market,
        "passes_fairness": not distribution_result["fairness_alert"],
        "current_distribution": distribution_result["distribution"],
        "details": (
            "该方案所在市场的肤色分布符合公平性要求。"
            if not distribution_result["fairness_alert"]
            else distribution_result["alert_details"]
        ),
        "expected_demographics": distribution_result.get("expected_demographics"),
    }


async def get_fairness_report(
    db: AsyncSession,
    market: str,
    date_range_days: int = 30,
) -> dict:
    """生成指定市场的公平性报告。"""
    from app.models.image import GeneratedImage

    cutoff_date = datetime.utcnow() - timedelta(days=date_range_days)

    query = select(GeneratedImage).where(
        GeneratedImage.market_variant == market,
        GeneratedImage.image_url != "",
        GeneratedImage.created_at >= cutoff_date,
    )

    result = await db.execute(query)
    images = result.scalars().all()

    distribution = {"light": 0, "medium": 0, "dark": 0, "no_person": 0, "unknown": 0}
    for label in await _classify_images(db, images):
        distribution[label] = distribution.get(label, 0) + 1

    total = sum(distribution.values())
    summary = _distribution_metrics(distribution, market)
    recommendation = (
        "该时间范围内的肤色分布与目标市场基准偏差超过阈值，建议复核分类结果与基准来源后再调整生成策略。"
        if summary["fairness_alert"]
        else "该时间范围内的肤色分布未超过当前偏差阈值。"
    )

    logger.info(
        "公平性报告已生成",
        market=market,
        date_range_days=date_range_days,
        total=total,
        alert=summary["fairness_alert"],
    )

    return {
        "market": market,
        "date_range_days": date_range_days,
        "total_images": total,
        "distribution": distribution,
        "expected_demographics": summary["expected_demographics"],
        "baseline_source": settings.FAIRNESS_BASELINE_SOURCE,
        "deviations": summary["deviations"],
        "fairness_alert": summary["fairness_alert"],
        "recommendation": recommendation,
        "generated_at": datetime.utcnow().isoformat(),
    }


async def get_all_markets_report(
    db: AsyncSession,
    markets: list[str] | None = None,
) -> dict:
    """一次性分类所有图片，按市场分组对比报告。"""
    from app.models.image import GeneratedImage

    query = select(GeneratedImage).where(GeneratedImage.image_url != "")
    result = await db.execute(query)
    images = result.scalars().all()

    market_labels: dict[str, list[str]] = {}
    labels = await _classify_images(db, images)
    for image, label in zip(images, labels, strict=True):
        market = image.market_variant or "default"
        if market not in market_labels:
            market_labels[market] = []
        market_labels[market].append(label)

    market_reports = []
    for market in (markets or ["us", "eu", "me", "seasia"]):
        labels = market_labels.get(market, [])

        dist = {"light": 0, "medium": 0, "dark": 0, "no_person": 0, "unknown": 0}
        for label in labels:
            dist[label] = dist.get(label, 0) + 1

        summary = _distribution_metrics(dist, market)
        demo = summary["expected_demographics"]
        actual = summary["ratios"]
        expected = {
            "light": demo.get("light", 0),
            "medium": demo.get("medium", 0),
            "dark": demo.get("dark", 0),
        }
        deviations = summary["deviations"]

        market_reports.append({
            "market": market,
            "expected": expected,
            "actual": actual,
            "deviation": deviations,
            "baseline_source": settings.FAIRNESS_BASELINE_SOURCE,
        })

    logger.info(
        "全市场公平性报告已生成",
        markets=[m["market"] for m in market_reports],
        total_images=len(images),
    )

    return {"markets": market_reports}
