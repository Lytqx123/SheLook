"""预测记录与每日指标模型"""

from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ReturnRiskLevel(StrEnum):
    """退货风险等级"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class PredictionRecord(Base):
    """预测记录 —— CTR/爆款/退货风险预估值"""

    __tablename__ = "prediction_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    image_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("generated_images.id"), nullable=False, index=True
    )
    predicted_ctr: Mapped[float | None] = mapped_column(Float, nullable=True)
    ctr_confidence_interval: Mapped[dict | None] = mapped_column(
        # JSON 存置信区间 {"lower": 0.012, "upper": 0.028}
        JSON, nullable=True,
    )
    predicted_hit_probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    return_risk_level: Mapped[ReturnRiskLevel | None] = mapped_column(
        Enum(ReturnRiskLevel, name="returnrisklevel", values_callable=lambda x: [e.value for e in x]),
        nullable=True,
    )
    predicted_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now())

    def __repr__(self) -> str:
        return f"<PredictionRecord #{self.id} ctr={self.predicted_ctr}>"


class DailyMetric(Base):
    """每日指标 —— 每张图每天的曝光/点击/转化数据"""

    __tablename__ = "daily_metrics"
    __table_args__ = (
        UniqueConstraint(
            "image_id",
            "date",
            "source_platform",
            name="daily_metrics_image_date_platform_key",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    image_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("generated_images.id"), nullable=False, index=True
    )
    source_platform: Mapped[str] = mapped_column(
        String(32), server_default="manual", nullable=False
    )
    impressions: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    clicks: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    ctr: Mapped[float | None] = mapped_column(Float, nullable=True)
    cvr: Mapped[float | None] = mapped_column(Float, nullable=True)
    add_to_cart_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    return_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    revenue: Mapped[float | None] = mapped_column(Float, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<DailyMetric {self.date} img=#{self.image_id} ctr={self.ctr}>"
