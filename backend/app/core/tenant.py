"""请求和后台任务共用的租户上下文。"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass

from app.config import settings


@dataclass(frozen=True, slots=True)
class TenantContext:
    tenant_id: str
    user_id: str | None = None
    source: str = "request"


tenant_context_var: ContextVar[TenantContext | None] = ContextVar(
    "tenant_context", default=None
)


def get_tenant_context() -> TenantContext:
    """返回当前上下文；兼容存量脚本时收敛到默认租户。"""
    return tenant_context_var.get() or TenantContext(
        tenant_id=settings.DEFAULT_TENANT_ID,
        source="default",
    )


def get_current_tenant_id() -> str:
    return get_tenant_context().tenant_id


def set_tenant_context(
    tenant_id: str,
    *,
    user_id: str | None = None,
    source: str = "request",
) -> Token[TenantContext | None]:
    if not tenant_id or len(tenant_id) > 36:
        raise ValueError("tenant_id 必须是 1～36 位非空标识")
    return tenant_context_var.set(
        TenantContext(tenant_id=tenant_id, user_id=user_id, source=source)
    )


def clear_tenant_context() -> None:
    tenant_context_var.set(None)


@contextmanager
def tenant_context(
    tenant_id: str,
    *,
    user_id: str | None = None,
    source: str = "task",
) -> Iterator[None]:
    """后台任务显式绑定租户，避免默认租户误处理跨租户任务。"""
    token = set_tenant_context(tenant_id, user_id=user_id, source=source)
    try:
        yield
    finally:
        tenant_context_var.reset(token)
