"""Import local mock images as development-only CTR feedback data.

The script never calls external commerce or AI providers.  It uploads the
workspace's ``mock图片`` assets to the development MinIO bucket and creates
traceable synthetic catalog, prediction, daily metric, performance-fact and
mature-feedback records from 1 May of the current year through today.

It is intentionally a one-time, idempotent development seed: if this catalog
has already been inserted, it exits without writing duplicate business data.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import mimetypes
from collections import Counter
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

from sqlalchemy import select

from app.config import settings
from app.core.tenant import tenant_context
from app.db.session import async_session_factory
from app.models import (
    CampaignInsight,
    CommerceFact,
    ExternalEntityMapping,
    GeneratedImage,
    ImageScheme,
    ModelFeedbackLabel,
    PerformanceFact,
    PredictionRecord,
    PredictionSnapshot,
    Product,
    ProductStatus,
    ReturnRiskLevel,
    ReviewStatus,
    VisualOperationCampaign,
)
from app.models.prediction import DailyMetric
from app.services.ctr_feedback import create_mature_feedback_labels, payload_hash
from app.services.storage_service import get_minio_client, public_object_url


SEED_MARKER = "mock-catalog-2026-v1"
ASSET_ROOT = Path("/mock-assets")
MARKETS = ("us", "eu", "seasia", "me")
PLATFORMS = ("shopee", "amazon")


def _ensure_safe_environment() -> None:
    if settings.APP_ENV.lower() not in {"development", "test"}:
        raise SystemExit("Mock catalog seeding is allowed only in development/test environments.")


def _assets(asset_root: Path) -> list[Path]:
    if not asset_root.is_dir():
        raise SystemExit(
            f"Mock asset directory {asset_root} is not mounted. "
            "Use the development Docker Compose configuration."
        )
    files = sorted(path for path in asset_root.rglob("*.png") if path.is_file())
    if not files:
        raise SystemExit(f"No PNG assets found under {asset_root}.")
    return files


def _category_for(relative_path: Path) -> str:
    value = relative_path.as_posix().lower()
    if "女装" in relative_path.parts or any(
        token in value
        for token in (
            "dress", "shirt", "sweater", "cardigan", "blouse", "trouser", "jean",
            "skirt", "legging", "jacket", "tee", "bikini", "swimsuit", "coverup",
        )
    ):
        return "womens_fashion"
    if any(token in value for token in ("serum", "sunscreen", "lip", "skincare", "perfume")):
        return "beauty"
    if any(
        token in value
        for token in ("earbud", "speaker", "keyboard", "headphone", "lamp", "light", "kettle")
    ):
        return "electronics"
    if any(token in value for token in ("tote", "wallet", "umbrella", "shoe", "hanger")):
        return "accessories"
    return "home_lifestyle"


def _title_for(relative_path: Path) -> str:
    stem = relative_path.stem.replace("_", " ").replace("-", " ").strip()
    if stem.startswith("生成女装商品模特实拍图主图"):
        suffix = stem.removeprefix("生成女装商品模特实拍图主图").strip(" ()") or "01"
        return f"Mock 女装模特主图 {suffix}"
    return " ".join(piece.capitalize() for piece in stem.split())


def _price_range(category: str) -> str:
    return {
        "womens_fashion": "$24-68",
        "beauty": "$12-42",
        "electronics": "$28-95",
        "accessories": "$16-58",
        "home_lifestyle": "$14-52",
    }[category]


def _market_for(index: int) -> str:
    return MARKETS[index % len(MARKETS)]


def _review_status(index: int) -> ReviewStatus:
    if index % 17 == 0:
        return ReviewStatus.MANUAL_PENDING
    if index % 29 == 0:
        return ReviewStatus.REJECTED
    return ReviewStatus.AUTO_APPROVED


def _risk_for(index: int) -> ReturnRiskLevel:
    if index % 19 == 0:
        return ReturnRiskLevel.HIGH
    if index % 5 == 0:
        return ReturnRiskLevel.MEDIUM
    return ReturnRiskLevel.LOW


def _clip(value: float, *, lower: float = 0.0001, upper: float = 0.2) -> float:
    return round(max(lower, min(upper, value)), 4)


def _daily_values(index: int, metric_day: date, start_day: date) -> tuple[int, int, float, float, float, float, float]:
    day_index = (metric_day - start_day).days
    weekly_wave = ((day_index % 7) - 3) * 0.00035
    july_lift = 0.0016 if metric_day.month == 7 else 0.0
    base_ctr = 0.016 + ((index * 37) % 320) / 10_000
    ctr = _clip(base_ctr + weekly_wave + july_lift)
    impressions = 720 + ((index * 173 + day_index * 89) % 4_600)
    if metric_day.weekday() >= 5:
        impressions = int(impressions * 0.82)
    clicks = max(1, round(impressions * ctr))
    cvr = _clip(0.025 + ((index * 11 + day_index) % 85) / 10_000, lower=0.005, upper=0.12)
    add_to_cart = _clip(cvr + 0.022 + (index % 7) / 10_000, lower=0.01, upper=0.2)
    return_rate = _clip(0.018 + (index % 9) / 1_000, lower=0.005, upper=0.1)
    revenue = round(max(0, round(clicks * cvr)) * (18 + index % 42), 2)
    return impressions, clicks, ctr, cvr, add_to_cart, return_rate, revenue


def _put_image(asset: Path, *, object_key: str) -> tuple[str, str]:
    payload = asset.read_bytes()
    content_type = mimetypes.guess_type(asset.name)[0] or "image/png"
    client = get_minio_client()
    if not client.bucket_exists(settings.MINIO_BUCKET):
        client.make_bucket(settings.MINIO_BUCKET)
    client.put_object(
        settings.MINIO_BUCKET,
        object_key,
        io.BytesIO(payload),
        length=len(payload),
        content_type=content_type,
    )
    return public_object_url(object_key), hashlib.sha256(payload).hexdigest()


async def _upload_asset(asset: Path, *, index: int) -> tuple[str, str, str]:
    relative = asset.relative_to(ASSET_ROOT)
    stable_name = hashlib.sha256(relative.as_posix().encode("utf-8")).hexdigest()[:16]
    object_key = f"mock-catalog-2026/source/{index:03d}-{stable_name}.png"
    url, digest = await asyncio.to_thread(_put_image, asset, object_key=object_key)
    return object_key, url, digest


async def _already_seeded(session) -> bool:
    return (
        await session.scalar(
            select(Product.id).where(Product.sku_code == "MOCK-2026-0001").limit(1)
        )
    ) is not None


async def seed_mock_catalog(asset_root: Path) -> dict[str, int | str]:
    _ensure_safe_environment()
    assets = _assets(asset_root)
    today = date.today()
    start_day = date(today.year, 5, 1)
    if today < start_day:
        raise SystemExit("The mock timeline requires a date on or after 1 May of the current year.")
    metric_days = [start_day + timedelta(days=offset) for offset in range((today - start_day).days + 1)]
    mature_cutoff = today - timedelta(days=2)
    counts: Counter[str] = Counter()

    async with async_session_factory() as session:
        with tenant_context(settings.DEFAULT_TENANT_ID, user_id="mock-catalog-seed", source="mock-seed"):
            if await _already_seeded(session):
                return {
                    "status": "already_seeded",
                    "assets": len(assets),
                    "timeline_start": start_day.isoformat(),
                    "timeline_end": today.isoformat(),
                }

            catalog_rows: list[tuple[Product, GeneratedImage, PredictionSnapshot]] = []
            for index, asset in enumerate(assets, start=1):
                relative = asset.relative_to(asset_root)
                category = _category_for(relative)
                market = _market_for(index)
                object_key, image_url, digest = await _upload_asset(asset, index=index)
                created_at = datetime.combine(
                    start_day + timedelta(days=(index - 1) % len(metric_days)),
                    time(hour=9, minute=index % 60),
                )
                sku = f"MOCK-2026-{index:04d}"
                product = Product(
                    tenant_id=settings.DEFAULT_TENANT_ID,
                    sku_code=sku,
                    title=_title_for(relative),
                    category=category,
                    price_range=_price_range(category),
                    target_markets=[market],
                    supplier_id=f"MOCK-SUP-{category[:4].upper()}-{(index - 1) % 6 + 1:02d}",
                    image_raw_url=image_url,
                    status=ProductStatus.PUBLISHED,
                    created_at=created_at,
                )
                session.add(product)
                await session.flush()

                scheme = ImageScheme(
                    tenant_id=settings.DEFAULT_TENANT_ID,
                    product_id=product.id,
                    scheme_name="本地 Mock 素材方案",
                    style_tags={
                        "category": category,
                        "market": market,
                        "source": "local_mock_assets",
                        "asset_group": relative.parent.name or "root",
                    },
                    reference_images=[image_url],
                    recommendation_reason="使用开发目录中的本地模拟素材验证 CTR 反馈闭环。",
                    recommendation_score=round(0.68 + (index % 25) / 100, 2),
                    created_at=created_at,
                )
                session.add(scheme)
                await session.flush()

                review_status = _review_status(index)
                image = GeneratedImage(
                    tenant_id=settings.DEFAULT_TENANT_ID,
                    scheme_id=scheme.id,
                    image_url=image_url,
                    storage_bucket=settings.MINIO_BUCKET,
                    storage_object_key=object_key,
                    is_public=True,
                    task_id=f"mock-catalog-2026-{index:04d}",
                    generation_status="completed",
                    market_variant=market,
                    generation_params={
                        "provider": "local-mock-assets",
                        "seed_marker": SEED_MARKER,
                        "relative_path": relative.as_posix(),
                        "asset_sha256": digest,
                    },
                    quality_scores={
                        "source": "local_mock_assets",
                        "overall_score": round(72 + (index * 13) % 25, 1),
                        "dimensions": {
                            "sharpness": round(74 + (index * 7) % 22, 1),
                            "composition": round(70 + (index * 11) % 27, 1),
                            "color_harmony": round(71 + (index * 5) % 25, 1),
                        },
                    },
                    overall_score=round(72 + (index * 13) % 25, 1),
                    review_status=review_status,
                    c2pa_manifest=json.dumps(
                        {"source": "local-mock-assets", "seed_marker": SEED_MARKER},
                        ensure_ascii=False,
                    ),
                    created_at=created_at,
                )
                session.add(image)
                await session.flush()

                predicted_ctr = _clip(0.018 + ((index * 41) % 300) / 10_000)
                prediction = PredictionRecord(
                    tenant_id=settings.DEFAULT_TENANT_ID,
                    image_id=image.id,
                    predicted_ctr=predicted_ctr,
                    ctr_confidence_interval={
                        "lower": _clip(predicted_ctr - 0.006),
                        "upper": _clip(predicted_ctr + 0.006),
                    },
                    predicted_hit_probability=_clip(0.25 + (index % 61) / 100, upper=0.9),
                    return_risk_level=_risk_for(index),
                    predicted_at=datetime.combine(start_day, time(hour=8, minute=index % 60)),
                )
                session.add(prediction)
                await session.flush()
                snapshot = PredictionSnapshot(
                    tenant_id=settings.DEFAULT_TENANT_ID,
                    prediction_record_id=prediction.id,
                    image_id=image.id,
                    predicted_ctr=predicted_ctr,
                    model_version="mock-ctr-v2026.06",
                    feature_version="mock-assets-v1",
                    entity_snapshot_json={
                        "sku": sku,
                        "category": category,
                        "market": market,
                        "asset_relative_path": relative.as_posix(),
                    },
                    predicted_at=prediction.predicted_at,
                )
                session.add(snapshot)

                external_id = f"mock-listing-{index:04d}"
                mapping = ExternalEntityMapping(
                    tenant_id=settings.DEFAULT_TENANT_ID,
                    provider="mock_dianxiaomi",
                    connection_key=SEED_MARKER,
                    shop_reference="mock-dianxiaomi-dev-shop",
                    marketplace=market,
                    entity_type="listing",
                    external_id=external_id,
                    external_sku=sku,
                    product_id=product.id,
                    image_id=image.id,
                    status="mapped",
                    mapping_method="mock_seed",
                    metadata_json={"asset_sha256": digest, "seed_marker": SEED_MARKER},
                    created_by="mock-catalog-seed",
                    updated_by="mock-catalog-seed",
                )
                session.add(mapping)
                await session.flush()
                commerce_payload = {
                    "sku": sku,
                    "title": product.title,
                    "category": category,
                    "marketplace": market,
                    "source": "local_mock_assets",
                }
                session.add(
                    CommerceFact(
                        tenant_id=settings.DEFAULT_TENANT_ID,
                        provider="mock_dianxiaomi",
                        connection_key=SEED_MARKER,
                        shop_reference="mock-dianxiaomi-dev-shop",
                        marketplace=market,
                        entity_type="listing",
                        external_id=external_id,
                        source_updated_at=datetime.combine(today, time(hour=7, minute=index % 60)),
                        occurred_at=created_at,
                        payload_json=commerce_payload,
                        payload_hash=payload_hash(commerce_payload),
                    )
                )
                catalog_rows.append((product, image, snapshot))
                counts["products"] += 1
                counts["images"] += 1
                counts["predictions"] += 1
                counts["mappings"] += 1
                counts["commerce_facts"] += 1

            await session.flush()
            for index, (product, image, _snapshot) in enumerate(catalog_rows, start=1):
                market = image.market_variant or "us"
                external_id = f"mock-listing-{index:04d}"
                mapping = await session.scalar(
                    select(ExternalEntityMapping).where(
                        ExternalEntityMapping.image_id == image.id,
                        ExternalEntityMapping.provider == "mock_dianxiaomi",
                    )
                )
                if mapping is None:
                    raise RuntimeError(f"Mock mapping for image #{image.id} was not created.")
                for metric_day in metric_days:
                    impressions, clicks, ctr, cvr, add_to_cart, return_rate, revenue = _daily_values(
                        index, metric_day, start_day
                    )
                    platform = PLATFORMS[(index + (metric_day - start_day).days) % len(PLATFORMS)]
                    session.add(
                        DailyMetric(
                            tenant_id=settings.DEFAULT_TENANT_ID,
                            date=metric_day,
                            image_id=image.id,
                            source_platform=platform,
                            impressions=impressions,
                            clicks=clicks,
                            ctr=ctr,
                            cvr=cvr,
                            add_to_cart_rate=add_to_cart,
                            return_rate=return_rate,
                            revenue=revenue,
                        )
                    )
                    performance_payload = {
                        "seed_marker": SEED_MARKER,
                        "listing": external_id,
                        "image_id": image.id,
                        "date": metric_day.isoformat(),
                        "platform": platform,
                        "impressions": impressions,
                        "clicks": clicks,
                    }
                    session.add(
                        PerformanceFact(
                            tenant_id=settings.DEFAULT_TENANT_ID,
                            source_name="mock_dianxiaomi",
                            source_record_id=f"{SEED_MARKER}:{index:04d}:{metric_day.isoformat()}",
                            metric_date=metric_day,
                            shop_reference="mock-dianxiaomi-dev-shop",
                            marketplace=market,
                            external_listing_id=external_id,
                            mapping_id=mapping.id,
                            image_id=image.id,
                            impressions=impressions,
                            clicks=clicks,
                            orders=max(0, round(clicks * cvr)),
                            revenue=revenue,
                            currency="USD",
                            source_updated_at=datetime.combine(metric_day, time(hour=23, minute=45)),
                            data_mature_at=datetime.combine(metric_day + timedelta(days=2), time(hour=6)),
                            is_mature=metric_day <= mature_cutoff,
                            quality_status="mapped",
                            metric_definition_version="mock-v1",
                            source_payload_hash=payload_hash(performance_payload),
                        )
                    )
                    counts["daily_metrics"] += 1
                    counts["performance_facts"] += 1

            await session.flush()
            feedback_summary = await create_mature_feedback_labels(
                session, tenant_id=settings.DEFAULT_TENANT_ID
            )
            counts["feedback_labels"] = int(feedback_summary["mature_labels_created"])

            categories: dict[str, tuple[Product, GeneratedImage]] = {}
            for product, image, _snapshot in catalog_rows:
                categories.setdefault(product.category, (product, image))
            for category, (product, image) in categories.items():
                campaign = VisualOperationCampaign(
                    tenant_id=settings.DEFAULT_TENANT_ID,
                    product_id=product.id,
                    name=f"{category} 2026 年 6–7 月 Mock CTR 运营活动",
                    market=image.market_variant,
                    objective="验证本地 Mock 素材的预测 CTR、真实 CTR 与反馈标签闭环。",
                    objective_metric="ctr",
                    target_value=0.032,
                    status="learning",
                    current_stage="learning",
                    scheme_ids=[image.scheme_id],
                    image_ids=[image.id],
                    description="开发环境模拟活动：所有效果数据均为本地确定性生成，非真实经营数据。",
                    next_step="查看已成熟的真实 CTR，并以反馈标签验证预测校准。",
                    owner_id="mock-catalog-seed",
                    started_at=datetime.combine(start_day, time(hour=9)),
                    completed_at=datetime.combine(today, time(hour=18)),
                )
                session.add(campaign)
                await session.flush()
                session.add(
                    CampaignInsight(
                        tenant_id=settings.DEFAULT_TENANT_ID,
                        campaign_id=campaign.id,
                        insight_type="learning",
                        title=f"{category} Mock CTR 数据已覆盖 6 月至当前日期",
                        summary="该结论由开发环境本地素材和确定性模拟曝光/点击生成，仅用于功能验证。",
                        source_type="mock_seed",
                        source_id=SEED_MARKER,
                        confidence=0.88,
                        metric_snapshot={
                            "timeline_start": start_day.isoformat(),
                            "timeline_end": today.isoformat(),
                            "sample_image_id": image.id,
                        },
                        recommended_action="在仪表盘、预测和数据质量页面验证真实 CTR 反馈链路。",
                        status="validated",
                        created_by="mock-catalog-seed",
                    )
                )
                counts["campaigns"] += 1
                counts["campaign_insights"] += 1

            await session.commit()

    return {
        "status": "seeded",
        "assets": len(assets),
        "timeline_start": start_day.isoformat(),
        "timeline_end": today.isoformat(),
        **dict(counts),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset-root", type=Path, default=ASSET_ROOT)
    args = parser.parse_args()
    summary = asyncio.run(seed_mock_catalog(args.asset_root))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
