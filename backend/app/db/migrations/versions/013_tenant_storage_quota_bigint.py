"""将租户存储配额提升为 BIGINT，支持企业级对象存储上限。

Revision ID: 013
Revises: 012
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "013"
down_revision: str | None = "012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "tenant_quotas",
        "storage_limit_bytes",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        postgresql_using="storage_limit_bytes::bigint",
    )


def downgrade() -> None:
    op.alter_column(
        "tenant_quotas",
        "storage_limit_bytes",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        postgresql_using="storage_limit_bytes::integer",
    )
