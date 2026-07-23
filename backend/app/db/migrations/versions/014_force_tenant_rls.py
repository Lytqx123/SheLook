"""Force row-level security for every tenant-owned table.

Revision ID: 014
Revises: 013

`ENABLE ROW LEVEL SECURITY` does not constrain a table owner.  Production
runtime roles are intentionally not owners, but FORCE RLS makes that boundary
survive an accidental ownership grant as well.  Superusers and BYPASSRLS roles
remain privileged by PostgreSQL design and are rejected at API startup.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "014"
down_revision: str | None = "013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RLS_TABLES = (
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
    "workflow_tasks",
    "outbox_events",
    "organization_units",
    "tenant_memberships",
    "tenant_quotas",
    "tenant_feature_flags",
    "ai_usage_records",
)


def upgrade() -> None:
    for table_name in RLS_TABLES:
        op.execute(f'ALTER TABLE "{table_name}" FORCE ROW LEVEL SECURITY')


def downgrade() -> None:
    for table_name in reversed(RLS_TABLES):
        op.execute(f'ALTER TABLE "{table_name}" NO FORCE ROW LEVEL SECURITY')
