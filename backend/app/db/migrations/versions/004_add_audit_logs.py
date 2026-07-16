"""新增 audit_logs 表 —— C2PA 合规 + 审计日志

Revision ID: 004
Revises: 003
Create Date: 2026-07-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "004"
down_revision: str | None = "003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """创建 audit_logs 表"""
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("request_id", sa.String(64), nullable=False, index=True,
                  comment="UUIDv4 请求唯一ID"),
        sa.Column("operation", sa.String(32), nullable=False,
                  comment="操作类型: generate / evaluate / review / export"),
        sa.Column("product_id", sa.Integer(), nullable=True, index=True,
                  comment="关联商品ID"),
        sa.Column("scheme_id", sa.Integer(), nullable=True, index=True,
                  comment="关联方案ID"),
        sa.Column("image_id", sa.Integer(), nullable=True, index=True,
                  comment="关联生成图片ID"),
        sa.Column("model_name", sa.String(128), nullable=True,
                  comment="使用的 AI 模型名称"),
        sa.Column("prompt_hash", sa.String(64), nullable=True,
                  comment="生成 prompt 的 SHA-256 哈希"),
        sa.Column("generation_params", sa.JSON(), nullable=True,
                  comment="生成参数（精简版）"),
        sa.Column("image_url", sa.String(512), nullable=True,
                  comment="生成图片 URL"),
        sa.Column("c2pa_manifest_present", sa.Boolean(), nullable=True,
                  comment="是否包含 C2PA manifest"),
        sa.Column("compliance_checks_passed", sa.Boolean(), nullable=True,
                  comment="合规校验是否通过"),
        sa.Column("jurisdiction", sa.String(128), nullable=True,
                  comment="适用司法辖区"),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending",
                  comment="操作状态: pending / success / failed"),
        sa.Column("error_message", sa.Text(), nullable=True,
                  comment="失败时的错误信息"),
        sa.Column("duration_ms", sa.Integer(), nullable=True,
                  comment="操作耗时（毫秒）"),
        sa.Column("ip_address", sa.String(45), nullable=True,
                  comment="请求来源 IP"),
        sa.Column("user_agent", sa.String(512), nullable=True,
                  comment="请求 User-Agent"),
        sa.Column("created_at", sa.DateTime(), nullable=False,
                  server_default=sa.func.now(), index=True,
                  comment="日志创建时间"),
        sa.PrimaryKeyConstraint("id"),
    )

    # 复合索引：按时间 + 操作类型快速回溯
    op.create_index("ix_audit_logs_created_operation", "audit_logs",
                    ["created_at", "operation"])


def downgrade() -> None:
    op.drop_index("ix_audit_logs_created_operation", table_name="audit_logs")
    op.drop_table("audit_logs")
