"""商品发布或主图更新后的异步 CLIP 向量索引。"""

import asyncio

from app.core.logging import logger
from app.tasks.celery_app import app


@app.task(
    bind=True,
    name="index_product_embedding",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 5},
)
def index_product_embedding(self, product_id: int) -> dict:
    from sqlalchemy import select

    from app.db.session import async_session_factory
    from app.models.product import Product, ProductStatus
    from app.services.embedding_service import encode_image
    from app.services.pgvector_store import PgvectorStore

    async def _run() -> dict:
        async with async_session_factory() as db:
            product = (
                await db.execute(select(Product).where(Product.id == product_id))
            ).scalar_one_or_none()
            if not product:
                return {"status": "skipped", "reason": "product_not_found", "product_id": product_id}
            store = PgvectorStore(db)
            if product.status != ProductStatus.PUBLISHED or not product.image_raw_url:
                await store.delete(product_id)
                return {"status": "removed", "product_id": product_id}
            embedding = await asyncio.to_thread(encode_image, product.image_raw_url)
            await store.insert(product_id, embedding, "CLIP-ViT-B/32")
            logger.info("商品向量索引已更新", product_id=product_id)
            return {"status": "indexed", "product_id": product_id}

    return asyncio.run(_run())
