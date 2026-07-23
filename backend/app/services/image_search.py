"""
以图搜图服务 —— CLIP 向量 + pgvector HNSW 检索。

上传一张图片，返回视觉最相似的 top_k 商品方案。
"""

import asyncio
import io
import json
from typing import Any

from PIL import Image
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.logging import logger
from app.core.tenant import get_current_tenant_id


async def search_by_image(
    db: AsyncSession,
    image_data: bytes,
    top_k: int = 10,
    category_filter: str | None = None,
    market_filter: str | None = None,
) -> list[dict[str, Any]]:
    """以图搜图主入口

    流程：CLIP 编码 → pgvector HNSW 余弦检索 → JOIN 方案表 → 按相似度排序。
    """
    from app.services.embedding_service import get_clip_embedding

    # 1) CLIP 编码
    image = Image.open(io.BytesIO(image_data)).convert("RGB")
    query_embedding = await asyncio.to_thread(get_clip_embedding, image)

    # 2) pgvector HNSW 检索
    dim = settings.VECTOR_DIMENSION
    safe_vec = "[" + ",".join(repr(float(v)) for v in query_embedding) + "]"

    base_sql = f"""
        SELECT pe.product_id,
               CAST(pe.embedding AS vector({dim})) <=> CAST('{safe_vec}' AS vector({dim})) AS distance,
               p.title, p.category, p.image_raw_url
        FROM product_embeddings pe
        JOIN products p ON p.id = pe.product_id
        WHERE p.status = 'published'
          AND pe.tenant_id = :tenant_id
          AND p.tenant_id = :tenant_id
    """

    if category_filter:
        base_sql += " AND p.category = :category"
    if market_filter:
        base_sql += " AND CAST(p.target_markets AS jsonb) @> CAST(:market_json AS jsonb)"

    base_sql += """
        ORDER BY distance ASC
        LIMIT :top_k
    """

    params: dict = {"top_k": top_k, "tenant_id": get_current_tenant_id()}
    if category_filter:
        params["category"] = category_filter
    if market_filter:
        params["market_json"] = json.dumps([market_filter])

    result = await db.execute(text(base_sql), params)
    rows = result.fetchall()

    if not rows:
        logger.info("以图搜图无结果")
        return []

    # 3) 查询关联方案
    product_ids = [row.product_id for row in rows]
    from app.models.image import ImageScheme
    schemes_result = await db.execute(
        select(ImageScheme).where(ImageScheme.product_id.in_(product_ids))
    )
    all_schemes = schemes_result.scalars().all()

    schemes_by_product: dict[int, list] = {}
    for s in all_schemes:
        pid = s.product_id
        if pid not in schemes_by_product:
            schemes_by_product[pid] = []
        schemes_by_product[pid].append({
            "id": s.id,
            "scheme_name": s.scheme_name,
            "style_tags": s.style_tags,
            "reference_images": s.reference_images,
            "recommendation_reason": s.recommendation_reason,
            "recommendation_score": s.recommendation_score,
        })

    # 4) 组装结果（similarity = 1 - cosine_distance）
    results = []
    for row in rows:
        similarity = round(1.0 - row.distance, 4)
        pid = row.product_id
        results.append({
            "product_id": pid,
            "similarity": similarity,
            "title": row.title,
            "category": row.category,
            "image_url": row.image_raw_url,
            "schemes": schemes_by_product.get(pid, []),
        })

    logger.info("以图搜图完成", top_k=top_k, count=len(results))
    return results


async def search_by_image_url(
    db: AsyncSession,
    image_url: str,
    top_k: int = 10,
    category_filter: str | None = None,
    market_filter: str | None = None,
) -> list[dict[str, Any]]:
    """通过 URL 以图搜图（下载 → 编码 → 检索）"""
    from app.services.image_fetcher import fetch_image

    image_data = (await fetch_image(image_url)).data

    return await search_by_image(
        db=db,
        image_data=image_data,
        top_k=top_k,
        category_filter=category_filter,
        market_filter=market_filter,
    )
