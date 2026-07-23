"""Add encrypted, tenant-scoped external provider configuration.

Revision ID: 019
Revises: 018
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "019"
down_revision: str | None = "018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


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
        "provider_configs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="incomplete"),
        sa.Column("config_json", sa.JSON(), nullable=True),
        sa.Column("credentials_encrypted", sa.Text(), nullable=True),
        sa.Column("credentials_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("config_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", sa.String(length=128), nullable=True),
        sa.Column("updated_by", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "provider", name="uq_provider_config_tenant_provider"),
    )
    op.create_index("ix_provider_configs_tenant_id", "provider_configs", ["tenant_id"])
    op.create_index("ix_provider_configs_tenant_status", "provider_configs", ["tenant_id", "status"])
    op.create_index("ix_provider_configs_tenant_updated", "provider_configs", ["tenant_id", "updated_at"])
    if _is_postgresql():
        _enable_tenant_rls("provider_configs")


def downgrade() -> None:
    if _is_postgresql():
        _disable_tenant_rls("provider_configs")
    op.drop_table("provider_configs")
