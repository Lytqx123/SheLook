"""建立企业租户、组织成员与业务数据隔离底座。

存量数据先回填到 default 租户，再把租户字段收紧为非空。RLS 策略使用
app.tenant_id 会话变量；生产环境必须用非表所有者的运行时数据库角色连接。

Revision ID: 009
Revises: 008
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "009"
down_revision: str | None = "008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULT_TENANT_ID = "default"
TENANT_TABLES = (
    "products",
    "image_schemes",
    "generated_images",
    "review_records",
    "ab_experiments",
    "prediction_records",
    "daily_metrics",
    "product_embeddings",
    "brand_standards",
    "supplier_visual_scores",
    "supplier_analysis_reports",
    "audit_logs",
    "external_listing_mappings",
)


def _add_tenant_column(table_name: str) -> None:
    op.add_column(
        table_name,
        sa.Column(
            "tenant_id",
            sa.String(length=36),
            nullable=False,
            server_default=DEFAULT_TENANT_ID,
        ),
    )
    op.create_foreign_key(
        f"fk_{table_name}_tenant_id",
        table_name,
        "tenants",
        ["tenant_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(f"ix_{table_name}_tenant_id", table_name, ["tenant_id"])
    op.alter_column(table_name, "tenant_id", server_default=None)


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
        "tenants",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.execute(
        "INSERT INTO tenants (id, slug, name, status) "
        "VALUES ('default', 'default', '默认租户', 'active')"
    )

    op.create_table(
        "organization_units",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("parent_id", sa.String(length=36), nullable=True),
        sa.Column("unit_type", sa.String(length=24), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("external_ref", sa.String(length=128), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["parent_id"], ["organization_units.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "unit_type", "name", name="uq_org_unit_scope"),
    )
    op.create_index("ix_organization_units_tenant_id", "organization_units", ["tenant_id"])
    op.create_index("ix_organization_units_parent_id", "organization_units", ["parent_id"])
    op.create_index("ix_organization_units_unit_type", "organization_units", ["unit_type"])

    op.create_table(
        "tenant_memberships",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=True),
        sa.Column("role", sa.String(length=32), nullable=False, server_default="viewer"),
        sa.Column("permissions", sa.JSON(), nullable=True),
        sa.Column("unit_ids", sa.JSON(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_tenant_membership_user"),
    )
    op.create_index("ix_tenant_memberships_tenant_id", "tenant_memberships", ["tenant_id"])
    op.create_index("ix_tenant_memberships_user_id", "tenant_memberships", ["user_id"])

    op.create_table(
        "tenant_quotas",
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("api_requests_per_minute", sa.Integer(), nullable=False, server_default="600"),
        sa.Column("generation_concurrency", sa.Integer(), nullable=False, server_default="4"),
        sa.Column("monthly_generation_limit", sa.Integer(), nullable=True),
        sa.Column("storage_limit_bytes", sa.Integer(), nullable=True),
        sa.Column("monthly_budget_cents", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("tenant_id"),
    )
    op.execute(
        "INSERT INTO tenant_quotas (tenant_id) VALUES ('default')"
    )

    for table_name in TENANT_TABLES:
        _add_tenant_column(table_name)

    op.drop_constraint("products_sku_code_key", "products", type_="unique")
    op.create_unique_constraint("uq_products_tenant_sku", "products", ["tenant_id", "sku_code"])

    op.drop_constraint("uq_external_listing_platform_id", "external_listing_mappings", type_="unique")
    op.create_unique_constraint(
        "uq_external_listing_platform_id",
        "external_listing_mappings",
        ["tenant_id", "platform", "external_id"],
    )

    op.drop_constraint(
        "supplier_analysis_reports_report_id_key",
        "supplier_analysis_reports",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_supplier_analysis_report_tenant",
        "supplier_analysis_reports",
        ["tenant_id", "report_id"],
    )

    for table_name in TENANT_TABLES:
        _enable_rls(table_name)


def downgrade() -> None:
    for table_name in TENANT_TABLES:
        policy_name = f"{table_name}_tenant_isolation"
        op.execute(f'DROP POLICY IF EXISTS "{policy_name}" ON "{table_name}"')
        op.execute(f'ALTER TABLE "{table_name}" DISABLE ROW LEVEL SECURITY')

    op.drop_constraint("uq_products_tenant_sku", "products", type_="unique")
    op.create_unique_constraint("products_sku_code_key", "products", ["sku_code"])

    op.drop_constraint("uq_external_listing_platform_id", "external_listing_mappings", type_="unique")
    op.create_unique_constraint(
        "uq_external_listing_platform_id",
        "external_listing_mappings",
        ["platform", "external_id"],
    )

    op.drop_constraint("uq_supplier_analysis_report_tenant", "supplier_analysis_reports", type_="unique")
    op.create_unique_constraint(
        "supplier_analysis_reports_report_id_key",
        "supplier_analysis_reports",
        ["report_id"],
    )

    for table_name in reversed(TENANT_TABLES):
        op.drop_index(f"ix_{table_name}_tenant_id", table_name=table_name)
        op.drop_constraint(f"fk_{table_name}_tenant_id", table_name, type_="foreignkey")
        op.drop_column(table_name, "tenant_id")

    op.drop_table("tenant_quotas")
    op.drop_table("tenant_memberships")
    op.drop_table("organization_units")
    op.drop_table("tenants")
