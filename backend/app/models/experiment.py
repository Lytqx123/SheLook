"""A/B 实验模型"""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ExperimentStatus(StrEnum):
    """实验状态：运行中 / 已停止 / 已完成"""

    RUNNING = "running"
    STOPPED = "stopped"
    COMPLETED = "completed"


class ABExperiment(Base):
    """A/B 实验表 —— 对比两版图片的 CTR 表现，含统计显著性"""

    __tablename__ = "ab_experiments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("products.id"), nullable=False, index=True
    )
    variant_a_image_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("generated_images.id"), nullable=False
    )
    variant_b_image_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("generated_images.id"), nullable=False
    )
    traffic_ratio: Mapped[float] = mapped_column(Float, server_default="0.5", nullable=False)
    status: Mapped[ExperimentStatus] = mapped_column(
        Enum(ExperimentStatus, name="experimentstatus", values_callable=lambda x: [e.value for e in x]),
        nullable=True,
        server_default=ExperimentStatus.RUNNING.value,
    )
    start_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    end_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # 实验结果字段（stop 时回填）
    result_ctr_a: Mapped[float | None] = mapped_column(Float, nullable=True)
    result_ctr_b: Mapped[float | None] = mapped_column(Float, nullable=True)
    p_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    winner_image_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("generated_images.id"), nullable=True
    )
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now())

    def __repr__(self) -> str:
        return f"<ABExperiment #{self.id} [{self.status.value if self.status else '?'}]>"
