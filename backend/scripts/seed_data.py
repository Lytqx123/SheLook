"""
SheLook Mock 数据填充脚本

插入 Demo 所需的全部数据：
- 30款商品（连衣裙/上衣/裤装/外套）
- 每款商品 3-5 套方案
- 每套方案 4-6 张生成图片
- 历史上的每日指标数据（60天）
- A/B 实验数据（15个已完成实验）
- 预测记录

用法：
    docker compose run backend python scripts/seed_data.py
    或本地：
    cd backend && python ../scripts/seed_data.py
"""

import asyncio
import hashlib
import io
import random
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from PIL import Image as PILImage
from PIL import ImageDraw

# 添加 backend 目录到 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select, text

from app.config import settings
from app.db.session import async_session_factory
from app.models import (
    ABExperiment,
    DailyMetric,
    ExperimentStatus,
    GeneratedImage,
    ImageScheme,
    PredictionRecord,
    Product,
    ProductStatus,
    ReturnRiskLevel,
    ReviewAction,
    ReviewRecord,
    ReviewStatus,
)
from app.services.storage_service import get_minio_client, public_object_url

# ── 商品数据 ────────────────────────────────────────────────

PRODUCTS = [
    # 连衣裙 (12)
    {"sku": "DRS-001", "title": "夏季碎花V领连衣裙", "category": "dress", "price": "$15-25", "markets": ["us", "eu"]},
    {"sku": "DRS-002", "title": "法式茶歇裙收腰显瘦", "category": "dress", "price": "$15-25", "markets": ["us", "eu"]},
    {"sku": "DRS-003", "title": "波西米亚长裙度假风", "category": "dress", "price": "$25+", "markets": ["us", "eu", "me"]},
    {"sku": "DRS-004", "title": "简约通勤衬衫连衣裙", "category": "dress", "price": "$15-25", "markets": ["us", "eu"]},
    {"sku": "DRS-005", "title": "吊带修身针织连衣裙", "category": "dress", "price": "$5-15", "markets": ["us", "seasia"]},
    {"sku": "DRS-006", "title": "优雅蕾丝拼接小黑裙", "category": "dress", "price": "$25+", "markets": ["us", "eu"]},
    {"sku": "DRS-007", "title": "宽松A字娃娃连衣裙", "category": "dress", "price": "$5-15", "markets": ["seasia"]},
    {"sku": "DRS-008", "title": "宫廷风泡泡袖方领裙", "category": "dress", "price": "$15-25", "markets": ["me", "eu"]},
    {"sku": "DRS-009", "title": "针织两件套连衣裙套装", "category": "dress", "price": "$25+", "markets": ["us", "eu"]},
    {"sku": "DRS-010", "title": "不对称剪裁不规则裙摆", "category": "dress", "price": "$15-25", "markets": ["us"]},
    {"sku": "DRS-011", "title": "长袖雪纺印花连衣裙", "category": "dress", "price": "$5-15", "markets": ["seasia", "me"]},
    {"sku": "DRS-012", "title": "丝绒复古旗袍式连衣裙", "category": "dress", "price": "$25+", "markets": ["us", "eu", "me"]},
    # 上衣 (8)
    {"sku": "TOP-001", "title": "基础款圆领纯棉T恤", "category": "tops", "price": "$5-15", "markets": ["us", "eu", "seasia"]},
    {"sku": "TOP-002", "title": "灯笼袖雪纺衬衫女", "category": "tops", "price": "$15-25", "markets": ["us", "eu"]},
    {"sku": "TOP-003", "title": "短款针织开衫外套", "category": "tops", "price": "$15-25", "markets": ["us", "eu", "me"]},
    {"sku": "TOP-004", "title": "一字肩露肩泡泡袖上衣", "category": "tops", "price": "$5-15", "markets": ["seasia"]},
    {"sku": "TOP-005", "title": "优雅真丝衬衫职业装", "category": "tops", "price": "$25+", "markets": ["us", "eu"]},
    {"sku": "TOP-006", "title": "宽松蝙蝠袖罩衫", "category": "tops", "price": "$5-15", "markets": ["me", "seasia"]},
    {"sku": "TOP-007", "title": "蕾丝拼接打底衫", "category": "tops", "price": "$5-15", "markets": ["us", "eu"]},
    {"sku": "TOP-008", "title": "复古方领短袖T恤", "category": "tops", "price": "$5-15", "markets": ["seasia"]},
    # 裤装 (6)
    {"sku": "PNT-001", "title": "高腰阔腿裤垂感西裤", "category": "bottoms", "price": "$15-25", "markets": ["us", "eu"]},
    {"sku": "PNT-002", "title": "弹力紧身小脚牛仔裤", "category": "bottoms", "price": "$5-15", "markets": ["us", "eu", "seasia"]},
    {"sku": "PNT-003", "title": "亚麻宽松阔腿长裤", "category": "bottoms", "price": "$25+", "markets": ["me", "eu"]},
    {"sku": "PNT-004", "title": "工装风口袋直筒裤", "category": "bottoms", "price": "$15-25", "markets": ["us"]},
    {"sku": "PNT-005", "title": "缎面垂感居家阔腿裤", "category": "bottoms", "price": "$5-15", "markets": ["seasia", "me"]},
    {"sku": "PNT-006", "title": "九分烟管裤通勤西装裤", "category": "bottoms", "price": "$15-25", "markets": ["us", "eu"]},
    # 外套 (4)
    {"sku": "JKT-001", "title": "经典双排扣风衣外套", "category": "outerwear", "price": "$25+", "markets": ["us", "eu"]},
    {"sku": "JKT-002", "title": "短款牛仔夹克外套", "category": "outerwear", "price": "$15-25", "markets": ["us", "eu", "seasia"]},
    {"sku": "JKT-003", "title": "轻薄防晒连帽外套", "category": "outerwear", "price": "$5-15", "markets": ["seasia"]},
    {"sku": "JKT-004", "title": "羊毛混纺呢子大衣", "category": "outerwear", "price": "$25+", "markets": ["us", "eu", "me"]},
]

SCHEME_NAMES = [
    ("欧美街拍风", {"lighting": "自然光", "scene": "街头", "pose": "动态抓拍", "composition": "三分法", "color_tone": "高饱和度"}),
    ("极简白底风", {"lighting": "均匀柔光", "scene": "纯白背景", "pose": "站姿", "composition": "居中构图", "color_tone": "低饱和中性"}),
    ("生活场景风", {"lighting": "暖光", "scene": "咖啡馆/书店", "pose": "坐姿", "composition": "黄金比例", "color_tone": "暖色调"}),
    ("博主种草风", {"lighting": "环形光", "scene": "室内/对镜", "pose": "对镜自拍", "composition": "对角线", "color_tone": "冷暖对比"}),
    ("平铺展示风", {"lighting": "顶光", "scene": "纯色平面", "pose": "平铺", "composition": "俯拍", "color_tone": "真实还原"}),
    ("户外自然风", {"lighting": "黄金时刻光", "scene": "公园/海滩", "pose": "自然走动", "composition": "景深虚化", "color_tone": "暖金色调"}),
    ("中东典雅风", {"lighting": "柔光", "scene": "室内奢华", "pose": "端庄站姿", "composition": "对称构图", "color_tone": "金色/珠宝色"}),
    ("东南亚清新风", {"lighting": "明亮日光", "scene": "热带植物", "pose": "俏皮", "composition": "留白多", "color_tone": "马卡龙色系"}),
]

MARKETS = ["us", "eu", "me", "seasia"]

# ── 辅助函数 ────────────────────────────────────────────────


def random_score(base: float, spread: float = 15) -> float:
    """生成随机评分（0-100）"""
    return max(0, min(100, base + random.uniform(-spread, spread)))


def generate_quality_scores(review_status: str) -> dict:
    """根据审核状态生成质量评分"""
    if review_status == "auto_approved":
        base = 82
    elif review_status == "rejected":
        base = 55
    else:
        base = 68
    return {
        "l1": {"passed": base >= 70, "checks": ["resolution_ok", "aspect_ok", "file_size_ok"]},
        "l2": {
            "overall_score": round(random_score(base, 10), 1),
            "dimensions": {
                "sharpness": round(random_score(base, 20), 1),
                "lighting_uniformity": round(random_score(base, 15), 1),
                "color_harmony": round(random_score(base, 15), 1),
                "composition_balance": round(random_score(base, 15), 1),
                "information_density": round(random_score(base, 12), 1),
            },
            "verdict": "pass" if base >= 60 else "fail",
        },
        "l3": {
            "aesthetic_score": round(random_score(base - 5, 12), 1),
            "composition": round(random_score(base - 5, 10), 1),
            "color_harmony": round(random_score(base - 3, 10), 1),
            "lighting_depth": round(random_score(base - 8, 10), 1),
        },
    }


def pick_schemes_for_product(product_idx: int) -> list[int]:
    """为一款商品选择 3-5 套方案"""
    n = random.choice([3, 4, 4, 5, 5])
    return random.sample(range(len(SCHEME_NAMES)), n)


def pick_markets_for_image(product_markets: list[str]) -> list[str]:
    """为一套方案选择生成的市场变体（4-6张图片）"""
    available = [m for m in MARKETS if m in product_markets]
    if len(available) < 4:
        available = MARKETS
    n = random.choice([4, 5, 6])
    # 确保至少覆盖 2 个 market
    picks = random.choices(available, k=n)
    if len(set(picks)) < 2:
        picks[0] = available[1] if len(available) > 1 else available[0]
    return picks


def _placeholder_bytes(label: str) -> bytes:
    """生成可被真实读取/编码的轻量演示图，不留下指向不存在对象的假 URL。"""
    digest = hashlib.sha256(label.encode()).digest()
    background = tuple(80 + value % 140 for value in digest[:3])
    accent = tuple(30 + value % 180 for value in digest[3:6])
    image = PILImage.new("RGB", (512, 512), background)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((72, 64, 440, 448), radius=36, fill=accent, outline="white", width=8)
    draw.ellipse((176, 120, 336, 280), fill=background, outline="white", width=6)
    draw.text((96, 384), label[:42], fill="white")
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=82, optimize=True)
    return buffer.getvalue()


def _put_demo_image(client, object_key: str, label: str) -> str:
    data = _placeholder_bytes(label)
    client.put_object(
        settings.MINIO_BUCKET,
        object_key,
        io.BytesIO(data),
        length=len(data),
        content_type="image/jpeg",
    )
    return public_object_url(object_key)


def _demo_storage_client():
    client = get_minio_client()
    if not client.bucket_exists(settings.MINIO_BUCKET):
        client.make_bucket(settings.MINIO_BUCKET)
    return client


def _demo_skin_tone(market: str | None, identity: str) -> str:
    """按市场基线稳定生成演示标签，使报告可复现且无需重复 CLIP。"""
    baseline = settings.FAIRNESS_MARKET_BASELINES.get(
        market or "default",
        settings.FAIRNESS_MARKET_BASELINES["default"],
    )
    value = int.from_bytes(hashlib.sha256(identity.encode()).digest()[:8], "big") / 2**64
    cumulative = 0.0
    for label in ("light", "medium", "dark"):
        cumulative += baseline[label]
        if value < cumulative:
            return label
    return "no_person"


def _is_legacy_demo_url(value: str | None) -> bool:
    url = str(value or "")
    valid_prefix = (
        f"{settings.MINIO_PUBLIC_BASE_URL.rstrip('/')}/"
        f"{settings.MINIO_BUCKET}/demo/"
    )
    return url.startswith("http://localhost:9000/") and not url.startswith(valid_prefix)


# ── 主逻辑 ──────────────────────────────────────────────────


async def seed():
    async with async_session_factory() as session:
        print("=== SheLook 数据填充开始 ===\n")
        storage = _demo_storage_client()

        reference_urls = {
            index: [
                _put_demo_image(storage, f"demo/references/style-{index}/ref-{ref}.jpg", f"style-{index}-ref-{ref}")
                for ref in (1, 2)
            ]
            for index in range(len(SCHEME_NAMES))
        }

        # 1. 清空旧数据
        print("[1/7] 清空旧数据...")
        tables = [
            "audit_logs",
            "supplier_visual_scores",
            "brand_standards",
            "daily_metrics",
            "prediction_records",
            "review_records",
            "ab_experiments",
            "generated_images",
            "image_schemes",
            "product_embeddings",
            "products",
        ]
        for t in tables:
            await session.execute(text(f"TRUNCATE TABLE {t} CASCADE"))
        await session.commit()
        print(f"  ✓ 已清空 {len(tables)} 张表")

        # 2. 插入商品
        print("\n[2/7] 插入商品...")
        product_records: list[Product] = []
        for p in PRODUCTS:
            raw_key = f"demo/raw/{p['sku']}/flat-lay.jpg"
            product = Product(
                sku_code=p["sku"],
                title=p["title"],
                category=p["category"],
                price_range=p["price"],
                target_markets=p["markets"],
                supplier_id=f"SUP-{random.randint(1000, 9999)}",
                image_raw_url=_put_demo_image(storage, raw_key, f"{p['sku']}-raw"),
                status=ProductStatus.PUBLISHED,
                created_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=random.randint(30, 180)),
            )
            session.add(product)
            product_records.append(product)
        await session.commit()
        print(f"  ✓ 已插入 {len(PRODUCTS)} 款商品")

        # 3. 插入方案 + 生成图片
        print("\n[3/7] 插入方案和生成图片...")
        total_schemes = 0
        total_images = 0
        all_images: list[GeneratedImage] = []

        for idx, product in enumerate(product_records):
            selected_scheme_indices = pick_schemes_for_product(idx)
            for si in selected_scheme_indices:
                scheme_data = SCHEME_NAMES[si]
                scheme = ImageScheme(
                    product_id=product.id,
                    scheme_name=scheme_data[0],
                    style_tags=scheme_data[1],
                    reference_images=reference_urls[si],
                    recommendation_reason=f"该方案适合{product.category}品类，{scheme_data[0]}风格在{', '.join(product.target_markets or [])}市场表现优异",
                    recommendation_score=round(random.uniform(0.65, 0.98), 2),
                )
                session.add(scheme)
                total_schemes += 1

        await session.commit()

        # 为每个 scheme 生成图片
        schemes = (await session.execute(select(ImageScheme))).scalars().all()
        for scheme in schemes:
            product = (await session.execute(
                select(Product).where(Product.id == scheme.product_id)
            )).scalar_one()
            markets = product.target_markets or MARKETS
            selected_markets = pick_markets_for_image(markets)

            for mi, market in enumerate(selected_markets):
                # 审核状态分布：auto_approved 40%, manual_pending 45%, rejected 15%
                roll = random.random()
                if roll < 0.40:
                    review_status = ReviewStatus.AUTO_APPROVED
                elif roll < 0.85:
                    review_status = ReviewStatus.MANUAL_PENDING
                else:
                    review_status = ReviewStatus.REJECTED

                quality = generate_quality_scores(review_status.value)
                quality["skin_tone"] = _demo_skin_tone(
                    market,
                    f"{product.sku_code}-{scheme.id}-{market}-{mi}",
                )
                overall = quality["l2"]["overall_score"]
                object_key = f"demo/generated/{product.sku_code}/scheme-{scheme.id}/{market}/v{mi}.jpg"

                image = GeneratedImage(
                    scheme_id=scheme.id,
                    image_url=_put_demo_image(
                        storage,
                        object_key,
                        f"{product.sku_code}-{market}-{mi}",
                    ),
                    storage_bucket=settings.MINIO_BUCKET,
                    storage_object_key=object_key,
                    market_variant=market,
                    generation_params={
                        "model": "FLUX.2 Pro",
                        "prompt": f"A {product.category} in {scheme.scheme_name} style, {market} market",
                        "negative_prompt": "blurry, low quality",
                        "steps": 28,
                        "guidance_scale": 7.5,
                    },
                    quality_scores=quality,
                    overall_score=overall,
                    review_status=review_status,
                    c2pa_manifest=f'{{"generator": "SheLook/v1", "model": "FLUX.2 Pro", "timestamp": "{datetime.now(UTC).replace(tzinfo=None).isoformat()}"}}',
                    reviewer_notes=None,
                )
                session.add(image)
                all_images.append(image)
                total_images += 1

        await session.commit()
        print(f"  ✓ 已插入 {total_schemes} 套方案")
        print(f"  ✓ 已插入 {total_images} 张生成图片")

        # 刷新 all_images 以获取 ID
        all_images = (await session.execute(select(GeneratedImage))).scalars().all()

        # 4. 插入每日指标（60天）
        print("\n[4/7] 插入每日指标数据（60天）...")
        today = date.today()
        metric_count = 0

        # 只为 auto_approved 和部分 manual_pending 的图片生成 metrics
        active_images = [img for img in all_images if img.review_status != ReviewStatus.REJECTED]
        for img in active_images[: len(active_images) // 2]:  # 取一半图片
            for days_ago in range(60):
                d = today - timedelta(days=days_ago)
                # 模拟季节性波动和周末效应
                day_of_week = d.weekday()
                weekend_boost = 1.3 if day_of_week >= 5 else 1.0
                base_ctr = random.uniform(0.01, 0.06) * weekend_boost

                impressions = random.randint(200, 2000)
                clicks = int(impressions * base_ctr)

                metric = DailyMetric(
                    date=d,
                    image_id=img.id,
                    impressions=impressions,
                    clicks=clicks,
                    ctr=round(base_ctr, 4),
                    cvr=round(random.uniform(0.005, 0.04), 4),
                    add_to_cart_rate=round(random.uniform(0.02, 0.12), 4),
                    return_rate=round(random.uniform(0.01, 0.15), 4),
                    revenue=round(random.uniform(50, 5000), 2),
                )
                session.add(metric)
                metric_count += 1

        await session.commit()
        print(f"  ✓ 已插入 {metric_count} 条每日指标")

        # 5. 插入预测记录
        print("\n[5/7] 插入预测记录...")
        pred_count = 0
        for img in all_images:
            ctr_pred = round(random.uniform(0.005, 0.08), 4)
            ci_half = ctr_pred * 0.3
            hit_prob = round(random.uniform(0.05, 0.45), 4)
            risk_score = random.uniform(0, 1)

            if risk_score < 0.4:
                risk = ReturnRiskLevel.LOW
            elif risk_score < 0.75:
                risk = ReturnRiskLevel.MEDIUM
            else:
                risk = ReturnRiskLevel.HIGH

            pred = PredictionRecord(
                image_id=img.id,
                predicted_ctr=ctr_pred,
                ctr_confidence_interval={"lower": round(ctr_pred - ci_half, 4), "upper": round(ctr_pred + ci_half, 4)},
                predicted_hit_probability=hit_prob,
                return_risk_level=risk,
            )
            session.add(pred)
            pred_count += 1

        await session.commit()
        print(f"  ✓ 已插入 {pred_count} 条预测记录")

        # 6. 插入 A/B 实验数据（15个）
        print("\n[6/7] 插入 A/B 实验数据...")
        auto_approved = [img for img in all_images if img.review_status == ReviewStatus.AUTO_APPROVED]

        if len(auto_approved) >= 30:
            for i in range(15):
                a = auto_approved[i * 2]
                b = auto_approved[i * 2 + 1]

                # 随机生成CTR差异
                ctr_a = round(random.uniform(0.015, 0.055), 4)
                diff = random.uniform(-0.015, 0.02)
                ctr_b = round(ctr_a + diff, 4)

                # p-value 基于差异大小
                if abs(diff) > 0.012:
                    p_val = round(random.uniform(0.001, 0.04), 4)
                    status = ExperimentStatus.COMPLETED
                else:
                    p_val = round(random.uniform(0.08, 0.8), 4)
                    status = random.choice([ExperimentStatus.COMPLETED, ExperimentStatus.RUNNING])

                winner = a.id if ctr_a > ctr_b else b.id
                start_d = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=random.randint(7, 30))

                # 通过 scheme_id 关联查询 product_id（避免 async lazy loading）
                scheme = next((s for s in schemes if s.id == a.scheme_id), None)
                exp = ABExperiment(
                    product_id=scheme.product_id if scheme else 1,
                    variant_a_image_id=a.id,
                    variant_b_image_id=b.id,
                    traffic_ratio=0.5,
                    status=status,
                    start_date=start_d,
                    end_date=start_d + timedelta(days=14) if status == ExperimentStatus.COMPLETED else None,
                    result_ctr_a=ctr_a,
                    result_ctr_b=ctr_b,
                    p_value=p_val,
                    winner_image_id=winner,
                )
                session.add(exp)

        await session.commit()
        print("  ✓ 已插入 15 个 A/B 实验")

        # 7. 插入审核记录
        print("\n[7/7] 插入审核记录...")
        review_count = 0
        for img in all_images:
            if img.review_status == ReviewStatus.AUTO_APPROVED:
                review = ReviewRecord(
                    image_id=img.id,
                    reviewer_id="system",
                    action=ReviewAction.APPROVED,
                    reason="质量评分达到自动通过阈值",
                )
            elif img.review_status == ReviewStatus.REJECTED:
                dims = ["sharpness", "lighting_uniformity", "color_harmony", "composition_balance", "information_density"]
                review = ReviewRecord(
                    image_id=img.id,
                    reviewer_id=f"reviewer-{random.randint(1, 5)}",
                    action=ReviewAction.REJECTED,
                    reason="部分质量维度不达标",
                    problem_dimensions=random.sample(dims, random.randint(1, 3)),
                )
            else:
                continue
            session.add(review)
            review_count += 1

        await session.commit()
        print(f"  ✓ 已插入 {review_count} 条审核记录")

        print("\n=== 数据填充完成 ===")
        print(f"  商品: {len(PRODUCTS)}")
        print(f"  方案: {total_schemes}")
        print(f"  图片: {total_images}")
        print(f"  每日指标: {metric_count}")
        print(f"  预测记录: {pred_count}")
        print("  实验: 15")
        print(f"  审核记录: {review_count}")


async def repair_demo_images() -> None:
    """只修复旧版 seed 留下的假 localhost URL，不清空或改写业务数据。"""
    storage = _demo_storage_client()
    async with async_session_factory() as session:
        products = (await session.execute(select(Product))).scalars().all()
        schemes = (await session.execute(select(ImageScheme))).scalars().all()
        images = (await session.execute(select(GeneratedImage))).scalars().all()

        repaired_products = 0
        for product in products:
            if _is_legacy_demo_url(product.image_raw_url):
                key = f"demo/raw/{product.sku_code}/flat-lay.jpg"
                product.image_raw_url = _put_demo_image(storage, key, f"{product.sku_code}-raw")
                repaired_products += 1

        repaired_schemes = 0
        for scheme in schemes:
            references = scheme.reference_images or []
            if any(_is_legacy_demo_url(url) for url in references):
                scheme.reference_images = [
                    _put_demo_image(
                        storage,
                        f"demo/references/scheme-{scheme.id}/ref-{index}.jpg",
                        f"scheme-{scheme.id}-ref-{index}",
                    )
                    for index in (1, 2)
                ]
                repaired_schemes += 1

        repaired_images = 0
        labeled_images = 0
        for image in images:
            if _is_legacy_demo_url(image.image_url):
                key = f"demo/generated/image-{image.id}.jpg"
                image.image_url = _put_demo_image(storage, key, f"generated-{image.id}")
                image.storage_bucket = settings.MINIO_BUCKET
                image.storage_object_key = key
                repaired_images += 1
            quality = image.quality_scores if isinstance(image.quality_scores, dict) else {}
            if quality.get("skin_tone") not in {"light", "medium", "dark", "no_person"}:
                image.quality_scores = {
                    **quality,
                    "skin_tone": _demo_skin_tone(image.market_variant, f"generated-{image.id}"),
                }
                labeled_images += 1

        await session.commit()
        print(
            "演示图片修复完成: "
            f"products={repaired_products}, schemes={repaired_schemes}, "
            f"images={repaired_images}, labels={labeled_images}"
        )


if __name__ == "__main__":
    asyncio.run(repair_demo_images() if "--repair-images-only" in sys.argv else seed())
