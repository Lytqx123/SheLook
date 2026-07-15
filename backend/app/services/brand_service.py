"""
品牌视觉一致性服务

从 brand_standards 表加载品牌规范，对生成图片做：
1. 色板检测 —— 提取图片主色调，与品牌色板比对
2. 水印检测 —— 检测四角区域是否存在未授权水印
3. 禁用图案检测 —— 基于规则的禁用元素筛查
4. 供应商评分聚合 —— 按品牌聚合供应商的通过率/质量分/合规分
"""

import math

from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.models import BrandStandard, GeneratedImage, ReviewStatus
from app.services.image_fetcher import open_image_source

# 色板匹配阈值：颜色距离小于此值视为"在色板内"
# RGB 空间欧氏距离，经验值 ~30 容许轻微色偏
COLOR_DISTANCE_THRESHOLD = 30.0

# 主色调覆盖率下限：至少 60% 像素落在品牌色板内才算通过
COLOR_COVERAGE_MIN = 0.60

# 水印检测参数
WATERMARK_CORNER_SIZE = 0.15  # 角落区域占图片尺寸的比例
WATERMARK_BRIGHTNESS_THRESHOLD = 220  # 角落区域亮度高于此值疑似水印

# Logo 检测参数
LOGO_CLIP_THRESHOLD = 0.25  # CLIP 相似度高于此值视为疑似 Logo 区域
LOGO_REGIONS = ["top_left", "top_right", "bottom_left", "bottom_right"]

# 禁用图案 CLIP 检测阈值
FORBIDDEN_PATTERN_CLIP_THRESHOLD = 0.30

# 常见禁用图案标签 → CLIP 文本描述映射
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
    """从数据库加载品牌视觉规范

    Args:
        db: 异步数据库会话
        brand_id: 品牌唯一标识

    Returns:
        BrandStandard 对象，不存在或已停用则返回 None
    """
    result = await db.execute(
        select(BrandStandard)
        .where(
            BrandStandard.brand_id == brand_id,
            BrandStandard.is_active == True,  # noqa: E712
        )
    )
    return result.scalar_one_or_none()


def extract_dominant_colors(image_path: str, num_colors: int = 5) -> list[tuple[int, int, int]]:
    """提取图片主色调

    用 PIL 缩放 + 颜色量化快速获取主色调，不依赖 scikit-learn。

    Args:
        image_path: 图片本地路径
        num_colors: 返回的颜色数量

    Returns:
        [(R, G, B), ...] 按"像素占比从高到低"排序
    """
    img = open_image_source(image_path)
    # 缩放到 100x100 加速处理，不影响主色调提取
    img.thumbnail((100, 100))

    # 量化到指定颜色数
    quantized = img.quantize(colors=num_colors, method=Image.Quantize.MEDIANCUT)
    palette = quantized.getpalette()  # [R,G,B, R,G,B, ...]

    # 统计每种颜色的像素数
    color_counts = quantized.getcolors()  # [(count, palette_index), ...]
    color_counts.sort(reverse=True)  # 按像素数降序

    colors = []
    for _count, idx in color_counts[:num_colors]:
        r = palette[idx * 3]
        g = palette[idx * 3 + 1]
        b = palette[idx * 3 + 2]
        colors.append((r, g, b))

    return colors


def _color_distance(c1: tuple[int, int, int], c2: tuple[int, int, int]) -> float:
    """RGB 空间欧氏距离"""
    return math.sqrt(
        (c1[0] - c2[0]) ** 2 + (c1[1] - c2[1]) ** 2 + (c1[2] - c2[2]) ** 2
    )


def check_color_palette(
    image_path: str,
    brand_palette: list[list[int]],
) -> dict:
    """色板合规检测

    提取图片主色调，检查是否落在品牌色板范围内。

    Args:
        image_path: 图片本地路径
        brand_palette: 品牌色板，如 [[255, 0, 0], [0, 255, 0], ...]

    Returns:
        {
            "passed": bool,
            "coverage": float,  # 0-1，落在色板内的像素比例
            "dominant_colors": [(R,G,B), ...],
            "matched_colors": [...],
            "unmatched_colors": [...],
        }
    """
    if not brand_palette:
        # 未配置色板则跳过
        return {
            "passed": True,
            "coverage": 1.0,
            "note": "品牌未配置色板，跳过检测",
        }

    # 将品牌色板转为 tuple 列表
    palette_tuples = [tuple(c) for c in brand_palette]

    # 提取主色调
    dominant_colors = extract_dominant_colors(image_path, num_colors=8)

    matched = []
    unmatched = []
    total_weight = 0
    matched_weight = 0

    # 对每个主色调检查是否在品牌色板内
    # 简化处理：每个主色调等权
    for color in dominant_colors:
        # 找品牌色板中最近的颜色
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
    """水印检测

    检测图片四角是否存在未授权水印/Logo 叠加。
    原理：水印通常出现在角落，且亮度明显高于或低于周围区域。

    Args:
        image_path: 图片本地路径
        watermark_prohibited: 是否禁止水印（品牌规范）

    Returns:
        {"passed": bool, "detected": bool, "corners": {...}}
    """
    if not watermark_prohibited:
        return {"passed": True, "detected": False, "note": "品牌允许水印，跳过检测"}

    import numpy as np

    img = open_image_source(image_path)
    width, height = img.size
    arr = np.array(img, dtype=np.float64)

    # 四角区域大小
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
        # 高亮度区域疑似水印（白色文字/Logo 叠加）
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
    """用 CLIP zero-shot 检测图片中的 Logo 区域

    把图片切 4 宫格（左上/右上/左下/右下），对每个格子计算与
    "a brand logo watermark text overlay" 文本的 CLIP 相似度。
    CLIP 未初始化时降级到角落亮度检测（复用水印检测逻辑）。

    Args:
        image_path: 图片本地路径
        threshold: 相似度高于此值视为疑似 Logo 区域

    Returns:
        {
            "method": "clip_zero_shot" | "brightness_fallback",
            "threshold": float,
            "region_scores": {"top_left": 0.31, ...},
            "detected_regions": ["top_left"],
            "has_logo": bool,
        }
    """

    img = open_image_source(image_path)
    width, height = img.size

    # 4 宫格切分
    regions = {
        "top_left": (0, 0, width // 2, height // 2),
        "top_right": (width // 2, 0, width, height // 2),
        "bottom_left": (0, height // 2, width // 2, height),
        "bottom_right": (width // 2, height // 2, width, height),
    }

    # 尝试用 CLIP zero-shot 检测
    try:
        from app.services.embedding_service import (
            compute_similarity,
            encode_text,
            get_clip_embedding,
        )

        # 文本 prompt：Logo/水印/品牌标识
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
        # CLIP 未初始化，降级到亮度检测
        return _detect_logo_by_brightness(image_path, img)


def _detect_logo_by_brightness(image_path: str, img=None) -> dict:
    """亮度检测降级方案：检测四角区域是否存在高亮 Logo 叠加

    复用水印检测的亮度逻辑，作为 CLIP 不可用时的兜底。
    """
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
        # 归一化到 0-1 作为 score
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
    """使用 CLIP zero-shot 检测禁用图案

    将图片与禁用图案的文本描述进行 CLIP 相似度比对。
    CLIP 不可用时降级为跳过。

    Args:
        image_path: 图片本地路径
        pattern: 禁用图案名称

    Returns:
        {"method": str, "detected": bool, "score": float|None, ...}
    """
    pattern_lower = pattern.lower()

    # 匹配禁用图案标签
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
    """检查 Logo 位置是否符合品牌规范

    Args:
        image_path: 图片本地路径
        expected_position: 品牌规范要求的位置，如 "top_left" / "top_right" /
                          "bottom_left" / "bottom_right" / "none"（禁止 Logo）

    Returns:
        {
            "passed": bool,
            "expected_position": str,
            "detected_regions": [...],
            "has_logo": bool,
            "note": str,
        }
    """
    if not expected_position:
        return {"passed": True, "note": "品牌未配置 Logo 位置规范，跳过检测"}

    detection = detect_logo_regions(image_path)
    detected = detection["detected_regions"]
    has_logo = detection["has_logo"]

    # 品牌规范禁止 Logo
    if expected_position == "none":
        return {
            "passed": not has_logo,
            "expected_position": expected_position,
            "detected_regions": detected,
            "has_logo": has_logo,
            "method": detection["method"],
            "note": "品牌禁止 Logo" + ("，检测到疑似 Logo" if has_logo else ""),
        }

    # 品牌要求 Logo 在指定位置
    if expected_position not in LOGO_REGIONS:
        return {
            "passed": True,
            "expected_position": expected_position,
            "note": f"未知 Logo 位置规范: {expected_position}，跳过检测",
        }

    # 检查检测到的 Logo 是否在期望位置
    if expected_position in detected:
        passed = True
        note = f"Logo 位置符合规范: {expected_position}"
    elif has_logo:
        # 检测到 Logo 但不在期望位置
        passed = False
        note = f"Logo 位置不符规范，期望 {expected_position}，实际 {detected}"
    else:
        # 未检测到 Logo
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
    """禁用图案检测

    基于 CLIP zero-shot 目标检测：当禁用图案包含 "logo" 相关项时，
    调用 detect_logo_regions 做实际检测；其他图案使用 CLIP zero-shot
    分类与常见禁用图案标签（offensive/explicit/violence/weapon 等）比对。

    Args:
        image_path: 图片本地路径
        forbidden_patterns: 禁用图案名称列表

    Returns:
        {"passed": bool, "checked_patterns": [...], "violations": [...]}
    """
    if not forbidden_patterns:
        return {"passed": True, "checked_patterns": [], "note": "无禁用图案配置"}

    checked = []
    violations = []

    for pattern in forbidden_patterns:
        pattern_lower = pattern.lower()

        # Logo 相关图案：调用 CLIP zero-shot 检测
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
            # 其他禁用图案：使用 CLIP zero-shot 分类检测
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
    """品牌视觉一致性完整评估

    从 brand_standards 表加载品牌规范，执行色板/水印/禁用图案三项检测。

    Args:
        db: 异步数据库会话
        image_path: 图片本地路径
        brand_id: 品牌ID

    Returns:
        {
            "passed": bool,
            "brand_id": str,
            "brand_name": str,
            "color_palette_check": {...},
            "watermark_check": {...},
            "forbidden_patterns_check": {...},
        }
    """
    standard = await load_brand_standard(db, brand_id)

    if standard is None:
        # 品牌规范不存在，走默认宽松校验
        logger.warning(f"品牌规范未找到: {brand_id}，使用默认宽松校验")
        return {
            "passed": True,
            "brand_id": brand_id,
            "brand_name": "unknown",
            "note": "品牌规范未配置，跳过品牌一致性校验",
        }

    # 色板检测
    color_palette = standard.color_palette or []
    palette_list = color_palette.get("colors", []) if isinstance(color_palette, dict) else color_palette
    color_result = check_color_palette(image_path, palette_list)

    # 水印检测
    watermark_rules = standard.watermark_rules or {}
    watermark_prohibited = watermark_rules.get("prohibited", True) if isinstance(watermark_rules, dict) else True
    watermark_result = check_watermark(image_path, watermark_prohibited)

    # 禁用图案检测
    forbidden = standard.forbidden_patterns or []
    forbidden_result = check_forbidden_patterns(image_path, forbidden)

    # Logo 位置检测（基于 CLIP zero-shot 目标检测）
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
    """供应商视觉评分聚合

    从 generated_images + review_records 表聚合该供应商所有图片的：
    - 通过率/质量分（基础指标）
    - problem_dimensions 维度违规次数（003 迁移新增）
    回写到 supplier_visual_scores 表，合规分按违规严重程度加权。

    应在审核完成后调用，保持评分实时更新。

    Args:
        db: 异步数据库会话
        supplier_id: 供应商ID
        brand_id: 品牌ID（可选，按品牌细分评分）

    Returns:
        {"supplier_id": str, "total_images": int, "pass_rate": float,
         "problem_dimension_scores": {...}, "compliance_score": float, ...}
    """
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

    # 注意：Product 表无 brand_id 字段，brand_id 仅用于 SupplierVisualScore 记录的分类键
    # 不在此处对 Product 做品牌过滤

    result = (await db.execute(base_query)).one()

    total = int(result.total_images or 0)
    approved = int(result.approved_count or 0)
    rejected = int(result.rejected_count or 0)
    avg_quality = float(result.avg_quality or 0)

    pass_rate = approved / total if total > 0 else 0

    # ---- 聚合 problem_dimensions：统计各维度违规次数 ----
    # 关联 ReviewRecord，查出该供应商所有驳回记录的问题维度标注
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

    # Python 层面聚合：{dimension_key: violation_count}
    dim_counts: dict[str, int] = {}
    for dims in problem_rows:
        if not isinstance(dims, dict):
            continue
        for key, val in dims.items():
            if val:  # 只统计值为 True 的维度
                dim_counts[key] = dim_counts.get(key, 0) + 1

    total_violations = sum(dim_counts.values())

    # 合规分 = 通过率 * 100 - 维度违规惩罚（每次违规扣 5 分，最多扣 30 分）
    violation_penalty = min(total_violations * 5, 30)
    compliance_score = max(0.0, pass_rate * 100 - violation_penalty)

    # 回写 supplier_visual_scores 表
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
