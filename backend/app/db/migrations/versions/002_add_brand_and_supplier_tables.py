"""新增品牌视觉规范库与供应商视觉评分表

Revision ID: 002
Revises: 001
Create Date: 2026-07-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "002"
down_revision: str | None = "001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---- 1. 品牌视觉规范库 ----
    op.create_table(
        "brand_standards",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("brand_id", sa.String(64), nullable=False),
        sa.Column("brand_name", sa.String(128), nullable=False),
        sa.Column("color_palette", sa.JSON(), nullable=True),
        sa.Column("lighting_preferences", sa.JSON(), nullable=True),
        sa.Column("composition_rules", sa.JSON(), nullable=True),
        sa.Column("logo_position", sa.String(32), nullable=True),
        sa.Column("watermark_rules", sa.JSON(), nullable=True),
        sa.Column("forbidden_patterns", sa.JSON(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_brand_standards_brand_id", "brand_standards", ["brand_id"])

    # ---- 2. 供应商视觉评分表 ----
    op.create_table(
        "supplier_visual_scores",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("supplier_id", sa.String(64), nullable=False),
        sa.Column("brand_id", sa.String(64), nullable=True),
        sa.Column("total_images", sa.Integer(), server_default="0", nullable=False),
        sa.Column("pass_rate", sa.Float(), nullable=True),
        sa.Column("avg_quality_score", sa.Float(), nullable=True),
        sa.Column("compliance_score", sa.Float(), nullable=True),
        sa.Column("last_evaluated_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_supplier_visual_scores_supplier_id",
        "supplier_visual_scores",
        ["supplier_id"],
    )


def downgrade() -> None:
    """回滚：删除供应商视觉评分表与品牌规范库（无新增枚举类型需清理）"""
    op.drop_table("supplier_visual_scores")
    op.drop_table("brand_standards")
