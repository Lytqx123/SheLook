"""对齐 ORM 约束并清理被唯一索引覆盖的普通索引

Revision ID: 006
Revises: 005
Create Date: 2026-07-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "006"
down_revision: str | None = "005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_unique_constraint(table_name: str, constraint_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(
        item.get("name") == constraint_name
        for item in inspector.get_unique_constraints(table_name)
    )


def _has_index(table_name: str, index_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(item.get("name") == index_name for item in inspector.get_indexes(table_name))


def upgrade() -> None:
    op.execute("UPDATE ab_experiments SET traffic_ratio = 0.5 WHERE traffic_ratio IS NULL")
    op.alter_column(
        "ab_experiments",
        "traffic_ratio",
        existing_type=sa.Float(),
        existing_server_default="0.5",
        nullable=False,
    )

    for column_name in ("impressions", "clicks"):
        op.execute(
            sa.text(
                f'UPDATE daily_metrics SET "{column_name}" = 0 '
                f'WHERE "{column_name}" IS NULL'
            )
        )
        op.alter_column(
            "daily_metrics",
            column_name,
            existing_type=sa.Integer(),
            existing_server_default="0",
            nullable=False,
        )

    if not _has_unique_constraint(
        "daily_metrics", "daily_metrics_image_id_date_key"
    ):
        op.create_unique_constraint(
            "daily_metrics_image_id_date_key",
            "daily_metrics",
            ["image_id", "date"],
        )

    op.execute(
        "UPDATE product_embeddings "
        "SET embedding_model = 'CLIP-ViT-B/32' WHERE embedding_model IS NULL"
    )
    op.alter_column(
        "product_embeddings",
        "embedding_model",
        existing_type=sa.String(64),
        existing_server_default="CLIP-ViT-B/32",
        nullable=False,
    )

    # 唯一约束/索引已经能支持同字段查询，删除重复的普通索引。
    for table_name, index_name in (
        ("products", "ix_products_sku_code"),
        ("product_embeddings", "ix_product_embeddings_product_id"),
        ("supplier_analysis_reports", "ix_supplier_analysis_reports_report_id"),
    ):
        if _has_index(table_name, index_name):
            op.drop_index(index_name, table_name=table_name)

    comments = {
        "request_id": "UUIDv4 请求唯一ID，关联一次提交请求",
        "prompt_hash": "生成 prompt 的 SHA-256 哈希（不存原始 prompt）",
        "generation_params": "生成参数（精简版，不含 prompt 原文）",
        "jurisdiction": "适用司法辖区: EU-AI-Act / CN-DS-Regulation-2026",
        "ip_address": "请求来源 IP（IPv4/IPv6）",
    }
    for column_name, comment in comments.items():
        op.alter_column("audit_logs", column_name, comment=comment)


def downgrade() -> None:
    op.create_index("ix_products_sku_code", "products", ["sku_code"])
    op.create_index(
        "ix_product_embeddings_product_id", "product_embeddings", ["product_id"]
    )
    op.create_index(
        "ix_supplier_analysis_reports_report_id",
        "supplier_analysis_reports",
        ["report_id"],
    )

    op.alter_column(
        "product_embeddings",
        "embedding_model",
        existing_type=sa.String(64),
        existing_server_default="CLIP-ViT-B/32",
        nullable=True,
    )
    op.alter_column(
        "daily_metrics",
        "clicks",
        existing_type=sa.Integer(),
        existing_server_default="0",
        nullable=True,
    )
    op.alter_column(
        "daily_metrics",
        "impressions",
        existing_type=sa.Integer(),
        existing_server_default="0",
        nullable=True,
    )
    op.alter_column(
        "ab_experiments",
        "traffic_ratio",
        existing_type=sa.Float(),
        existing_server_default="0.5",
        nullable=True,
    )
