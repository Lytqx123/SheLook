"""
依赖注入，给路由用的 Service 工厂和通用参数。
"""

from fastapi import Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.pgvector_store import PgvectorStore
from app.services.predictor import CTRPredictor, get_runtime_predictor


def get_vector_store(db: AsyncSession = Depends(get_db)) -> PgvectorStore:
    return PgvectorStore(db)


def get_predictor() -> CTRPredictor:
    return get_runtime_predictor()


async def get_pagination_params(
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量，1-100"),
) -> dict:
    return {"page": page, "page_size": page_size}
