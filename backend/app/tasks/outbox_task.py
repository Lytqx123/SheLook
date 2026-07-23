"""Outbox 发布器：数据库事务提交后再把事件投递给 Celery。"""

from datetime import UTC, datetime, timedelta

from celery import shared_task
from sqlalchemy import select

from app.core.logging import logger
from app.core.tenant import tenant_context
from app.db.session import async_session_factory
from app.models.workflow import OutboxEvent, OutboxStatus, WorkflowTask, WorkflowTaskStatus
from app.tasks.async_utils import run_async_task


@shared_task(name="dispatch_outbox_events")
def dispatch_outbox_events(limit: int = 50) -> dict[str, int]:
    async def _dispatch() -> dict[str, int]:
        published = 0
        failed = 0
        async with async_session_factory() as db:
            result = await db.execute(
                select(OutboxEvent)
                .execution_options(skip_tenant_scope=True)
                .where(
                    OutboxEvent.status == OutboxStatus.PENDING,
                    OutboxEvent.available_at <= datetime.now(UTC).replace(tzinfo=None),
                )
                .order_by(OutboxEvent.created_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
            events = result.scalars().all()
            for event in events:
                event.attempt_count += 1
                try:
                    with tenant_context(event.tenant_id, source="outbox"):
                        if event.event_type != "generation.requested":
                            raise ValueError(f"不支持的 Outbox 事件类型: {event.event_type}")
                        workflow_task = await db.scalar(
                            select(WorkflowTask).where(WorkflowTask.id == event.aggregate_id)
                        )
                        if workflow_task is not None and workflow_task.status == WorkflowTaskStatus.CANCELLED:
                            event.status = OutboxStatus.FAILED
                            event.last_error = "Cancelled before publishing"
                            continue
                        from app.tasks.generation_task import generate_single_image

                        payload = event.payload
                        generate_single_image.apply_async(
                            kwargs=payload,
                            task_id=payload["workflow_task_id"],
                        )
                        if workflow_task is not None:
                            workflow_task.status = WorkflowTaskStatus.QUEUED
                        event.status = OutboxStatus.PUBLISHED
                        event.published_at = datetime.now(UTC).replace(tzinfo=None)
                        event.last_error = None
                        published += 1
                except Exception as exc:
                    event.last_error = str(exc)[:1000]
                    if event.attempt_count >= 10:
                        event.status = OutboxStatus.FAILED
                    else:
                        event.available_at = datetime.now(UTC).replace(tzinfo=None) + timedelta(
                            seconds=min(300, 2 ** event.attempt_count)
                        )
                    failed += 1
                    logger.exception("Outbox 事件发布失败", event_id=event.id, error=str(exc))
            await db.commit()
        return {"published": published, "failed": failed}

    return run_async_task(_dispatch())
