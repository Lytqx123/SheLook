"""
合规校验服务 —— EU AI Act 披露 + 品牌一致性 + 内容安全。
独立于 reward_scorer 的 L1 质检，专注法律合规与平台治理。
"""

import logging
from pathlib import Path

from app.services.image_fetcher import open_image_source

logger = logging.getLogger(__name__)

# EU AI Act 要求的关键披露字段
_REQUIRED_DISCLOSURE_FIELDS = [
    "ai_generated",
    "generation_model",
    "generation_timestamp",
]

# 敏感内容检测阈值
SENSITIVE_CLIP_THRESHOLD = 0.30

SENSITIVE_CONTENT_LABELS = [
    "explicit content",
    "violence",
    "drug reference",
    "weapon",
    "alcohol",
]


def check_ai_disclosure(metadata: dict | None = None) -> dict:
    """检查 EU AI Act 披露标识是否完备。"""
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
    """品牌视觉一致性校验：色板 / 水印 / 禁用图案。

    brand_standard 来自 brand_standards 表，未提供时只做基础尺寸检查。
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

        if width < 200 or height < 200:
            violations.append({
                "rule": "min_dimensions",
                "description": "Image too small, possible corrupted or thumbnailed",
                "requirement": ">=200px each dimension",
                "actual": f"{width}x{height}",
            })

        if brand_standard is None:
            checks.append({
                "rule": "brand_standard",
                "description": "品牌规范未加载，跳过色板/水印/禁用图案检测",
                "passed": True,
                "note": "Pass brand_standard dict to enable full checks",
            })
        else:
            # 色板
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
                    "description": f"色板覆盖率低于阈值",
                })

            # 水印
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

            # 禁用图案
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
    """敏感内容检测：NSFW + CLIP Zero-shot 分类 + 像素统计。
    
    双层检测：NSFW CLIP 分类 + 像素统计分析。
    这段是跟 fairness 那边一起写的，阈值是拍脑袋定的，后续需要校准。
    """

    # NSFW 检测（v2 新增）
    nsfw_result = check_nsfw(image_path)

    try:
        import numpy as np

        img = open_image_source(image_path)
        img_array = np.array(img, dtype=np.float64)

        mean_brightness = np.mean(img_array)
        std_brightness = np.std(img_array)

        pixel_risk = "safe"
        if std_brightness < 10:
            pixel_risk = "low"

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

        risk_rank = {"safe": 0, "low": 1, "medium": 2, "high": 3}
        final_rank = max(
            risk_rank.get(pixel_risk, 0),
            risk_rank.get(clip_risk_level, 0),
        )

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


# NSFW 检测
NSFW_CLIP_THRESHOLD = 0.28

NSFW_LABELS = [
    "not safe for work explicit sexual content nudity",
    "safe for work professional product photo",
]

NSFW_PIXEL_RISK_THRESHOLD = 5.0


def check_nsfw(image_path: str | Path) -> dict:
    """NSFW 检测：CLIP Zero-shot safe/nsfw 二分类，不可用时降级像素分析。"""
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

        nsfw_score = scores.get(NSFW_LABELS[0], 0.0)
        safe_score = scores.get(NSFW_LABELS[1], 0.0)

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

    # 降级：纯像素
    try:
        import numpy as np

        img = open_image_source(image_path)
        pixels = np.array(img, dtype=np.float64)
        gray = np.mean(pixels, axis=2)

        std_brightness = np.std(gray)

        if std_brightness < NSFW_PIXEL_RISK_THRESHOLD:
            return {
                "passed": True,
                "risk_level": "low",
                "score": 0.0,
                "method": "pixel_fallback",
                "note": "Low variance image - cannot determine NSFW status reliably",
            }

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
    """EXIF 合规：检查 GPS 定位泄漏。"""
    issues = []

    try:
        img = open_image_source(image_path)
        exif = img.getexif()

        if not exif:
            return {"passed": True, "issues": []}

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
    """验证 C2PA manifest 是否存在且有效（兼容旧接口）。"""
    from app.services.c2pa_service import verify_c2pa_manifest_v2
    return verify_c2pa_manifest_v2(c2pa_manifest)


def full_compliance_check(
    image_path: str | Path,
    metadata: dict | None = None,
    brand_id: str | None = None,
    c2pa_manifest: str | None = None,
    brand_standard: dict | None = None,
) -> dict:
    """完整合规流水线：AI披露 → 品牌一致性 → 敏感内容 → EXIF → C2PA。"""
    ai_disclosure = check_ai_disclosure(metadata)
    brand_compliance = check_brand_compliance(image_path, brand_id, brand_standard)
    sensitive_content = check_sensitive_content(image_path)
    exif_compliance = check_exif_compliance(image_path)

    c2pa_result = verify_c2pa_manifest(c2pa_manifest) if c2pa_manifest is not None else None

    all_passed = (
        ai_disclosure["passed"]
        and brand_compliance["passed"]
        and sensitive_content["passed"]
        and exif_compliance["passed"]
        and (c2pa_result["passed"] if c2pa_result is not None else True)
    )

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
