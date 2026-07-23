"""
品牌视觉一致性服务 —— 色板 / 水印 / 禁用图案 / 供应商评分聚合。
从 brand_standards 表加载规范，对生成图片做检测。
"""

import math

from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.models import BrandStandard, GeneratedImage, ReviewStatus
from app.services.image_fetcher import open_image_source

# 色板匹配阈值（RGB 欧氏距离）
COLOR_DISTANCE_THRESHOLD = 30.0

# 主色调覆盖率下限
COLOR_COVERAGE_MIN = 0.60

# 水印检测
WATERMARK_CORNER_SIZE = 0.15
WATERMARK_BRIGHTNESS_THRESHOLD = 220

# Logo 检测
LOGO_CLIP_THRESHOLD = 0.25
LOGO_REGIONS = ["top_left", "top_right", "bottom_left", "bottom_right"]

# 禁用图案
FORBIDDEN_PATTERN_CLIP_THRESHOLD = 0.30

FORBIDDEN_PATTERN_LABELS = {
    "offensive": "offensive text or hateful symbol",
    "explicit": "explicit nudity or sexual content",
    "violence": "violence symbol or gore",
    "weapon": "weapon or firearm",
    "drug": "drug reference or paraphernalia",
    "alcohol": "alcohol bottle or drinking reference",
    "trademark": "trademark violation or counterfeit logo",
}


async def load_brand_standard(db: AsyncSession, brand_id: str) -> BrandStandard | None:
    """从 DB 加载品牌规范。"""
    result = await db.execute(
        select(BrandStandard)
        .where(
            BrandStandard.brand_id == brand_id,
            BrandStandard.is_active == True,  # noqa: E712
        )
    )
    return result.scalar_one_or_none()


def extract_dominant_colors(image_path: str, num_colors: int = 5) -> list[tuple[int, int, int]]:
    """提取主色调，用 PIL 缩放 + 量化，不依赖 sklearn。"""
    img = open_image_source(image_path)
    img.thumbnail((100, 100))

    quantized = img.quantize(colors=num_colors, method=Image.Quantize.MEDIANCUT)
    palette = quantized.getpalette()

    color_counts = quantized.getcolors()
    color_counts.sort(reverse=True)

    colors = []
    for _count, idx in color_counts[:num_colors]:
        r = palette[idx * 3]
        g = palette[idx * 3 + 1]
        b = palette[idx * 3 + 2]
        colors.append((r, g, b))

    return colors


def _color_distance(c1: tuple[int, int, int], c2: tuple[int, int, int]) -> float:
    return math.sqrt(
        (c1[0] - c2[0]) ** 2 + (c1[1] - c2[1]) ** 2 + (c1[2] - c2[2]) ** 2
    )


def check_color_palette(
    image_path: str,
    brand_palette: list[list[int]],
) -> dict:
    """色板合规：提取主色调，检查落在品牌色板内的像素比例。"""
    if not brand_palette:
        return {
            "passed": True,
            "coverage": 1.0,
            "note": "品牌未配置色板，跳过检测",
        }

    palette_tuples = [tuple(c) for c in brand_palette]
    dominant_colors = extract_dominant_colors(image_path, num_colors=8)

    matched = []
    unmatched = []
    total_weight = 0
    matched_weight = 0

    for color in dominant_colors:
        min_dist = min(_color_distance(color, pc) for pc in palette_tuples)
        if min_dist <= COLOR_DISTANCE_THRESHOLD:
            matched.append(color)
            matched_weight += 1
        else:
            unmatched.append({"color": color, "nearest_distance": round(min_dist, 2)})
        total_weight += 1

    coverage = matched_weight / total_weight if total_weight > 0 else 0
    passed = coverage >= COLOR_COVERAGE_MIN

    return {
        "passed": passed,
        "coverage": round(coverage, 4),
        "threshold": COLOR_COVERAGE_MIN,
        "dominant_colors": dominant_colors,
        "matched_count": len(matched),
        "unmatched": unmatched,
    }


def check_watermark(
    image_path: str,
    watermark_prohibited: bool = True,
) -> dict:
    """水印检测：检查四角高亮区域是否有疑似水印。"""
    if not watermark_prohibited:
        return {"passed": True, "detected": False, "note": "品牌允许水印，跳过检测"}

    import numpy as np

    img = open_image_source(image_path)
    width, height = img.size
    arr = np.array(img, dtype=np.float64)

    corner_w = int(width * WATERMARK_CORNER_SIZE)
    corner_h = int(height * WATERMARK_CORNER_SIZE)

    corners = {}
    detected = False

    for name, (y_start, y_end, x_start, x_end) in {
        "top_left": (0, corner_h, 0, corner_w),
        "top_right": (0, corner_h, width - corner_w, width),
        "bottom_left": (height - corner_h, height, 0, corner_w),
        "bottom_right": (height - corner_h, height, width - corner_w, width),
    }.items():
        region = arr[y_start:y_end, x_start:x_end]
        mean_brightness = float(np.mean(region))
        has_watermark = mean_brightness > WATERMARK_BRIGHTNESS_THRESHOLD
        corners[name] = {
            "mean_brightness": round(mean_brightness, 2),
            "suspected_watermark": has_watermark,
        }
        if has_watermark:
            detected = True

    return {
        "passed": not detected,
        "detected": detected,
        "corners": corners,
    }


def detect_logo_regions(image_path: str, threshold: float = LOGO_CLIP_THRESHOLD) -> dict:
    """4 宫格切分图片，用 CLIP zero-shot 检测 Logo 区域。

    这段 AI 写的，CLIP 不可用时降级亮度检测。
    FIXME: CLIP 对透明 Logo 的检测效果一般。
    """

    img = open_image_source(image_path)
    width, height = img.size

    regions = {
        "top_left": (0, 0, width // 2, height // 2),
        "top_right": (width // 2, 0, width, height // 2),
        "bottom_left": (0, height // 2, width // 2, height),
        "bottom_right": (width // 2, height // 2, width, height),
    }

    try:
        from app.services.embedding_service import (
            compute_similarity,
            encode_text,
            get_clip_embedding,
        )

        logo_text_vec = encode_text("a brand logo watermark text overlay")

        region_scores = {}
        detected_regions = []

        for name, box in regions.items():
            crop = img.crop(box)
            img_vec = get_clip_embedding(crop)
            score = compute_similarity(img_vec, logo_text_vec)
            region_scores[name] = round(score, 4)
            if score >= threshold:
                detected_regions.append(name)

        return {
            "method": "clip_zero_shot",
            "threshold": threshold,
            "region_scores": region_scores,
            "detected_regions": detected_regions,
            "has_logo": len(detected_regions) > 0,
        }
    except RuntimeError:
        return _detect_logo_by_brightness(image_path, img)


def _detect_logo_by_brightness(image_path: str, img=None) -> dict:
    """亮度降级检测——检测四角区域高亮叠加。"""
    import numpy as np

    if img is None:
        img = open_image_source(image_path)

    width, height = img.size
    arr = np.array(img, dtype=np.float64)

    corner_w = int(width * WATERMARK_CORNER_SIZE)
    corner_h = int(height * WATERMARK_CORNER_SIZE)

    region_scores = {}
    detected_regions = []

    for name, (y_start, y_end, x_start, x_end) in {
        "top_left": (0, corner_h, 0, corner_w),
        "top_right": (0, corner_h, width - corner_w, width),
        "bottom_left": (height - corner_h, height, 0, corner_w),
        "bottom_right": (height - corner_h, height, width - corner_w, width),
    }.items():
        region = arr[y_start:y_end, x_start:x_end]
        mean_brightness = float(np.mean(region))
        score = round(mean_brightness / 255.0, 4)
        region_scores[name] = score
        if mean_brightness > WATERMARK_BRIGHTNESS_THRESHOLD:
            detected_regions.append(name)

    return {
        "method": "brightness_fallback",
        "threshold": WATERMARK_BRIGHTNESS_THRESHOLD / 255.0,
        "region_scores": region_scores,
        "detected_regions": detected_regions,
        "has_logo": len(detected_regions) > 0,
        "note": "CLIP 未初始化，降级到亮度检测",
    }


def _detect_pattern_via_clip(image_path: str, pattern: str) -> dict:
    """CLIP zero-shot 禁用图案检测。"""
    pattern_lower = pattern.lower()

    matched_label = pattern
    for key, label in FORBIDDEN_PATTERN_LABELS.items():
        if key in pattern_lower:
            matched_label = label
            break

    try:
        from app.services.embedding_service import (
            compute_similarity,
            encode_image,
            encode_text,
        )

        image_vector = encode_image(image_path)
        text_vector = encode_text(matched_label)
        score = compute_similarity(image_vector, text_vector)
        detected = score >= FORBIDDEN_PATTERN_CLIP_THRESHOLD
        return {
            "method": "clip_zero_shot",
            "detected": detected,
            "score": round(score, 4),
            "label": matched_label,
        }
    except Exception as e:
        logger.warning(f"CLIP 禁用图案检测失败 '{pattern}': {e}")
        return {
            "method": "clip_unavailable",
            "detected": False,
            "score": None,
            "note": "CLIP 不可用，跳过检测",
        }


def check_logo_position(image_path: str, expected_position: str | None) -> dict:
    """检查 Logo 位置是否符品牌规范。"""
    if not expected_position:
        return {"passed": True, "note": "品牌未配置 Logo 位置规范，跳过检测"}

    detection = detect_logo_regions(image_path)
    detected = detection["detected_regions"]
    has_logo = detection["has_logo"]

    if expected_position == "none":
        return {
            "passed": not has_logo,
            "expected_position": expected_position,
            "detected_regions": detected,
            "has_logo": has_logo,
            "method": detection["method"],
            "note": "品牌禁止 Logo" + ("，检测到疑似 Logo" if has_logo else ""),
        }

    if expected_position not in LOGO_REGIONS:
        return {
            "passed": True,
            "expected_position": expected_position,
            "note": f"未知 Logo 位置规范: {expected_position}，跳过检测",
        }

    if expected_position in detected:
        passed = True
        note = f"Logo 位置符合规范: {expected_position}"
    elif has_logo:
        passed = False
        note = f"Logo 位置不符规范，期望 {expected_position}，实际 {detected}"
    else:
        passed = False
        note = f"期望 Logo 在 {expected_position}，但未检测到"

    return {
        "passed": passed,
        "expected_position": expected_position,
        "detected_regions": detected,
        "has_logo": has_logo,
        "method": detection["method"],
        "region_scores": detection["region_scores"],
        "note": note,
    }


def check_forbidden_patterns(
    image_path: str,
    forbidden_patterns: list[str],
) -> dict:
    """禁用图案检测：Logo 相关用 CLIP 区域检测，其余用 Zero-shot 分类。"""
    if not forbidden_patterns:
        return {"passed": True, "checked_patterns": [], "note": "无禁用图案配置"}

    checked = []
    violations = []

    for pattern in forbidden_patterns:
        pattern_lower = pattern.lower()

        if "logo" in pattern_lower or "水印" in pattern or "watermark" in pattern_lower:
            detection = detect_logo_regions(image_path)
            detected = detection["has_logo"]
            checked.append({
                "pattern": pattern,
                "detected": detected,
                "method": detection["method"],
                "detected_regions": detection["detected_regions"],
                "region_scores": detection["region_scores"],
            })
            if detected:
                violations.append({
                    "pattern": pattern,
                    "regions": detection["detected_regions"],
                })
        else:
            detection = _detect_pattern_via_clip(image_path, pattern)
            checked.append({
                "pattern": pattern,
                "detected": detection["detected"],
                "method": detection["method"],
                "score": detection.get("score"),
            })
            if detection["detected"]:
                violations.append({
                    "pattern": pattern,
                    "score": detection.get("score"),
                })

    return {
        "passed": len(violations) == 0,
        "checked_patterns": checked,
        "violations": violations,
    }


async def evaluate_brand_compliance(
    db: AsyncSession,
    image_path: str,
    brand_id: str,
) -> dict:
    """品牌视觉一致性完整评估。"""
    standard = await load_brand_standard(db, brand_id)

    if standard is None:
        logger.warning(f"品牌规范未找到: {brand_id}，使用默认宽松校验")
        return {
            "passed": True,
            "brand_id": brand_id,
            "brand_name": "unknown",
            "note": "品牌规范未配置，跳过品牌一致性校验",
        }

    color_palette = standard.color_palette or []
    palette_list = color_palette.get("colors", []) if isinstance(color_palette, dict) else color_palette
    color_result = check_color_palette(image_path, palette_list)

    watermark_rules = standard.watermark_rules or {}
    watermark_prohibited = watermark_rules.get("prohibited", True) if isinstance(watermark_rules, dict) else True
    watermark_result = check_watermark(image_path, watermark_prohibited)

    forbidden = standard.forbidden_patterns or []
    forbidden_result = check_forbidden_patterns(image_path, forbidden)

    logo_result = check_logo_position(image_path, standard.logo_position)

    all_passed = (
        color_result["passed"]
        and watermark_result["passed"]
        and forbidden_result["passed"]
        and logo_result["passed"]
    )

    return {
        "passed": all_passed,
        "brand_id": brand_id,
        "brand_name": standard.brand_name,
        "color_palette_check": color_result,
        "watermark_check": watermark_result,
        "forbidden_patterns_check": forbidden_result,
        "logo_position_check": logo_result,
    }


async def update_supplier_score(
    db: AsyncSession,
    supplier_id: str,
    brand_id: str | None = None,
) -> dict:
    """供应商评分聚合：通过率/质量分/合规分 + 问题维度统计。"""
    from app.models import ImageScheme, Product, ReviewAction, ReviewRecord

    base_query = (
        select(
            func.count(GeneratedImage.id).label("total_images"),
            func.avg(GeneratedImage.overall_score).label("avg_quality"),
            func.count(GeneratedImage.id)
            .filter(GeneratedImage.review_status == ReviewStatus.AUTO_APPROVED)
            .label("approved_count"),
            func.count(GeneratedImage.id)
            .filter(GeneratedImage.review_status == ReviewStatus.REJECTED)
            .label("rejected_count"),
        )
        .join(ImageScheme, ImageScheme.id == GeneratedImage.scheme_id)
        .join(Product, Product.id == ImageScheme.product_id)
        .where(Product.supplier_id == supplier_id)
    )

    result = (await db.execute(base_query)).one()

    total = int(result.total_images or 0)
    approved = int(result.approved_count or 0)
    rejected = int(result.rejected_count or 0)
    avg_quality = float(result.avg_quality or 0)

    pass_rate = approved / total if total > 0 else 0

    # 聚合问题维度
    problem_query = (
        select(ReviewRecord.problem_dimensions)
        .join(GeneratedImage, GeneratedImage.id == ReviewRecord.image_id)
        .join(ImageScheme, ImageScheme.id == GeneratedImage.scheme_id)
        .join(Product, Product.id == ImageScheme.product_id)
        .where(
            Product.supplier_id == supplier_id,
            ReviewRecord.action == ReviewAction.REJECTED,
            ReviewRecord.problem_dimensions.isnot(None),
        )
    )
    problem_rows = (await db.execute(problem_query)).scalars().all()

    dim_counts: dict[str, int] = {}
    for dims in problem_rows:
        if not isinstance(dims, dict):
            continue
        for key, val in dims.items():
            if val:
                dim_counts[key] = dim_counts.get(key, 0) + 1

    total_violations = sum(dim_counts.values())

    # 合规分 = 通过率 * 100 - 维度违规惩罚
    violation_penalty = min(total_violations * 5, 30)
    compliance_score = max(0.0, pass_rate * 100 - violation_penalty)

    from datetime import datetime

    from app.models import SupplierVisualScore

    existing = await db.execute(
        select(SupplierVisualScore)
        .where(
            SupplierVisualScore.supplier_id == supplier_id,
            SupplierVisualScore.brand_id == brand_id if brand_id else SupplierVisualScore.brand_id.is_(None),
        )
    )
    existing_record = existing.scalar_one_or_none()

    if existing_record:
        existing_record.total_images = total
        existing_record.pass_rate = round(pass_rate, 4)
        existing_record.avg_quality_score = round(avg_quality, 2)
        existing_record.compliance_score = round(compliance_score, 2)
        existing_record.problem_dimension_scores = dim_counts if dim_counts else None
        existing_record.last_evaluated_at = datetime.utcnow()
    else:
        new_record = SupplierVisualScore(
            supplier_id=supplier_id,
            brand_id=brand_id,
            total_images=total,
            pass_rate=round(pass_rate, 4),
            avg_quality_score=round(avg_quality, 2),
            compliance_score=round(compliance_score, 2),
            problem_dimension_scores=dim_counts if dim_counts else None,
            last_evaluated_at=datetime.utcnow(),
        )
        db.add(new_record)

    await db.commit()

    logger.info(
        "供应商评分更新",
        supplier_id=supplier_id,
        brand_id=brand_id,
        total=total,
        pass_rate=pass_rate,
        violations=total_violations,
        dim_counts=dim_counts,
    )

    return {
        "supplier_id": supplier_id,
        "brand_id": brand_id,
        "total_images": total,
        "approved_count": approved,
        "rejected_count": rejected,
        "pass_rate": round(pass_rate, 4),
        "avg_quality_score": round(avg_quality, 2),
        "compliance_score": round(compliance_score, 2),
        "problem_dimension_scores": dim_counts,
        "total_violations": total_violations,
    }
