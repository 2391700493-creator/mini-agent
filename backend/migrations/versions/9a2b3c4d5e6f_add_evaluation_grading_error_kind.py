"""add evaluation grading error kind

Revision ID: 9a2b3c4d5e6f
Revises: 8f1a2b3c4d5e
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9a2b3c4d5e6f"
down_revision: str | Sequence[str] | None = "8f1a2b3c4d5e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("evaluation_task_cases") as batch:
        batch.add_column(sa.Column("grading_error_kind", sa.String(length=20), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("evaluation_task_cases") as batch:
        batch.drop_column("grading_error_kind")
