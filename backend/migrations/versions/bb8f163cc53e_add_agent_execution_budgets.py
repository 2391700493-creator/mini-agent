"""add agent execution budgets

Revision ID: bb8f163cc53e
Revises: c6a85ee5b628
Create Date: 2026-09-18 11:51:26.514510

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "bb8f163cc53e"
down_revision: str | Sequence[str] | None = "c6a85ee5b628"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column(
            "max_runtime_seconds", sa.Integer(), server_default=sa.text("300"), nullable=False
        ),
    )
    op.add_column(
        "agents",
        sa.Column("max_tool_calls", sa.Integer(), server_default=sa.text("30"), nullable=False),
    )
    op.add_column("agents", sa.Column("max_total_tokens", sa.Integer(), nullable=True))


def downgrade() -> None:
    for column in ("max_total_tokens", "max_tool_calls", "max_runtime_seconds"):
        op.drop_column("agents", column)
