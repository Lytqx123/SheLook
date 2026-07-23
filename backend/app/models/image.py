"""视觉方案与生成图片模型"""

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, Enum, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TenantScopedMixin

if TYPE_CHECKING:
    from app.models.product import Product
    from app.models.review import ReviewRecord


class ReviewStatus(StrEnum):
    """审核状态：自动通过 / 待人工 / 已驳回"""
    AUTO_APPROVED = "auto_approved"
    MANUAL_PENDING = "manual_pending"
    REJECTED = "rejected"


class ImageScheme(TenantScopedMixin, Base):
    """视觉方案 —— 一款商品可有多套拍摄/生成方案"""

    __tablename__ = "image_schemes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("products.id"), nullable=False, index=True
    )
    scheme_name: Mapped[str] = mapped_column(String(128), nullable=False)
    style_tags: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    reference_images: Mapped[list | None] = mapped_column(JSON, nullable=True)
    recommendation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommendation_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now())

    product: Mapped["Product"] = relationship(back_populates="schemes")
    images: Mapped[list["GeneratedImage"]] = relationship(
        back_populates="scheme",
        cascade="all, delete-orphan",
        lazy="select",
    )

    def __repr__(self) -> str:
        return f"<ImageScheme #{self.id} {self.scheme_name}>"


class GeneratedImage(TenantScopedMixin, Base):
    """生成图片 —— AIGC 产出的实际图片，带质检分数和审核状态"""

    __tablename__ = "generated_images"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scheme_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("image_schemes.id"), nullable=False, index=True
    )
    image_url: Mapped[str] = mapped_column(String(512), nullable=False)
    storage_bucket: Mapped[str | None] = mapped_column(String(128), nullable=True)
    storage_object_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    is_public: Mapped[bool] = mapped_column(nullable=False, server_default="false")
    # task_id 记得改：切换文生图服务后格式可能变
    task_id: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True, index=True)
    generation_status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="pending", index=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    market_variant: Mapped[str | None] = mapped_column(String(32), nullable=True)
    generation_params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    quality_scores: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    overall_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    review_status: Mapped[ReviewStatus] = mapped_column(
        Enum(ReviewStatus, name="reviewstatus", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        server_default=ReviewStatus.MANUAL_PENDING.value,
    )
    c2pa_manifest: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewer_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    scheme: Mapped["ImageScheme"] = relationship(back_populates="images")
    review_records: Mapped[list["ReviewRecord"]] = relationship(
        back_populates="image",
        cascade="all, delete-orphan",
        lazy="select",
    )

    def __repr__(self) -> str:
        return f"<GeneratedImage #{self.id} [{self.review_status.value}] score={self.overall_score}>"
