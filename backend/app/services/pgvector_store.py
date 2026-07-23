"""
pgvector 向量存储实现 —— HNSW 索引 + 余弦距离检索。
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.tenant import get_current_tenant_id
from app.services.vector_store import VectorStore


class PgvectorStore(VectorStore):
    """基于 pgvector + HNSW 索引的向量存储"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def search(self, query_vector: list[float], top_k: int = 5) -> list[dict]:
        dim = settings.VECTOR_DIMENSION
        tenant_id = get_current_tenant_id()
        # 向量转字符串，所有值都经过 float() 校验，无 SQL 注入风险
        safe_vec = "[" + ",".join(repr(float(v)) for v in query_vector) + "]"

        sql = text(f"""
            SELECT pe.product_id,
                   CAST(pe.embedding AS vector({dim})) <=> CAST('{safe_vec}' AS vector({dim})) AS distance,
                   p.title, p.category, p.image_raw_url
            FROM product_embeddings pe
            JOIN products p ON p.id = pe.product_id
            WHERE p.status = 'published'
              AND pe.tenant_id = :tenant_id
              AND p.tenant_id = :tenant_id
            ORDER BY distance ASC
            LIMIT :top_k
        """)

        result = await self.session.execute(
            sql, {"top_k": top_k, "tenant_id": tenant_id}
        )
        rows = result.fetchall()

        return [
            {
                "product_id": row.product_id,
                "distance": round(float(row.distance), 4),
                "title": row.title,
                "category": row.category,
                "image_raw_url": row.image_raw_url,
            }
            for row in rows
        ]

    async def insert(self, product_id: int, embedding: list[float], model_name: str) -> bool:
        dim = settings.VECTOR_DIMENSION
        safe_vec = "[" + ",".join(repr(float(v)) for v in embedding) + "]"

        tenant_id = get_current_tenant_id()
        sql = text(f"""
            INSERT INTO product_embeddings (tenant_id, product_id, embedding, embedding_model)
            VALUES (:tenant_id, :pid, CAST('{safe_vec}' AS vector({dim})), :model)
            ON CONFLICT (product_id) DO UPDATE SET
                embedding = EXCLUDED.embedding,
                embedding_model = EXCLUDED.embedding_model,
                created_at = NOW()
            WHERE product_embeddings.tenant_id = EXCLUDED.tenant_id
        """)

        await self.session.execute(
            sql,
            {
                "tenant_id": tenant_id,
                "pid": product_id,
                "model": model_name,
            },
        )
        await self.session.commit()
        return True

    async def delete(self, product_id: int) -> bool:
        sql = text(
            "DELETE FROM product_embeddings WHERE product_id = :pid AND tenant_id = :tenant_id"
        )
        result = await self.session.execute(
            sql, {"pid": product_id, "tenant_id": get_current_tenant_id()}
        )
        await self.session.commit()
        return result.rowcount > 0

    async def batch_index(self, items: list[tuple[int, list[float], str]]) -> int:
        count = 0
        for product_id, embedding, model_name in items:
            success = await self.insert(product_id, embedding, model_name)
            if success:
                count += 1
        return count
