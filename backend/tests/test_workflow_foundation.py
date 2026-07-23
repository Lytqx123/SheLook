"""阶段三：可靠工作流状态与权限边界回归测试。"""

import asyncio

import pytest
from fastapi import HTTPException

from app.api.workflows import require_workflow_operator
from app.core.auth import UserInfo
from app.models.workflow import WorkflowTask, WorkflowTaskStatus
from app.services.workflow_service import (
    mark_task_failed,
    mark_task_retrying,
    mark_task_running,
    mark_task_succeeded,
)


def _task() -> WorkflowTask:
    return WorkflowTask(
        id="task-1",
        tenant_id="default",
        task_type="image_generation",
        resource_type="generated_image",
        resource_id="100",
        idempotency_key="request-1",
        status=WorkflowTaskStatus.CREATED,
        attempt_count=0,
        max_attempts=3,
    )


def test_workflow_state_transitions_preserve_operation_history() -> None:
    task = _task()
    mark_task_running(task)
    assert task.status == WorkflowTaskStatus.RUNNING
    assert task.attempt_count == 1
    assert task.started_at is not None

    transient_error = RuntimeError("provider timeout")
    mark_task_retrying(task, transient_error)
    assert task.status == WorkflowTaskStatus.RETRYING
    assert task.error_code == "RuntimeError"
    assert task.completed_at is None

    mark_task_succeeded(task, {"image_id": 100})
    assert task.status == WorkflowTaskStatus.SUCCEEDED
    assert task.result == {"image_id": 100}
    assert task.completed_at is not None


def test_workflow_failure_captures_safe_error_details() -> None:
    task = _task()
    mark_task_failed(task, ValueError("invalid generation payload"))
    assert task.status == WorkflowTaskStatus.FAILED
    assert task.error_code == "ValueError"
    assert task.error_message == "invalid generation payload"
    assert task.completed_at is not None


def test_workflow_operator_permission_requires_explicit_capability() -> None:
    operator = UserInfo(user_id="operator", role="operator", tenant_id="default")
    assert asyncio.run(require_workflow_operator(operator)) == operator

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(require_workflow_operator(UserInfo(user_id="viewer", role="viewer")))
    assert exc_info.value.status_code == 403
