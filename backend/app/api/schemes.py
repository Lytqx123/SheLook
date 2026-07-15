"""视觉方案 API —— 推荐 + 相似检索"""

import asyncio
import io
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, File, Query, Request
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_vector_store
from app.core.logging import logger
from app.db.session import get_db
from app.models.image import ImageScheme
from app.schemas import (
    SchemeFusionRecommendOut,
    SchemeFusionRecommendRequest,
    SchemeOut,
    SchemeRecommendOut,
    SchemeRecommendRequest,
)
from app.services.pgvector_store import PgvectorStore

router = APIRouter(prefix="/api/schemes", tags=["Schemes"])


# ---- 以图搜图 ----

@router.post("/search-by-image")
async def search_by_image(
    request: Request,
    image_url: str | None = None,
    top_k: Annotated[int, Query(ge=1, le=50)] = 10,
    category: str | None = None,
    market: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """以图搜图 —— 上传图片 URL，返回视觉相似的商品方案"""
    from app.services.image_search import search_by_image_url

    if not image_url:
        return {"results": [], "message": "请提供 image_url 参数"}

    results = await search_by_image_url(
        db=db,
        image_url=image_url,
        top_k=top_k,
        category_filter=category,
        market_filter=market,
    )

    return {"results": results, "source": "clip+pgvector", "total": len(results)}


@router.post("/search-by-image/upload")
async def search_by_image_upload(
    request: Request,
    image_data: bytes = File(...),
    top_k: Annotated[int, Query(ge=1, le=50)] = 10,
    category: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """以图搜图（直接上传二进制）"""
    from app.services.image_search import search_by_image

    results = await search_by_image(
        db=db,
        image_data=image_data,
        top_k=top_k,
        category_filter=category,
    )

    return {"results": results, "source": "clip+pgvector", "total": len(results)}


@router.post("/recommend", response_model=SchemeRecommendOut)
async def recommend_scheme(
    request: Request,
    body: SchemeRecommendRequest,
    db: AsyncSession = Depends(get_db),
    vector_store: PgvectorStore = Depends(get_vector_store),
):
    """基于 CLIP 相似度推荐视觉方案

    流程：
    1. 下载上传的平铺图
    2. 用 CLIP 提取图片向量
    3. 在 pgvector 中搜索最相似的嵌入
    4. 返回对应商品的方案列表
    """
    # 1) 经统一 SSRF/大小/类型策略下载图片
    from fastapi import HTTPException

    from app.services.embedding_service import get_clip_embedding
    from app.services.image_fetcher import ImageFetchError, fetch_image
    try:
        fetched = await fetch_image(body.image_url)
    except (ImageFetchError, httpx.HTTPError) as e:
        raise HTTPException(status_code=400, detail=f"图片下载失败: {e}") from e

    try:
        image = Image.open(io.BytesIO(fetched.data))
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"无法解析图片文件: {e}") from e

    # 2) 提取 CLIP 向量（线程池执行，避免阻塞事件循环）
    embedding = await asyncio.to_thread(get_clip_embedding, image)

    # 3) pgvector 相似检索
    search_results = await vector_store.search(embedding, top_k=body.top_k or 5)

    if not search_results:
        logger.info("CLIP 检索无结果", image_url=body.image_url)
        return SchemeRecommendOut(schemes=[], source="clip")

    # 4) 查询对应的方案
    product_ids = [item["product_id"] for item in search_results]
    schemes_result = await db.execute(
        select(ImageScheme).where(ImageScheme.product_id.in_(product_ids))
    )
    all_schemes = schemes_result.scalars().all()

    # 按 product_id 分组
    schemes_by_product: dict[int, list] = {}
    for s in all_schemes:
        if s.product_id not in schemes_by_product:
            schemes_by_product[s.product_id] = []
        schemes_by_product[s.product_id].append(SchemeOut(
            id=s.id,
            product_id=s.product_id,
            scheme_name=s.scheme_name,
            style_tags=s.style_tags or {},
            reference_images=s.reference_images or [],
            recommendation_reason=s.recommendation_reason,
            recommendation_score=s.recommendation_score,
            created_at=s.created_at.isoformat() if s.created_at else None,
        ))

    # 组装返回结果（similarity = 1 - distance）
    schemes = []
    for item in search_results:
        similarity = round(1.0 - item["distance"], 4)
        schemes.append({
            "product_id": item["product_id"],
            "similarity": similarity,
            "schemes": schemes_by_product.get(item["product_id"], []),
        })

    logger.info("CLIP 推荐完成", count=len(schemes))
    return SchemeRecommendOut(
        schemes=schemes,
        source="clip",
    )


@router.post("/recommend-fusion", response_model=SchemeFusionRecommendOut)
async def recommend_fusion(
    request: Request,
    body: SchemeFusionRecommendRequest,
    db: AsyncSession = Depends(get_db),
):
    """三维度融合方案推荐

    融合三个维度：
    1. 同品类历史最优（权重 45%）—— 同品类中 CTR 最高的方案风格
    2. 跨品类风格迁移趋势（权重 25%）—— 其他品类中表现优异、具迁移潜力的风格
    3. 市场本地化偏好（权重 30%）—— 目标市场中表现最好的风格

    每个推荐结果附带可解释的量化理由。
    """
    from app.services.scheme_recommender import recommend_schemes

    result = await recommend_schemes(
        db=db,
        category=body.category,
        market=body.market,
        top_k=body.top_k,
    )

    logger.info(
        "三维度融合推荐完成",
        category=body.category,
        market=body.market,
        count=len(result["recommendations"]),
    )

    return SchemeFusionRecommendOut(
        recommendations=result["recommendations"],
        weights=result["weights"],
        source=result["source"],
    )
