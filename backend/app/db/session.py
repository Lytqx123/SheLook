"""
数据库会话管理 —— 异步引擎 + 连接池 + 依赖注入
"""

from collections.abc import AsyncGenerator

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

# 异步引擎（全局单例）。SQLite 用 StaticPool，不接受 PostgreSQL 连接池参数。
_database_backend = make_url(settings.DATABASE_URL).get_backend_name()
_engine_options: dict = {"echo": settings.DEBUG}
if _database_backend == "postgresql":
    _engine_options.update(
        pool_size=10,
        max_overflow=10,
        pool_recycle=900,
        pool_pre_ping=True,
        pool_timeout=10,
        connect_args={
            "server_settings": {"application_name": "shelook_backend"},
            "statement_cache_size": 0,
        },
    )

engine = create_async_engine(settings.DATABASE_URL, **_engine_options)

# 会话工厂
async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,            # 由业务显式控制 flush
)


async def get_db() -> AsyncGenerator[AsyncSession]:
    """FastAPI 依赖注入：获取数据库会话。

    自动处理 commit / rollback，确保请求结束后释放连接。
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        # async with 离开时自动 close()
