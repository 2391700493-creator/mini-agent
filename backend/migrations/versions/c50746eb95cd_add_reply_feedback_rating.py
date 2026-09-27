"""add reply feedback rating

Revision ID: c50746eb95cd
Revises: 96bfb1d06227
Create Date: 2026-09-27 12:28:52.017802

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c50746eb95cd"
down_revision: str | Sequence[str] | None = "96bfb1d06227"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("chat_messages", schema=None) as batch_op:
        batch_op.add_column(sa.Column("feedback_rating", sa.String(length=20), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("chat_messages", schema=None) as batch_op:
        batch_op.drop_column("feedback_rating")
