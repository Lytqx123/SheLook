"""
向量存储抽象接口 —— 支持 pgvector（默认）和 Qdrant（可切换）。
"""

from abc import ABC, abstractmethod


class VectorStore(ABC):
    """向量存储抽象基类，定义统一接口"""

    @abstractmethod
    async def search(self, query_vector: list[float], top_k: int = 5) -> list[dict]:
        """余弦相似度检索"""
        ...

    @abstractmethod
    async def insert(self, product_id: int, embedding: list[float], model_name: str) -> bool:
        """插入向量记录"""
        ...

    @abstractmethod
    async def delete(self, product_id: int) -> bool:
        """删除指定商品的向量"""
        ...

    @abstractmethod
    async def batch_index(self, items: list[tuple[int, list[float], str]]) -> int:
        """批量插入向量，返回成功数量"""
        ...
