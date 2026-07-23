"""补齐组织表 RLS，并增加灰度发布与 AI 预算预留。

Revision ID: 012
Revises: 011
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "012"
down_revision: str | None = "011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RLS_TABLES = (
    "organization_units",
    "tenant_memberships",
    "tenant_quotas",
    "tenant_feature_flags",
    "ai_usage_records",
)


def _enable_rls(table_name: str) -> None:
    policy_name = f"{table_name}_tenant_isolation"
    op.execute(f'ALTER TABLE "{table_name}" ENABLE ROW LEVEL SECURITY')
    op.execute(
        f'CREATE POLICY "{policy_name}" ON "{table_name}" '
        "USING (tenant_id = current_setting('app.tenant_id', true)) "
        "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
    )


def upgrade() -> None:
    op.create_table(
        "tenant_feature_flags",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("flag_key", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("rollout_note", sa.Text(), nullable=True),
        sa.Column("updated_by", sa.String(length=128), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "flag_key", name="uq_tenant_feature_flag"),
    )
    op.create_index(
        "ix_tenant_feature_flags_tenant_enabled",
        "tenant_feature_flags",
        ["tenant_id", "enabled"],
    )

    op.create_table(
        "ai_usage_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("workflow_task_id", sa.String(length=36), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("operation", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("reserved_cost_cents", sa.Integer(), nullable=False),
        sa.Column("actual_cost_cents", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="reserved"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("settled_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["workflow_task_id"], ["workflow_tasks.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_ai_usage_idempotency"),
    )
    op.create_index(
        "ix_ai_usage_tenant_created_status",
        "ai_usage_records",
        ["tenant_id", "created_at", "status"],
    )
    op.create_index("ix_ai_usage_workflow_task", "ai_usage_records", ["workflow_task_id"])

    for table_name in RLS_TABLES:
        _enable_rls(table_name)


def downgrade() -> None:
    for table_name in reversed(RLS_TABLES):
        policy_name = f"{table_name}_tenant_isolation"
        op.execute(f'DROP POLICY IF EXISTS "{policy_name}" ON "{table_name}"')
        op.execute(f'ALTER TABLE "{table_name}" DISABLE ROW LEVEL SECURITY')

    op.drop_table("ai_usage_records")
    op.drop_table("tenant_feature_flags")
