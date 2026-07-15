"""每日指标增加来源平台维度，避免多平台数据相互覆盖。

Revision ID: 008
Revises: 007
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "008"
down_revision: str | None = "007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "daily_metrics",
        sa.Column("source_platform", sa.String(length=32), nullable=False, server_default="manual"),
    )
    op.drop_constraint("daily_metrics_image_id_date_key", "daily_metrics", type_="unique")
    op.create_unique_constraint(
        "daily_metrics_image_date_platform_key",
        "daily_metrics",
        ["image_id", "date", "source_platform"],
    )


def downgrade() -> None:
    op.drop_constraint("daily_metrics_image_date_platform_key", "daily_metrics", type_="unique")
    # 多平台记录回退为单维度前，保留每图每天优先级最高的一条。
    op.execute(
        """
        DELETE FROM daily_metrics newer
        USING daily_metrics older
        WHERE newer.image_id = older.image_id
          AND newer.date = older.date
          AND newer.id > older.id
        """
    )
    op.drop_column("daily_metrics", "source_platform")
    op.create_unique_constraint(
        "daily_metrics_image_id_date_key", "daily_metrics", ["image_id", "date"]
    )
