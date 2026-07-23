"""面向任务中心的工作流查询与操作模型。"""

from datetime import datetime

from pydantic import BaseModel, Field


class WorkflowTaskResponse(BaseModel):
    """可展示、可审计的异步任务状态。"""

    id: str
    task_type: str
    resource_type: str
    resource_id: str
    request_id: str | None = None
    status: str
    priority: int
    attempt_count: int
    max_attempts: int
    result: dict | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    updated_at: datetime


class WorkflowTaskListResponse(BaseModel):
    """分页任务列表。"""

    items: list[WorkflowTaskResponse]
    total: int
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)


class WorkflowActionResponse(BaseModel):
    """任务重试、取消后的最新状态。"""

    task: WorkflowTaskResponse
    message: str
