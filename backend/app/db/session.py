"""
数据库会话 —— 异步引擎 + 连接池 + FastAPI 依赖注入
"""

from collections.abc import AsyncGenerator

from sqlalchemy import event, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, with_loader_criteria

from app.config import settings
from app.core.tenant import get_current_tenant_id
from app.db.base import TenantScopedMixin

# 根据数据库类型选连接池参数，SQLite 和 PG 不一样
_database_backend = make_url(settings.DATABASE_URL).get_backend_name()
# SQL logging is independently opt-in: application DEBUG must not add
# synchronous per-query output to a high-concurrency request path.
_engine_options: dict = {"echo": settings.DATABASE_ECHO}
if _database_backend == "postgresql":
    _engine_options.update(
        pool_size=settings.DATABASE_POOL_SIZE,
        max_overflow=settings.DATABASE_MAX_OVERFLOW,
        pool_recycle=settings.DATABASE_POOL_RECYCLE_SECONDS,
        pool_pre_ping=True,
        pool_timeout=settings.DATABASE_POOL_TIMEOUT_SECONDS,
        connect_args={
            "server_settings": {
                "application_name": settings.DATABASE_APPLICATION_NAME,
                "statement_timeout": str(settings.DATABASE_STATEMENT_TIMEOUT_MS),
                "lock_timeout": str(settings.DATABASE_LOCK_TIMEOUT_MS),
            },
            "statement_cache_size": 0,
        },
    )

engine = create_async_engine(settings.DATABASE_URL, **_engine_options)

async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,            # 业务自己控制 flush
)


@event.listens_for(Session, "do_orm_execute")
def _apply_tenant_scope(execute_state) -> None:
    """为 ORM SELECT 自动补齐租户条件，阻止遗漏 where 的跨租户读取。"""
    if (
        not settings.TENANT_ENFORCEMENT_ENABLED
        or not execute_state.is_select
        or execute_state.execution_options.get("skip_tenant_scope", False)
    ):
        return

    tenant_id = get_current_tenant_id()
    execute_state.statement = execute_state.statement.options(
        with_loader_criteria(
            TenantScopedMixin,
            lambda entity: entity.tenant_id == tenant_id,
            include_aliases=True,
        )
    )


@event.listens_for(Session, "before_flush")
def _assign_and_validate_tenant(session: Session, _flush_context, _instances) -> None:
    """新记录自动继承当前租户，显式写入其他租户会被拒绝。"""
    if not settings.TENANT_ENFORCEMENT_ENABLED:
        return

    tenant_id = get_current_tenant_id()
    for instance in session.new:
        if not isinstance(instance, TenantScopedMixin):
            continue
        existing_tenant_id = getattr(instance, "tenant_id", None)
        if existing_tenant_id and existing_tenant_id != tenant_id:
            raise ValueError("禁止在当前租户上下文中创建其他租户的数据")
        instance.tenant_id = tenant_id


@event.listens_for(Session, "after_begin")
def _apply_tenant_rls_setting(session: Session, _transaction, connection) -> None:
    """为 HTTP 请求和 Celery 会话统一设置 PostgreSQL 的事务级租户变量。"""
    if not settings.TENANT_RLS_ENABLED or _database_backend != "postgresql":
        return
    connection.execute(
        text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
        {"tenant_id": get_current_tenant_id()},
    )


async def get_db() -> AsyncGenerator[AsyncSession]:
    """FastAPI 依赖注入用，自动 commit/rollback，请求结束释放连接"""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
