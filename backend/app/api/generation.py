"""图片生成 API —— Replicate SD 生图 + 质量评估 + 合规校验 + 审计

WebSocket 通知已升级为 Redis Pub/Sub，支持多 worker 横向扩展。
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
    """提交生图任务（异步，提交后由 Celery 处理）

    返回 task_id 用于 WebSocket 或轮询进度。
    """
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

    # 创建生成记录（初始状态）
    image = GeneratedImage(
        scheme_id=body.scheme_id,
        image_url="",  # 生成后填充
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

    # 必须先提交生成记录，Celery worker 才不会在事务提交前读取到“不存在”。
    await db.commit()

    # 提交 Celery 任务（传递 request_id 用于全链路追踪）
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
    """查询生成任务进度"""
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
    """WebSocket 推送生成进度（基于 Redis Pub/Sub）

    架构：
      - 客户端通过 WebSocket 连接此端点
      - Celery 任务完成后通过 Redis Pub/Sub 发布消息
      - 此端点订阅对应 channel，转发到客户端
      - 若 Redis 不可用，降级为轮询模式
    """
    await websocket.accept()

    from app.services.pubsub import pubsub

    async def on_message(data: dict[str, Any]) -> None:
        """收到 Redis Pub/Sub 消息，转发给客户端"""
        with suppress(Exception):
            await websocket.send_json(data)

    try:
        # 尝试 Redis Pub/Sub 订阅
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

        # 降级：轮询模式（兼容 Redis 不可用场景）
        from app.db.session import async_session_factory
        for _ in range(60):  # 最多等待 60 轮 × 2秒 = 120秒
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
    """图片-文本匹配验证

    基于 CLIP 模型计算生成图片与商品标题/描述/标签之间的相似度，
    验证图片内容是否与商品信息一致。
    """
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
    """参考 VisionReward 维度设计的审美启发式评估。

    对生成图片按 9 个美学维度进行评估，返回综合评分、
    逐维度评分和两两对比结果。当前采用启发式规则 + CLIP
    Zero-shot 组合方案（model_version: heuristic-v1）。
    """
    from app.services.vision_reward import evaluate_vision_reward

    result = await evaluate_vision_reward(
        image_path=body.image_path,
        dimensions=body.dimensions,
    )
    return result


@router.get("/platforms")
async def list_export_platforms():
    """列出所有支持的平台导出规格"""
    from app.services.image_export_service import get_platform_summary

    return {"platforms": get_platform_summary()}


@router.post("/export")
async def export_image(
    image_id: int,
    platform: str = Query(..., description="目标平台: amazon/tmall/tiktok_shop/tiktok_square/shopify"),
    db: AsyncSession = Depends(get_db),
):
    """将指定图片导出为目标平台格式（自动裁切/补白/加 AI 标注）

    支持 Amazon / 天猫 / TikTok Shop / Shopify 四大平台，
    自动适配尺寸、背景色和 AI 内容标注要求。
    """
    from app.services.image_export_service import export_for_platform

    # 1) 查询图片记录
    result = await db.execute(
        select(GeneratedImage).where(GeneratedImage.id == image_id)
    )
    image = result.scalar_one_or_none()
    if not image:
        raise HTTPException(status_code=404, detail=f"图片 #{image_id} 不存在")

    if not image.image_url:
        raise HTTPException(status_code=400, detail="图片尚未生成完成，无法导出")

    # 2) 下载图片
    from app.services.image_fetcher import fetch_image
    from app.services.storage_service import resolve_image_url
    try:
        image_data = (await fetch_image(await resolve_image_url(image))).data
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"图片下载失败: {e}") from e

    # 3) 平台适配处理
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

    # 4) 返回处理后的图片
    return Response(
        content=processed,
        media_type="image/jpeg",
        headers={
            "Content-Disposition": f'attachment; filename="image_{image_id}_{platform}.jpg"',
        },
    )
