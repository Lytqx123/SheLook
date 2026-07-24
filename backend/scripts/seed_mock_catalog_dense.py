"""密集版 Mock 数据填充脚本 —— 模拟生产环境三个月满功率运行状态。

与 seed_mock_catalog.py (v1) 的区别：
- 每个商品 3 套方案（影棚/生活/模特），模拟 A/B 测试
- 每套方案 2 张产出图（主市场 + 次市场）
- 每张产出图 4 轮预测记录（约每 3 周一次模型重校准）
- 更丰富的活动分布（品类 × 市场交叉）
- 数据总量约为 v1 的 6 倍

用法:
    docker exec shelook-dev-backend-1 python -m scripts.seed_mock_catalog_dense --clear
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

from sqlalchemy import delete, select

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

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
SEED_MARKER = "mock-catalog-dense-2026-v1"
ASSET_ROOT = Path("/mock-assets")
MARKETS = ("us", "eu", "seasia", "me")
PLATFORMS = ("shopee", "amazon")

# 每商品 3 套方案，风格不同
SCHEME_DEFS: list[dict] = [
    {"name": "标准影棚方案", "tags": {"style": "studio", "lighting": "professional", "background": "white"}},
    {"name": "生活场景方案", "tags": {"style": "lifestyle", "context": "indoor", "lighting": "natural"}},
    {"name": "模特实拍方案", "tags": {"style": "model_showcase", "pose": "full_body", "background": "outdoor"}},
]

# 每方案产生 2 张产出图（主/次市场）
MARKET_PAIRS = [
    ("us", "eu"),
    ("seasia", "me"),
    ("eu", "us"),
    ("me", "seasia"),
]

# 预测间隔（天）——约每 3 周一次，4 轮覆盖 85 天
PREDICTION_INTERVALS = [0, 21, 42, 63]

MODEL_VERSIONS = ["mock-ctr-v2026.05", "mock-ctr-v2026.06", "mock-ctr-v2026.07a", "mock-ctr-v2026.07b"]

CATEGORY_PRICE: dict[str, str] = {
    "womens_fashion": "$24-68",
    "beauty": "$12-42",
    "electronics": "$28-95",
    "accessories": "$16-58",
    "home_lifestyle": "$14-52",
}

# ---------------------------------------------------------------------------
# 工具函数（大部分从 v1 复用）
# ---------------------------------------------------------------------------
def _ensure_safe_environment() -> None:
    if settings.APP_ENV.lower() not in {"development", "test"}:
        raise SystemExit("仅允许在 development/test 环境运行。")


def _assets(asset_root: Path) -> list[Path]:
    if not asset_root.is_dir():
        raise SystemExit(f"素材目录 {asset_root} 未挂载。")
    files = sorted(p for p in asset_root.rglob("*.png") if p.is_file())
    if not files:
        raise SystemExit(f"在 {asset_root} 下未找到 PNG 素材。")
    return files


def _category_for(relative_path: Path) -> str:
    value = relative_path.as_posix().lower()
    if "女装" in relative_path.parts or any(t in value for t in (
        "dress", "shirt", "sweater", "cardigan", "blouse", "trouser",
        "jean", "skirt", "legging", "jacket", "tee", "bikini", "swimsuit", "coverup",
    )):
        return "womens_fashion"
    if any(t in value for t in ("serum", "sunscreen", "lip", "skincare", "perfume")):
        return "beauty"
    if any(t in value for t in ("earbud", "speaker", "keyboard", "headphone", "lamp", "light", "kettle")):
        return "electronics"
    if any(t in value for t in ("tote", "wallet", "umbrella", "shoe", "hanger")):
        return "accessories"
    return "home_lifestyle"


def _title_for(relative_path: Path) -> str:
    stem = relative_path.stem.replace("_", " ").replace("-", " ").strip()
    if stem.startswith("生成女装商品模特实拍图主图"):
        suffix = stem.removeprefix("生成女装商品模特实拍图主图").strip(" ()") or "01"
        return f"Mock 女装模特主图 {suffix}"
    return " ".join(p.capitalize() for p in stem.split())


def _clip(value: float, *, lower: float = 0.0001, upper: float = 0.2) -> float:
    return round(max(lower, min(upper, value)), 4)


def _daily_values(
    seed: int, metric_day: date, start_day: date,
) -> tuple[int, int, float, float, float, float, float]:
    """确定性生成每日指标，种子不同则曲线不同。"""
    day_index = (metric_day - start_day).days
    weekly = ((day_index % 7) - 3) * 0.00035
    july_lift = 0.0016 if metric_day.month == 7 else 0.0
    base_ctr = 0.016 + ((seed * 37) % 320) / 10_000
    ctr = _clip(base_ctr + weekly + july_lift)
    impressions = 720 + ((seed * 173 + day_index * 89) % 4_600)
    if metric_day.weekday() >= 5:
        impressions = int(impressions * 0.82)
    clicks = max(1, round(impressions * ctr))
    cvr = _clip(0.025 + ((seed * 11 + day_index) % 85) / 10_000, lower=0.005, upper=0.12)
    add_to_cart = _clip(cvr + 0.022 + (seed % 7) / 10_000, lower=0.01, upper=0.2)
    return_rate = _clip(0.018 + (seed % 9) / 1_000, lower=0.005, upper=0.1)
    revenue = round(max(0, round(clicks * cvr)) * (18 + seed % 42), 2)
    return impressions, clicks, ctr, cvr, add_to_cart, return_rate, revenue


def _put_image(asset: Path, *, object_key: str) -> tuple[str, str]:
    payload = asset.read_bytes()
    content_type = mimetypes.guess_type(asset.name)[0] or "image/png"
    client = get_minio_client()
    if not client.bucket_exists(settings.MINIO_BUCKET):
        client.make_bucket(settings.MINIO_BUCKET)
    client.put_object(
        settings.MINIO_BUCKET, object_key,
        io.BytesIO(payload), length=len(payload), content_type=content_type,
    )
    return public_object_url(object_key), hashlib.sha256(payload).hexdigest()


async def _upload_asset(asset: Path, *, idx: int, prefix: str) -> tuple[str, str, str]:
    relative = asset.relative_to(ASSET_ROOT)
    stable = hashlib.sha256(relative.as_posix().encode()).hexdigest()[:16]
    key = f"{prefix}/source/{idx:03d}-{stable}.png"
    url, digest = await asyncio.to_thread(_put_image, asset, object_key=key)
    return key, url, digest


# ---------------------------------------------------------------------------
# 清理旧数据
# ---------------------------------------------------------------------------
async def _clear_old_seed(session) -> int:
    """删除 v1 和本版旧数据，返回删除行数。"""
    tables = [
        CampaignInsight, VisualOperationCampaign,
        ModelFeedbackLabel, PerformanceFact, DailyMetric,
        PredictionSnapshot, PredictionRecord,
        CommerceFact, ExternalEntityMapping,
        GeneratedImage, ImageScheme, Product,
    ]
    total = 0
    for table in tables:
        result = await session.execute(
            delete(table).where(table.tenant_id == settings.DEFAULT_TENANT_ID)
        )
        total += result.rowcount
    await session.flush()
    return total


# ---------------------------------------------------------------------------
# 主逻辑
# ---------------------------------------------------------------------------
async def seed_mock_catalog_dense(asset_root: Path, *, clear: bool = False) -> dict:
    _ensure_safe_environment()
    assets = _assets(asset_root)
    today = date.today()
    start_day = date(today.year, 5, 1)
    if today < start_day:
        raise SystemExit("当前日期须在 5 月 1 日之后。")
    metric_days = [start_day + timedelta(days=i) for i in range((today - start_day).days + 1)]
    mature_cutoff = today - timedelta(days=2)
    counts: Counter[str] = Counter()

    async with async_session_factory() as session:
        with tenant_context(settings.DEFAULT_TENANT_ID, user_id="mock-dense-seed", source="mock-seed"):

            # —— 清理 ——
            if clear:
                deleted = await _clear_old_seed(session)
                counts["cleared_rows"] = deleted

            # —— 幂等检查 ——
            exists = await session.scalar(
                select(Product.id).where(Product.sku_code == "MOCK-D-2026-0001").limit(1)
            )
            if exists is not None:
                return {
                    "status": "already_seeded",
                    "assets": len(assets),
                    "timeline_start": start_day.isoformat(),
                    "timeline_end": today.isoformat(),
                }

            # —— 上传素材到 MinIO ——
            asset_records: list[dict] = []
            for i, asset in enumerate(assets, start=1):
                key, url, digest = await _upload_asset(asset, idx=i, prefix=SEED_MARKER)
                asset_records.append({
                    "asset": asset,
                    "relative": asset.relative_to(asset_root),
                    "object_key": key,
                    "image_url": url,
                    "digest": digest,
                    "index": i,
                })

            # —— 创建商品、方案、产出图、预测、映射、CommerceFact ——
            image_id_seed = 0  # 全局递增种子，用于 daily_values
            all_images: list[dict] = []  # {(product, image, scheme_id, market, idx)}

            for rec in asset_records:
                asset_idx = rec["index"]
                relative = rec["relative"]
                category = _category_for(relative)

                # 商品
                created_at = datetime.combine(
                    start_day + timedelta(days=(asset_idx - 1) % len(metric_days)),
                    time(hour=9, minute=asset_idx % 60),
                )
                sku = f"MOCK-D-2026-{asset_idx:04d}"
                product = Product(
                    tenant_id=settings.DEFAULT_TENANT_ID,
                    sku_code=sku,
                    title=_title_for(relative),
                    category=category,
                    price_range=CATEGORY_PRICE.get(category, "$14-52"),
                    target_markets=[MARKETS[asset_idx % len(MARKETS)]],
                    supplier_id=f"MOCK-SUP-{category[:4].upper()}-{(asset_idx - 1) % 6 + 1:02d}",
                    image_raw_url=rec["image_url"],
                    status=ProductStatus.PUBLISHED,
                    created_at=created_at,
                )
                session.add(product)
                await session.flush()

                # 3 套方案
                for si, sdef in enumerate(SCHEME_DEFS):
                    review_status = ReviewStatus.AUTO_APPROVED
                    if (asset_idx * 3 + si) % 17 == 0:
                        review_status = ReviewStatus.MANUAL_PENDING
                    elif (asset_idx * 3 + si) % 23 == 0:
                        review_status = ReviewStatus.REJECTED

                    scheme = ImageScheme(
                        tenant_id=settings.DEFAULT_TENANT_ID,
                        product_id=product.id,
                        scheme_name=sdef["name"],
                        style_tags={
                            **sdef["tags"],
                            "category": category,
                            "source": "local_mock_assets",
                            "asset_group": relative.parent.name or "root",
                        },
                        reference_images=[rec["image_url"]],
                        recommendation_reason=f"基于素材 {relative.name} 的 {sdef['name']} 验证方案。",
                        recommendation_score=round(0.65 + ((asset_idx * 7 + si * 13) % 30) / 100, 2),
                        created_at=created_at,
                    )
                    session.add(scheme)
                    await session.flush()

                    # 2 张产出图（主/次市场）
                    pair = MARKET_PAIRS[(asset_idx + si) % len(MARKET_PAIRS)]
                    for mi, market in enumerate(pair):
                        image_id_seed += 1
                        gi = GeneratedImage(
                            tenant_id=settings.DEFAULT_TENANT_ID,
                            scheme_id=scheme.id,
                            image_url=rec["image_url"],
                            storage_bucket=settings.MINIO_BUCKET,
                            storage_object_key=rec["object_key"],
                            is_public=True,
                            task_id=f"{SEED_MARKER}-{image_id_seed:04d}",
                            generation_status="completed",
                            market_variant=market,
                            generation_params={
                                "provider": "local-mock-assets",
                                "seed_marker": SEED_MARKER,
                                "scheme_type": sdef["name"],
                                "market": market,
                                "relative_path": relative.as_posix(),
                            },
                            quality_scores={
                                "overall_score": round(72 + (image_id_seed * 13) % 25, 1),
                                "dimensions": {
                                    "sharpness": round(74 + (image_id_seed * 7) % 22, 1),
                                    "composition": round(70 + (image_id_seed * 11) % 27, 1),
                                    "color_harmony": round(71 + (image_id_seed * 5) % 25, 1),
                                },
                            },
                            overall_score=round(72 + (image_id_seed * 13) % 25, 1),
                            review_status=review_status,
                            c2pa_manifest=json.dumps(
                                {"source": "local-mock-assets", "seed_marker": SEED_MARKER},
                                ensure_ascii=False,
                            ),
                            created_at=created_at,
                            updated_at=created_at,
                        )
                        session.add(gi)
                        await session.flush()

                        # 4 轮预测（每约 3 周一次）
                        for pi, interval in enumerate(PREDICTION_INTERVALS):
                            pred_date = start_day + timedelta(days=interval)
                            if pred_date > today:
                                break
                            predicted_ctr = _clip(0.016 + ((image_id_seed * 41 + pi * 17) % 300) / 10_000 + pi * 0.0008)
                            risk_map = [ReturnRiskLevel.LOW, ReturnRiskLevel.MEDIUM, ReturnRiskLevel.MEDIUM, ReturnRiskLevel.HIGH]
                            risk = risk_map[(image_id_seed + pi) % 4]

                            pred = PredictionRecord(
                                tenant_id=settings.DEFAULT_TENANT_ID,
                                image_id=gi.id,
                                predicted_ctr=predicted_ctr,
                                ctr_confidence_interval={
                                    "lower": _clip(predicted_ctr - 0.005 - pi * 0.0005),
                                    "upper": _clip(predicted_ctr + 0.005 + pi * 0.0005),
                                },
                                predicted_hit_probability=_clip(0.25 + (image_id_seed % 61) / 100 + pi * 0.03, upper=0.92),
                                return_risk_level=risk,
                                predicted_at=datetime.combine(pred_date, time(hour=8, minute=(image_id_seed + pi) % 60)),
                            )
                            session.add(pred)
                            await session.flush()

                            session.add(PredictionSnapshot(
                                tenant_id=settings.DEFAULT_TENANT_ID,
                                prediction_record_id=pred.id,
                                image_id=gi.id,
                                predicted_ctr=predicted_ctr,
                                model_version=MODEL_VERSIONS[pi],
                                feature_version=f"mock-features-v{pi + 1}",
                                entity_snapshot_json={
                                    "sku": sku, "category": category,
                                    "market": market, "scheme": sdef["name"],
                                    "prediction_round": pi + 1,
                                },
                                predicted_at=pred.predicted_at,
                            ))
                            counts["predictions"] += 1

                        # ExternalEntityMapping
                        ext_id = f"mock-dense-listing-{image_id_seed:04d}"
                        mapping = ExternalEntityMapping(
                            tenant_id=settings.DEFAULT_TENANT_ID,
                            provider="mock_dianxiaomi",
                            connection_key=SEED_MARKER,
                            shop_reference="mock-dianxiaomi-dev-shop",
                            marketplace=market,
                            entity_type="listing",
                            external_id=ext_id,
                            external_sku=sku,
                            product_id=product.id,
                            image_id=gi.id,
                            status="mapped",
                            mapping_method="mock_seed_dense",
                            metadata_json={"seed_marker": SEED_MARKER},
                            created_by="mock-dense-seed",
                            updated_by="mock-dense-seed",
                        )
                        session.add(mapping)
                        await session.flush()

                        # CommerceFact
                        session.add(CommerceFact(
                            tenant_id=settings.DEFAULT_TENANT_ID,
                            provider="mock_dianxiaomi",
                            connection_key=SEED_MARKER,
                            shop_reference="mock-dianxiaomi-dev-shop",
                            marketplace=market,
                            entity_type="listing",
                            external_id=ext_id,
                            source_updated_at=datetime.combine(today, time(hour=7, minute=image_id_seed % 60)),
                            occurred_at=created_at,
                            payload_json={"sku": sku, "title": product.title, "category": category, "market": market},
                            payload_hash=payload_hash({"sku": sku, "seed": SEED_MARKER}),
                        ))
                        counts["commerce_facts"] += 1
                        counts["mappings"] += 1
                        counts["images"] += 1

                        all_images.append({
                            "product": product,
                            "image": gi,
                            "scheme_id": scheme.id,
                            "market": market,
                            "external_id": ext_id,
                            "mapping_id": mapping.id,
                            "seed": image_id_seed,
                        })

                counts["schemes"] += 3
                counts["products"] += 1

            await session.flush()

            # —— 每日指标 & PerformanceFact（分批写入，每 10 张图 flush 一次） ——
            batch_size = 10
            for batch_start in range(0, len(all_images), batch_size):
                batch = all_images[batch_start:batch_start + batch_size]
                for img_rec in batch:
                    gi = img_rec["image"]
                    seed_val = img_rec["seed"]
                    market = img_rec["market"]
                    ext_id = img_rec["external_id"]
                    mapping_id = img_rec["mapping_id"]

                    for metric_day in metric_days:
                        impressions, clicks, ctr, cvr, add_to_cart, return_rate, revenue = _daily_values(
                            seed_val, metric_day, start_day
                        )
                        platform = PLATFORMS[(seed_val + (metric_day - start_day).days) % len(PLATFORMS)]

                        session.add(DailyMetric(
                            tenant_id=settings.DEFAULT_TENANT_ID,
                            date=metric_day,
                            image_id=gi.id,
                            source_platform=platform,
                            impressions=impressions,
                            clicks=clicks,
                            ctr=ctr,
                            cvr=cvr,
                            add_to_cart_rate=add_to_cart,
                            return_rate=return_rate,
                            revenue=revenue,
                        ))
                        counts["daily_metrics"] += 1

                        session.add(PerformanceFact(
                            tenant_id=settings.DEFAULT_TENANT_ID,
                            source_name="mock_dianxiaomi",
                            source_record_id=f"{SEED_MARKER}:{seed_val:04d}:{metric_day.isoformat()}",
                            metric_date=metric_day,
                            shop_reference="mock-dianxiaomi-dev-shop",
                            marketplace=market,
                            external_listing_id=ext_id,
                            mapping_id=mapping_id,
                            image_id=gi.id,
                            impressions=impressions,
                            clicks=clicks,
                            orders=max(0, round(clicks * cvr)),
                            revenue=revenue,
                            currency="USD",
                            source_updated_at=datetime.combine(metric_day, time(hour=23, minute=45)),
                            data_mature_at=datetime.combine(metric_day + timedelta(days=2), time(hour=6)),
                            is_mature=metric_day <= mature_cutoff,
                            quality_status="mapped",
                            metric_definition_version="mock-dense-v1",
                            source_payload_hash=payload_hash({"seed": SEED_MARKER, "date": metric_day.isoformat()}),
                        ))
                        counts["performance_facts"] += 1

                await session.flush()

            # —— 活动（品类 × 市场交叉，每个品类 4-6 个活动） ——
            categories_seen: dict[str, list[dict]] = {}
            for img_rec in all_images:
                cat = img_rec["product"].category
                categories_seen.setdefault(cat, []).append(img_rec)
            campaign_idx = 0
            for cat, imgs in categories_seen.items():
                unique_markets = list({r["market"] for r in imgs})
                for mkt in unique_markets[:4]:
                    sample = imgs[0]
                    campaign_idx += 1
                    campaign = VisualOperationCampaign(
                        tenant_id=settings.DEFAULT_TENANT_ID,
                        product_id=sample["product"].id,
                        name=f"{cat} {mkt.upper()} 2026 Q2-Q3 运营活动 #{campaign_idx}",
                        market=mkt,
                        objective=f"验证 {cat} 类目在 {mkt.upper()} 市场的 CTR 预测与真实反馈闭环。",
                        objective_metric="ctr",
                        target_value=round(0.028 + campaign_idx * 0.0015, 4),
                        status="learning",
                        current_stage="learning",
                        scheme_ids=[sample["scheme_id"]],
                        image_ids=[sample["image"].id],
                        description=f"Mock 密集数据活动 #{campaign_idx}：所有效果数据为本地确定性生成。",
                        next_step="持续监控 CTR 并校准预测模型。",
                        owner_id="mock-dense-seed",
                        started_at=datetime.combine(start_day, time(hour=9)),
                        completed_at=datetime.combine(today, time(hour=18)),
                    )
                    session.add(campaign)
                    await session.flush()
                    session.add(CampaignInsight(
                        tenant_id=settings.DEFAULT_TENANT_ID,
                        campaign_id=campaign.id,
                        insight_type="learning",
                        title=f"{cat} {mkt.upper()} CTR 数据概览",
                        summary=f"{cat} 类目在 {mkt.upper()} 市场的模拟数据已覆盖 5 月至当前，用于功能验证。",
                        source_type="mock_seed_dense",
                        source_id=SEED_MARKER,
                        confidence=0.85 + (campaign_idx % 10) / 100,
                        metric_snapshot={"start": start_day.isoformat(), "end": today.isoformat()},
                        recommended_action="在仪表盘验证 CTR 反馈链路。",
                        status="validated",
                        created_by="mock-dense-seed",
                    ))
                    counts["campaigns"] += 1
                    counts["campaign_insights"] += 1

            # —— 反馈标签 ——
            feedback = await create_mature_feedback_labels(session, tenant_id=settings.DEFAULT_TENANT_ID)
            counts["feedback_labels"] = int(feedback.get("mature_labels_created", 0))

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
    parser.add_argument("--clear", action="store_true", help="写入前清空该租户所有旧 mock 数据")
    args = parser.parse_args()
    summary = asyncio.run(seed_mock_catalog_dense(args.asset_root, clear=args.clear))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
