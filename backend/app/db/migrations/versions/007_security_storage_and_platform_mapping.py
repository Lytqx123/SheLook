"""security storage and external platform mapping

Revision ID: 007
Revises: 006
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "007"
down_revision: str | None = "006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("generated_images", sa.Column("storage_bucket", sa.String(128), nullable=True))
    op.add_column("generated_images", sa.Column("storage_object_key", sa.String(512), nullable=True))
    op.add_column(
        "generated_images",
        sa.Column("is_public", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "external_listing_mappings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("image_id", sa.Integer(), sa.ForeignKey("generated_images.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("platform", "external_id", name="uq_external_listing_platform_id"),
    )
    op.create_index("ix_external_listing_mappings_image_id", "external_listing_mappings", ["image_id"])


def downgrade() -> None:
    op.drop_index("ix_external_listing_mappings_image_id", table_name="external_listing_mappings")
    op.drop_table("external_listing_mappings")
    op.drop_column("generated_images", "is_public")
    op.drop_column("generated_images", "storage_object_key")
    op.drop_column("generated_images", "storage_bucket")
