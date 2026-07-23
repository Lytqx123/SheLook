"""增加可靠任务与 Outbox 事件表。

Revision ID: 010
Revises: 009
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "010"
down_revision: str | None = "009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workflow_tasks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("task_type", sa.String(length=64), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="created"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_workflow_task_idempotency"),
    )
    op.create_index("ix_workflow_tasks_tenant_id", "workflow_tasks", ["tenant_id"])
    op.create_index("ix_workflow_tasks_task_type", "workflow_tasks", ["task_type"])
    op.create_index("ix_workflow_tasks_request_id", "workflow_tasks", ["request_id"])
    op.create_index("ix_workflow_tasks_status", "workflow_tasks", ["status"])
    op.create_index("ix_workflow_tasks_tenant_status", "workflow_tasks", ["tenant_id", "status", "created_at"])

    op.create_table(
        "outbox_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("event_key", sa.String(length=160), nullable=False),
        sa.Column("event_type", sa.String(length=96), nullable=False),
        sa.Column("aggregate_type", sa.String(length=64), nullable=False),
        sa.Column("aggregate_id", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("available_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "event_key", name="uq_outbox_event_key"),
    )
    op.create_index("ix_outbox_events_tenant_id", "outbox_events", ["tenant_id"])
    op.create_index("ix_outbox_events_event_type", "outbox_events", ["event_type"])
    op.create_index("ix_outbox_events_status", "outbox_events", ["status"])
    op.create_index("ix_outbox_events_pending", "outbox_events", ["status", "available_at", "created_at"])

    for table_name in ("workflow_tasks", "outbox_events"):
        policy_name = f"{table_name}_tenant_isolation"
        op.execute(f'ALTER TABLE "{table_name}" ENABLE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY "{policy_name}" ON "{table_name}" '
            "USING (tenant_id = current_setting('app.tenant_id', true)) "
            "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
        )


def downgrade() -> None:
    for table_name in ("outbox_events", "workflow_tasks"):
        op.execute(f'DROP POLICY IF EXISTS "{table_name}_tenant_isolation" ON "{table_name}"')
        op.execute(f'ALTER TABLE "{table_name}" DISABLE ROW LEVEL SECURITY')
    op.drop_table("outbox_events")
    op.drop_table("workflow_tasks")
