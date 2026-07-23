"""供应商图片分析报告持久化模型。"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin


class SupplierAnalysisReport(TenantScopedMixin, Base):
    """供应商分析报告快照，重启和多 worker 场景下可追溯。"""

    __tablename__ = "supplier_analysis_reports"

    __table_args__ = (
        UniqueConstraint("tenant_id", "report_id", name="uq_supplier_analysis_report_tenant"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_id: Mapped[str] = mapped_column(String(32), nullable=False)
    supplier_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    report_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    # AI补的，JSON字段后来觉得应该拆开存，先这样
    analyzed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
