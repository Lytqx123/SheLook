"""supplier_visual_scores 新增 problem_dimension_scores 字段

Revision ID: 003
Revises: 002
Create Date: 2026-07-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: str | None = "002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 各维度违规次数，如 {"sharpness": 3, "lighting_uniformity": 1}
    op.add_column(
        "supplier_visual_scores",
        sa.Column("problem_dimension_scores", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("supplier_visual_scores", "problem_dimension_scores")
