"""
自定义异常，统一错误格式。
"""

from typing import Any


class AppError(Exception):
    """业务异常基类"""
    status_code: int = 500
    detail: str = "服务器内部错误"

    def __init__(self, detail: str | None = None, **extra: Any):
        self.detail = detail or self.detail
        self.extra = extra


class NotFoundError(AppError):
    status_code = 404
    detail = "资源不存在"


class ValidationError(AppError):
    status_code = 422
    detail = "校验失败"


class ConflictError(AppError):
    status_code = 409
    detail = "资源冲突"


class UnauthorizedError(AppError):
    status_code = 401
    detail = "未认证"


class ForbiddenError(AppError):
    status_code = 403
    detail = "无权限"


class ServiceUnavailableError(AppError):
    status_code = 503
    detail = "服务暂不可用"
