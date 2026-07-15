"""审核 API —— 人工审核 + 问题维度标注"""

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.logging import logger
from app.db.session import get_db
from app.models.image import GeneratedImage, ReviewStatus
from app.models.review import ReviewAction, ReviewRecord
from app.schemas import ReviewRequest, ReviewResponse

router = APIRouter(prefix="/api/review", tags=["Review"])


@router.post("/auto-review/{image_id}")
async def auto_review_image(
    image_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """AI 自动审核 —— 使用 Gemini Flash 预审图片质量

    返回结构化诊断报告（分数/问题维度/改进建议）。
    不会自动修改审核状态，需要人工确认。
    """
    from app.services.auto_reviewer import auto_review_image, format_review_for_ui

    # 查询图片
    result = await db.execute(select(GeneratedImage).where(GeneratedImage.id == image_id))
    image = result.scalar_one_or_none()
    if not image:
        raise NotFoundError(detail=f"图片 #{image_id} 不存在")

    from app.services.storage_service import resolve_image_url
    image_url = await resolve_image_url(image)

    # 查询关联商品信息
    product_category = ""
    product_title = ""
    try:
        from app.models.image import ImageScheme
        from app.models.product import Product

        scheme_result = await db.execute(
            select(Product)
            .join(ImageScheme, ImageScheme.product_id == Product.id)
            .where(ImageScheme.id == image.scheme_id)
        )
        product = scheme_result.scalar_one_or_none()
        if product:
            product_category = product.category or ""
            product_title = product.title or ""
    except Exception as error:
        logger.warning("自动审核未能读取关联商品信息", image_id=image_id, error=str(error))

    review = await auto_review_image(
        image_url=image_url,
        product_category=product_category,
        product_title=product_title,
    )

    # 写入审计日志
    try:
        from app.core.audit import audit_operation
        trace_id = getattr(request.state, "audit_trace_id", None)
        await audit_operation(
            operation="auto_review",
            request_id=trace_id,
            image_id=image_id,
            model_name=review.get("model"),
            status="success" if review.get("passed") else "review",
        )
    except Exception as error:
        logger.warning("自动审核完成但审计日志写入异常", image_id=image_id, error=str(error))

    return {
        **format_review_for_ui(review),
        "image_id": image_id,
    }


@router.get("/queue", response_model=dict)
async def get_review_queue(
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = 1,
    page_size: int = 20,
    market_variant: str | None = None,
):
    """获取待审队列 —— 按生成时间倒序，支持市场筛选"""
    query = select(GeneratedImage).where(
        GeneratedImage.review_status == ReviewStatus.MANUAL_PENDING
    )
    if market_variant:
        query = query.where(GeneratedImage.market_variant == market_variant)

    count_query = select(func.count()).select_from(GeneratedImage).where(
        GeneratedImage.review_status == ReviewStatus.MANUAL_PENDING
    )
    if market_variant:
        count_query = count_query.where(GeneratedImage.market_variant == market_variant)

    total = (await db.execute(count_query)).scalar() or 0

    query = query.order_by(GeneratedImage.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query)
    images = result.scalars().all()

    items = []
    from app.services.storage_service import resolve_image_url
    for img in images:
        image_url = await resolve_image_url(img)
        items.append({
            "id": img.id,
            "image_url": image_url,
            "market_variant": img.market_variant,
            "overall_score": img.overall_score,
            "review_status": img.review_status,
            "created_at": img.created_at.isoformat() if img.created_at else None,
            "quality_scores": img.quality_scores,
            "generation_params": img.generation_params,
            "c2pa_manifest": img.c2pa_manifest,
            "reviewer_notes": img.reviewer_notes,
        })

    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("/{image_id}/decide", response_model=ReviewResponse)
async def decide_review(
    image_id: int,
    body: ReviewRequest,
    db: AsyncSession = Depends(get_db),
):
    """审核决策（通过 / 驳回）"""
    result = await db.execute(select(GeneratedImage).where(GeneratedImage.id == image_id))
    image = result.scalar_one_or_none()
    if not image:
        raise NotFoundError(detail=f"图片 #{image_id} 不存在")

    # 更新图片审核状态
    action_enum = ReviewAction(body.action)
    if action_enum == ReviewAction.APPROVED:
        image.review_status = ReviewStatus.AUTO_APPROVED
    else:
        image.review_status = ReviewStatus.REJECTED

    image.reviewer_notes = body.notes

    # 创建审核记录
    record = ReviewRecord(
        image_id=image_id,
        reviewer_id=body.reviewer_id or "admin",
        action=action_enum,
        reason=body.reason,
        problem_dimensions=body.problem_dimensions,
    )
    db.add(record)
    await db.flush()
    await db.refresh(record)

    logger.info(
        "审核完成",
        image_id=image_id,
        action=body.action,
        reviewer=body.reviewer_id,
    )

    # ---- 审核完成后回写供应商视觉一致性得分 ----
    # 关联链：GeneratedImage → ImageScheme → Product.supplier_id
    try:
        from app.models import ImageScheme, Product
        from app.services.brand_service import update_supplier_score

        supplier_result = await db.execute(
            select(Product.supplier_id)
            .join(ImageScheme, ImageScheme.product_id == Product.id)
            .where(ImageScheme.id == image.scheme_id)
        )
        supplier_id = supplier_result.scalar_one_or_none()

        if supplier_id:
            score_result = await update_supplier_score(db, supplier_id)
            logger.info(
                "供应商评分已回写",
                supplier_id=supplier_id,
                image_id=image_id,
                compliance_score=score_result.get("compliance_score"),
                violations=score_result.get("total_violations"),
            )
    except Exception as e:
        # 评分回写失败不阻断审核流程
        logger.warning(
            "供应商评分回写失败",
            error=str(e),
            image_id=image_id,
        )

    return ReviewResponse(
        record_id=record.id,
        image_id=image_id,
        action=body.action,
        reason=body.reason,
        problem_dimensions=body.problem_dimensions or {},
        created_at=record.created_at.isoformat() if record.created_at else None,
    )
