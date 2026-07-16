"""补全生成任务状态闭环并修复商品向量唯一性

Revision ID: 005
Revises: 004
Create Date: 2026-07-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "005"
down_revision: str | None = "004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TIMESTAMP_COLUMNS = (
    ("products", "created_at"),
    ("products", "updated_at"),
    ("image_schemes", "created_at"),
    ("generated_images", "created_at"),
    ("review_records", "created_at"),
    ("ab_experiments", "created_at"),
    ("prediction_records", "predicted_at"),
    ("product_embeddings", "created_at"),
    ("brand_standards", "created_at"),
    ("brand_standards", "updated_at"),
    ("supplier_visual_scores", "created_at"),
    ("supplier_visual_scores", "updated_at"),
)


def upgrade() -> None:
    op.create_table(
        "supplier_analysis_reports",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("report_id", sa.String(32), nullable=False),
        sa.Column("supplier_id", sa.String(64), nullable=False),
        sa.Column("report_payload", sa.JSON(), nullable=False),
        sa.Column(
            "analyzed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("report_id"),
    )
    op.create_index(
        "ix_supplier_analysis_reports_report_id",
        "supplier_analysis_reports",
        ["report_id"],
    )
    op.create_index(
        "ix_supplier_analysis_reports_supplier_id",
        "supplier_analysis_reports",
        ["supplier_id"],
    )
    op.create_index(
        "ix_supplier_analysis_reports_analyzed_at",
        "supplier_analysis_reports",
        ["analyzed_at"],
    )

    op.add_column(
        "generated_images",
        sa.Column("task_id", sa.String(255), nullable=True),
    )
    op.add_column(
        "generated_images",
        sa.Column(
            "generation_status",
            sa.String(32),
            nullable=False,
            server_default="pending",
        ),
    )
    op.add_column(
        "daily_metrics",
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=True,
            server_default=sa.func.now(),
        ),
    )
    op.add_column(
        "generated_images",
        sa.Column("error_message", sa.Text(), nullable=True),
    )
    op.add_column(
        "generated_images",
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=True,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_generated_images_task_id",
        "generated_images",
        ["task_id"],
        unique=True,
    )
    op.create_index(
        "ix_generated_images_generation_status",
        "generated_images",
        ["generation_status"],
    )
    op.execute(
        """
        UPDATE generated_images
        SET generation_status = 'completed'
        WHERE image_url IS NOT NULL AND image_url <> ''
        """
    )

    # 旧迁移只在 ORM 设了默认值，数据库列没有 DEFAULT，补一下
    for table_name, column_name in _TIMESTAMP_COLUMNS:
        op.execute(
            sa.text(f'UPDATE "{table_name}" SET "{column_name}" = now() '
                    f'WHERE "{column_name}" IS NULL')
        )
        op.alter_column(
            table_name,
            column_name,
            existing_type=sa.DateTime(),
            existing_nullable=True,
            server_default=sa.func.now(),
        )

    # ON CONFLICT(product_id) 要求 product_id 唯一，去重保留最新
    op.execute(
        """
        DELETE FROM product_embeddings older
        USING product_embeddings newer
        WHERE older.product_id = newer.product_id
          AND older.id < newer.id
        """
    )
    op.create_index(
        "uq_product_embeddings_product_id",
        "product_embeddings",
        ["product_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_product_embeddings_product_id", table_name="product_embeddings")
    op.drop_index("ix_generated_images_generation_status", table_name="generated_images")
    op.drop_index("ix_generated_images_task_id", table_name="generated_images")
    for table_name, column_name in reversed(_TIMESTAMP_COLUMNS):
        op.alter_column(
            table_name,
            column_name,
            existing_type=sa.DateTime(),
            existing_nullable=True,
            server_default=None,
        )
    op.drop_column("generated_images", "updated_at")
    op.drop_column("daily_metrics", "updated_at")
    op.drop_column("generated_images", "error_message")
    op.drop_column("generated_images", "generation_status")
    op.drop_column("generated_images", "task_id")
    op.drop_index(
        "ix_supplier_analysis_reports_analyzed_at",
        table_name="supplier_analysis_reports",
    )
    op.drop_index(
        "ix_supplier_analysis_reports_supplier_id",
        table_name="supplier_analysis_reports",
    )
    op.drop_index(
        "ix_supplier_analysis_reports_report_id",
        table_name="supplier_analysis_reports",
    )
    op.drop_table("supplier_analysis_reports")
