"""填充与第六阶段架构一致的多租户演示数据。

默认只在空数据库运行；传入 ``--reset`` 会先调用受保护的开发数据清理脚本。
所有图片均为本地生成的占位素材，不调用任何真实 AI 供应商。
"""

import argparse
import asyncio
import hashlib
import io
import json
import math
import random
from collections import Counter
from datetime import UTC, date, datetime, timedelta

from PIL import Image as PILImage
from PIL import ImageDraw
from sqlalchemy import text

from app.config import settings
from app.core.tenant import tenant_context
from app.db.session import async_session_factory
from app.models import (
    ABExperiment,
    AIUsageRecord,
    AuditLog,
    BrandStandard,
    CampaignInsight,
    CampaignInsightStatus,
    CampaignInsightType,
    CampaignStage,
    CampaignStatus,
    DailyMetric,
    ExperimentStatus,
    ExternalListingMapping,
    GeneratedImage,
    ImageScheme,
    OrganizationUnit,
    OutboxEvent,
    OutboxStatus,
    PredictionRecord,
    Product,
    ProductEmbedding,
    ProductStatus,
    ReturnRiskLevel,
    ReviewAction,
    ReviewRecord,
    ReviewStatus,
    SupplierAnalysisReport,
    SupplierVisualScore,
    Tenant,
    TenantFeatureFlag,
    TenantMembership,
    TenantQuota,
    UsageStatus,
    VisualOperationCampaign,
    WorkflowTask,
    WorkflowTaskStatus,
)
from app.services.feature_flags import DEFAULT_FEATURE_FLAGS
from app.services.storage_service import get_minio_client, public_object_url

SEED = 20260718
MARKETS = ("us", "eu", "me", "seasia")
TENANTS = (
    {"id": "default", "slug": "default", "name": "SheLook 演示事业群", "brand": "Luma"},
    {"id": "northstar", "slug": "northstar", "name": "Northstar Commerce", "brand": "Northstar"},
    {"id": "atelier", "slug": "atelier", "name": "Atelier Collective", "brand": "Atelier"},
)
PRODUCT_FAMILIES = (
    ("dress", "Linen Wrap Dress", "$25-45"),
    ("tops", "Soft Knit Top", "$15-25"),
    ("bottoms", "Wide Leg Trouser", "$25-40"),
    ("outerwear", "Lightweight Trench", "$45-80"),
)
VISUAL_SCHEMES = (
    ("Clean studio", {"lighting": "soft daylight", "scene": "studio", "composition": "centered"}),
    ("Everyday lifestyle", {"lighting": "warm natural", "scene": "home", "composition": "rule_of_thirds"}),
    ("Marketplace detail", {"lighting": "neutral", "scene": "white background", "composition": "product_focus"}),
)


def _placeholder_bytes(label: str) -> bytes:
    digest = hashlib.sha256(label.encode("utf-8")).digest()
    background = tuple(70 + value % 140 for value in digest[:3])
    accent = tuple(30 + value % 180 for value in digest[3:6])
    image = PILImage.new("RGB", (720, 720), background)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((90, 80, 630, 640), radius=48, fill=accent, outline="white", width=8)
    draw.ellipse((230, 160, 490, 420), fill=background, outline="white", width=6)
    draw.text((120, 555), label[:46], fill="white")
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=84, optimize=True)
    return buffer.getvalue()


def _storage_client():
    client = get_minio_client()
    if not client.bucket_exists(settings.MINIO_BUCKET):
        client.make_bucket(settings.MINIO_BUCKET)
    return client


def _put_image(client, object_key: str, label: str) -> str:
    payload = _placeholder_bytes(label)
    client.put_object(
        settings.MINIO_BUCKET,
        object_key,
        io.BytesIO(payload),
        length=len(payload),
        content_type="image/jpeg",
    )
    return public_object_url(object_key)


def _quality_scores(status: ReviewStatus, rng: random.Random, market: str) -> dict:
    base = {
        ReviewStatus.AUTO_APPROVED: 88,
        ReviewStatus.MANUAL_PENDING: 74,
        ReviewStatus.REJECTED: 52,
    }[status]
    def score(spread: float) -> float:
        return round(max(0, min(100, base + rng.uniform(-spread, spread))), 1)
    skin_tone = ("light", "medium", "dark", "no_person")[rng.randrange(4)]
    return {
        "l1": {"passed": status != ReviewStatus.REJECTED, "checks": ["resolution", "aspect_ratio"]},
        "l2": {
            "overall_score": score(8),
            "dimensions": {
                "sharpness": score(10),
                "lighting_uniformity": score(10),
                "color_harmony": score(10),
                "composition_balance": score(10),
            },
            "verdict": "pass" if status != ReviewStatus.REJECTED else "fail",
        },
        "l3": {"aesthetic_score": score(9), "market": market},
        "skin_tone": skin_tone,
    }


def _embedding(seed: int) -> str:
    values = [round(math.sin(seed * 0.11 + index * 0.017), 6) for index in range(512)]
    return json.dumps(values, separators=(",", ":"))


def _risk(value: float) -> ReturnRiskLevel:
    if value < 0.35:
        return ReturnRiskLevel.LOW
    if value < 0.72:
        return ReturnRiskLevel.MEDIUM
    return ReturnRiskLevel.HIGH


async def _ensure_empty_database(reset: bool) -> None:
    if settings.APP_ENV.lower() not in {"development", "test"}:
        raise SystemExit("演示数据只能写入 development/test 环境")
    if reset:
        from scripts.reset_demo_data import reset_demo_data

        await reset_demo_data()
        return

    async with async_session_factory() as session:
        existing = await session.scalar(text("SELECT COUNT(*) FROM products"))
    if existing:
        raise SystemExit("数据库已有业务数据；如需重新填充，请传入 --reset")


async def _prepare_tenants(session) -> None:
    for tenant_data in TENANTS:
        tenant = await session.get(Tenant, tenant_data["id"])
        if tenant is None:
            tenant = Tenant(
                id=tenant_data["id"],
                slug=tenant_data["slug"],
                name=tenant_data["name"],
                status="active",
            )
            session.add(tenant)
        else:
            tenant.slug = tenant_data["slug"]
            tenant.name = tenant_data["name"]
            tenant.status = "active"
    await session.flush()


async def _seed_tenant(
    session,
    *,
    tenant_data: dict[str, str],
    storage,
    rng: random.Random,
    products_per_tenant: int,
    metric_days: int,
) -> Counter:
    tenant_id = tenant_data["id"]
    brand_id = f"brand-{tenant_id}"
    counts: Counter = Counter()
    with tenant_context(tenant_id, user_id=f"seed-{tenant_id}", source="demo-seed"):
        quota = await session.get(TenantQuota, tenant_id)
        if quota is None:
            quota = TenantQuota(tenant_id=tenant_id)
            session.add(quota)
        quota.api_requests_per_minute = 1_200
        quota.generation_concurrency = 6
        quota.monthly_generation_limit = 1_500
        quota.storage_limit_bytes = 20 * 1024 * 1024 * 1024
        quota.monthly_budget_cents = 120_000

        brand_unit = OrganizationUnit(
            tenant_id=tenant_id,
            unit_type="brand",
            name=tenant_data["brand"],
            external_ref=brand_id,
        )
        session.add(brand_unit)
        await session.flush()
        store_unit = OrganizationUnit(
            tenant_id=tenant_id,
            parent_id=brand_unit.id,
            unit_type="store",
            name=f"{tenant_data['brand']} Global Store",
            external_ref=f"store-{tenant_id}",
        )
        review_unit = OrganizationUnit(
            tenant_id=tenant_id,
            parent_id=brand_unit.id,
            unit_type="team",
            name="Visual Review Team",
            external_ref=f"team-review-{tenant_id}",
        )
        session.add_all((store_unit, review_unit))
        await session.flush()
        session.add_all(
            (
                TenantMembership(
                    tenant_id=tenant_id,
                    user_id=f"{tenant_id}-admin",
                    display_name="Operations Admin",
                    role="admin",
                    permissions=["tenant:manage", "model:manage"],
                    unit_ids=[brand_unit.id, store_unit.id],
                ),
                TenantMembership(
                    tenant_id=tenant_id,
                    user_id=f"{tenant_id}-reviewer",
                    display_name="Visual Reviewer",
                    role="reviewer",
                    permissions=["review:write"],
                    unit_ids=[review_unit.id],
                ),
            )
        )
        session.add(
            BrandStandard(
                brand_id=brand_id,
                brand_name=tenant_data["brand"],
                color_palette={"primary": "#1F5EFF", "accent": "#FF8A65"},
                lighting_preferences={"preferred": "soft daylight"},
                composition_rules={"safe_margin": "8%", "hero_product": True},
                logo_position="bottom_right",
                watermark_rules={"required": True},
                forbidden_patterns=["watermark", "blur", "misleading scale"],
            )
        )
        for flag_key, enabled in DEFAULT_FEATURE_FLAGS.items():
            session.add(
                TenantFeatureFlag(
                    flag_key=flag_key,
                    enabled=enabled if tenant_id != "atelier" else flag_key != "automated_experiments",
                    rollout_note="demo rollout baseline",
                    updated_by="seed",
                )
            )
        await session.flush()

        products: list[Product] = []
        for index in range(products_per_tenant):
            category, title, price_range = PRODUCT_FAMILIES[index % len(PRODUCT_FAMILIES)]
            sku = f"{tenant_id[:3].upper()}-{category[:3].upper()}-{index + 1:03d}"
            markets = list(MARKETS[index % len(MARKETS) :]) or list(MARKETS)
            object_key = f"demo-v2/{tenant_id}/raw/{sku}.jpg"
            product = Product(
                sku_code=sku,
                title=f"{tenant_data['brand']} {title} {index + 1}",
                category=category,
                price_range=price_range,
                target_markets=markets[: min(3, len(markets))],
                supplier_id=f"SUP-{tenant_id[:3].upper()}-{index % 4 + 1:02d}",
                image_raw_url=_put_image(storage, object_key, f"{tenant_id}-{sku}-raw"),
                status=ProductStatus.PUBLISHED,
                created_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=20 + index * 4),
            )
            session.add(product)
            products.append(product)
        await session.flush()
        counts["products"] += len(products)

        images: list[GeneratedImage] = []
        schemes: list[ImageScheme] = []
        for _product_index, product in enumerate(products):
            for style_index, (scheme_name, style_tags) in enumerate(VISUAL_SCHEMES):
                reference_key = f"demo-v2/{tenant_id}/references/{style_index}.jpg"
                scheme = ImageScheme(
                    product_id=product.id,
                    scheme_name=scheme_name,
                    style_tags={**style_tags, "category": product.category},
                    reference_images=[_put_image(storage, reference_key, f"{tenant_id}-{scheme_name}")],
                    recommendation_reason=f"Optimised for {product.category} in {', '.join(product.target_markets or [])}",
                    recommendation_score=round(0.72 + rng.random() * 0.24, 2),
                )
                session.add(scheme)
                schemes.append(scheme)
        await session.flush()
        counts["schemes"] += len(schemes)

        for scheme_index, scheme in enumerate(schemes):
            product = products[scheme_index // len(VISUAL_SCHEMES)]
            for market_index, market in enumerate((product.target_markets or list(MARKETS))[:3]):
                position = scheme_index * 3 + market_index
                status = (
                    ReviewStatus.AUTO_APPROVED
                    if position % 5 in {0, 1, 2}
                    else ReviewStatus.MANUAL_PENDING
                    if position % 5 == 3
                    else ReviewStatus.REJECTED
                )
                object_key = f"demo-v2/{tenant_id}/generated/{product.sku_code}/{scheme.id}/{market}.jpg"
                scores = _quality_scores(status, rng, market)
                image = GeneratedImage(
                    scheme_id=scheme.id,
                    image_url=_put_image(storage, object_key, f"{product.sku_code}-{market}"),
                    storage_bucket=settings.MINIO_BUCKET,
                    storage_object_key=object_key,
                    is_public=True,
                    task_id=f"seed-{tenant_id}-{scheme.id}-{market}",
                    generation_status="completed",
                    market_variant=market,
                    generation_params={"provider": "demo-synthetic", "seed": SEED, "market": market},
                    quality_scores=scores,
                    overall_score=scores["l2"]["overall_score"],
                    review_status=status,
                    c2pa_manifest=json.dumps({"source": "synthetic-demo", "tenant": tenant_id}),
                )
                session.add(image)
                images.append(image)
        await session.flush()
        counts["images"] += len(images)

        for product_index, product in enumerate(products):
            session.add(
                ProductEmbedding(
                    product_id=product.id,
                    embedding=_embedding(product.id + product_index),
                    embedding_model="demo-deterministic-512",
                )
            )

        today = date.today()
        approved_images = [image for image in images if image.review_status != ReviewStatus.REJECTED]
        for image_index, image in enumerate(approved_images):
            for days_ago in range(metric_days):
                metric_date = today - timedelta(days=days_ago)
                impressions = 400 + ((image_index * 97 + days_ago * 29) % 1_800)
                ctr = round(0.012 + ((image_index + days_ago) % 40) / 1_000, 4)
                clicks = max(1, int(impressions * ctr))
                session.add(
                    DailyMetric(
                        date=metric_date,
                        image_id=image.id,
                        source_platform="amazon" if days_ago % 2 else "shopee",
                        impressions=impressions,
                        clicks=clicks,
                        ctr=ctr,
                        cvr=round(0.01 + (image_index % 10) / 1_000, 4),
                        add_to_cart_rate=round(0.04 + (days_ago % 8) / 1_000, 4),
                        return_rate=round(0.02 + (image_index % 6) / 1_000, 4),
                        revenue=round(clicks * (18 + image_index % 12), 2),
                    )
                )
                counts["metrics"] += 1
            risk_value = rng.random()
            session.add(
                PredictionRecord(
                    image_id=image.id,
                    predicted_ctr=round(0.016 + rng.random() * 0.04, 4),
                    ctr_confidence_interval={"lower": 0.012, "upper": 0.058},
                    predicted_hit_probability=round(0.12 + rng.random() * 0.6, 4),
                    return_risk_level=_risk(risk_value),
                )
            )
            counts["predictions"] += 1
            if image.review_status != ReviewStatus.MANUAL_PENDING:
                session.add(
                    ReviewRecord(
                        image_id=image.id,
                        reviewer_id="auto-review" if image.review_status == ReviewStatus.AUTO_APPROVED else f"{tenant_id}-reviewer",
                        action=ReviewAction.APPROVED if image.review_status == ReviewStatus.AUTO_APPROVED else ReviewAction.REJECTED,
                        reason="Synthetic quality gate result",
                        problem_dimensions={"dimensions": ["lighting_uniformity"]}
                        if image.review_status == ReviewStatus.REJECTED
                        else None,
                    )
                )
                counts["reviews"] += 1

        experiments: list[ABExperiment] = []
        for experiment_index in range(min(2, len(products))):
            product = products[experiment_index]
            candidates = [image for image in images if image.scheme.product_id == product.id]
            if len(candidates) >= 2:
                winner = candidates[0] if experiment_index % 2 == 0 else candidates[1]
                experiment = ABExperiment(
                    product_id=product.id,
                    variant_a_image_id=candidates[0].id,
                    variant_b_image_id=candidates[1].id,
                    traffic_ratio=0.5,
                    status=ExperimentStatus.COMPLETED if experiment_index == 0 else ExperimentStatus.RUNNING,
                    start_date=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=14),
                    end_date=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=2)
                    if experiment_index == 0
                    else None,
                    result_ctr_a=0.032,
                    result_ctr_b=0.041,
                    p_value=0.018 if experiment_index == 0 else None,
                    winner_image_id=winner.id if experiment_index == 0 else None,
                )
                session.add(experiment)
                experiments.append(experiment)
                counts["experiments"] += 1

        # 让演示数据完整呈现产品主线：任务/活动串起商品、方案、素材、审核、
        # 预测、实验与复盘，并将可复用的经营结论沉淀为 insight。
        await session.flush()
        campaign_specs = (
            (CampaignStatus.LEARNING, CampaignStage.LEARNING, "复盘已完成的高 CTR 方案"),
            (CampaignStatus.EXPERIMENTING, CampaignStage.EXPERIMENT, "继续验证素材变体的增量"),
            (CampaignStatus.WAITING_REVIEW, CampaignStage.REVIEW, "处理人工质量审核后再进入预测"),
        )
        campaigns: list[VisualOperationCampaign] = []
        for campaign_index, product in enumerate(products[: len(campaign_specs)]):
            status, stage, next_step = campaign_specs[campaign_index]
            product_schemes = [scheme for scheme in schemes if scheme.product_id == product.id]
            product_images = [image for image in images if image.scheme.product_id == product.id]
            product_experiments = [
                experiment for experiment in experiments if experiment.product_id == product.id
            ]
            market = (product.target_markets or list(MARKETS))[0]
            campaign = VisualOperationCampaign(
                tenant_id=tenant_id,
                product_id=product.id,
                name=f"{product.title} · {market.upper()} 视觉运营活动",
                market=market,
                objective="提升目标市场商品主图的点击效率，并沉淀可复用的视觉策略。",
                objective_metric="ctr",
                target_value=0.035,
                status=status.value,
                current_stage=stage.value,
                scheme_ids=[scheme.id for scheme in product_schemes[:3]],
                image_ids=[image.id for image in product_images[:6]],
                experiment_ids=[experiment.id for experiment in product_experiments],
                description="由演示数据生成的端到端视觉运营任务，包含内容生产、质量门禁、预测、实验和复盘。",
                recommended_action={
                    "priority": "high" if campaign_index < 2 else "medium",
                    "action_type": "review" if status == CampaignStatus.WAITING_REVIEW else "optimize",
                    "rationale": "基于当前质量评分、预测 CTR 与实验结果的合成演示信号。",
                },
                next_step=next_step,
                owner_id=f"{tenant_id}-admin",
                started_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=12 - campaign_index),
                completed_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=2)
                if status == CampaignStatus.LEARNING
                else None,
            )
            session.add(campaign)
            campaigns.append(campaign)
            counts["campaigns"] += 1

        await session.flush()
        for campaign_index, campaign in enumerate(campaigns):
            if campaign_index == 0:
                insight_type = CampaignInsightType.STRATEGY_VALIDATED
                insight_status = CampaignInsightStatus.VALIDATED
                title = "生活化场景方案在目标市场获得稳定点击优势"
                action = "将获胜方案加入同类商品的默认候选，并在下一个市场保留 20% 流量复验。"
            elif campaign_index == 1:
                insight_type = CampaignInsightType.EXPERIMENT
                insight_status = CampaignInsightStatus.OBSERVED
                title = "当前 A/B 实验仍需累积显著性证据"
                action = "保持均分流量，达到样本阈值后再确认胜出版本。"
            else:
                insight_type = CampaignInsightType.RISK
                insight_status = CampaignInsightStatus.OBSERVED
                title = "人工审核待办会阻塞投放决策"
                action = "优先处理待审素材的构图与合规问题，再发起效果预测。"
            session.add(
                CampaignInsight(
                    tenant_id=tenant_id,
                    campaign_id=campaign.id,
                    insight_type=insight_type.value,
                    title=title,
                    summary="该结论来自演示数据中的质量评分、预测指标和实验状态，用于展示可追溯的数据飞轮。",
                    source_type="demo_seed",
                    source_id=str(campaign.product_id),
                    confidence=round(0.72 + campaign_index * 0.08, 2),
                    metric_snapshot={
                        "target_metric": campaign.objective_metric,
                        "target_value": campaign.target_value,
                        "linked_images": len(campaign.image_ids or []),
                        "linked_experiments": len(campaign.experiment_ids or []),
                    },
                    recommended_action=action,
                    status=insight_status.value,
                    created_by=f"{tenant_id}-admin",
                )
            )
            counts["campaign_insights"] += 1

        for supplier_index in range(1, 5):
            supplier_id = f"SUP-{tenant_id[:3].upper()}-{supplier_index:02d}"
            session.add(
                SupplierVisualScore(
                    supplier_id=supplier_id,
                    brand_id=brand_id,
                    total_images=18 + supplier_index * 7,
                    pass_rate=round(0.72 + supplier_index * 0.04, 3),
                    avg_quality_score=round(70 + supplier_index * 4.2, 1),
                    compliance_score=round(0.78 + supplier_index * 0.03, 3),
                    problem_dimension_scores={"sharpness": 2, "lighting_uniformity": supplier_index},
                    last_evaluated_at=datetime.now(UTC).replace(tzinfo=None),
                )
            )
        session.add(
            SupplierAnalysisReport(
                report_id=f"RPT-{tenant_id[:8]}-001",
                supplier_id=f"SUP-{tenant_id[:3].upper()}-01",
                report_payload={"summary": "Synthetic supplier quality baseline", "priority": "medium"},
            )
        )

        for image_index, image in enumerate(images[:4]):
            session.add(
                ExternalListingMapping(
                    platform="amazon" if image_index % 2 == 0 else "shopee",
                    external_id=f"{tenant_id}-{image.id}",
                    image_id=image.id,
                )
            )
            session.add(
                AuditLog(
                    request_id=f"seed-{tenant_id}-{image.id}",
                    operation="generate",
                    image_id=image.id,
                    scheme_id=image.scheme_id,
                    model_name="demo-synthetic",
                    status="success",
                    duration_ms=420 + image_index * 45,
                    c2pa_manifest_present=True,
                    compliance_checks_passed=image.review_status != ReviewStatus.REJECTED,
                )
            )

        task_specs: list[tuple[str, WorkflowTaskStatus, int]] = []
        for task_index, image in enumerate(images[:3]):
            task_id = f"seed-task-{tenant_id}-{task_index}"
            status = WorkflowTaskStatus.SUCCEEDED if task_index < 2 else WorkflowTaskStatus.WAITING_HUMAN
            session.add(
                WorkflowTask(
                    id=task_id,
                    task_type="image_generation",
                    resource_type="generated_image",
                    resource_id=str(image.id),
                    idempotency_key=f"seed:{tenant_id}:{task_index}",
                    request_id=f"seed-request-{tenant_id}-{task_index}",
                    status=status,
                    payload={"demo": True, "image_id": image.id},
                    result={"image_id": image.id} if status == WorkflowTaskStatus.SUCCEEDED else None,
                    completed_at=datetime.now(UTC).replace(tzinfo=None)
                    if status == WorkflowTaskStatus.SUCCEEDED
                    else None,
                )
            )
            task_specs.append((task_id, status, task_index))
            counts["workflows"] += 1

        # AI 用量记录引用 workflow_tasks；必须先 flush 任务本身。
        await session.flush()
        # Flush the referenced workflow rows before inserting AI usage records.
        await session.flush()
        for task_id, status, task_index in task_specs:
            session.add(
                OutboxEvent(
                    event_key=f"seed.generation:{task_id}",
                    event_type="generation.requested",
                    aggregate_type="workflow_task",
                    aggregate_id=task_id,
                    payload={"demo": True, "workflow_task_id": task_id},
                    status=OutboxStatus.PUBLISHED,
                    published_at=datetime.now(UTC).replace(tzinfo=None),
                )
            )
            session.add(
                AIUsageRecord(
                    workflow_task_id=task_id,
                    idempotency_key=f"seed-usage:{tenant_id}:{task_index}",
                    operation="image_generation",
                    provider="demo-synthetic",
                    reserved_cost_cents=settings.IMAGE_GENERATION_RESERVATION_CENTS,
                    actual_cost_cents=settings.IMAGE_GENERATION_RESERVATION_CENTS
                    if status == WorkflowTaskStatus.SUCCEEDED
                    else None,
                    status=UsageStatus.SUCCEEDED if status == WorkflowTaskStatus.SUCCEEDED else UsageStatus.RESERVED,
                )
            )
        await session.flush()
    return counts


async def seed(*, products_per_tenant: int, metric_days: int, reset: bool) -> dict[str, int]:
    await _ensure_empty_database(reset)
    storage = _storage_client()
    totals: Counter = Counter()
    async with async_session_factory() as session:
        await _prepare_tenants(session)
        await session.commit()
        for tenant_index, tenant_data in enumerate(TENANTS):
            totals.update(
                await _seed_tenant(
                    session,
                    tenant_data=tenant_data,
                    storage=storage,
                    rng=random.Random(SEED + tenant_index),
                    products_per_tenant=products_per_tenant,
                    metric_days=metric_days,
                )
            )
            await session.commit()
    return dict(totals)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--products-per-tenant", type=int, default=12)
    parser.add_argument("--metric-days", type=int, default=45)
    parser.add_argument("--reset", action="store_true", help="先清理开发演示数据")
    args = parser.parse_args()
    if args.products_per_tenant < 3 or args.metric_days < 7:
        raise SystemExit("products-per-tenant 至少为 3，metric-days 至少为 7")
    summary = asyncio.run(
        seed(
            products_per_tenant=args.products_per_tenant,
            metric_days=args.metric_days,
            reset=args.reset,
        )
    )
    print(json.dumps({"seed": SEED, "tenants": len(TENANTS), **summary}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
