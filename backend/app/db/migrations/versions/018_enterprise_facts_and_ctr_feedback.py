"""Add canonical enterprise facts, mappings and immutable CTR feedback evidence.

Revision ID: 018
Revises: 017
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "018"
down_revision: str | None = "017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_TABLES = (
    "external_entity_mappings",
    "commerce_facts",
    "performance_facts",
    "prediction_snapshots",
    "model_feedback_labels",
)


def _is_postgresql() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _enable_tenant_rls(table_name: str) -> None:
    policy_name = f"{table_name}_tenant_isolation"
    op.execute(f'ALTER TABLE "{table_name}" ENABLE ROW LEVEL SECURITY')
    op.execute(
        f'CREATE POLICY "{policy_name}" ON "{table_name}" '
        "USING (tenant_id = current_setting('app.tenant_id', true)) "
        "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
    )
    op.execute(f'ALTER TABLE "{table_name}" FORCE ROW LEVEL SECURITY')


def _disable_tenant_rls(table_name: str) -> None:
    policy_name = f"{table_name}_tenant_isolation"
    op.execute(f'DROP POLICY IF EXISTS "{policy_name}" ON "{table_name}"')
    op.execute(f'ALTER TABLE "{table_name}" NO FORCE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table_name}" DISABLE ROW LEVEL SECURITY')


def upgrade() -> None:
    op.add_column("integration_sync_runs", sa.Column("cursor_before", sa.Text(), nullable=True))
    op.add_column("integration_sync_runs", sa.Column("cursor_after", sa.Text(), nullable=True))

    op.create_table(
        "external_entity_mappings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("connection_key", sa.String(length=64), nullable=False, server_default="manual"),
        sa.Column("shop_reference", sa.String(length=128), nullable=True),
        sa.Column("marketplace", sa.String(length=64), nullable=True),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("external_sku", sa.String(length=255), nullable=True),
        sa.Column("product_id", sa.Integer(), nullable=True),
        sa.Column("image_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="mapped"),
        sa.Column("mapping_method", sa.String(length=32), nullable=False, server_default="manual"),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_by", sa.String(length=128), nullable=True),
        sa.Column("updated_by", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["image_id"], ["generated_images.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "provider", "connection_key", "entity_type", "external_id",
            name="uq_external_entity_mapping_identity",
        ),
    )
    op.create_index("ix_external_entity_mappings_tenant_id", "external_entity_mappings", ["tenant_id"])
    op.create_index("ix_external_entity_mappings_product_id", "external_entity_mappings", ["product_id"])
    op.create_index("ix_external_entity_mappings_image_id", "external_entity_mappings", ["image_id"])
    op.create_index("ix_external_entity_mappings_tenant_status", "external_entity_mappings", ["tenant_id", "status"])
    op.create_index("ix_external_entity_mappings_image", "external_entity_mappings", ["tenant_id", "image_id"])

    op.create_table(
        "commerce_facts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("connection_key", sa.String(length=64), nullable=False),
        sa.Column("sync_run_id", sa.String(length=36), nullable=True),
        sa.Column("shop_reference", sa.String(length=128), nullable=True),
        sa.Column("marketplace", sa.String(length=64), nullable=True),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("source_updated_at", sa.DateTime(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["sync_run_id"], ["integration_sync_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "provider", "connection_key", "entity_type", "external_id",
            name="uq_commerce_fact_identity",
        ),
    )
    op.create_index("ix_commerce_facts_tenant_id", "commerce_facts", ["tenant_id"])
    op.create_index("ix_commerce_facts_tenant_type_updated", "commerce_facts", ["tenant_id", "entity_type", "source_updated_at"])
    op.create_index("ix_commerce_facts_tenant_run", "commerce_facts", ["tenant_id", "sync_run_id"])

    op.create_table(
        "performance_facts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("source_name", sa.String(length=64), nullable=False),
        sa.Column("source_record_id", sa.String(length=255), nullable=False),
        sa.Column("metric_date", sa.Date(), nullable=False),
        sa.Column("shop_reference", sa.String(length=128), nullable=True),
        sa.Column("marketplace", sa.String(length=64), nullable=True),
        sa.Column("external_listing_id", sa.String(length=255), nullable=True),
        sa.Column("mapping_id", sa.String(length=36), nullable=True),
        sa.Column("image_id", sa.Integer(), nullable=True),
        sa.Column("impressions", sa.Integer(), nullable=False),
        sa.Column("clicks", sa.Integer(), nullable=False),
        sa.Column("orders", sa.Integer(), nullable=True),
        sa.Column("revenue", sa.Float(), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(), nullable=True),
        sa.Column("data_mature_at", sa.DateTime(), nullable=True),
        sa.Column("is_mature", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("quality_status", sa.String(length=32), nullable=False, server_default="pending_mapping"),
        sa.Column("metric_definition_version", sa.String(length=32), nullable=False, server_default="v1"),
        sa.Column("source_payload_hash", sa.String(length=64), nullable=False),
        sa.Column("ingested_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["mapping_id"], ["external_entity_mappings.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["image_id"], ["generated_images.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "source_name", "source_record_id", name="uq_performance_fact_source_record"),
    )
    op.create_index("ix_performance_facts_tenant_id", "performance_facts", ["tenant_id"])
    op.create_index("ix_performance_facts_image_id", "performance_facts", ["image_id"])
    op.create_index("ix_performance_facts_tenant_image_date", "performance_facts", ["tenant_id", "image_id", "metric_date"])
    op.create_index("ix_performance_facts_tenant_maturity", "performance_facts", ["tenant_id", "is_mature", "metric_date"])

    op.create_table(
        "prediction_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("prediction_record_id", sa.Integer(), nullable=False),
        sa.Column("image_id", sa.Integer(), nullable=False),
        sa.Column("predicted_ctr", sa.Float(), nullable=True),
        sa.Column("model_version", sa.String(length=128), nullable=True),
        sa.Column("feature_version", sa.String(length=64), nullable=False, server_default="v1"),
        sa.Column("entity_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("predicted_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["prediction_record_id"], ["prediction_records.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["image_id"], ["generated_images.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "prediction_record_id", name="uq_prediction_snapshot_record"),
    )
    op.create_index("ix_prediction_snapshots_tenant_id", "prediction_snapshots", ["tenant_id"])
    op.create_index("ix_prediction_snapshots_tenant_image_time", "prediction_snapshots", ["tenant_id", "image_id", "predicted_at"])

    op.create_table(
        "model_feedback_labels",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("prediction_snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("image_id", sa.Integer(), nullable=False),
        sa.Column("observation_start", sa.Date(), nullable=False),
        sa.Column("observation_end", sa.Date(), nullable=False),
        sa.Column("impressions", sa.Integer(), nullable=False),
        sa.Column("clicks", sa.Integer(), nullable=False),
        sa.Column("actual_ctr", sa.Float(), nullable=False),
        sa.Column("source_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="mature"),
        sa.Column("label_version", sa.String(length=32), nullable=False, server_default="v1"),
        sa.Column("matured_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["prediction_snapshot_id"], ["prediction_snapshots.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["image_id"], ["generated_images.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "prediction_snapshot_id", "label_version", name="uq_feedback_label_snapshot_version"),
    )
    op.create_index("ix_model_feedback_labels_tenant_id", "model_feedback_labels", ["tenant_id"])
    op.create_index("ix_model_feedback_labels_tenant_status", "model_feedback_labels", ["tenant_id", "status", "matured_at"])

    if _is_postgresql():
        for table_name in _TENANT_TABLES:
            _enable_tenant_rls(table_name)


def downgrade() -> None:
    if _is_postgresql():
        for table_name in reversed(_TENANT_TABLES):
            _disable_tenant_rls(table_name)
    op.drop_table("model_feedback_labels")
    op.drop_table("prediction_snapshots")
    op.drop_table("performance_facts")
    op.drop_table("commerce_facts")
    op.drop_table("external_entity_mappings")
    op.drop_column("integration_sync_runs", "cursor_after")
    op.drop_column("integration_sync_runs", "cursor_before")
