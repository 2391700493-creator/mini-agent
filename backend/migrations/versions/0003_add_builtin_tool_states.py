"""add builtin tool states

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-11 18:05:01.627601

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "tool_states",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.CheckConstraint("id IN ('current_time', 'shell', 'file')", name="ck_builtin_tool_id"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.bulk_insert(
        sa.table("tool_states", sa.column("id", sa.String), sa.column("enabled", sa.Boolean)),
        [
            {"id": "current_time", "enabled": True},
            {"id": "shell", "enabled": False},
            {"id": "file", "enabled": False},
        ],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("tool_states")
