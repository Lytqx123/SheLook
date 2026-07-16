"""AI 生成审计日志，符合深度合成监管要求。"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AuditLog(Base):
    """AI 生成操作审计日志，用于合规回溯。"""

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_created_operation", "created_at", "operation"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # --- 操作标识
    request_id: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True,
        comment="UUIDv4 请求唯一ID",
    )
    operation: Mapped[str] = mapped_column(
        String(32), nullable=False,
        comment="操作类型: generate / evaluate / review / export",
    )

    # --- 关联实体
    product_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, index=True,
    )
    scheme_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, index=True,
    )
    image_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, index=True,
    )

    # --- AI 生成核心信息
    model_name: Mapped[str | None] = mapped_column(
        String(128), nullable=True,
    )
    prompt_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True,
        comment="生成 prompt 的 SHA-256 哈希（不存原始 prompt）",
    )
    generation_params: Mapped[dict | None] = mapped_column(
        JSON, nullable=True,
        comment="生成参数（精简版，不含 prompt 原文）",
    )
    image_url: Mapped[str | None] = mapped_column(
        String(512), nullable=True,
    )

    # --- 合规字段
    c2pa_manifest_present: Mapped[bool | None] = mapped_column(
        nullable=True,
        comment="是否包含 C2PA manifest",
    )
    compliance_checks_passed: Mapped[bool | None] = mapped_column(
        nullable=True,
    )
    jurisdiction: Mapped[str | None] = mapped_column(
        String(128), nullable=True,
    )

    # --- 操作结果
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="pending",
        comment="pending / success / failed",
    )
    error_message: Mapped[str | None] = mapped_column(
        Text, nullable=True,
    )
    duration_ms: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
    )

    # --- 审计元数据（记得改：线上部署前切真实IP头）
    ip_address: Mapped[str | None] = mapped_column(
        String(45), nullable=True,
    )
    user_agent: Mapped[str | None] = mapped_column(
        String(512), nullable=True,
    )

    # --- 时间戳
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), index=True,
    )

    def __repr__(self) -> str:
        return (
            f"<AuditLog #{self.id} "
            f"op={self.operation} "
            f"status={self.status} "
            f"model={self.model_name}>"
        )
