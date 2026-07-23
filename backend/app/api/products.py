"""商品管理 API —— CRUD + 上传"""

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.deps import get_pagination_params
from app.core.exceptions import ConflictError, NotFoundError
from app.core.logging import logger
from app.core.middleware import request_id_var
from app.core.tenant import get_current_tenant_id
from app.db.session import get_db
from app.models.product import Product, ProductStatus
from app.schemas import (
    ProductCreate,
    ProductListOut,
    ProductOut,
    ProductUpdate,
    SchemeOut,
)
from app.services.product_catalog_cache import (
    get_product_list_cache,
    invalidate_product_list_cache,
    set_product_list_cache,
)

router = APIRouter(prefix="/api/products", tags=["Products"])


def _get_minio():
    """延迟导入 MinIO，避免模块加载时就连"""
    from minio import Minio

    from app.config import settings
    return Minio(
        settings.MINIO_ENDPOINT,
        access_key=settings.MINIO_ACCESS_KEY,
        secret_key=settings.MINIO_SECRET_KEY,
        secure=settings.MINIO_SECURE,
    )


def _batch_scheme(product: Product) -> list[SchemeOut]:
    """product.schemes → 响应模型列表"""
    return [
        SchemeOut(
            id=s.id,
            product_id=s.product_id,
            scheme_name=s.scheme_name,
            style_tags=s.style_tags,
            reference_images=s.reference_images,
            recommendation_reason=s.recommendation_reason,
            recommendation_score=s.recommendation_score,
            created_at=s.created_at.isoformat() if s.created_at else None,
        )
        for s in (product.schemes or [])
    ]


def _to_product_out(product: Product, schemes: list[SchemeOut] | None = None) -> ProductOut:
    """ORM 转响应模型，统一入口避免字段映射散得到处都是

    schemes 可以手动传（create 时 product 还没关联），不传就从 product.schemes 自动转。
    """
    return ProductOut(
        id=product.id,
        sku_code=product.sku_code,
        title=product.title,
        category=product.category,
        price_range=product.price_range,
        target_markets=product.target_markets,
        supplier_id=product.supplier_id,
        image_raw_url=product.image_raw_url,
        status=product.status,
        schemes=schemes if schemes is not None else _batch_scheme(product),
        created_at=product.created_at.isoformat() if product.created_at else None,
        updated_at=product.updated_at.isoformat() if product.updated_at else None,
    )


@router.get("", response_model=ProductListOut)
async def list_products(
    request: Request,
    db: AsyncSession = Depends(get_db),
    pagination: dict = Depends(get_pagination_params),
    category: str | None = None,
    status: str | None = None,
):
    """分页查商品，支持品类和状态筛选"""
    page = pagination["page"]
    page_size = pagination["page_size"]
    request_id = request_id_var.get()
    logger.info("查询商品列表", request_id=request_id, page=page, category=category)

    tenant_id = get_current_tenant_id()
    cached = await get_product_list_cache(
        tenant_id=tenant_id,
        page=page,
        page_size=page_size,
        category=category,
        status=status,
    )
    if cached is not None:
        return ProductListOut.model_validate(cached)

    query = select(Product).options(selectinload(Product.schemes))
    if category:
        query = query.where(Product.category == category)
    if status:
        query = query.where(Product.status == status)
    query = query.order_by(Product.updated_at.desc()).offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query)
    products = result.scalars().all()

    count_query = select(func.count(Product.id))
    if category:
        count_query = count_query.where(Product.category == category)
    if status:
        count_query = count_query.where(Product.status == status)
    total_result = await db.execute(count_query)
    total = total_result.scalar_one()

    response = ProductListOut(
        items=[_to_product_out(p) for p in products],
        total=total,
        page=page,
        page_size=page_size,
    )
    await set_product_list_cache(
        tenant_id=tenant_id,
        page=page,
        page_size=page_size,
        category=category,
        status=status,
        payload=response.model_dump(mode="json"),
    )
    return response


@router.get("/{product_id}", response_model=ProductOut)
async def get_product(
    product_id: int,
    db: AsyncSession = Depends(get_db),
):
    """查单个商品详情（含关联方案）"""
    result = await db.execute(select(Product).options(selectinload(Product.schemes)).where(Product.id == product_id))
    product = result.scalar_one_or_none()
    if not product:
        raise NotFoundError(detail=f"商品 #{product_id} 不存在")

    return _to_product_out(product)


@router.post("", response_model=ProductOut, status_code=201)
async def create_product(
    request: Request,
    body: ProductCreate,
    db: AsyncSession = Depends(get_db),
):
    """创建商品，会做 SKU 去重"""
    # SKU 唯一性校验
    existing = await db.execute(select(Product).where(Product.sku_code == body.sku_code))
    if existing.scalar_one_or_none():
        raise ConflictError(detail=f"SKU '{body.sku_code}' 已存在")

    product = Product(
        sku_code=body.sku_code,
        title=body.title,
        category=body.category,
        price_range=body.price_range,
        target_markets=body.target_markets or [],
        supplier_id=body.supplier_id,
        image_raw_url=body.image_raw_url,
        status=ProductStatus.DRAFT,
    )
    db.add(product)
    await db.flush()
    await db.commit()
    await db.refresh(product)
    await invalidate_product_list_cache(product.tenant_id)

    logger.info("商品创建成功", sku_code=body.sku_code, product_id=product.id)

    return _to_product_out(product, schemes=[])


@router.put("/{product_id}", response_model=ProductOut)
async def update_product(
    product_id: int,
    body: ProductUpdate,
    db: AsyncSession = Depends(get_db),
):
    """更新商品信息"""
    result = await db.execute(
        select(Product).options(selectinload(Product.schemes)).where(Product.id == product_id)
    )
    product = result.scalar_one_or_none()
    if not product:
        raise NotFoundError(detail=f"商品 #{product_id} 不存在")

    changed_fields = body.model_dump(exclude_unset=True)
    image_changed = "image_raw_url" in changed_fields and changed_fields["image_raw_url"] != product.image_raw_url
    for key, value in changed_fields.items():
        setattr(product, key, value)

    await db.commit()
    await db.refresh(product)
    await invalidate_product_list_cache(product.tenant_id)

    # 如果图片变了且已发布，重新触发向量索引
    if image_changed and product.status == ProductStatus.PUBLISHED:
        try:
            from app.tasks.vector_task import index_product_embedding

            index_product_embedding.delay(product.id, product.tenant_id)
        except Exception as exc:
            logger.error("商品已更新但向量索引任务入队失败", product_id=product.id, error=str(exc))

    logger.info("商品更新成功", product_id=product_id)

    return _to_product_out(product)


@router.delete("/{product_id}", status_code=204)
async def delete_product(
    product_id: int,
    db: AsyncSession = Depends(get_db),
):
    """删除商品（软删除，改归档状态）"""
    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()
    if not product:
        raise NotFoundError(detail=f"商品 #{product_id} 不存在")

    product.status = ProductStatus.ARCHIVED
    await db.commit()
    await invalidate_product_list_cache(product.tenant_id)
    try:
        from app.tasks.vector_task import index_product_embedding

        index_product_embedding.delay(product.id, product.tenant_id)
    except Exception as exc:
        logger.error("商品已归档但向量清理任务入队失败", product_id=product.id, error=str(exc))

    logger.info("商品已归档", product_id=product_id)
    return Response(status_code=204)


@router.patch("/{product_id}/publish", response_model=ProductOut)
async def publish_product(
    product_id: int,
    db: AsyncSession = Depends(get_db),
):
    """发布商品 —— 把状态改成 published，同时把关联图片从私桶挪到公桶"""
    result = await db.execute(
        select(Product).options(selectinload(Product.schemes)).where(Product.id == product_id)
    )
    product = result.scalar_one_or_none()
    if not product:
        raise NotFoundError(detail=f"商品 #{product_id} 不存在")

    from app.models.image import GeneratedImage, ImageScheme
    from app.services.storage_service import publish_object, remove_object

    images = (
        await db.execute(
            select(GeneratedImage)
            .join(ImageScheme, GeneratedImage.scheme_id == ImageScheme.id)
            .where(ImageScheme.product_id == product_id)
        )
    ).scalars().all()
    private_sources: list[tuple[str, str]] = []
    for image in images:
        if image.is_public:
            continue
        if not image.storage_bucket or not image.storage_object_key:
            if image.image_url:
                raise ConflictError(
                    detail=f"图片 #{image.id} 缺少对象存储定位信息，无法保证发布后稳定公开 URL"
                )
            continue
        source_bucket = image.storage_bucket
        published = await publish_object(source_bucket, image.storage_object_key)
        if source_bucket != published.bucket:
            private_sources.append((source_bucket, image.storage_object_key))
        image.storage_bucket = published.bucket
        image.image_url = published.url
        image.is_public = True

    product.status = ProductStatus.PUBLISHED
    await db.commit()
    await db.refresh(product)
    await invalidate_product_list_cache(product.tenant_id)

    # DB 确认公开后再清私桶副本，失败了不回滚
    for bucket, object_key in private_sources:
        try:
            await remove_object(bucket, object_key)
        except Exception as exc:
            logger.warning(
                "发布后私有对象清理失败",
                bucket=bucket,
                object_key=object_key,
                error=str(exc),
            )

    try:
        from app.tasks.vector_task import index_product_embedding

        index_product_embedding.delay(product.id, product.tenant_id)
    except Exception as exc:
        logger.error("商品已发布但向量索引任务入队失败", product_id=product.id, error=str(exc))

    logger.info("商品已发布", product_id=product_id)

    return _to_product_out(product)
