"""企业任务中心：查询、取消和人工重试可靠异步任务。"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserInfo, has_permission, require_auth
from app.db.session import get_db
from app.models.image import GeneratedImage
from app.models.workflow import OutboxEvent, OutboxStatus, WorkflowTask, WorkflowTaskStatus
from app.schemas.workflow import (
    WorkflowActionResponse,
    WorkflowTaskListResponse,
    WorkflowTaskResponse,
)

router = APIRouter(prefix="/api/workflows", tags=["Workflows"])


def _task_response(task: WorkflowTask) -> WorkflowTaskResponse:
    return WorkflowTaskResponse(
        id=task.id,
        task_type=task.task_type,
        resource_type=task.resource_type,
        resource_id=task.resource_id,
        request_id=task.request_id,
        status=task.status,
        priority=task.priority,
        attempt_count=task.attempt_count,
        max_attempts=task.max_attempts,
        result=task.result,
        error_code=task.error_code,
        error_message=task.error_message,
        created_at=task.created_at,
        started_at=task.started_at,
        completed_at=task.completed_at,
        updated_at=task.updated_at,
    )


async def require_workflow_operator(user: UserInfo = Depends(require_auth)) -> UserInfo:
    if not (
        user.role == "admin"
        or has_permission(user, "generation:run")
        or has_permission(user, "workflow:manage")
    ):
        raise HTTPException(status_code=403, detail="需要任务运营权限")
    return user


@router.get("", response_model=WorkflowTaskListResponse)
async def list_workflow_tasks(
    status: WorkflowTaskStatus | None = None,
    task_type: str | None = Query(default=None, max_length=64),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _user: UserInfo = Depends(require_workflow_operator),
    db: AsyncSession = Depends(get_db),
) -> WorkflowTaskListResponse:
    filters = []
    if status:
        filters.append(WorkflowTask.status == status)
    if task_type:
        filters.append(WorkflowTask.task_type == task_type)

    total = await db.scalar(select(func.count()).select_from(WorkflowTask).where(*filters))
    result = await db.execute(
        select(WorkflowTask)
        .where(*filters)
        .order_by(WorkflowTask.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return WorkflowTaskListResponse(
        items=[_task_response(task) for task in result.scalars()],
        total=total or 0,
        page=page,
        page_size=page_size,
    )


@router.get("/{task_id}", response_model=WorkflowTaskResponse)
async def get_workflow_task(
    task_id: str,
    _user: UserInfo = Depends(require_workflow_operator),
    db: AsyncSession = Depends(get_db),
) -> WorkflowTaskResponse:
    task = await db.scalar(select(WorkflowTask).where(WorkflowTask.id == task_id))
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return _task_response(task)


@router.post("/{task_id}/cancel", response_model=WorkflowActionResponse)
async def cancel_workflow_task(
    task_id: str,
    _user: UserInfo = Depends(require_workflow_operator),
    db: AsyncSession = Depends(get_db),
) -> WorkflowActionResponse:
    task = await db.scalar(
        select(WorkflowTask).where(WorkflowTask.id == task_id).with_for_update()
    )
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    cancellable = {
        WorkflowTaskStatus.CREATED,
        WorkflowTaskStatus.QUEUED,
        WorkflowTaskStatus.RETRYING,
        WorkflowTaskStatus.WAITING_EXTERNAL,
        WorkflowTaskStatus.WAITING_HUMAN,
    }
    if task.status not in cancellable:
        raise HTTPException(status_code=409, detail=f"当前状态 {task.status} 不允许取消")

    now = datetime.now(UTC).replace(tzinfo=None)
    task.status = WorkflowTaskStatus.CANCELLED
    task.completed_at = now
    task.error_code = "CancelledByUser"
    task.error_message = "任务在执行前被人工取消"

    pending_events = await db.execute(
        select(OutboxEvent)
        .where(
            OutboxEvent.aggregate_type == "workflow_task",
            OutboxEvent.aggregate_id == task.id,
            OutboxEvent.status == OutboxStatus.PENDING,
        )
        .with_for_update()
    )
    for event in pending_events.scalars():
        event.status = OutboxStatus.FAILED
        event.last_error = "Cancelled before publishing"

    if task.resource_type == "generated_image":
        image = await db.scalar(
            select(GeneratedImage).where(GeneratedImage.id == int(task.resource_id))
        )
        if image is not None:
            image.generation_status = "cancelled"
            image.error_message = "任务已取消"

    await db.commit()
    await db.refresh(task)
    return WorkflowActionResponse(task=_task_response(task), message="任务已取消")


@router.post("/{task_id}/retry", response_model=WorkflowActionResponse, status_code=202)
async def retry_workflow_task(
    task_id: str,
    _user: UserInfo = Depends(require_workflow_operator),
    db: AsyncSession = Depends(get_db),
) -> WorkflowActionResponse:
    task = await db.scalar(
        select(WorkflowTask).where(WorkflowTask.id == task_id).with_for_update()
    )
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status != WorkflowTaskStatus.FAILED:
        raise HTTPException(status_code=409, detail="仅失败任务支持人工重试")
    if task.task_type != "image_generation" or not task.payload:
        raise HTTPException(status_code=422, detail="当前任务类型尚不支持人工重试")

    task.status = WorkflowTaskStatus.RETRYING
    task.error_code = None
    task.error_message = None
    task.completed_at = None
    task.result = None
    retry_number = task.attempt_count + 1
    db.add(
        OutboxEvent(
            event_key=f"generation.requested:{task.id}:manual-retry:{retry_number}",
            event_type="generation.requested",
            aggregate_type="workflow_task",
            aggregate_id=task.id,
            payload=task.payload,
            status=OutboxStatus.PENDING,
        )
    )
    if task.resource_type == "generated_image":
        image = await db.scalar(
            select(GeneratedImage).where(GeneratedImage.id == int(task.resource_id))
        )
        if image is not None:
            image.generation_status = "pending"
            image.error_message = None

    await db.commit()
    await db.refresh(task)
    try:
        from app.tasks.outbox_task import dispatch_outbox_events

        dispatch_outbox_events.delay()
    except Exception:
        # 事件已落库，由 Beat 的周期扫描保证最终投递。
        pass
    return WorkflowActionResponse(task=_task_response(task), message="任务已进入重试队列")
