"""AI 自动审核服务 —— 基于 Gemini Flash 多模态大模型

2026 最新研究（SIGIR 2025）：
  MLLMs（Gemini / GPT-4o / Claude）在电商图片质量评估中
  与人工评审的一致性可达 0.85+ Spearman 相关性。

本服务对 L2（视觉效果）和 L3（美学）评分进行 LLM 增强，
输出结构化诊断报告（问题类别 + 严重程度 + 改进建议）。

审核流程：
  1. Gemini Flash 图片预审 → 生成结构化诊断
  2. 阈值判断（overall >= 70 自动通过，< 40 自动驳回，中间人工复审）
  3. 输出问题维度 + 置信度
"""

import json

from app.config import settings
from app.core.logging import logger

# 审核维度定义（与 L2/L3 对齐）
REVIEW_DIMENSIONS = {
    "sharpness": {
        "label": "清晰度",
        "severity_weights": {"严重": 10, "中等": 5, "轻微": 2},
    },
    "lighting": {
        "label": "光照",
        "severity_weights": {"严重": 10, "中等": 5, "轻微": 2},
    },
    "color_harmony": {
        "label": "色彩和谐",
        "severity_weights": {"严重": 8, "中等": 4, "轻微": 1},
    },
    "composition": {
        "label": "构图",
        "severity_weights": {"严重": 8, "中等": 4, "轻微": 1},
    },
    "product_visibility": {
        "label": "商品可见性",
        "severity_weights": {"严重": 12, "中等": 6, "轻微": 3},
    },
    "aesthetic_appeal": {
        "label": "美学吸引力",
        "severity_weights": {"严重": 6, "中等": 3, "轻微": 1},
    },
    "brand_compliance": {
        "label": "品牌一致性",
        "severity_weights": {"严重": 10, "中等": 5, "轻微": 2},
    },
}

# 自动审核阈值
AUTO_APPROVE_THRESHOLD = 70  # >= 70 分自动通过
AUTO_REJECT_THRESHOLD = 40   # < 40 分自动驳回
# 中间区间 [40, 70) → 人工复审


async def auto_review_image(
    image_url: str,
    product_category: str = "",
    product_title: str = "",
) -> dict:
    """使用 Gemini Flash 自动审核图片质量

    Args:
        image_url: 图片 URL
        product_category: 商品品类（用于上下文）
        product_title: 商品标题（用于图文一致性检查）

    Returns:
        {
            "overall_score": int (0-100),
            "passed": bool,
            "need_manual_review": bool,
            "dimensions": {...},
            "diagnosis": str,
            "suggestions": [...],
            "model": "gemini-2.0-flash",
        }
    """
    api_key = settings.GEMINI_API_KEY
    if not api_key:
        if settings.APP_ENV == "production":
            raise RuntimeError("GEMINI_API_KEY 未配置，生产环境拒绝伪造 AI 审核结果")
        logger.warning("GEMINI_API_KEY 未配置，开发环境使用启发式审核")
        return _mock_auto_review(image_url)

    try:
        from google import genai
        from google.genai import types

        http_options = types.HttpOptions(base_url=settings.GEMINI_BASE_URL) if settings.GEMINI_BASE_URL else None
        client = genai.Client(api_key=api_key, http_options=http_options)

        # 构建审核 prompt
        context = ""
        if product_category:
            context += f"商品品类: {product_category}\n"
        if product_title:
            context += f"商品标题: {product_title}\n"

        prompt = f"""You are an e-commerce product image quality auditor.
Evaluate this product image for the following dimensions.
{context}
For each dimension, provide:
  - score: integer 0-100
  - severity: "正常" | "轻微" | "中等" | "严重"
  - remark: brief comment in Chinese

Dimensions:
  1. sharpness - 清晰度/分辨率是否足够，是否有模糊
  2. lighting - 光照是否均匀，是否有过曝/欠曝
  3. color_harmony - 色彩搭配是否和谐，饱和度是否自然
  4. composition - 构图是否合理，商品是否居中对焦
  5. product_visibility - 商品是否完整可见，是否被遮挡
  6. aesthetic_appeal - 整体美学观感（风格、质感、高级感）
  7. brand_compliance - 品牌调性是否一致

Return ONLY a JSON object (no markdown, no explanation):
{{
  "overall_score": <0-100>,
  "dimensions": {{
    "sharpness": {{"score": <0-100>, "severity": "...", "remark": "..."}},
    "lighting": {{"score": <0-100>, "severity": "...", "remark": "..."}},
    "color_harmony": {{"score": <0-100>, "severity": "...", "remark": "..."}},
    "composition": {{"score": <0-100>, "severity": "...", "remark": "..."}},
    "product_visibility": {{"score": <0-100>, "severity": "...", "remark": "..."}},
    "aesthetic_appeal": {{"score": <0-100>, "severity": "...", "remark": "..."}},
    "brand_compliance": {{"score": <0-100>, "severity": "...", "remark": "..."}}
  }},
  "diagnosis": "<overall quality assessment in Chinese>",
  "suggestions": ["<improvement tip 1>", "<improvement tip 2>"]
}}"""

        # 下载图片并转为 inline_data 传给 Gemini
        from app.services.image_fetcher import fetch_image

        fetched = await fetch_image(image_url)
        image_data = fetched.data
        content_type = fetched.content_type

        response = await client.aio.models.generate_content(
            model="gemini-2.0-flash",
            contents=[
                types.Part.from_bytes(data=image_data, mime_type=content_type),
                prompt,
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.1,
            ),
        )

        result_text = response.text.strip()
        # 清理可能的 markdown 代码块标记
        if result_text.startswith("```"):
            result_text = result_text.split("\n", 1)[-1] if "\n" in result_text else result_text
        if result_text.endswith("```"):
            result_text = result_text.rsplit("```", 1)[0]
        result_text = result_text.strip()
        review = json.loads(result_text)

        overall = review.get("overall_score", 50)
        review["passed"] = overall >= AUTO_APPROVE_THRESHOLD
        review["need_manual_review"] = (
            AUTO_REJECT_THRESHOLD <= overall < AUTO_APPROVE_THRESHOLD
        )
        review["model"] = "gemini-2.0-flash"

        # 提取严重问题维度
        problem_dimensions = {}
        for dim_key, dim_data in review.get("dimensions", {}).items():
            severity = dim_data.get("severity", "轻微")
            if severity in ("严重", "中等"):
                dim_label = REVIEW_DIMENSIONS.get(dim_key, {}).get("label", dim_key)
                problem_dimensions[dim_label] = severity

        review["problem_dimensions"] = problem_dimensions

        logger.info(
            "AI 自动审核完成",
            overall=overall,
            passed=review["passed"],
            need_manual=review["need_manual_review"],
        )
        return review

    except ImportError:
        if settings.APP_ENV == "production":
            raise
        logger.debug("google-genai 未安装，开发环境使用启发式审核")
        return _mock_auto_review(image_url)
    except json.JSONDecodeError as e:
        logger.warning("AI 审核 JSON 解析失败", error=str(e))
        if settings.APP_ENV == "production":
            raise
        return _mock_auto_review(image_url)
    except Exception as e:
        logger.error("AI 自动审核失败", error=str(e))
        if settings.APP_ENV == "production":
            raise
        return _mock_auto_review(image_url)


def _mock_auto_review(image_url: str = "") -> dict:
    """模拟审核（Gemini 不可用时的降级）

    基于图片属性（分辨率、文件大小、宽高比）计算启发式评分，
    使不同图片获得不同分数而非固定值。
    """
    base_score = 50.0
    image_info = {}

    try:
        from app.services.image_fetcher import fetch_image_sync, open_image_source

        source_str = str(image_url) if image_url else ""
        img = None
        file_size_kb = 0.0

        if source_str.startswith(("http://", "https://")):
            img_data = fetch_image_sync(source_str).data
            file_size_kb = len(img_data) / 1024
            img = open_image_source(img_data)
        elif source_str:
            import os

            if os.path.exists(source_str):
                file_size_kb = os.path.getsize(source_str) / 1024
                img = open_image_source(source_str)

        if img is not None:
            width, height = img.size
            image_info = {
                "width": width,
                "height": height,
                "file_size_kb": round(file_size_kb, 1),
            }

            # 分辨率评分：min(边) >= 800 得满分 30，按比例递减
            min_dim = min(width, height)
            res_score = min(30.0, min_dim / 800 * 30)
            base_score += res_score

            # 宽高比评分：接近 1:1 得满分 20
            aspect = width / height if height > 0 else 1.0
            aspect_score = max(0.0, 20.0 - abs(aspect - 1.0) * 40)
            base_score += aspect_score

            # 文件大小评分：>= 100KB 得满分 20
            size_score = min(20.0, file_size_kb / 100 * 20)
            base_score += size_score

    except Exception as error:
        logger.warning("启发式审核无法读取图片属性", error=str(error))

    overall = round(min(100.0, max(0.0, base_score)), 1)

    return {
        "overall_score": overall,
        "passed": overall >= AUTO_APPROVE_THRESHOLD,
        "need_manual_review": AUTO_REJECT_THRESHOLD <= overall < AUTO_APPROVE_THRESHOLD,
        "dimensions": {},
        "diagnosis": "AI 审核暂不可用，基于图片属性启发式评分，请人工复核",
        "suggestions": ["请人工检查图片质量", "AI 审核服务恢复后建议重新审核"],
        "model": "heuristic_mock",
        "problem_dimensions": {},
        "image_info": image_info,
    }


def format_review_for_ui(review: dict) -> dict:
    """格式化审核结果为前端展示格式"""
    return {
        "overall_score": review.get("overall_score", 0),
        "passed": review.get("passed", False),
        "need_manual_review": review.get("need_manual_review", True),
        "diagnosis": review.get("diagnosis", ""),
        "suggestions": review.get("suggestions", []),
        "problem_dimensions": review.get("problem_dimensions", {}),
        "dimensions": {
            dim_key: {
                "label": REVIEW_DIMENSIONS.get(dim_key, {}).get("label", dim_key),
                **dim_data,
            }
            for dim_key, dim_data in review.get("dimensions", {}).items()
        },
        "model": review.get("model", "mock"),
        "thresholds": {
            "auto_approve": AUTO_APPROVE_THRESHOLD,
            "auto_reject": AUTO_REJECT_THRESHOLD,
        },
    }
