"""AI 视频生成 API —— Kling 主通道 + Runway 降级通道。"""

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationError
from app.core.logging import logger
from app.db.session import get_db
from app.schemas import VideoGenerateRequest

router = APIRouter(prefix="/api/video", tags=["Video"])


@router.post("/generate")
async def generate_video(
    request: Request,
    body: VideoGenerateRequest,
    db: AsyncSession = Depends(get_db),
):
    """生成商品展示短视频

    降级顺序：Kling API → Runway API；全部不可用时明确返回 unavailable。

    支持风格：
      - product_showcase: 360° 产品旋转展示
      - lifestyle: 生活场景展示
      - unboxing: 开箱演示
    """
    from app.models.image import GeneratedImage
    from app.services.video_generator import generate_product_video

    # 如果提供了 image_id 但没给 image_url，从数据库查询
    image_url = body.image_url
    if not image_url and body.image_id:
        img_result = await db.execute(select(GeneratedImage).where(GeneratedImage.id == body.image_id))
        img = img_result.scalar_one_or_none()
        if not img:
            raise NotFoundError(detail=f"图片 #{body.image_id} 不存在")
        from app.services.storage_service import resolve_image_url
        image_url = await resolve_image_url(img)
    if not image_url:
        raise ValidationError(detail="必须提供 image_url 或有效的 image_id")

    result = await generate_product_video(
        image_url=image_url,
        prompt=body.prompt,
        duration_seconds=body.duration,
        resolution=body.resolution,
        style=body.style,
    )

    # 写入审计日志
    try:
        from app.core.audit import audit_operation
        trace_id = getattr(request.state, "audit_trace_id", None)
        await audit_operation(
            operation="video_generate",
            request_id=trace_id,
            image_url=image_url,
            model_name=result.get("model"),
            status=result.get("status", "failed"),
        )
    except Exception as error:
        logger.warning("视频生成完成但审计日志写入异常", error=str(error))

    logger.info(
        "视频生成完成",
        provider=result.get("provider"),
        status=result.get("status"),
    )

    return result


@router.get("/providers")
async def list_providers(request: Request):
    """列出可用的视频生成提供商及预估成本"""
    from app.config import settings

    kling_configured = bool(
        settings.KLING_API_KEY or (settings.KLING_ACCESS_KEY and settings.KLING_SECRET_KEY)
    )
    runway_configured = bool(settings.RUNWAY_API_KEY)
    return {
        "providers": [
            {
                "name": "Kling AI 3.0",
                "type": "primary",
                "cost_per_second": "$0.08-$0.15",
                "max_duration": "120s",
                "max_resolution": "4K",
                "strengths": ["中文文字渲染", "4K原生", "性价比最高"],
                "status": "configured" if kling_configured else "unconfigured",
            },
            {
                "name": "Runway Gen-4.5",
                "type": "fallback",
                "cost_per_second": "$0.06-$0.08",
                "max_duration": "18s",
                "max_resolution": "1080p",
                "strengths": ["相机运动控制", "电影级画质"],
                "status": "configured" if runway_configured else "unconfigured",
            },
            {
                "name": "Sora 2",
                "type": "discontinued",
                "cost_per_second": "—",
                "max_duration": "—",
                "max_resolution": "—",
                "strengths": [],
                "status": "已关闭 (2026-03-24)",
                "note": "OpenAI 已终止 Sora 服务",
            },
        ]
    }
