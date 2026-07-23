"""为多租户时间序列与审计查询补齐组合索引。

Revision ID: 011
Revises: 010
"""

from collections.abc import Sequence

from alembic import op

revision: str = "011"
down_revision: str | None = "010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


INDEXES: tuple[tuple[str, str, list[str]], ...] = (
    ("ix_audit_logs_tenant_created", "audit_logs", ["tenant_id", "created_at"]),
    (
        "ix_audit_logs_tenant_operation_created",
        "audit_logs",
        ["tenant_id", "operation", "created_at"],
    ),
    (
        "ix_prediction_records_tenant_predicted",
        "prediction_records",
        ["tenant_id", "predicted_at"],
    ),
    (
        "ix_daily_metrics_tenant_date_platform",
        "daily_metrics",
        ["tenant_id", "date", "source_platform"],
    ),
    (
        "ix_daily_metrics_tenant_image_date",
        "daily_metrics",
        ["tenant_id", "image_id", "date"],
    ),
)


def upgrade() -> None:
    for name, table, columns in INDEXES:
        op.create_index(name, table, columns)


def downgrade() -> None:
    for name, table, _columns in reversed(INDEXES):
        op.drop_index(name, table_name=table)
