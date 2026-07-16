"""商品向量嵌入模型"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ProductEmbedding(Base):
    """商品向量嵌入 —— 用于相似商品检索（pgvector HNSW 索引）"""

    __tablename__ = "product_embeddings"
    __table_args__ = (
        Index("uq_product_embeddings_product_id", "product_id", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("products.id"), nullable=False
    )
    # embedding 存Text再通过::vector(512)强转，因为SQLAlchemy vector类型不太好用
    embedding: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding_model: Mapped[str] = mapped_column(
        String(64), server_default="CLIP-ViT-B/32", nullable=False
    )
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now())

    def __repr__(self) -> str:
        return f"<ProductEmbedding product=#{self.product_id} model={self.embedding_model}>"
