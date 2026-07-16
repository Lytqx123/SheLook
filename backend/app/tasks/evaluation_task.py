"""Celery 质检评估任务 —— L1→L2→L3 串行流水线"""

import asyncio

from celery import shared_task

from app.core.logging import logger


@shared_task(
    bind=True,
    name="evaluate_image_quality",
    max_retries=1,
    default_retry_delay=60,
)
def evaluate_image_quality(
    self,
    image_id: int,
    image_url: str,
) -> dict:
    """L1→L2→L3 三级质检流水线"""
    from sqlalchemy import select

    from app.db.session import async_session_factory
    from app.models.image import GeneratedImage
    from app.services.reward_scorer import evaluate_quality

    async def _evaluate():
        async with async_session_factory() as db:
            result = await db.execute(
                select(GeneratedImage).where(GeneratedImage.id == image_id)
            )
            image = result.scalar_one_or_none()
            if not image:
                logger.error("图片不存在，无法评估", image_id=image_id)
                return {"status": "error", "detail": "图片不存在"}

            try:
                quality = await asyncio.to_thread(evaluate_quality, image_url, image.scheme)
                if quality:
                    image.quality_scores = quality.get("scores")
                    image.overall_score = quality.get("overall")
                    await db.commit()

                    logger.info(
                        "质检评估完成",
                        image_id=image_id,
                        overall=image.overall_score,
                    )
                    # WebSocket 通知预留，生产环境通过 Redis Pub/Sub 跨进程推送
                    return {
                        "status": "completed",
                        "overall_score": image.overall_score,
                        "quality_scores": image.quality_scores,
                    }
            except Exception as e:
                logger.error("质量评估失败", image_id=image_id, error=str(e))
                raise

            return {"status": "skipped", "detail": "无质量结果"}

    return asyncio.run(_evaluate())
