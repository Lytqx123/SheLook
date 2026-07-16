"""图片生成 API —— Replicate SD 生图 + 质量评估 + 合规 + 审计

WebSocket 通知走的 Redis Pub/Sub，方便多 worker 扩容。
"""

import asyncio
import uuid
from contextlib import suppress
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.db.session import get_db
from app.models.image import GeneratedImage, ImageScheme, ReviewStatus
from app.schemas import (
    GenerateRequest,
    GenerateResponse,
    GenerationStatusOut,
    TextMatchRequest,
    TextMatchResponse,
    VisionRewardRequest,
    VisionRewardResponse,
)

router = APIRouter(prefix="/api/generation", tags=["Generation"])


@router.post("", response_model=GenerateResponse, status_code=202)
async def generate_images(
    request: Request,
    body: GenerateRequest,
    db: AsyncSession = Depends(get_db),
):
    """提交生图任务（异步，丢 Celery 就跑），返回 task_id 给前端轮询"""
    # 验证方案存在
    scheme_result = await db.execute(
        select(ImageScheme).where(ImageScheme.id == body.scheme_id)
    )
    scheme = scheme_result.scalar_one_or_none()
    if not scheme:
        raise HTTPException(status_code=404, detail=f"方案 #{body.scheme_id} 不存在")

    # 获取审计 trace_id
    request_id = getattr(request.state, "audit_trace_id", None)
    if request_id is None:
        request_id = str(uuid.uuid4())

    task_id = str(uuid.uuid4())

    # 创建生成记录（先占位，URL 后续填充）
    image = GeneratedImage(
        scheme_id=body.scheme_id,
        image_url="",
        task_id=task_id,
        generation_status="pending",
        market_variant=body.market_variant,
        generation_params=body.params,
        quality_scores=None,
        overall_score=None,
        review_status=ReviewStatus.MANUAL_PENDING,
    )
    db.add(image)
    await db.flush()
    await db.refresh(image)

    # 必须先 commit，否则 Celery worker 读到不存在
    await db.commit()

    # 丢 Celery 任务
    try:
        from app.tasks.generation_task import generate_single_image
        generate_single_image.apply_async(
            kwargs={
                "image_id": image.id,
                "scheme_id": body.scheme_id,
                "market_variant": body.market_variant,
                "generation_params": body.params,
                "request_id": request_id,
            },
            task_id=task_id,
        )
    except Exception as e:
        image.generation_status = "failed"
        image.error_message = str(e)[:1000]
        await db.commit()
        logger.error("Celery 任务提交失败", error=str(e))
        raise HTTPException(status_code=503, detail="任务队列暂不可用") from e

    logger.info(
        "生图任务已提交",
        image_id=image.id,
        task_id=task_id,
        scheme_id=body.scheme_id,
        request_id=request_id,
    )

    return GenerateResponse(
        task_id=task_id,
        image_id=image.id,
        status="pending",
    )


@router.get("/{image_id}/status", response_model=GenerationStatusOut)
async def get_generation_status(
    image_id: int,
    db: AsyncSession = Depends(get_db),
):
    """轮询生图进度"""
    result = await db.execute(
        select(GeneratedImage).where(GeneratedImage.id == image_id)
    )
    image = result.scalar_one_or_none()
    if not image:
        raise HTTPException(status_code=404, detail=f"生成任务 #{image_id} 不存在")

    from app.services.storage_service import resolve_image_url
    image_url = await resolve_image_url(image)

    return GenerationStatusOut(
        image_id=image.id,
        task_id=image.task_id,
        status=image.generation_status,
        image_url=image_url or None,
        error_message=image.error_message,
        overall_score=image.overall_score,
        review_status=image.review_status,
        quality_scores=image.quality_scores,
        generation_params=image.generation_params,
        c2pa_manifest=image.c2pa_manifest,
    )


@router.websocket("/ws/{image_id}")
async def generation_ws(websocket: WebSocket, image_id: int):
    """WebSocket 推送生图进度（Redis Pub/Sub，挂了降级轮询）"""
    await websocket.accept()

    from app.services.pubsub import pubsub

    async def on_message(data: dict[str, Any]) -> None:
        with suppress(Exception):
            await websocket.send_json(data)

    try:
        # 优先走 Redis Pub/Sub
        if pubsub is not None:
            try:
                await pubsub.subscribe(image_id, callback=on_message, timeout=300.0)
                return
            except Exception as e:
                logger.warning(
                    "Redis Pub/Sub 不可用，降级为轮询模式",
                    image_id=image_id,
                    error=str(e),
                )

        # 降级：轮询，最多等 120 秒
        from app.db.session import async_session_factory
        for _ in range(60):
            await asyncio.sleep(2)
            async with async_session_factory() as db:
                result = await db.execute(
                    select(GeneratedImage).where(GeneratedImage.id == image_id)
                )
                image = result.scalar_one_or_none()
                if image and image.generation_status in {"completed", "failed"}:
                    from app.services.storage_service import resolve_image_url
                    image_url = await resolve_image_url(image)
                    await websocket.send_json({
                        "status": image.generation_status,
                        "image_id": image_id,
                        "image_url": image_url or None,
                        "overall_score": image.overall_score,
                        "error_message": image.error_message,
                    })
                    return
    except WebSocketDisconnect:
        logger.debug("WebSocket 客户端断开", image_id=image_id)
    except Exception as e:
        logger.error("WebSocket 异常", image_id=image_id, error=str(e))
        with suppress(Exception):
            await websocket.close()


@router.post("/check-text-match", response_model=TextMatchResponse)
async def check_image_text_match(
    body: TextMatchRequest,
):
    """图片-文本匹配校验（CLIP），看看生图跟商品描述对得上不"""
    from app.services.image_text_matcher import check_image_text_match as _check

    result = await _check(
        image_path=body.image_path,
        product_title=body.product_title,
        product_description=body.product_description,
        tags=body.tags,
    )
    return result


@router.post("/evaluate-aesthetic", response_model=VisionRewardResponse)
async def evaluate_aesthetic(
    body: VisionRewardRequest,
):
    """审美评估 —— 参考 VisionReward 维度，目前用启发式规则 + CLIP zero-shot"""
    from app.services.vision_reward import evaluate_vision_reward

    result = await evaluate_vision_reward(
        image_path=body.image_path,
        dimensions=body.dimensions,
    )
    return result


@router.get("/platforms")
async def list_export_platforms():
    """列出支持的平台导出规格"""
    from app.services.image_export_service import get_platform_summary

    return {"platforms": get_platform_summary()}


@router.post("/export")
async def export_image(
    image_id: int,
    platform: str = Query(..., description="目标平台: amazon/tmall/tiktok_shop/tiktok_square/shopify"),
    db: AsyncSession = Depends(get_db),
):
    """图片导出为各平台格式（自动裁切/补白/加AI标注）"""
    from app.services.image_export_service import export_for_platform

    # 查图片
    result = await db.execute(
        select(GeneratedImage).where(GeneratedImage.id == image_id)
    )
    image = result.scalar_one_or_none()
    if not image:
        raise HTTPException(status_code=404, detail=f"图片 #{image_id} 不存在")

    if not image.image_url:
        raise HTTPException(status_code=400, detail="图片尚未生成完成，无法导出")

    # 下载图片
    from app.services.image_fetcher import fetch_image
    from app.services.storage_service import resolve_image_url
    try:
        image_data = (await fetch_image(await resolve_image_url(image))).data
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"图片下载失败: {e}") from e

    # 平台适配
    try:
        processed = await export_for_platform(
            image_data=image_data,
            platform=platform,
            is_ai_generated=True,
            add_badge=True,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    logger.info("图片已导出", image_id=image_id, platform=platform)

    return Response(
        content=processed,
        media_type="image/jpeg",
        headers={
            "Content-Disposition": f'attachment; filename="image_{image_id}_{platform}.jpg"',
        },
    )
