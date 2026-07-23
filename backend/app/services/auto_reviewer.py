"""AI 自动审核 —— 用 Gemini Flash 做图片质量 L2/L3 评分。
SIGIR 2025 研究显示 MLLM 与人工评审相关性可达 0.85+ Spearman。
审核流程：Gemini 预审 → 阈值判断 → 输出问题维度 + 置信度。
"""

import json

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.logging import logger
from app.services.provider_config_service import resolve_provider_runtime_config

# 审核维度定义（跟 L2/L3 对齐）
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

# 阈值设定
AUTO_APPROVE_THRESHOLD = 70  # >= 70 自动通过
AUTO_REJECT_THRESHOLD = 40   # < 40 自动驳回
# [40, 70) → 人工复审


async def auto_review_image(
    image_url: str,
    product_category: str = "",
    product_title: str = "",
    *,
    db: AsyncSession | None = None,
    tenant_id: str | None = None,
) -> dict:
    """用 Gemini Flash 审核图片质量，返回评分 + 诊断 + 建议。"""
    provider_config = (
        await resolve_provider_runtime_config(db, "gemini", tenant_id) if db is not None else None
    )
    if provider_config is None:
        if settings.APP_ENV == "production":
            raise RuntimeError("Gemini 未在外部 API 配置中心启用，生产环境拒绝伪造 AI 审核结果")
        logger.warning("Gemini 未在外部 API 配置中心启用，开发环境使用启发式审核")
        return _mock_auto_review(image_url)

    try:
        from google import genai
        from google.genai import types

        base_url = provider_config.config.get("api_base_url")
        http_options = types.HttpOptions(base_url=base_url) if base_url else None
        client = genai.Client(api_key=provider_config.credentials["api_key"], http_options=http_options)

        context = ""
        if product_category:
            context += f"商品品类: {product_category}\n"
        if product_title:
            context += f"商品标题: {product_title}\n"

        # 这段 prompt 是 AI 写的，调了好几次才稳定输出 JSON 格式
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
        # 清理 markdown 代码块标记（Gemini 偶尔会在 JSON 外面包 ```）
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

        # 提取严重/中等问题维度
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
    """Gemini 不可用时降级为启发式评分。

    根据图片分辨率/文件大小/宽高比算一个启发式分数，
    让不同图片得分不同而不是固定值。
    先这样，后面有更好的降级方案再改。
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

            # 分辨率评分：min(边) >= 800 得满分 30
            min_dim = min(width, height)
            res_score = min(30.0, min_dim / 800 * 30)
            base_score += res_score

            # 宽高比评分：接近 1:1 得满分 20
            aspect = width / height if height > 0 else 1.0
            aspect_score = max(0.0, 20.0 - abs(aspect - 1.0) * 40)
            base_score += aspect_score

            # 文件大小：>= 100KB 得满分 20
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
    """格式化为前端展示用的数据结构。"""
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
