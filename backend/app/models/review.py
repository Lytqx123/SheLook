"""审核记录模型"""

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.image import GeneratedImage


class ReviewAction(StrEnum):
    """审核动作：通过 / 驳回"""

    APPROVED = "approved"
    REJECTED = "rejected"


class ReviewRecord(Base):
    """人工审核记录 —— 留痕可追溯"""

    __tablename__ = "review_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    image_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("generated_images.id"), nullable=False, index=True
    )
    reviewer_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action: Mapped[ReviewAction] = mapped_column(
        Enum(ReviewAction, name="reviewaction", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    problem_dimensions: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now())

    image: Mapped["GeneratedImage"] = relationship(back_populates="review_records")

    def __repr__(self) -> str:
        return f"<ReviewRecord #{self.id} action={self.action.value}>"
