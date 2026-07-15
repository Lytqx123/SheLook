"""品牌视觉规范库模型（002 迁移新增）"""

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class BrandStandard(Base):
    """品牌视觉规范库 —— 约束 AIGC 生成的色彩/构图/水印等

    用于 L1 合规层 check_brand_compliance，确保生成图符合品牌调性。
    """

    __tablename__ = "brand_standards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    brand_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    brand_name: Mapped[str] = mapped_column(String(128), nullable=False)
    color_palette: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    lighting_preferences: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    composition_rules: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    logo_position: Mapped[str | None] = mapped_column(String(32), nullable=True)
    watermark_rules: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    forbidden_patterns: Mapped[list | None] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true", nullable=False)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<BrandStandard {self.brand_id} {self.brand_name}>"
