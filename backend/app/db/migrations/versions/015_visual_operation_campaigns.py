"""Add tenant-scoped visual operation campaigns and learning records.

Revision ID: 015
Revises: 014

The JSON ID lists deliberately avoid PostgreSQL-specific array operators so
the schema and runtime queries work with both PostgreSQL and SQLite.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "015"
down_revision: str | None = "014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_TABLES = ("visual_operation_campaigns", "campaign_insights")


def _is_postgresql() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _enable_tenant_rls(table_name: str) -> None:
    """RLS is PostgreSQL-only; SQLite remains supported for local/test use."""
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
    op.create_table(
        "visual_operation_campaigns",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("market", sa.String(length=64), nullable=True),
        sa.Column("objective", sa.Text(), nullable=True),
        sa.Column("objective_metric", sa.String(length=64), nullable=True),
        sa.Column("target_value", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column("current_stage", sa.String(length=32), nullable=False, server_default="brief"),
        sa.Column("scheme_ids", sa.JSON(), nullable=True),
        sa.Column("image_ids", sa.JSON(), nullable=True),
        sa.Column("experiment_ids", sa.JSON(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("recommended_action", sa.JSON(), nullable=True),
        sa.Column("next_step", sa.Text(), nullable=True),
        sa.Column("owner_id", sa.String(length=128), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_visual_operation_campaigns_tenant_id",
        "visual_operation_campaigns",
        ["tenant_id"],
    )
    op.create_index(
        "ix_visual_operation_campaigns_product_id",
        "visual_operation_campaigns",
        ["product_id"],
    )
    op.create_index(
        "ix_visual_operation_campaigns_market",
        "visual_operation_campaigns",
        ["market"],
    )
    op.create_index(
        "ix_visual_operation_campaigns_status",
        "visual_operation_campaigns",
        ["status"],
    )
    op.create_index(
        "ix_visual_operation_campaigns_current_stage",
        "visual_operation_campaigns",
        ["current_stage"],
    )
    op.create_index(
        "ix_visual_operation_campaigns_owner_id",
        "visual_operation_campaigns",
        ["owner_id"],
    )
    op.create_index(
        "ix_visual_operation_campaigns_tenant_status_updated",
        "visual_operation_campaigns",
        ["tenant_id", "status", "updated_at"],
    )
    op.create_index(
        "ix_visual_operation_campaigns_tenant_product",
        "visual_operation_campaigns",
        ["tenant_id", "product_id"],
    )

    op.create_table(
        "campaign_insights",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("campaign_id", sa.String(length=36), nullable=False),
        sa.Column("insight_type", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("source_type", sa.String(length=64), nullable=True),
        sa.Column("source_id", sa.String(length=64), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("metric_snapshot", sa.JSON(), nullable=True),
        sa.Column("recommended_action", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="observed"),
        sa.Column("created_by", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["campaign_id"], ["visual_operation_campaigns.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_campaign_insights_tenant_id", "campaign_insights", ["tenant_id"])
    op.create_index("ix_campaign_insights_campaign_id", "campaign_insights", ["campaign_id"])
    op.create_index("ix_campaign_insights_insight_type", "campaign_insights", ["insight_type"])
    op.create_index(
        "ix_campaign_insights_tenant_campaign_created",
        "campaign_insights",
        ["tenant_id", "campaign_id", "created_at"],
    )

    if _is_postgresql():
        for table_name in _TENANT_TABLES:
            _enable_tenant_rls(table_name)


def downgrade() -> None:
    if _is_postgresql():
        for table_name in reversed(_TENANT_TABLES):
            _disable_tenant_rls(table_name)
    op.drop_table("campaign_insights")
    op.drop_table("visual_operation_campaigns")
