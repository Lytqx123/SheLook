"""
Visual Reward 打分服务 —— L1-L3 三级质检（v2）

参考 VisionReward 多维度框架（基础质量/内容相关性/美学价值）
v2 升级：L2 质量评估采用学术级算法
- 清晰度: FFT 高频能量占比（替代灰度方差近似）
- 色彩和谐度: HSV 色相分布熵（替代 RGB 标准差均值）
- 信息密度: Laplacian 方差（新增维度）
"""

import logging
from pathlib import Path

import numpy as np

from app.services.image_analysis_utils import (
    composition_balance_score,
    fft_high_freq_energy,
    histogram_entropy_score,
    hsv_entropy,
    is_url,
    # v2 学术级算法
    laplacian_variance,
    lighting_uniformity_score,
    load_image,
    load_image_pixels,
)

logger = logging.getLogger(__name__)


# L1 合规层：规则引擎
def l1_compliance_check(image_path: str | Path) -> dict:
    """
    L1 合规检查

    检查项：
    - 分辨率 >= 800x800
    - 主体占比 >= 40%（简化：图像文件大小判断）
    - 尺寸比例偏差 < 5%

    Returns:
        {"passed": bool, "checks": [...], "issues": [...]}
    """
    issues = []

    try:
        img = load_image(image_path)
        width, height = img.size

        # 分辨率检查
        if width < 800 or height < 800:
            issues.append({
                "dimension": "resolution",
                "requirement": ">=800x800",
                "actual": f"{width}x{height}",
                "passed": False,
            })
        else:
            issues.append({
                "dimension": "resolution",
                "requirement": ">=800x800",
                "actual": f"{width}x{height}",
                "passed": True,
            })

        # 尺寸比例检查（期望 1:1，偏差 < 5%）
        aspect_ratio = width / height if height > 0 else 0
        ratio_deviation = abs(aspect_ratio - 1.0)
        if ratio_deviation > 0.05:
            issues.append({
                "dimension": "aspect_ratio",
                "requirement": "1:1 (±5%)",
                "actual": f"{width}x{height} ({aspect_ratio:.3f})",
                "passed": False,
            })
        else:
            issues.append({
                "dimension": "aspect_ratio",
                "requirement": "1:1 (±5%)",
                "actual": f"{width}x{height} ({aspect_ratio:.3f})",
                "passed": True,
            })

        # 文件大小合理性检查（URL 时用 Content-Length，本地用 stat）
        if is_url(image_path):
            try:
                from app.services.image_fetcher import fetch_image_sync

                file_size_kb = len(fetch_image_sync(str(image_path)).data) / 1024
            except Exception:
                file_size_kb = 0
        else:
            path_obj = Path(image_path)
            file_size_kb = path_obj.stat().st_size / 1024 if path_obj.exists() else 0
        if file_size_kb < 10:
            issues.append({
                "dimension": "file_size",
                "requirement": ">=10KB",
                "actual": f"{file_size_kb:.1f}KB",
                "passed": False,
            })
        else:
            issues.append({
                "dimension": "file_size",
                "requirement": ">=10KB",
                "actual": f"{file_size_kb:.1f}KB",
                "passed": True,
            })

    except Exception as e:
        logger.error(f"L1 check error: {e}")
        issues.append({
            "dimension": "file_read",
            "requirement": "valid image file",
            "actual": str(e),
            "passed": False,
        })

    all_passed = all(c["passed"] for c in issues)

    return {
        "passed": all_passed,
        "checks": issues,
        "issues": [i for i in issues if not i["passed"]],
    }


# L2 质量层：多维度打分（v2 学术级算法）
def l2_quality_scoring(image_path: str | Path) -> dict:
    """
    L2 质量评分 —— v2 学术级算法版本

    维度1：清晰度（FFT 高频能量占比）
    维度2：光影均匀度（亮度直方图标准差）
    维度3：色彩和谐度（HSV 色相分布熵）
    维度4：构图平衡（中心区域亮度与边缘差异）
    维度5：信息密度（Laplacian 方差）

    Returns:
        {
            "overall_score": float (0-100),
            "dimensions": {
                "sharpness": float,
                "lighting_uniformity": float,
                "color_harmony": float,
                "composition_balance": float,
                "information_density": float,
            },
            "verdict": "auto_approved" | "manual_pending" | "rejected"
        }
    """
    try:
        pixels = load_image_pixels(image_path)
        if pixels is None:
            raise ValueError("图片像素加载失败")

        # 1. 清晰度（FFT 高频能量占比，权重 0.25）
        sharpness = fft_high_freq_energy(pixels)

        # 2. 光影均匀度（亮度标准差越小越均匀，权重 0.15）
        lighting_uniformity = lighting_uniformity_score(pixels)

        # 3. 色彩和谐度（HSV 色相分布熵，权重 0.25）
        color_harmony = hsv_entropy(pixels)

        # 4. 构图平衡（中心 vs 四角亮度差异，权重 0.15）
        composition_balance = composition_balance_score(pixels)

        # 5. 信息密度（Laplacian 方差，权重 0.20）
        information_density = laplacian_variance(pixels)

        dimension_scores = {
            "sharpness": round(float(sharpness), 1),
            "lighting_uniformity": round(float(lighting_uniformity), 1),
            "color_harmony": round(float(color_harmony), 1),
            "composition_balance": round(float(composition_balance), 1),
            "information_density": round(float(information_density), 1),
        }

        # 综合分 = 加权平均
        weights = {
            "sharpness": 0.25,
            "lighting_uniformity": 0.15,
            "color_harmony": 0.25,
            "composition_balance": 0.15,
            "information_density": 0.20,
        }
        overall = sum(dimension_scores[k] * weights[k] for k in dimension_scores)

        # 判定
        if overall >= 75:
            verdict = "auto_approved"
        elif overall >= 60:
            verdict = "manual_pending"
        else:
            verdict = "rejected"

        return {
            "overall_score": round(float(overall), 1),
            "dimensions": dimension_scores,
            "verdict": verdict,
        }

    except Exception as e:
        logger.error(f"L2 quality scoring error: {e}")
        return {
            "overall_score": 0,
            "dimensions": {},
            "verdict": "rejected",
            "error": str(e),
        }


# L3 审美层：美学评分
def l3_aesthetic_scoring(image_path: str | Path) -> dict:
    """
    L3 审美评分（简化版：基于图像统计特征）

    评估构图、光影美学、色彩和谐度
    返回 0-100 分的审美分
    """
    try:
        pixels = load_image_pixels(image_path)
        if pixels is None:
            raise ValueError("图片像素加载失败")

        gray = np.mean(pixels, axis=2)

        # 三分法构图评分（简化：偏离中心的吸引力）
        h, w = gray.shape
        h_third, w_third = h // 3, w // 3
        # 检查三分线交点区域的亮度对比
        points = [
            (h_third, w_third),
            (h_third, 2 * w_third),
            (2 * h_third, w_third),
            (2 * h_third, 2 * w_third),
        ]
        contrast_scores = []
        for py, px in points:
            patch = gray[max(0, py - 10):min(h, py + 10), max(0, px - 10):min(w, px + 10)]
            if patch.size > 0:
                patch_std = np.std(patch)
                contrast_scores.append(min(1.0, patch_std / 50))
        composition_score = np.mean(contrast_scores) * 100 if contrast_scores else 50

        # 色彩和谐度（饱和度适中为佳）
        r, g, b = pixels[:, :, 0], pixels[:, :, 1], pixels[:, :, 2]
        saturation = np.std([np.mean(r), np.mean(g), np.mean(b)])
        saturation_score = min(100, max(0, 100 - abs(saturation - 40) * 2))

        # 光影层次（直方图熵）
        lighting_score = histogram_entropy_score(pixels)

        overall_aesthetic = (composition_score + saturation_score + lighting_score) / 3

        return {
            "aesthetic_score": round(float(overall_aesthetic), 1),
            "composition": round(float(composition_score), 1),
            "color_harmony": round(float(saturation_score), 1),
            "lighting_depth": round(float(lighting_score), 1),
        }

    except Exception as e:
        logger.error(f"L3 aesthetic scoring error: {e}")
        return {"aesthetic_score": 0, "error": str(e)}


# 完整三级质检流水线
def full_quality_pipeline(
    image_path: str | Path,
    product_title: str = "",
    product_description: str = "",
    tags: list[str] | None = None,
) -> dict:
    """
    执行完整 L1 → L2 → L3 质检流水线

    Args:
        image_path: 图片路径或 URL
        product_title: 商品标题（可选，用于 L1 图文匹配验证）
        product_description: 商品描述（可选）
        tags: 商品标签（可选）

    Returns:
        {
            "l1": {...},
            "l2": {...},
            "l3": {...},
            "overall_score": float,
            "review_status": "auto_approved" | "manual_pending" | "rejected",
            "failed_dimensions": [...],
        }
    """
    # L1 合规
    l1 = l1_compliance_check(image_path)

    # L1 图文匹配验证（当商品标题提供时）
    if product_title and l1["passed"]:
        try:
            from app.services.image_text_matcher import check_image_text_match_sync
            match_result = check_image_text_match_sync(
                image_path=str(image_path),
                product_title=product_title,
                product_description=product_description,
                tags=tags,
            )
            l1["text_match"] = match_result
            if not match_result["match"]:
                l1["passed"] = False
                l1["issues"].append({
                    "dimension": "text_match",
                    "requirement": f"similarity >= {match_result['threshold']}",
                    "actual": f"{match_result['similarity_score']}",
                    "passed": False,
                })
                l1["checks"].append({
                    "dimension": "text_match",
                    "requirement": f"similarity >= {match_result['threshold']}",
                    "actual": f"{match_result['similarity_score']}",
                    "passed": False,
                })
            else:
                l1["checks"].append({
                    "dimension": "text_match",
                    "requirement": f"similarity >= {match_result['threshold']}",
                    "actual": f"{match_result['similarity_score']}",
                    "passed": True,
                })
        except Exception as e:
            logger.error(f"L1 图文匹配验证失败: {e}")
            # 图文匹配失败不阻塞整体流程

    if not l1["passed"]:
        return {
            "l1": l1,
            "l2": None,
            "l3": None,
            "overall_score": 0,
            "review_status": "rejected",
            "failed_dimensions": [i["dimension"] for i in l1["issues"]],
        }

    # L2 质量
    l2 = l2_quality_scoring(image_path)

    # L3 审美
    l3 = l3_aesthetic_scoring(image_path)

    # L2 综合分 × 0.7 + L3 审美分 × 0.3
    overall = l2["overall_score"] * 0.7 + l3.get("aesthetic_score", 0) * 0.3

    if overall >= 75:
        review_status = "auto_approved"
    elif overall >= 60:
        review_status = "manual_pending"
    else:
        review_status = "rejected"

    # 收集不合格维度（<60 分的维度）
    failed_dimensions = [
        dim for dim, score in l2["dimensions"].items() if score < 60
    ]

    return {
        "l1": l1,
        "l2": l2,
        "l3": l3,
        "overall_score": round(float(overall), 1),
        "review_status": review_status,
        "failed_dimensions": failed_dimensions,
    }


def evaluate_quality(image_url: str, scheme: object | None = None) -> dict | None:
    """
    质量评估统一入口（供 Celery 任务调用）

    支持 HTTP(S) URL 和本地路径。URL 会通过 httpx 下载到内存后评估。
    仅当真实评估失败时才降级为保守低分（50.0），标记为需人工复审。

    Args:
        image_url: 图片 URL 或本地路径
        scheme: 关联的方案对象（用于风格一致性校验，预留）

    Returns:
        {"scores": {...}, "overall": float} 或 None
    """
    try:
        result = full_quality_pipeline(image_url)
        return {
            "scores": result,
            "overall": result.get("overall_score", 0),
        }
    except Exception as e:
        logger.warning(f"evaluate_quality 真实评估失败，降级为保守低分（需人工复审）: {e}")
        conservative_score = 50.0
        return {
            "scores": {
                "l1": {
                    "passed": False,
                    "checks": [],
                    "issues": [{
                        "dimension": "assessment_failure",
                        "requirement": "real quality assessment completed",
                        "actual": f"assessment failed: {e}",
                        "passed": False,
                    }],
                },
                "l2": {
                    "overall_score": conservative_score,
                    "dimensions": {
                        "sharpness": conservative_score,
                        "lighting_uniformity": conservative_score,
                        "color_harmony": conservative_score,
                        "composition_balance": conservative_score,
                        "information_density": conservative_score,
                    },
                    "verdict": "manual_pending",
                },
                "l3": {
                    "aesthetic_score": conservative_score,
                    "composition": conservative_score,
                    "color_harmony": conservative_score,
                    "lighting_depth": conservative_score,
                },
                "overall_score": conservative_score,
                "review_status": "manual_pending",
                "failed_dimensions": ["assessment_failure"],
            },
            "overall": conservative_score,
        }


def calculate_significance(metrics_a: dict, metrics_b: dict) -> dict:
    """
    计算 A/B 两组指标的统计显著性

    Args:
        metrics_a: {"ctr": float, "impressions": int, "clicks": int}
        metrics_b: {"ctr": float, "impressions": int, "clicks": int}

    Returns:
        {"p_value": float, "winner": "A"|"B"|None, "is_significant": bool}
    """
    from app.services.attribution import calculate_p_value

    ctr_a = metrics_a.get("ctr", 0)
    ctr_b = metrics_b.get("ctr", 0)

    impressions_a = metrics_a.get("impressions", 1000)
    clicks_a = metrics_a.get("clicks", int(impressions_a * ctr_a))

    impressions_b = metrics_b.get("impressions", 1000)
    clicks_b = metrics_b.get("clicks", int(impressions_b * ctr_b))

    try:
        p_value = calculate_p_value(impressions_a, clicks_a, impressions_b, clicks_b)
    except Exception:
        p_value = 1.0

    is_significant = p_value < 0.05

    winner = None
    if is_significant:
        if ctr_a > ctr_b:
            winner = "A"
        elif ctr_b > ctr_a:
            winner = "B"

    return {
        "p_value": round(float(p_value), 4),
        "winner": winner,
        "is_significant": is_significant,
    }
