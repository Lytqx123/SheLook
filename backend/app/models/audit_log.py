"""AI 生成审计日志模型

符合《生成式AI服务深度合成监管细则（2026修订版）》要求：
- 全量日志留存
- 支持按 request_id / 时间范围 / 模型回溯
- 训练数据溯源
"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AuditLog(Base):
    """AI 生成操作审计日志

    每条日志记录一次 AI 生成操作的关键信息，
    用于合规回溯和监管审计。
    """

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_created_operation", "created_at", "operation"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # --- 操作标识 ---
    request_id: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True,
        comment="UUIDv4 请求唯一ID，关联一次提交请求",
    )
    operation: Mapped[str] = mapped_column(
        String(32), nullable=False,
        comment="操作类型: generate / evaluate / review / export",
    )

    # --- 关联实体 ---
    product_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, index=True,
        comment="关联商品ID",
    )
    scheme_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, index=True,
        comment="关联方案ID",
    )
    image_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, index=True,
        comment="关联生成图片ID",
    )

    # --- AI 生成核心信息 ---
    model_name: Mapped[str | None] = mapped_column(
        String(128), nullable=True,
        comment="使用的 AI 模型名称",
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
        comment="生成图片 URL",
    )

    # --- 合规字段 ---
    c2pa_manifest_present: Mapped[bool | None] = mapped_column(
        nullable=True,
        comment="是否包含 C2PA manifest",
    )
    compliance_checks_passed: Mapped[bool | None] = mapped_column(
        nullable=True,
        comment="合规校验是否通过",
    )
    jurisdiction: Mapped[str | None] = mapped_column(
        String(128), nullable=True,
        comment="适用司法辖区: EU-AI-Act / CN-DS-Regulation-2026",
    )

    # --- 操作结果 ---
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="pending",
        comment="操作状态: pending / success / failed",
    )
    error_message: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="失败时的错误信息",
    )
    duration_ms: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
        comment="操作耗时（毫秒）",
    )

    # --- 审计元数据 ---
    ip_address: Mapped[str | None] = mapped_column(
        String(45), nullable=True,
        comment="请求来源 IP（IPv4/IPv6）",
    )
    user_agent: Mapped[str | None] = mapped_column(
        String(512), nullable=True,
        comment="请求 User-Agent",
    )

    # --- 时间戳 ---
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), index=True,
        comment="日志创建时间",
    )

    def __repr__(self) -> str:
        return (
            f"<AuditLog #{self.id} "
            f"op={self.operation} "
            f"status={self.status} "
            f"model={self.model_name}>"
        )
