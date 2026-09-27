"""freeze agent mcp tool allowlists

Revision ID: d452e338028f
Revises: bb8f163cc53e
Create Date: 2026-09-18 11:53:02.901367

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d452e338028f"
down_revision: str | Sequence[str] | None = "bb8f163cc53e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agent_mcp_servers", sa.Column("allowed_tools", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_mcp_servers", "allowed_tools")
