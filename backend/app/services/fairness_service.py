"""
公平性约束服务 —— 皮肤色调分布分析与冷启动策略（1.6）

使用 CLIP Zero-shot 分类评估生成图片的肤色多样性，确保跨市场
视觉内容公平，避免 AI 偏见导致的单一肤色调主导问题。

流程：
  1. 从数据库查询已生成的图片并过滤
  2. 使用 CLIP 模型以零样本方式按肤色标签分类
  3. 与预期市场人口统计分布进行比较
  4. 当偏差超过 30% 时触发公平性告警
"""

import asyncio
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.logging import logger
from app.services.embedding_service import compute_similarity, encode_image, encode_text

# 肤色分类标签 — CLIP Zero-shot 使用
SKIN_TONE_LABELS = [
    "light skin tone person",
    "medium skin tone person",
    "dark skin tone person",
    "no person",
]

# 每个市场预期的人口统计分布（大致比例）
# 用于计算公平性偏差
MARKET_DEMOGRAPHICS = settings.FAIRNESS_MARKET_BASELINES

# 公平性告警阈值（当实际比例与预期人口分布偏差超过此值）
DEVIATION_THRESHOLD = settings.FAIRNESS_DEVIATION_THRESHOLD
SKIN_TONE_KEYS = {"light", "medium", "dark", "no_person"}


def _distribution_metrics(distribution: dict[str, int], market: str | None) -> dict:
    """计算可比较的分布指标，分类失败的图片不进入比例分母。"""
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
    """使用 CLIP Zero-shot 将单张图片按肤色进行分类。

    将图片嵌入向量与四个肤色描述标签的文本嵌入向量进行比对，
    返回余弦相似度最高的标签。

    支持 HTTP(S) URL 和本地路径：URL 会先下载到临时文件再编码。

    Returns:
        "light", "medium", "dark", 或 "no_person"
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

    # 将 CLIP 标签映射回内部键值
    mapping = {
        "light skin tone person": "light",
        "medium skin tone person": "medium",
        "dark skin tone person": "dark",
        "no person": "no_person",
    }
    return mapping.get(best_label, "unknown")


async def _classify_images(db: AsyncSession, images: list) -> list[str]:
    """复用持久化标签，并限制单次请求中新触发的 CLIP 推理量。"""
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
    """分析所有生成图片的肤色分布。

    使用 CLIP Zero-shot 分类（基于肤色相关标签）估计表征多样性。

    Args:
        db: 数据库会话
        market: 可选的目标市场过滤（us/eu/me/seasia）
        category: 可选品类过滤

    Returns:
        {
            "total_images": int,
            "distribution": {"light": int, "medium": int, "dark": int, "no_person": int, "unknown": int},
            "fairness_alert": bool,
            "alert_details": str | None,
            "recommendation": str,
        }
    """
    from app.models.image import GeneratedImage, ImageScheme
    from app.models.product import Product

    # 构建需要分析图片的查询
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

    # 生成告警详情
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
    """检查指定方案是否通过公平性约束。

    获取方案的 market_variant，然后分析该市场相关图片的肤色分布，
    返回该方案在当前分布背景下的公平性评估。

    Args:
        db: 数据库会话
        scheme_id: 方案 ID

    Returns:
        {
            "scheme_id": int,
            "market": str,
            "passes_fairness": bool,
            "current_distribution": dict,
            "details": str,
        }
    """
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

    # 查找该方案关联的所有已生成图片
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

    # 获取该市场的整体分布
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
    """生成指定市场的综合公平性报告。

    分析指定市场在给定时间窗口内的所有生成图片，
    提供肤色分布、偏差、趋势和可行性建议。

    Args:
        db: 数据库会话
        market: 目标市场（us/eu/me/seasia）
        date_range_days: 回溯天数

    Returns:
        {
            "market": str,
            "date_range_days": int,
            "total_images": int,
            "distribution": dict,
            "expected_demographics": dict,
            "deviations": dict,
            "fairness_alert": bool,
            "recommendation": str,
            "generated_at": str,
        }
    """
    from app.models.image import GeneratedImage

    cutoff_date = datetime.utcnow() - timedelta(days=date_range_days)

    # 查询该时间窗口内该市场所有已生成的图片
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
    """一次性分类所有图片，按市场分组生成公平性对比报告。

    对每张图片仅执行一次 CLIP 分类，然后按 market_variant 分组统计，
    避免对同一图片重复下载和分类。

    Returns:
        {
            "markets": [
                {
                    "market": "us",
                    "expected": {"light": 0.55, "medium": 0.25, "dark": 0.15},
                    "actual": {"light": 0.50, "medium": 0.30, "dark": 0.20},
                    "deviation": {"light": 0.05, "medium": 0.05, "dark": 0.05},
                },
                ...
            ]
        }
    """
    from app.models.image import GeneratedImage

    query = select(GeneratedImage).where(GeneratedImage.image_url != "")
    result = await db.execute(query)
    images = result.scalars().all()

    # 按市场分组，每张图片仅分类一次
    market_labels: dict[str, list[str]] = {}
    labels = await _classify_images(db, images)
    for image, label in zip(images, labels, strict=True):
        market = image.market_variant or "default"
        if market not in market_labels:
            market_labels[market] = []
        market_labels[market].append(label)

    # 为每个已知市场生成报告
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
