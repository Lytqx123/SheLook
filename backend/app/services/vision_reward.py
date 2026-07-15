"""
九维审美启发式评估（2.2-L3）

参考 VisionReward（CVPR 2025）多维度偏好学习框架，提供面向
AI 生成图片的 9 维度审美评估。当前实现采用
基于规则的评分 + CLIP Zero-shot 分析，具备清晰的接口以便后续
集成真实 VisionReward 模型权重。

真实模型集成路径（未来）：
  1. 下载 VisionReward 预训练权重
  2. 使用 torch.load 加载权重
  3. 将基于规则的评分替换为模型推理
  4. 切换 model_version 为 "visionreward-v1"
"""

import asyncio

import numpy as np

from app.core.logging import logger
from app.services.embedding_service import compute_similarity, encode_image, encode_text
from app.services.image_analysis_utils import (
    color_richness_score,
    composition_balance_score,
    histogram_entropy_score,
    lighting_uniformity_score,
    load_image_pixels,
    pixel_range_score,
    sharpness_score,
)

# VisionReward 9 维度定义
VISION_REWARD_DIMENSIONS = [
    "subject_consistency",      # 主体一致性
    "imaging_quality",          # 成像质量
    "motion_smoothness",        # 动作流畅度
    "aesthetic_quality",        # 美学质量
    "color_harmony",            # 色彩和谐
    "lighting_naturalness",     # 光影自然
    "composition_balance",      # 构图平衡
    "style_consistency",        # 风格一致
    "brand_alignment",          # 品牌调性
]

# 每维度对应的 CLIP 文本描述（用于 Zero-shot 相似度）
DIMENSION_TEXT_DESCRIPTORS = {
    "subject_consistency": "a photo with consistent subject identity and coherent visual elements",
    "imaging_quality": "a high resolution photo with sharp details and no artifacts",
    "motion_smoothness": "a photo with natural dynamic pose and smooth visual flow",
    "aesthetic_quality": "a visually beautiful and aesthetically pleasing photo",
    "color_harmony": "a photo with balanced and harmonious color palette",
    "lighting_naturalness": "a photo with natural and soft lighting conditions",
    "composition_balance": "a photo with well-balanced composition and framing",
    "style_consistency": "a photo with unified and consistent artistic style",
    "brand_alignment": "a professional e-commerce product photo suitable for brand display",
}


def _heuristic_dimension_score(dim: str, pixels: np.ndarray) -> float:
    """针对特定维度的基于规则启发式评分（0-100）。

    当无法进行 CLIP 分析或作为补充时使用。
    公共像素统计算法委托给 image_analysis_utils，此处仅保留
    vision_reward 特有的 motion_smoothness 维度。
    """
    if dim == "imaging_quality":
        return sharpness_score(pixels)

    elif dim == "lighting_naturalness":
        return lighting_uniformity_score(pixels)

    elif dim == "color_harmony":
        return color_richness_score(pixels)

    elif dim == "composition_balance":
        return composition_balance_score(pixels)

    elif dim == "aesthetic_quality":
        return histogram_entropy_score(pixels)

    elif dim == "motion_smoothness":
        # 近似：图像梯度平滑度（水平/垂直方向差异）
        gray = np.mean(pixels, axis=2)
        grad_h = np.mean(np.abs(np.diff(gray, axis=1)))
        grad_v = np.mean(np.abs(np.diff(gray, axis=0)))
        smoothness = (grad_h + grad_v) / 2
        return min(100, max(0, 100 - smoothness))

    else:
        # subject_consistency / style_consistency / brand_alignment
        # 基于像素统计给出中性基准分，主要依赖 CLIP 评分
        return pixel_range_score(pixels, floor=30)


async def _clip_dimension_scores(
    image_path: str,
    dimensions: list[str],
) -> dict[str, float]:
    """使用 CLIP Zero-shot 为各维度评分。

    将图片嵌入向量与每维度的文本描述进行比对，
    余弦相似度映射为 0-100 分数。
    """
    try:
        image_vector = await asyncio.to_thread(encode_image, image_path)
    except Exception as e:
        logger.warning(f"CLIP 图片编码失败 {image_path}: {e}")
        return {}

    scores = {}
    for dim in dimensions:
        descriptor = DIMENSION_TEXT_DESCRIPTORS.get(dim)
        if not descriptor:
            scores[dim] = 50.0
            continue

        try:
            text_vector = await asyncio.to_thread(encode_text, descriptor)
            similarity = compute_similarity(image_vector, text_vector)
            # 余弦相似度范围 [-1, 1] → [0, 100]
            scores[dim] = round(max(0, min(100, (similarity + 1) / 2 * 100)), 1)
        except Exception as e:
            logger.warning(f"CLIP 维度 '{dim}' 评分失败: {e}")
            scores[dim] = 50.0

    return scores


async def evaluate_vision_reward(
    image_path: str,
    dimensions: list[str] | None = None,
) -> dict:
    """参考 VisionReward 维度设计的多维度审美启发式评估。

    当前使用启发式规则 + CLIP 分析的组合方案。
    将像素级启发式评分与 CLIP Zero-shot 评分融合，生成
    包含逐维度和两两对比的完整评估结果。

    Args:
        image_path: 图片文件路径或 URL
        dimensions: 要评估的维度子集，None 表示使用全部 9 维度

    Returns:
        {
            "overall_score": float (0-100),
            "dimension_scores": {dim: float},
            "pairwise_comparisons": list[dict],
            "model_version": "heuristic-v1",
        }
    """
    target_dims = dimensions or VISION_REWARD_DIMENSIONS

    # 验证维度名称
    invalid_dims = [d for d in target_dims if d not in VISION_REWARD_DIMENSIONS]
    if invalid_dims:
        valid_list = ", ".join(VISION_REWARD_DIMENSIONS)
        logger.warning(f"无效维度: {invalid_dims}，有效选项: {valid_list}")

    valid_dims = [d for d in target_dims if d in VISION_REWARD_DIMENSIONS]
    if not valid_dims:
        valid_dims = VISION_REWARD_DIMENSIONS

    # 1. 像素级启发式评分
    pixels = load_image_pixels(image_path)
    heuristic_scores: dict[str, float] = {}
    if pixels is not None:
        for dim in valid_dims:
            heuristic_scores[dim] = _heuristic_dimension_score(dim, pixels)

    # 2. CLIP Zero-shot 评分
    clip_scores = await _clip_dimension_scores(image_path, valid_dims)

    # 3. 融合评分：CLIP 权重 0.6，启发式权重 0.4
    dimension_scores: dict[str, float] = {}
    for dim in valid_dims:
        h_score = heuristic_scores.get(dim, 50.0)
        c_score = clip_scores.get(dim, 50.0)
        dimension_scores[dim] = round(h_score * 0.4 + c_score * 0.6, 1)

    # 4. 综合评分（等权平均）
    if dimension_scores:
        overall_score = round(
            sum(dimension_scores.values()) / len(dimension_scores), 1
        )
    else:
        overall_score = 0.0

    # 5. 两两对比矩阵（相邻维度的相对比较）
    pairwise_comparisons = []
    sorted_dims = sorted(valid_dims, key=lambda d: dimension_scores.get(d, 0))
    for i in range(len(sorted_dims) - 1):
        dim_a = sorted_dims[i + 1]  # 得分更高
        dim_b = sorted_dims[i]      # 得分更低
        pairwise_comparisons.append({
            "dimension_a": dim_a,
            "score_a": dimension_scores[dim_a],
            "dimension_b": dim_b,
            "score_b": dimension_scores[dim_b],
            "delta": round(dimension_scores[dim_a] - dimension_scores[dim_b], 1),
            "preference": f"{dim_a} > {dim_b}",
        })

    logger.info(
        "审美启发式评估完成",
        image_path=str(image_path),
        overall_score=overall_score,
        dimensions_count=len(valid_dims),
    )

    return {
        "overall_score": overall_score,
        "dimension_scores": dimension_scores,
        "pairwise_comparisons": pairwise_comparisons,
        "model_version": "heuristic-v1",
    }
