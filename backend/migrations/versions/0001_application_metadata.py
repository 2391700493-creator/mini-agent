"""Create application metadata and record the project name.

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    metadata = op.create_table(
        "app_metadata",
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value", sa.String(length=500), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )
    op.bulk_insert(metadata, [{"key": "project_name", "value": "mini-agent"}])


def downgrade() -> None:
    op.drop_table("app_metadata")
