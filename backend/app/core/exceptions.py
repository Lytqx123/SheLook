"""
自定义异常类 —— 统一错误处理
"""

from typing import Any


class AppError(Exception):
    """应用基础异常"""
    status_code: int = 500
    detail: str = "服务器内部错误"

    def __init__(self, detail: str | None = None, **extra: Any):
        self.detail = detail or self.detail
        self.extra = extra


class NotFoundError(AppError):
    """资源不存在"""
    status_code = 404
    detail = "资源不存在"


class ValidationError(AppError):
    """业务校验失败"""
    status_code = 422
    detail = "校验失败"


class ConflictError(AppError):
    """资源冲突（如重复 SKU）"""
    status_code = 409
    detail = "资源冲突"


class UnauthorizedError(AppError):
    """未认证"""
    status_code = 401
    detail = "未认证"


class ForbiddenError(AppError):
    """无权限"""
    status_code = 403
    detail = "无权限"


class ServiceUnavailableError(AppError):
    """服务暂不可用（外部依赖故障）"""
    status_code = 503
    detail = "服务暂不可用"
