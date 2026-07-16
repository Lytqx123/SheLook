"""商品主表模型"""

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, Enum, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.image import ImageScheme


class ProductStatus(StrEnum):
    """商品状态：草稿 / 已上架 / 已归档"""
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class Product(Base):
    """商品主表 —— SheLook 一切业务的起点"""

    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sku_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # 先这样用字符串存，后面统一改 Decimal
    price_range: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_markets: Mapped[list | None] = mapped_column(JSON, nullable=True)
    supplier_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    image_raw_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[ProductStatus] = mapped_column(
        Enum(ProductStatus, name="productstatus", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        server_default=ProductStatus.DRAFT.value,
    )
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # 关联方案，按需加载，避免 N+1
    schemes: Mapped[list["ImageScheme"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
        lazy="select",
    )

    def __repr__(self) -> str:
        return f"<Product #{self.id} {self.sku_code} [{self.status.value}]>"
