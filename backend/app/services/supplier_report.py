"""供应商分析报告服务 —— 三级质检 + 品类标杆对比 + 改进建议。"""

import asyncio
import hashlib
import time
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.schemas.supplier import (
    BenchmarkInfo,
    DimensionScore,
    ImprovementSuggestion,
    SupplierReportResponse,
)
from app.services.predictor import get_runtime_predictor
from app.services.reward_scorer import full_quality_pipeline

# --- 市场映射：供应商 API 国家代码 → 预测器市场代码

MARKET_MAPPING: dict[str, str] = {
    "SG": "seasia", "MY": "seasia", "TH": "seasia",
    "ID": "seasia", "VN": "seasia", "PH": "seasia", "TW": "seasia",
    "BR": "us", "MX": "us", "CO": "us",
}


def _map_market(supplier_market: str) -> str:
    """将供应商 API 的国家代码映射为预测器使用的市场代码"""
    normalized = supplier_market.strip().lower()
    if normalized in {"us", "eu", "me", "seasia"}:
        return normalized
    return MARKET_MAPPING.get(supplier_market.upper(), "us")


def _predict_supplier_metrics(
    category: str, market: str, image_path: str
) -> dict[str, float | None]:
    """同步执行供应商图片的 CTR / 退货风险预测（含 CLIP 推理）"""
    predictor = get_runtime_predictor()
    predictor_market = _map_market(market)
    features = predictor.extract_features(
        category=category,
        price_range="mid",
        market=predictor_market,
        image_url=image_path,
    )
    pred = predictor.predict_ctr(features, category=category)
    return_result = predictor.predict_return_risk(features)
    return {
        "predicted_ctr": round(float(pred.get("predicted_ctr", 0)), 4),
        "normalized_ctr": round(float(pred.get("normalized_ctr", 0)), 2),
        "return_risk": round(float(return_result.get("return_risk_probability", 0)), 4),
    }


# --- 维度定义

DIMENSION_META = [
    {"name": "sharpness", "display_name": "清晰度", "weight": 0.25},
    {"name": "lighting_uniformity", "display_name": "光照均匀度", "weight": 0.15},
    {"name": "color_harmony", "display_name": "色彩和谐度", "weight": 0.25},
    {"name": "composition_balance", "display_name": "构图均衡度", "weight": 0.15},
    {"name": "information_density", "display_name": "信息密度", "weight": 0.20},
]

# 改进建议模板库
SUGGESTION_TEMPLATES: dict[str, list[dict]] = {
    "sharpness": [
        {
            "title": "提升图片清晰度",
            "description": "使用三脚架固定拍摄，确保对焦准确。建议在自然光或专业摄影灯下拍摄，避免手持抖动。",
            "expected_improvement": "清晰度预计提升 10-15 分，高清晰度的商品图 CTR 平均高 23%。",
        },
        {
            "title": "增加图片细节层次",
            "description": "拍摄时确保商品纹理、Logo、缝线等细节清晰可见。建议使用微距镜头拍摄材质特写。",
            "expected_improvement": "增加细节层次可使信息密度同时提升 8-12 分。",
        },
    ],
    "lighting_uniformity": [
        {
            "title": "优化布光均匀度",
            "description": "当前图片存在明显的亮暗区域差异。建议使用双灯 45° 侧光 + 顶光的经典布光方案，或使用柔光箱消除阴影。",
            "expected_improvement": "布光改善后，光照均匀度可提升 15-20 分。",
        },
        {
            "title": "避免过曝和死黑",
            "description": "检查是否有纯白（RGB>245）或纯黑（RGB<10）的大面积区域。适当降低曝光补偿，使用反光板补暗部。",
            "expected_improvement": "避免极端亮度区域可提升整体质量感知 10-15 分。",
        },
    ],
    "color_harmony": [
        {
            "title": "优化配色方案",
            "description": "当前图片色彩单调或杂乱。建议：白色/灰色背景突出商品主体，或使用与商品主色互补的背景色。",
            "expected_improvement": "色彩和谐度提升 10-18 分，视觉吸引力和停留时长均有提升。",
        },
        {
            "title": "提升色彩饱和度",
            "description": "商品色彩不够鲜艳。检查是否因过曝导致褪色，适当增加饱和度 +5~+10（避免过度处理）。",
            "expected_improvement": "合适饱和度可提升色彩维度 8-12 分。",
        },
    ],
    "composition_balance": [
        {
            "title": "调整构图让商品居中",
            "description": "当前商品偏离画面中心。建议将商品主体置于画面中央，留白均匀分布四周。主体占比建议 60-75%。",
            "expected_improvement": "居中构图可提升构图均衡度 12-18 分。",
        },
        {
            "title": "减少杂乱背景",
            "description": "背景元素过多会分散注意力。使用纯色背景或简单场景，确保商品是画面唯一焦点。",
            "expected_improvement": "简化背景可同时提升构图和清晰度维度。",
        },
    ],
    "information_density": [
        {
            "title": "增加图片信息量",
            "description": "当前图片细节较少。建议：增加模特穿着场景图、多角度展示（正面/侧面/背面）、添加细节特写。",
            "expected_improvement": "信息密度提升 8-15 分，丰富的信息量有助于降低退货率。",
        },
        {
            "title": "优化图片尺寸和格式",
            "description": "确保图片分辨率 ≥ 1200×1200，使用 JPEG quality 85+ 或 PNG 格式保存，避免压缩过度。",
            "expected_improvement": "高分辨率图片的信息密度和清晰度均有提升。",
        },
    ],
}


# --- 核心服务

class SupplierReportService:
    """供应商分析报告服务"""

    @staticmethod
    def generate_report_id() -> str:
        """生成唯一报告 ID"""
        raw = f"{uuid.uuid4().hex}{time.time()}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    @staticmethod
    async def analyze_image(
        image_path: str,
        category: str,
        market: str,
        db: AsyncSession,
    ) -> SupplierReportResponse:
        """分析供应商上传的图片，生成完整分析报告"""
        report_id = SupplierReportService.generate_report_id()

        # 1. 执行三级质检
        try:
            quality_result = await asyncio.to_thread(full_quality_pipeline, image_path)
        except Exception as e:
            logger.error(f"质检流水线失败: {e}")
            quality_result = {
                "l1": {"passed": False, "issues": [{"dimension": "error", "passed": False}]},
                "l2": {"overall_score": 50.0, "verdict": "manual_pending", "dimensions": {}},
                "l3": {"overall_score": 50.0},
                "overall_score": 50.0,
                "verdict": "manual_pending",
            }

        l2_dims = quality_result.get("l2", {}).get("dimensions", {})

        # 2. 获取品类标杆
        benchmark = await SupplierReportService._get_benchmark(category, db)

        # 3. 构建维度对比
        dimensions = []
        for dim_meta in DIMENSION_META:
            dim_name = dim_meta["name"]
            current_score = float(l2_dims.get(dim_name, 50.0))
            bench_score = benchmark.get(dim_name, 60.0) if benchmark else 60.0
            dimensions.append(DimensionScore(
                name=dim_name,
                display_name=dim_meta["display_name"],
                score=round(current_score, 1),
                benchmark=round(bench_score, 1),
                gap=round(current_score - bench_score, 1),
                weight=dim_meta["weight"],
            ))

        # 4. 生成改进建议
        suggestions = SupplierReportService._generate_suggestions(dimensions)

        # 5. 预测 CTR / 退货风险
        predicted_ctr = None
        normalized_ctr = None
        return_risk = None

        if get_runtime_predictor().is_trained:
            try:
                pred_result = await asyncio.to_thread(
                    _predict_supplier_metrics, category, market, image_path
                )
                predicted_ctr = pred_result["predicted_ctr"]
                normalized_ctr = pred_result["normalized_ctr"]
                return_risk = pred_result["return_risk"]
            except Exception as e:
                logger.warning(f"预测失败: {e}")

        # 6. 构建响应
        return SupplierReportResponse(
            report_id=report_id,
            image_url=image_path if image_path.startswith("http") else f"/images/{image_path}",
            category=category,
            market=market,
            overall_score=round(float(quality_result.get("overall_score", 50.0)), 1),
            quality_verdict=quality_result.get(
                "review_status",
                quality_result.get("l2", {}).get("verdict", "manual_pending"),
            ),
            l1_passed=quality_result.get("l1", {}).get("passed", False),
            l1_details=quality_result.get("l1", {}),
            dimensions=dimensions,
            suggestions=suggestions,
            benchmark=BenchmarkInfo(
                category=category,
                sample_count=benchmark.get("sample_count", 0) if benchmark else 0,
                top_ctr_threshold=round(benchmark.get("ctr_threshold", 0.03), 4) if benchmark else 0.03,
            ) if benchmark else None,
            predicted_ctr=predicted_ctr,
            normalized_ctr=normalized_ctr,
            return_risk_probability=return_risk,
        )

    @staticmethod
    async def _get_benchmark(category: str, db: AsyncSession) -> dict | None:
        """查询品类 Top 20% CTR 的标杆值"""
        try:
            from app.models.image import GeneratedImage, ImageScheme
            from app.models.prediction import DailyMetric
            from app.models.product import Product

            stmt = (
                select(
                    GeneratedImage.id.label("image_id"),
                    GeneratedImage.quality_scores,
                    func.sum(DailyMetric.clicks).label("clicks"),
                    func.sum(DailyMetric.impressions).label("impressions"),
                )
                .join(GeneratedImage, DailyMetric.image_id == GeneratedImage.id)
                .join(ImageScheme, GeneratedImage.scheme_id == ImageScheme.id)
                .join(Product, ImageScheme.product_id == Product.id)
                .where(Product.category == category)
                .group_by(GeneratedImage.id)
                .having(func.sum(DailyMetric.impressions) >= 100)
            )

            result = await db.execute(stmt)
            rows = result.all()

            if not rows:
                logger.info(f"品类 {category} 无足够样本，使用默认标杆")
                return {
                    "sharpness": 65.0,
                    "lighting_uniformity": 70.0,
                    "color_harmony": 68.0,
                    "composition_balance": 72.0,
                    "information_density": 60.0,
                    "sample_count": 0,
                    "ctr_threshold": 0.03,
                }

            ranked_rows = sorted(
                rows,
                key=lambda row: (row.clicks / row.impressions) if row.impressions else 0,
                reverse=True,
            )
            total = len(ranked_rows)
            top_n = max(1, int(total * 0.2))
            top_rows = ranked_rows[:top_n]
            ctr_threshold = (
                top_rows[-1].clicks / top_rows[-1].impressions
                if top_rows and top_rows[-1].impressions
                else 0.03
            )

            dimension_values: dict[str, list[float]] = {
                item["name"]: [] for item in DIMENSION_META
            }
            for row in top_rows:
                quality_scores = row.quality_scores or {}
                dimensions = (quality_scores.get("l2") or {}).get("dimensions") or {}
                for dimension_name in dimension_values:
                    value = dimensions.get(dimension_name)
                    if isinstance(value, int | float):
                        dimension_values[dimension_name].append(float(value))

            defaults = {
                "sharpness": 65.0,
                "lighting_uniformity": 70.0,
                "color_harmony": 68.0,
                "composition_balance": 72.0,
                "information_density": 60.0,
            }
            return {
                **{
                    name: (
                        sum(values) / len(values)
                        if values
                        else defaults[name]
                    )
                    for name, values in dimension_values.items()
                },
                "sample_count": total,
                "ctr_threshold": ctr_threshold,
            }

        except Exception as e:
            logger.warning(f"标杆查询失败: {e}")
            return None

    @staticmethod
    def _generate_suggestions(dimensions: list[DimensionScore]) -> list[ImprovementSuggestion]:
        """基于各维度差距生成具体改进建议，选取差距最大的 3 个维度。"""
        suggestions: list[ImprovementSuggestion] = []

        sorted_dims = sorted(dimensions, key=lambda d: d.gap)

        priority = 1
        for dim in sorted_dims:
            if dim.gap >= -5:
                continue

            templates = SUGGESTION_TEMPLATES.get(dim.name, [])
            if templates:
                tpl = templates[0]
                suggestions.append(ImprovementSuggestion(
                    dimension=dim.name,
                    priority=priority,
                    title=tpl["title"],
                    description=tpl["description"],
                    expected_improvement=tpl["expected_improvement"],
                ))
                priority += 1

            if priority > 4:
                break

        if not suggestions:
            suggestions.append(ImprovementSuggestion(
                dimension="overall",
                priority=1,
                title="图片质量良好",
                description="所有质量维度均已达到或超过品类标杆水平。建议保持当前拍摄标准，关注市场趋势变化。",
                expected_improvement="维持当前水平即可获得稳定的 CTR 表现。",
            ))

        return suggestions
