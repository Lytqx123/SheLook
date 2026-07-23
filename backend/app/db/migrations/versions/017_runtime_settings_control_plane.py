"""Add tenant-managed runtime setting overrides and revision history.

Revision ID: 017
Revises: 016
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "017"
down_revision: str | None = "016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_TABLES = ("runtime_settings", "runtime_setting_revisions")


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
        "runtime_settings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("setting_key", sa.String(length=128), nullable=False),
        sa.Column("value_json", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_by", sa.String(length=128), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "setting_key", name="uq_runtime_setting_tenant_key"),
    )
    op.create_index("ix_runtime_settings_tenant_id", "runtime_settings", ["tenant_id"])
    op.create_index(
        "ix_runtime_settings_tenant_updated", "runtime_settings", ["tenant_id", "updated_at"]
    )

    op.create_table(
        "runtime_setting_revisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("setting_id", sa.String(length=36), nullable=True),
        sa.Column("setting_key", sa.String(length=128), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("value_json", sa.JSON(), nullable=True),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("changed_by", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["setting_id"], ["runtime_settings.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "setting_key",
            "version",
            name="uq_runtime_setting_revision_tenant_key_version",
        ),
    )
    op.create_index(
        "ix_runtime_setting_revisions_tenant_id", "runtime_setting_revisions", ["tenant_id"]
    )
    op.create_index(
        "ix_runtime_setting_revisions_tenant_key_created",
        "runtime_setting_revisions",
        ["tenant_id", "setting_key", "created_at"],
    )

    if _is_postgresql():
        for table_name in _TENANT_TABLES:
            _enable_tenant_rls(table_name)


def downgrade() -> None:
    if _is_postgresql():
        for table_name in reversed(_TENANT_TABLES):
            _disable_tenant_rls(table_name)
    op.drop_table("runtime_setting_revisions")
    op.drop_table("runtime_settings")
