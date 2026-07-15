"""
依赖注入模块 —— 统一管理 Service 层依赖与通用参数

通过 FastAPI Depends 提供各类服务实例，
便于测试替换和生命周期管理。
"""

from fastapi import Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.pgvector_store import PgvectorStore
from app.services.predictor import CTRPredictor, get_runtime_predictor


def get_vector_store(db: AsyncSession = Depends(get_db)) -> PgvectorStore:
    """获取向量存储实例"""
    return PgvectorStore(db)


def get_predictor() -> CTRPredictor:
    """获取 CTR 预测器实例（单例）"""
    return get_runtime_predictor()


async def get_pagination_params(
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量，1-100"),
) -> dict:
    """通用分页参数校验"""
    return {"page": page, "page_size": page_size}
