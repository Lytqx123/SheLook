"""初始建表 —— SheLook 全部数据表

Revision ID: 001
Revises: None
Create Date: 2026-07-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # --- 1. 商品主表
    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("sku_code", sa.String(64), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("price_range", sa.String(32), nullable=True),
        sa.Column("target_markets", sa.JSON(), nullable=True),
        sa.Column("supplier_id", sa.String(64), nullable=True),
        sa.Column("image_raw_url", sa.Text(), nullable=True),
        sa.Column("status", sa.Enum("draft", "published", "archived", name="productstatus"), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sku_code"),
    )
    op.create_index("ix_products_sku_code", "products", ["sku_code"])
    op.create_index("ix_products_category", "products", ["category"])
    op.create_index("ix_products_supplier_id", "products", ["supplier_id"])

    # --- 2. 视觉方案表
    op.create_table(
        "image_schemes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("scheme_name", sa.String(128), nullable=False),
        sa.Column("style_tags", sa.JSON(), nullable=True),
        sa.Column("reference_images", sa.JSON(), nullable=True),
        sa.Column("recommendation_reason", sa.Text(), nullable=True),
        sa.Column("recommendation_score", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_image_schemes_product_id", "image_schemes", ["product_id"])

    # --- 3. 生成图片表
    op.create_table(
        "generated_images",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("scheme_id", sa.Integer(), nullable=False),
        sa.Column("image_url", sa.String(512), nullable=False),
        sa.Column("market_variant", sa.String(32), nullable=True),
        sa.Column("generation_params", sa.JSON(), nullable=True),
        sa.Column("quality_scores", sa.JSON(), nullable=True),
        sa.Column("overall_score", sa.Float(), nullable=True),
        sa.Column(
            "review_status",
            sa.Enum("auto_approved", "manual_pending", "rejected", name="reviewstatus"),
            nullable=False,
            server_default="manual_pending",
        ),
        sa.Column("c2pa_manifest", sa.Text(), nullable=True),
        sa.Column("reviewer_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["scheme_id"], ["image_schemes.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_generated_images_scheme_id", "generated_images", ["scheme_id"])

    # --- 4. 审核记录表
    op.create_table(
        "review_records",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("image_id", sa.Integer(), nullable=False),
        sa.Column("reviewer_id", sa.String(64), nullable=True),
        sa.Column("action", sa.Enum("approved", "rejected", name="reviewaction"), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("problem_dimensions", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["image_id"], ["generated_images.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_review_records_image_id", "review_records", ["image_id"])

    # --- 5. A/B 实验表
    op.create_table(
        "ab_experiments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("variant_a_image_id", sa.Integer(), nullable=False),
        sa.Column("variant_b_image_id", sa.Integer(), nullable=False),
        sa.Column("traffic_ratio", sa.Float(), server_default="0.5"),
        sa.Column("status", sa.Enum("running", "stopped", "completed", name="experimentstatus"), nullable=True, server_default="running"),
        sa.Column("start_date", sa.DateTime(), nullable=True),
        sa.Column("end_date", sa.DateTime(), nullable=True),
        sa.Column("result_ctr_a", sa.Float(), nullable=True),
        sa.Column("result_ctr_b", sa.Float(), nullable=True),
        sa.Column("p_value", sa.Float(), nullable=True),
        sa.Column("winner_image_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.ForeignKeyConstraint(["variant_a_image_id"], ["generated_images.id"]),
        sa.ForeignKeyConstraint(["variant_b_image_id"], ["generated_images.id"]),
        sa.ForeignKeyConstraint(["winner_image_id"], ["generated_images.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ab_experiments_product_id", "ab_experiments", ["product_id"])

    # --- 6. 预测记录表
    op.create_table(
        "prediction_records",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("image_id", sa.Integer(), nullable=False),
        sa.Column("predicted_ctr", sa.Float(), nullable=True),
        sa.Column("ctr_confidence_interval", sa.JSON(), nullable=True),
        sa.Column("predicted_hit_probability", sa.Float(), nullable=True),
        sa.Column("return_risk_level", sa.Enum("low", "medium", "high", name="returnrisklevel"), nullable=True),
        sa.Column("predicted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["image_id"], ["generated_images.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_prediction_records_image_id", "prediction_records", ["image_id"])

    # --- 7. 每日指标表
    op.create_table(
        "daily_metrics",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("image_id", sa.Integer(), nullable=False),
        sa.Column("impressions", sa.Integer(), server_default="0"),
        sa.Column("clicks", sa.Integer(), server_default="0"),
        sa.Column("ctr", sa.Float(), nullable=True),
        sa.Column("cvr", sa.Float(), nullable=True),
        sa.Column("add_to_cart_rate", sa.Float(), nullable=True),
        sa.Column("return_rate", sa.Float(), nullable=True),
        sa.Column("revenue", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["image_id"], ["generated_images.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_daily_metrics_date", "daily_metrics", ["date"])
    op.create_index("ix_daily_metrics_image_id", "daily_metrics", ["image_id"])
    # 每张图每天一条，供 INSERT ... ON CONFLICT DO UPDATE
    op.create_unique_constraint(
        "daily_metrics_image_id_date_key",
        "daily_metrics",
        ["image_id", "date"],
    )

    # --- 8. 商品向量嵌入表
    op.create_table(
        "product_embeddings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("embedding", sa.Text(), nullable=True),
        sa.Column("embedding_model", sa.String(64), server_default="CLIP-ViT-B/32"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_product_embeddings_product_id", "product_embeddings", ["product_id"])
    # HNSW 向量索引（pgvector），cosine 距离
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_product_embeddings_embedding "
        "ON product_embeddings "
        "USING hnsw ((embedding::vector(512)) vector_cosine_ops)"
    )


def downgrade() -> None:
    """回滚：按外键依赖顺序删除所有表"""
    op.drop_table("product_embeddings")
    op.drop_table("daily_metrics")
    op.drop_table("prediction_records")
    op.drop_table("ab_experiments")
    op.drop_table("review_records")
    op.drop_table("generated_images")
    op.drop_table("image_schemes")
    op.drop_table("products")

    op.execute("DROP TYPE IF EXISTS productstatus")
    op.execute("DROP TYPE IF EXISTS reviewstatus")
    op.execute("DROP TYPE IF EXISTS reviewaction")
    op.execute("DROP TYPE IF EXISTS experimentstatus")
    op.execute("DROP TYPE IF EXISTS returnrisklevel")
