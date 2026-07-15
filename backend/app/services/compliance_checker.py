"""
合规校验服务 —— EU AI Act 披露 + 品牌一致性 + 内容安全

独立于 reward_scorer.py 的 L1 质检（图片质量维度），
本模块专注于法律合规与平台治理相关的校验。
"""

import logging
from pathlib import Path

from app.services.image_fetcher import open_image_source

logger = logging.getLogger(__name__)

# EU AI Act 要求的关键披露信息
_REQUIRED_DISCLOSURE_FIELDS = [
    "ai_generated",
    "generation_model",
    "generation_timestamp",
]

# CLIP 敏感内容检测阈值
SENSITIVE_CLIP_THRESHOLD = 0.30

# 敏感内容 CLIP 标签
SENSITIVE_CONTENT_LABELS = [
    "explicit content",
    "violence",
    "drug reference",
    "weapon",
    "alcohol",
]


def check_ai_disclosure(metadata: dict | None = None) -> dict:
    """
    EU AI Act 披露标识检查

    检查生成图片的元数据中是否包含 AI 生成的合规标识。

    Args:
        metadata: 图片元数据字典（从 generation_params 或 c2pa_manifest 提取）

    Returns:
        {"passed": bool, "missing_fields": [...], "recommendation": str}
    """
    if metadata is None:
        metadata = {}

    missing = [f for f in _REQUIRED_DISCLOSURE_FIELDS if f not in metadata]

    return {
        "passed": len(missing) == 0,
        "missing_fields": missing,
        "recommendation": (
            "All AI-generated images must include ai_generated=True, "
            "generation_model name, and generation_timestamp in metadata"
            if missing
            else "Disclosure compliant"
        ),
    }


def check_brand_compliance(
    image_path: str | Path,
    brand_id: str | None = None,
    brand_standard: dict | None = None,
) -> dict:
    """
    品牌视觉一致性校验

    检查项：
    - 色板合规：提取图片主色调，与品牌色板比对
    - 水印检测：检测四角是否存在未授权水印
    - 禁用图案：基于规则的禁用元素筛查

    Args:
        image_path: 图片本地路径
        brand_id: 品牌ID（用于标识）
        brand_standard: 品牌规范字典（从 brand_standards 表加载），
                       含 color_palette/watermark_rules/forbidden_patterns。
                       未提供时走基础尺寸校验。

    Returns:
        {"passed": bool, "checks": [...], "violations": [...], "brand_id": str}
    """
    from app.services.brand_service import (
        check_color_palette,
        check_forbidden_patterns,
        check_watermark,
    )

    checks = []
    violations = []

    try:
        img = open_image_source(image_path)
        width, height = img.size

        # 基础尺寸校验
        if width < 200 or height < 200:
            violations.append({
                "rule": "min_dimensions",
                "description": "Image too small, possible corrupted or thumbnailed",
                "requirement": ">=200px each dimension",
                "actual": f"{width}x{height}",
            })

        if brand_standard is None:
            # 未提供品牌规范，仅做基础校验
            checks.append({
                "rule": "brand_standard",
                "description": "品牌规范未加载，跳过色板/水印/禁用图案检测",
                "passed": True,
                "note": "Pass brand_standard dict to enable full checks",
            })
        else:
            # 色板检测
            color_palette = brand_standard.get("color_palette", [])
            palette_list = (
                color_palette.get("colors", [])
                if isinstance(color_palette, dict)
                else color_palette
            )
            color_result = check_color_palette(str(image_path), palette_list)
            checks.append({
                "rule": "color_palette",
                "description": f"色板覆盖率 {color_result.get('coverage', 0):.1%}",
                "passed": color_result["passed"],
                "detail": color_result,
            })
            if not color_result["passed"]:
                violations.append({
                    "rule": "color_palette",
                    "description": f"色板覆盖率 {color_result.get('coverage', 0):.1%} 低于阈值 {color_result.get('threshold', 0):.1%}",
                })

            # 水印检测
            watermark_rules = brand_standard.get("watermark_rules", {})
            watermark_prohibited = (
                watermark_rules.get("prohibited", True)
                if isinstance(watermark_rules, dict)
                else True
            )
            watermark_result = check_watermark(str(image_path), watermark_prohibited)
            checks.append({
                "rule": "watermark",
                "description": "未授权水印检测",
                "passed": watermark_result["passed"],
                "detail": watermark_result,
            })
            if not watermark_result["passed"]:
                violations.append({
                    "rule": "watermark",
                    "description": "检测到疑似未授权水印",
                    "corners": watermark_result.get("corners", {}),
                })

            # 禁用图案检测
            forbidden = brand_standard.get("forbidden_patterns", [])
            forbidden_result = check_forbidden_patterns(str(image_path), forbidden)
            checks.append({
                "rule": "forbidden_patterns",
                "description": f"禁用图案检测（{len(forbidden)} 项）",
                "passed": forbidden_result["passed"],
                "detail": forbidden_result,
            })
            if not forbidden_result["passed"]:
                violations.append({
                    "rule": "forbidden_patterns",
                    "description": "检测到禁用图案",
                    "detail": forbidden_result,
                })

    except Exception as e:
        logger.warning(f"Brand compliance check error: {e}")
        violations.append({
            "rule": "file_access",
            "description": f"Cannot process image: {e}",
        })

    all_checks_passed = len(violations) == 0

    return {
        "passed": all_checks_passed,
        "checks": checks,
        "violations": violations,
        "brand_id": brand_id,
    }


def check_sensitive_content(image_path: str | Path) -> dict:
    """
    敏感内容检测（含 NSFW 检测 v2）

    双层检测：
    1. NSFW 内容检测（CLIP Zero-shot 分类：nsfw/safe）
    2. 像素统计分析 + CLIP 敏感内容分类（原有逻辑）

    Returns:
        {"passed": bool, "risk_level": "safe"|"low"|"medium"|"high"}
    """

    # --- NSFW 检测（v2 新增）---
    nsfw_result = check_nsfw(image_path)

    # --- 原有敏感内容检测逻辑 ---
    try:
        import numpy as np

        img = open_image_source(image_path)
        img_array = np.array(img, dtype=np.float64)

        # 像素统计分析
        mean_brightness = np.mean(img_array)
        std_brightness = np.std(img_array)

        pixel_risk = "safe"
        # 全黑或全白可能意味着生成失败（非安全风险但需标记）
        if std_brightness < 10:
            pixel_risk = "low"

        # CLIP zero-shot 分类
        clip_risk_level = "safe"
        clip_scores = {}
        max_score = 0.0
        matched_label = None

        try:
            from app.services.embedding_service import (
                compute_similarity,
                encode_image,
                encode_text,
            )

            image_vector = encode_image(str(image_path))
            for label in SENSITIVE_CONTENT_LABELS:
                text_vector = encode_text(label)
                score = compute_similarity(image_vector, text_vector)
                clip_scores[label] = round(score, 4)
                if score > max_score:
                    max_score = score
                    matched_label = label

            if max_score >= SENSITIVE_CLIP_THRESHOLD:
                clip_risk_level = "high"
            elif max_score >= SENSITIVE_CLIP_THRESHOLD * 0.8:
                clip_risk_level = "medium"
        except Exception as e:
            logger.warning(f"CLIP 敏感内容检测失败，仅使用像素分析: {e}")

        # 综合像素分析和 CLIP 分类，取较高风险等级
        risk_rank = {"safe": 0, "low": 1, "medium": 2, "high": 3}
        final_rank = max(
            risk_rank.get(pixel_risk, 0),
            risk_rank.get(clip_risk_level, 0),
        )

        # NSFW 检测结果融合：如果 NSFW 检测认为不安全，提升风险等级
        if not nsfw_result["passed"]:
            nsfw_rank = risk_rank.get(nsfw_result["risk_level"], 2)
            final_rank = max(final_rank, nsfw_rank)
            if clip_risk_level == "safe":
                clip_risk_level = "medium"

        final_risk_level = {v: k for k, v in risk_rank.items()}.get(final_rank, "safe")

        result = {
            "passed": final_risk_level in ("safe", "low"),
            "risk_level": final_risk_level,
            "pixel_analysis": {
                "mean_brightness": round(float(mean_brightness), 2),
                "std_brightness": round(float(std_brightness), 2),
                "risk": pixel_risk,
            },
        }
        if clip_scores:
            result["clip_analysis"] = {
                "scores": clip_scores,
                "matched_label": matched_label,
                "max_score": round(max_score, 4),
                "risk": clip_risk_level,
            }
        if nsfw_result:
            result["nsfw_analysis"] = nsfw_result
        if final_risk_level == "low":
            result["note"] = "Low variance image - possible generation artifact"
        return result

    except Exception as e:
        logger.error(f"Sensitive content check error: {e}")
        return {
            "passed": False,
            "risk_level": "medium",
            "error": str(e),
        }


# NSFW 检测阈值
NSFW_CLIP_THRESHOLD = 0.28

# NSFW 检测标签
NSFW_LABELS = [
    "not safe for work explicit sexual content nudity",
    "safe for work professional product photo",
]

# NSFW 降级像素检查：极暗/极亮/极低方差 → 可能是生成失败的图
NSFW_PIXEL_RISK_THRESHOLD = 5.0


def check_nsfw(image_path: str | Path) -> dict:
    """
    NSFW 内容检测（基于 CLIP Zero-shot 分类）

    使用 CLIP 模型对图片进行 safe/nsfw 二分类。
    CLIP 不可用时降级为像素统计分析。

    Args:
        image_path: 图片本地路径

    Returns:
        {
            "passed": bool,
            "risk_level": "safe" | "low" | "medium" | "high",
            "score": float,  # nsfw 倾向分数（0-1）
            "method": "clip" | "pixel_fallback",
        }
    """
    # 优先使用 CLIP Zero-shot
    try:
        from app.services.embedding_service import (
            compute_similarity,
            encode_image,
            encode_text,
        )

        image_vector = encode_image(str(image_path))
        scores = {}
        for label in NSFW_LABELS:
            tv = encode_text(label)
            scores[label] = compute_similarity(image_vector, tv)

        # nsfw 分数（nsfw 标签的相似度）
        nsfw_score = scores.get(NSFW_LABELS[0], 0.0)
        safe_score = scores.get(NSFW_LABELS[1], 0.0)

        # 归一化：nsfw / (nsfw + safe)
        total = nsfw_score + safe_score + 1e-10
        nsfw_ratio = nsfw_score / total

        if nsfw_ratio >= NSFW_CLIP_THRESHOLD:
            risk_level = "high"
            passed = False
        elif nsfw_ratio >= NSFW_CLIP_THRESHOLD * 0.7:
            risk_level = "medium"
            passed = False
        elif nsfw_ratio >= NSFW_CLIP_THRESHOLD * 0.4:
            risk_level = "low"
            passed = True
        else:
            risk_level = "safe"
            passed = True

        return {
            "passed": passed,
            "risk_level": risk_level,
            "score": round(nsfw_ratio, 4),
            "method": "clip",
            "detail": {
                "nsfw_raw": round(nsfw_score, 4),
                "safe_raw": round(safe_score, 4),
                "nsfw_ratio": round(nsfw_ratio, 4),
                "threshold": NSFW_CLIP_THRESHOLD,
            },
        }
    except Exception as e:
        logger.warning(f"CLIP NSFW 检测失败，降级为像素分析: {e}")

    # 降级：纯像素统计分析
    try:
        import numpy as np

        img = open_image_source(image_path)
        pixels = np.array(img, dtype=np.float64)
        gray = np.mean(pixels, axis=2)

        std_brightness = np.std(gray)

        # 极低方差 → 纯色图 → 可能安全（生成失败），标记为 low
        if std_brightness < NSFW_PIXEL_RISK_THRESHOLD:
            return {
                "passed": True,
                "risk_level": "low",
                "score": 0.0,
                "method": "pixel_fallback",
                "note": "Low variance image - cannot determine NSFW status reliably",
            }

        # 正常像素分析结果 → 标记为 safe（保守策略，不误判）
        return {
            "passed": True,
            "risk_level": "safe",
            "score": 0.0,
            "method": "pixel_fallback",
            "note": "CLIP unavailable, pixel analysis only - assuming safe",
        }
    except Exception as e:
        logger.error(f"NSFW pixel fallback error: {e}")
        return {
            "passed": False,
            "risk_level": "medium",
            "score": 0.5,
            "method": "error",
            "error": str(e),
        }


def check_exif_compliance(image_path: str | Path) -> dict:
    """
    EXIF 合规校验

    检查项：
    - 是否包含 GPS 定位（合规要求：不允许泄露地理位置）
    - 相机型号非空则记录（用于溯源，不视为违规）

    使用 PIL.Image.Exif 读取图片 EXIF 数据。

    Args:
        image_path: 图片本地路径

    Returns:
        {"passed": bool, "issues": [...]}
    """
    issues = []

    try:

        img = open_image_source(image_path)
        exif = img.getexif()  # PIL.Image.Exif 对象

        if not exif:
            # 无 EXIF 数据，视为合规
            return {"passed": True, "issues": []}

        # GPS 定位检查（GPSInfo IFD，tag 0x8825）
        gps_ifd = exif.get_ifd(0x8825)
        if gps_ifd:
            issues.append({
                "rule": "gps_location",
                "description": "Image contains GPS location data",
                "requirement": "No GPS data allowed for privacy compliance",
            })

    except Exception as e:
        logger.warning(f"EXIF compliance check error: {e}")
        issues.append({
            "rule": "exif_read_error",
            "description": f"Cannot read EXIF data: {e}",
        })

    return {
        "passed": len(issues) == 0,
        "issues": issues,
    }


def verify_c2pa_manifest(c2pa_manifest: str | None) -> dict:
    """
    验证 C2PA manifest 是否存在且有效（兼容旧接口）

    内部委托给 c2pa_service.verify_c2pa_manifest_v2() 进行
    C2PA 2.1 结构级校验（JSON 解析 + 关键字段验证）。

    Args:
        c2pa_manifest: C2PA manifest 字符串（JSON 格式）

    Returns:
        {"passed": bool, "manifest_valid": bool, "checks": [...], "issues": [...]}
    """
    from app.services.c2pa_service import verify_c2pa_manifest_v2
    return verify_c2pa_manifest_v2(c2pa_manifest)


def full_compliance_check(
    image_path: str | Path,
    metadata: dict | None = None,
    brand_id: str | None = None,
    c2pa_manifest: str | None = None,
    brand_standard: dict | None = None,
) -> dict:
    """
    完整合规校验流水线

    执行顺序：AI披露 → 品牌一致性 → 敏感内容 → EXIF → C2PA（若提供）

    Args:
        image_path: 图片本地路径
        metadata: 图片元数据（用于 AI 披露校验）
        brand_id: 品牌ID（用于品牌规范加载）
        c2pa_manifest: C2PA manifest 字符串（提供时才执行 C2PA 校验）
        brand_standard: 品牌规范字典（从 brand_standards 表加载），
                       含 color_palette/watermark_rules/forbidden_patterns

    Returns:
        {
            "passed": bool,
            "ai_disclosure": {...},
            "brand_compliance": {...},
            "sensitive_content": {...},
            "exif_compliance": {...},
            "c2pa_manifest": {...},  # 仅当 c2pa_manifest 提供时存在
            "violations_summary": [...],
        }
    """
    ai_disclosure = check_ai_disclosure(metadata)
    brand_compliance = check_brand_compliance(image_path, brand_id, brand_standard)
    sensitive_content = check_sensitive_content(image_path)
    exif_compliance = check_exif_compliance(image_path)

    # C2PA 校验（仅当提供 manifest 时执行）
    c2pa_result = verify_c2pa_manifest(c2pa_manifest) if c2pa_manifest is not None else None

    all_passed = (
        ai_disclosure["passed"]
        and brand_compliance["passed"]
        and sensitive_content["passed"]
        and exif_compliance["passed"]
        and (c2pa_result["passed"] if c2pa_result is not None else True)
    )

    # 汇总所有违规项
    violations_summary = []
    if not ai_disclosure["passed"]:
        violations_summary.append({
            "category": "ai_disclosure",
            "detail": ai_disclosure["missing_fields"],
            "recommendation": ai_disclosure["recommendation"],
        })
    if not brand_compliance["passed"]:
        violations_summary.extend([
            {"category": "brand_compliance", **v}
            for v in brand_compliance["violations"]
        ])
    if not exif_compliance["passed"]:
        violations_summary.extend([
            {"category": "exif_compliance", **v}
            for v in exif_compliance["issues"]
        ])
    if c2pa_result is not None and not c2pa_result["passed"]:
        violations_summary.append({
            "category": "c2pa_manifest",
            "detail": "C2PA manifest missing or invalid",
        })

    result = {
        "passed": all_passed,
        "ai_disclosure": ai_disclosure,
        "brand_compliance": brand_compliance,
        "sensitive_content": sensitive_content,
        "exif_compliance": exif_compliance,
        "violations_summary": violations_summary,
    }
    if c2pa_result is not None:
        result["c2pa_manifest"] = c2pa_result
    return result
