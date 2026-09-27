"""add evaluation reproducibility and run costs

Revision ID: bc4366639aad
Revises: 9a2b3c4d5e6f
Create Date: 2026-09-18 11:35:23.374338

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "bc4366639aad"
down_revision: str | Sequence[str] | None = "9a2b3c4d5e6f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 全部是 SQLite 原生 ADD COLUMN。避免 batch 重建被其他表的外键阻止。
    op.add_column("chat_generations", sa.Column("pricing_snapshot", sa.JSON(), nullable=True))
    op.add_column("chat_generations", sa.Column("cost", sa.Float(), nullable=True))
    op.add_column(
        "chat_generations",
        sa.Column(
            "cost_status", sa.String(length=20), server_default=sa.text("'unknown'"), nullable=False
        ),
    )
    op.add_column("evaluation_cases", sa.Column("history", sa.JSON(), nullable=True))
    op.add_column("evaluation_cases", sa.Column("process_rules", sa.JSON(), nullable=True))
    op.add_column("evaluation_task_cases", sa.Column("history", sa.JSON(), nullable=True))
    op.add_column("evaluation_task_cases", sa.Column("process_rules", sa.JSON(), nullable=True))
    op.add_column(
        "evaluation_task_cases",
        sa.Column("scoring_cached_input_tokens", sa.Integer(), nullable=True),
    )
    op.add_column(
        "evaluation_task_cases",
        sa.Column(
            "scoring_usage_complete", sa.Boolean(), server_default=sa.text("1"), nullable=False
        ),
    )
    op.add_column(
        "evaluation_task_cases", sa.Column("issue_category", sa.String(length=40), nullable=True)
    )
    op.add_column(
        "evaluation_task_cases",
        sa.Column(
            "review_status",
            sa.String(length=20),
            server_default=sa.text("'unreviewed'"),
            nullable=False,
        ),
    )
    op.add_column("evaluation_task_cases", sa.Column("review_note", sa.Text(), nullable=True))
    op.add_column(
        "evaluation_tasks",
        sa.Column(
            "scoring_model_snapshot", sa.JSON(), server_default=sa.text("'{}'"), nullable=False
        ),
    )
    op.add_column(
        "language_models",
        sa.Column(
            "pricing_currency", sa.String(length=3), server_default=sa.text("'CNY'"), nullable=False
        ),
    )
    op.add_column(
        "language_models",
        sa.Column(
            "price_unit_tokens", sa.Integer(), server_default=sa.text("1000000"), nullable=False
        ),
    )


def downgrade() -> None:
    for table, columns in (
        ("language_models", ("price_unit_tokens", "pricing_currency")),
        ("evaluation_tasks", ("scoring_model_snapshot",)),
        (
            "evaluation_task_cases",
            (
                "review_note",
                "review_status",
                "issue_category",
                "scoring_usage_complete",
                "scoring_cached_input_tokens",
                "process_rules",
                "history",
            ),
        ),
        ("evaluation_cases", ("process_rules", "history")),
        ("chat_generations", ("cost_status", "cost", "pricing_snapshot")),
    ):
        for column in columns:
            op.drop_column(table, column)
