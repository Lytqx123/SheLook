"""Celery 异步生图任务 —— 三级降级 + 质量评估 + C2PA + 审计"""

import asyncio
import hashlib
import os
import time

from celery import shared_task
from celery.exceptions import Retry

from app.core.logging import logger
from app.core.tenant import tenant_context
from app.tasks.async_utils import run_async_task


@shared_task(
    bind=True,
    name="generate_single_image",
    max_retries=3,
    default_retry_delay=30,
)
def generate_single_image(
    self,
    image_id: int,
    scheme_id: int,
    market_variant: str | None = None,
    generation_params: dict | None = None,
    request_id: str | None = None,
    tenant_id: str = "default",
    workflow_task_id: str | None = None,
) -> dict:
    """异步生图 + 质量评估 + C2PA manifest + 审计日志"""
    from sqlalchemy import select

    from app.core.audit import audit_operation
    from app.db.session import async_session_factory
    from app.models.image import GeneratedImage, ImageScheme, ReviewStatus
    from app.models.product import Product, ProductStatus
    from app.services.generation_service import GenerationService
    from app.services.reward_scorer import evaluate_quality

    async def _persist_failure(error: Exception) -> None:
        """最终重试耗尽后持久化失败状态。"""
        async with async_session_factory() as db:
            img_result = await db.execute(
                select(GeneratedImage).where(GeneratedImage.id == image_id)
            )
            image = img_result.scalar_one_or_none()
            if image:
                image.generation_status = "failed"
                image.error_message = str(error)[:1000]
            if workflow_task_id:
                from app.models.workflow import WorkflowTask
                from app.services.workflow_service import mark_task_failed

                workflow_task = await db.scalar(
                    select(WorkflowTask).where(WorkflowTask.id == workflow_task_id)
                )
                if workflow_task and workflow_task.status != "cancelled":
                    mark_task_failed(workflow_task, error)
                from app.models.release_control import AIUsageRecord, UsageStatus

                usage = await db.scalar(
                    select(AIUsageRecord).where(AIUsageRecord.workflow_task_id == workflow_task_id)
                )
                if usage:
                    usage.status = UsageStatus.FAILED
                    usage.actual_cost_cents = usage.reserved_cost_cents
            await db.commit()
        try:
            from app.services.pubsub import notify_generation_completed

            await notify_generation_completed(
                image_id,
                {
                    "status": "failed",
                    "image_id": image_id,
                    "scheme_id": scheme_id,
                    "error_message": str(error)[:1000],
                },
            )
        except Exception as notify_error:
            logger.warning("失败通知发送失败", image_id=image_id, error=str(notify_error))

    async def _persist_retrying(error: Exception) -> None:
        """将可恢复的失败暴露给任务中心，而不是一直显示为运行中。"""
        if not workflow_task_id:
            return
        async with async_session_factory() as db:
            from app.models.workflow import WorkflowTask
            from app.services.workflow_service import mark_task_retrying

            workflow_task = await db.scalar(
                select(WorkflowTask).where(WorkflowTask.id == workflow_task_id)
            )
            if workflow_task and workflow_task.status != "cancelled":
                mark_task_retrying(workflow_task, error)
            await db.commit()

    async def _run():
        start_time = time.time()
        gen_params = generation_params or {}
        prompt = ""
        model_name = "unknown"

        try:
            async with async_session_factory() as db:
                if workflow_task_id:
                    from app.models.workflow import WorkflowTask

                    workflow_task = await db.scalar(
                        select(WorkflowTask).where(WorkflowTask.id == workflow_task_id)
                    )
                    if workflow_task and workflow_task.status in {"cancelled", "succeeded", "running"}:
                        logger.info(
                            "终态或重复任务跳过执行",
                            image_id=image_id,
                            workflow_task_id=workflow_task_id,
                            workflow_status=workflow_task.status,
                        )
                        return {"status": str(workflow_task.status), "image_id": image_id}
                img_result = await db.execute(
                    select(GeneratedImage).where(GeneratedImage.id == image_id)
                )
                image = img_result.scalar_one_or_none()
                if not image:
                    raise RuntimeError(f"生成记录 #{image_id} 不存在")
                image.generation_status = "processing"
                image.error_message = None
                if workflow_task_id:
                    from app.models.workflow import WorkflowTask
                    from app.services.workflow_service import mark_task_running

                    workflow_task = await db.scalar(
                        select(WorkflowTask).where(WorkflowTask.id == workflow_task_id)
                    )
                    if workflow_task:
                        mark_task_running(workflow_task)
                await db.commit()

                scheme_result = await db.execute(
                    select(ImageScheme).where(ImageScheme.id == scheme_id)
                )
                scheme = scheme_result.scalar_one_or_none()
                if not scheme:
                    error = RuntimeError(f"方案 #{scheme_id} 不存在")
                    await _persist_failure(error)
                    logger.error("方案不存在", scheme_id=scheme_id)
                    return {"status": "error", "detail": "方案不存在"}

                # 构建生图提示词
                prompt = f"E-commerce lifestyle photo, {scheme.scheme_name}"
                if scheme.style_tags:
                    tags = scheme.style_tags
                    if isinstance(tags, dict):
                        prompt += ", " + ", ".join(f"{k}: {v}" for k, v in tags.items())
                    elif isinstance(tags, list):
                        prompt += ", " + ", ".join(str(t) for t in tags)

                # 按品类路由模型
                category = None
                product = None
                if scheme and scheme.product_id:
                    product_result = await db.execute(
                        select(Product).where(Product.id == scheme.product_id)
                    )
                    product = product_result.scalar_one_or_none()
                    if product:
                        category = product.category

                service = GenerationService(db=db, tenant_id=tenant_id)
                gen_result = await service.generate(
                    prompt=prompt,
                    negative_prompt="blurry, low quality, distorted, watermark",
                    width=1024,
                    height=1024,
                    category=category,
                    public=bool(product and product.status == ProductStatus.PUBLISHED),
                    product_id=scheme.product_id,
                    scheme_id=scheme_id,
                    generation_params=gen_params,
                )

                model_name = gen_result.get("model", "unknown")
                image_url = gen_result["image_url"]

                img_result = await db.execute(
                    select(GeneratedImage).where(GeneratedImage.id == image_id)
                )
                image = img_result.scalar_one_or_none()
                if not image:
                    raise RuntimeError(f"生成记录 #{image_id} 不存在")
                if image:
                    image.image_url = image_url
                    prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
                    image.storage_bucket = gen_result.get("storage_bucket")
                    image.storage_object_key = gen_result.get("storage_object_key")
                    image.is_public = bool(gen_result.get("is_public"))
                    image.c2pa_manifest = gen_result.get("c2pa_manifest")
                    if gen_result.get("c2pa_signed"):
                        logger.info("C2PA Content Credential 已签名并嵌入", image_id=image_id)

                    await db.flush()
                    await db.refresh(image)

                    # 质量评估
                    quality = None
                    try:
                        quality = await asyncio.to_thread(evaluate_quality, image_url, scheme)
                        if quality:
                            image.quality_scores = quality.get("scores")
                            image.overall_score = quality.get("overall")
                            review_status = (quality.get("scores") or {}).get("review_status")
                            if review_status:
                                image.review_status = ReviewStatus(review_status)
                            logger.info("质量评估完成", image_id=image_id,
                                       overall=image.overall_score)
                    except Exception as e:
                        logger.error("质量评估失败", error=str(e))

                    image.generation_status = "completed"
                    image.error_message = None
                    if workflow_task_id:
                        from app.models.workflow import WorkflowTask
                        from app.services.workflow_service import mark_task_succeeded

                        workflow_task = await db.scalar(
                            select(WorkflowTask).where(WorkflowTask.id == workflow_task_id)
                        )
                        if workflow_task:
                            mark_task_succeeded(
                                workflow_task,
                                {"image_id": image.id, "image_url": image_url, "model": model_name},
                            )
                        from app.models.release_control import AIUsageRecord, UsageStatus

                        usage = await db.scalar(
                            select(AIUsageRecord).where(
                                AIUsageRecord.workflow_task_id == workflow_task_id
                            )
                        )
                        if usage:
                            usage.status = UsageStatus.SUCCEEDED
                            usage.actual_cost_cents = usage.reserved_cost_cents
                    await db.commit()
                    duration_ms = int((time.time() - start_time) * 1000)

                    # --- 审计日志
                    c2pa_present = bool(image.c2pa_manifest)
                    try:
                        await audit_operation(
                            operation="generate",
                            request_id=request_id or os.environ.get("TASK_REQUEST_ID"),
                            product_id=scheme.product_id if scheme else None,
                            scheme_id=scheme_id,
                            image_id=image_id,
                            model_name=model_name,
                            prompt_hash=prompt_hash,
                            generation_params={
                                "width": 1024,
                                "height": 1024,
                                "market_variant": market_variant,
                            },
                            image_url=image_url,
                            c2pa_manifest_present=c2pa_present,
                            compliance_checks_passed=c2pa_present and (quality is not None),
                            status="success",
                            duration_ms=duration_ms,
                        )
                    except Exception as audit_error:
                        logger.warning(
                            "生成成功但审计日志写入失败",
                            image_id=image_id,
                            error=str(audit_error),
                        )

                    # --- Redis Pub/Sub 通知
                    notify_data = {
                        "status": "completed",
                        "image_id": image_id,
                        "scheme_id": scheme_id,
                        "image_url": image_url,
                        "overall_score": image.overall_score,
                        "model": model_name,
                    }
                    try:
                        from app.services.pubsub import notify_generation_completed
                        await notify_generation_completed(image_id, notify_data)
                        logger.info("Pub/Sub 通知已发送", image_id=image_id)
                    except Exception as e:
                        logger.warning("Pub/Sub 通知失败，前端可通过轮询获取",
                                      error=str(e))

                return {
                    "status": "completed",
                    "image_url": image_url,
                    "model": model_name,
                }

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)

            # 失败审计日志
            try:
                prompt_hash = (hashlib.sha256(prompt.encode()).hexdigest()
                              if prompt else None)
                await audit_operation(
                    operation="generate",
                    request_id=request_id or os.environ.get("TASK_REQUEST_ID"),
                    scheme_id=scheme_id,
                    image_id=image_id,
                    model_name=model_name,
                    prompt_hash=prompt_hash,
                    status="failed",
                    error_message=str(e)[:500],
                    duration_ms=duration_ms,
                )
            except Exception as audit_error:
                logger.warning(
                    "生成失败且审计日志写入异常",
                    image_id=image_id,
                    error=str(audit_error),
                )

            logger.error("生图任务失败", image_id=image_id, error=str(e))
            raise

    try:
        with tenant_context(tenant_id, source="celery"):
            return run_async_task(_run())
    except Retry:
        raise
    except Exception as e:
        logger.error("生图任务致命错误", image_id=image_id, error=str(e))
        if self.request.retries >= self.max_retries:
            with tenant_context(tenant_id, source="celery"):
                run_async_task(_persist_failure(e))
            raise
        with tenant_context(tenant_id, source="celery"):
            run_async_task(_persist_retrying(e))
        raise self.retry(exc=e) from e


# --- sync_daily_metrics / retrain_models 在 flywheel_task.py 里定义
