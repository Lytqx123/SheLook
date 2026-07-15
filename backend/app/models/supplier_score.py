"""供应商视觉评分模型（002 迁移新增，003 迁移扩展）"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SupplierVisualScore(Base):
    """供应商视觉评分 —— 按品牌聚合供应商的图片质量/合规通过率

    用于运营筛选优质供应商、规避高频违规供应方。
    """

    __tablename__ = "supplier_visual_scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    supplier_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    brand_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    total_images: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    pass_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    compliance_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    # 003 迁移新增：各维度违规次数统计，如 {"sharpness": 3, "lighting_uniformity": 1}
    problem_dimension_scores: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    last_evaluated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<SupplierVisualScore {self.supplier_id} pass={self.pass_rate}>"
