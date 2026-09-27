"""add conversation pinning and custom titles

Revision ID: ec4256d0d69b
Revises: db0a193ebc09
Create Date: 2026-09-12 15:40:02.450408

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ec4256d0d69b"
down_revision: str | Sequence[str] | None = "db0a193ebc09"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # 原生 ADD COLUMN 避免重建父表，保留级联引用的聊天记录。
    op.add_column(
        "conversations",
        sa.Column("pinned", sa.Boolean(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "conversations",
        sa.Column("title_custom", sa.Boolean(), server_default=sa.text("0"), nullable=False),
    )


def downgrade() -> None:
    # SQLite 原生 DROP COLUMN 保留会话表及其引用；不重建表触发级联删除。
    op.drop_column("conversations", "title_custom")
    op.drop_column("conversations", "pinned")
