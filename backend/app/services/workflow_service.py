"""任务状态和 Outbox 事件的统一写入入口。"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workflow import OutboxEvent, OutboxStatus, WorkflowTask, WorkflowTaskStatus


async def create_task_with_outbox(
    db: AsyncSession,
    *,
    task_id: str,
    task_type: str,
    resource_type: str,
    resource_id: str,
    idempotency_key: str,
    request_id: str | None,
    payload: dict,
    event_type: str,
) -> tuple[WorkflowTask, bool]:
    """创建任务和 Outbox 事件；同租户相同幂等键直接返回旧任务。"""
    existing = await db.execute(
        select(WorkflowTask).where(WorkflowTask.idempotency_key == idempotency_key)
    )
    task = existing.scalar_one_or_none()
    if task is not None:
        return task, False

    task = WorkflowTask(
        id=task_id,
        task_type=task_type,
        resource_type=resource_type,
        resource_id=resource_id,
        idempotency_key=idempotency_key,
        request_id=request_id,
        status=WorkflowTaskStatus.CREATED,
        payload=payload,
    )
    db.add(task)
    db.add(
        OutboxEvent(
            event_key=f"{event_type}:{task_id}",
            event_type=event_type,
            aggregate_type="workflow_task",
            aggregate_id=task_id,
            payload=payload,
            status=OutboxStatus.PENDING,
        )
    )
    await db.flush()
    return task, True


def mark_task_running(task: WorkflowTask) -> None:
    task.status = WorkflowTaskStatus.RUNNING
    task.attempt_count += 1
    task.started_at = datetime.now(UTC).replace(tzinfo=None)
    task.error_code = None
    task.error_message = None


def mark_task_succeeded(task: WorkflowTask, result: dict) -> None:
    task.status = WorkflowTaskStatus.SUCCEEDED
    task.result = result
    task.completed_at = datetime.now(UTC).replace(tzinfo=None)


def mark_task_failed(task: WorkflowTask, error: Exception) -> None:
    task.status = WorkflowTaskStatus.FAILED
    task.error_code = type(error).__name__[:64]
    task.error_message = str(error)[:1000]
    task.completed_at = datetime.now(UTC).replace(tzinfo=None)


def mark_task_retrying(task: WorkflowTask, error: Exception) -> None:
    """记录 Celery 的可恢复失败，等待下一次自动投递。"""
    task.status = WorkflowTaskStatus.RETRYING
    task.error_code = type(error).__name__[:64]
    task.error_message = str(error)[:1000]
