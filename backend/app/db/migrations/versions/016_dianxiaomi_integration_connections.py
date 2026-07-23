"""Add tenant-scoped Dianxiaomi connection configuration and sync history.

Revision ID: 016
Revises: 015
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "016"
down_revision: str | None = "015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_TABLES = ("dianxiaomi_connections", "integration_sync_runs")


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
    op.create_table(
        "dianxiaomi_connections",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("merchant_reference", sa.String(length=128), nullable=True),
        sa.Column("api_base_url", sa.String(length=512), nullable=True),
        sa.Column("shop_references", sa.JSON(), nullable=True),
        sa.Column("sync_scopes", sa.JSON(), nullable=True),
        sa.Column("sync_interval_minutes", sa.Integer(), nullable=False, server_default="360"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column("credentials_encrypted", sa.Text(), nullable=True),
        sa.Column("credentials_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("config_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("last_sync_at", sa.DateTime(), nullable=True),
        sa.Column("last_sync_status", sa.String(length=32), nullable=True),
        sa.Column("last_sync_error", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=128), nullable=True),
        sa.Column("updated_by", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_dianxiaomi_connections_tenant_id", "dianxiaomi_connections", ["tenant_id"])
    op.create_index(
        "ix_dianxiaomi_connections_tenant_status",
        "dianxiaomi_connections",
        ["tenant_id", "status"],
    )
    op.create_index(
        "ix_dianxiaomi_connections_tenant_updated",
        "dianxiaomi_connections",
        ["tenant_id", "updated_at"],
    )

    op.create_table(
        "integration_sync_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("connection_id", sa.String(length=36), nullable=False),
        sa.Column("trigger", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("requested_scopes", sa.JSON(), nullable=True),
        sa.Column("config_version", sa.Integer(), nullable=False),
        sa.Column("records_received", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_applied", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["connection_id"], ["dianxiaomi_connections.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_integration_sync_runs_tenant_id", "integration_sync_runs", ["tenant_id"])
    op.create_index("ix_integration_sync_runs_connection_id", "integration_sync_runs", ["connection_id"])
    op.create_index(
        "ix_integration_sync_runs_connection_started",
        "integration_sync_runs",
        ["connection_id", "started_at"],
    )
    op.create_index(
        "ix_integration_sync_runs_tenant_status",
        "integration_sync_runs",
        ["tenant_id", "status"],
    )

    if _is_postgresql():
        for table_name in _TENANT_TABLES:
            _enable_tenant_rls(table_name)


def downgrade() -> None:
    if _is_postgresql():
        for table_name in reversed(_TENANT_TABLES):
            _disable_tenant_rls(table_name)
    op.drop_table("integration_sync_runs")
    op.drop_table("dianxiaomi_connections")
