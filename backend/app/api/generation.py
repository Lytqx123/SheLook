"""图片生成 API —— Replicate SD 生图 + 质量评估 + 合规 + 审计

WebSocket 通知走的 Redis Pub/Sub，方便多 worker 扩容。
"""

import asyncio
import uuid
from contextlib import suppress
from datetime import UTC, datetime
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

from app.config import settings
from app.core.logging import logger
from app.core.tenant import get_current_tenant_id
from app.db.session import get_db
from app.models.image import GeneratedImage, ImageScheme, ReviewStatus
from app.models.release_control import AIUsageRecord, UsageStatus
from app.models.workflow import WorkflowTask
from app.schemas import (
    GenerateRequest,
    GenerateResponse,
    GenerationStatusOut,
    TextMatchRequest,
    TextMatchResponse,
    VisionRewardRequest,
    VisionRewardResponse,
)
from app.services.workflow_service import create_task_with_outbox

router = APIRouter(prefix="/api/generation", tags=["Generation"])


def _require_remote_image_url(image_path: str) -> None:
    """Public API callers must never make the service read arbitrary local files."""
    if not image_path.startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="image_path 必须是受控的 http/https 图片 URL")


async def _enforce_generation_quota(db: AsyncSession, estimated_cost_cents: int) -> None:
    """Serialize generation admission per tenant and enforce active/monthly limits."""
    from sqlalchemy import func

    from app.models.organization import TenantQuota
    from app.models.workflow import WorkflowTaskStatus

    tenant_id = get_current_tenant_id()
    quota = await db.scalar(
        select(TenantQuota).where(TenantQuota.tenant_id == tenant_id).with_for_update()
    )
    if quota is None:
        return

    active_statuses = (
        WorkflowTaskStatus.CREATED,
        WorkflowTaskStatus.QUEUED,
        WorkflowTaskStatus.RETRYING,
        WorkflowTaskStatus.RUNNING,
        WorkflowTaskStatus.WAITING_EXTERNAL,
        WorkflowTaskStatus.WAITING_HUMAN,
    )
    active_tasks = await db.scalar(
        select(func.count())
        .select_from(WorkflowTask)
        .where(
            WorkflowTask.task_type == "image_generation",
            WorkflowTask.status.in_(active_statuses),
        )
    )
    if (active_tasks or 0) >= quota.generation_concurrency:
        raise HTTPException(status_code=429, detail="当前租户的生成并发配额已用尽，请稍后重试")

    now = datetime.now(UTC)
    month_start = datetime(now.year, now.month, 1)
    if quota.monthly_generation_limit is not None:
        monthly_images = await db.scalar(
            select(func.count())
            .select_from(GeneratedImage)
            .where(GeneratedImage.created_at >= month_start)
        )
        if (monthly_images or 0) >= quota.monthly_generation_limit:
            raise HTTPException(status_code=429, detail="当前租户本月生成额度已用尽")

    if quota.monthly_budget_cents is not None:
        reserved_cost = await db.scalar(
            select(func.coalesce(func.sum(AIUsageRecord.reserved_cost_cents), 0)).where(
                AIUsageRecord.created_at >= month_start,
                AIUsageRecord.status != UsageStatus.CANCELLED,
            )
        )
        if int(reserved_cost or 0) + estimated_cost_cents > quota.monthly_budget_cents:
            raise HTTPException(status_code=429, detail="当前租户本月 AI 预算不足")


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

    idempotency_key = request.headers.get("idempotency-key") or f"generation:{request_id}:{body.scheme_id}"
    existing_task_result = await db.execute(
        select(WorkflowTask).where(WorkflowTask.idempotency_key == idempotency_key)
    )
    existing_task = existing_task_result.scalar_one_or_none()
    if existing_task is not None:
        return GenerateResponse(
            task_id=existing_task.id,
            image_id=int(existing_task.resource_id),
            status=existing_task.status,
        )

    task_id = str(uuid.uuid4())
    from app.services.feature_flags import require_feature_enabled

    await require_feature_enabled(db, "ai_generation")
    estimated_cost_cents = settings.IMAGE_GENERATION_RESERVATION_CENTS
    await _enforce_generation_quota(db, estimated_cost_cents)

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

    event_payload = {
        "workflow_task_id": task_id,
        "tenant_id": image.tenant_id,
        "image_id": image.id,
        "scheme_id": body.scheme_id,
        "market_variant": body.market_variant,
        "generation_params": body.params,
        "request_id": request_id,
    }
    await create_task_with_outbox(
        db,
        task_id=task_id,
        task_type="image_generation",
        resource_type="generated_image",
        resource_id=str(image.id),
        idempotency_key=idempotency_key,
        request_id=request_id,
        payload=event_payload,
        event_type="generation.requested",
    )

    # create_task_with_outbox 已 flush 工作流任务；此后再写入用量记录，确保外键始终有效。
    params = body.params or {}
    db.add(
        AIUsageRecord(
            workflow_task_id=task_id,
            idempotency_key=idempotency_key,
            operation="image_generation",
            provider=str(params.get("provider") or "configured-default")[:64],
            reserved_cost_cents=estimated_cost_cents,
            status=UsageStatus.RESERVED,
        )
    )

    # 必须先 commit，否则 Celery worker 读到不存在
    await db.commit()

    # 触发 Outbox 发布器。发布失败时事件仍在数据库中，Beat 会自动重试。
    try:
        from app.tasks.outbox_task import dispatch_outbox_events

        dispatch_outbox_events.delay()
    except Exception as e:
        logger.warning("Outbox 发布器唤醒失败，等待定时重试", error=str(e), task_id=task_id)

    logger.info(
        "生图任务已可靠提交",
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

    _require_remote_image_url(body.image_path)
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

    _require_remote_image_url(body.image_path)
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
