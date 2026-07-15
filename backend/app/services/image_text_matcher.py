"""
图片-文本匹配验证服务

基于 CLIP 模型计算生成图片与商品描述之间的图文相似度，
用于 L1 合规层验证图片是否与商品信息匹配。
"""

import asyncio

from numpy import mean

from app.core.logging import logger
from app.services.embedding_service import compute_similarity, encode_image, encode_text

DEFAULT_THRESHOLD = 0.25


def _get_threshold() -> float:
    """获取配置的图文匹配阈值"""
    try:
        from app.config import settings
        return getattr(settings, "IMAGE_TEXT_MATCH_THRESHOLD", DEFAULT_THRESHOLD)
    except Exception:
        return DEFAULT_THRESHOLD


async def check_image_text_match(
    image_path: str,
    product_title: str,
    product_description: str = "",
    tags: list[str] | None = None,
) -> dict:
    """检查生成图片与商品文本描述的 CLIP 相似度（async 入口）

    内部通过 asyncio.to_thread 调用同步 CLIP 推理，避免阻塞事件循环。
    """
    return await asyncio.to_thread(
        _compute_image_text_match,
        image_path,
        product_title,
        product_description,
        tags,
    )


def _compute_image_text_match(
    image_path: str,
    product_title: str,
    product_description: str = "",
    tags: list[str] | None = None,
) -> dict:
    """同步核心逻辑：计算图文 CLIP 相似度

    Args:
        image_path: 图片文件路径
        product_title: 商品标题
        product_description: 商品描述（可选）
        tags: 商品标签列表（可选）

    Returns:
        {
            "match": bool,
            "similarity_score": float,
            "threshold": float,
            "product_title": str,
            "details": {
                "title_similarity": float,
                "description_similarity": float | None,
                "tag_similarities": dict[str, float] | None,
            }
        }
    """
    threshold = _get_threshold()

    # 编码图片（一次，复用）
    image_vec = encode_image(image_path)

    # 1. 标题相似度
    title_vec = encode_text(product_title)
    title_similarity = compute_similarity(image_vec, title_vec)

    # 2. 描述相似度
    description_similarity: float | None = None
    if product_description:
        desc_vec = encode_text(product_description)
        description_similarity = compute_similarity(image_vec, desc_vec)

    # 3. 标签相似度
    tag_similarities: dict[str, float] | None = None
    if tags:
        tag_similarities = {}
        for tag in tags:
            tag_vec = encode_text(tag)
            tag_similarities[tag] = compute_similarity(image_vec, tag_vec)

    # 4. 加权综合分
    has_desc = description_similarity is not None
    has_tags = tag_similarities is not None and len(tag_similarities) > 0

    if has_desc and has_tags:
        avg_tag_sim = mean(list(tag_similarities.values()))
        overall = 0.5 * title_similarity + 0.3 * description_similarity + 0.2 * avg_tag_sim
    elif has_desc:
        overall = 0.6 * title_similarity + 0.4 * description_similarity
    elif has_tags:
        avg_tag_sim = mean(list(tag_similarities.values()))
        overall = 0.6 * title_similarity + 0.4 * avg_tag_sim
    else:
        overall = title_similarity

    match = overall >= threshold

    logger.info(
        "图片-文本匹配检查完成",
        match=match,
        overall_score=round(overall, 4),
        threshold=threshold,
        title_similarity=round(title_similarity, 4),
    )

    return {
        "match": match,
        "similarity_score": round(float(overall), 4),
        "threshold": threshold,
        "product_title": product_title,
        "details": {
            "title_similarity": round(float(title_similarity), 4),
            "description_similarity": round(float(description_similarity), 4) if description_similarity is not None else None,
            "tag_similarities": {k: round(float(v), 4) for k, v in tag_similarities.items()} if tag_similarities else None,
        },
    }


def check_image_text_match_sync(
    image_path: str,
    product_title: str,
    product_description: str = "",
    tags: list[str] | None = None,
) -> dict:
    """同步包装器，供 Celery 任务直接调用

    Args 同 check_image_text_match。
    """
    return _compute_image_text_match(
        image_path=image_path,
        product_title=product_title,
        product_description=product_description,
        tags=tags,
    )
