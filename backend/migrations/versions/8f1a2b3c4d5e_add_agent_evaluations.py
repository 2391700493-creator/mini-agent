"""add agent evaluations

Revision ID: 8f1a2b3c4d5e
Revises: 3d80f81530be
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8f1a2b3c4d5e"
down_revision: str | Sequence[str] | None = "3d80f81530be"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("chat_generations") as batch:
        batch.alter_column("conversation_id", existing_type=sa.String(36), nullable=True)
        batch.alter_column("user_message_id", existing_type=sa.String(36), nullable=True)
        batch.add_column(sa.Column("source", sa.String(20), nullable=False, server_default="chat"))

    op.create_table(
        "evaluation_datasets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("stable_key", sa.String(100), nullable=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "uq_evaluation_dataset_stable_key", "evaluation_datasets", ["stable_key"], unique=True
    )
    op.create_table(
        "evaluation_cases",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "dataset_id",
            sa.String(36),
            sa.ForeignKey("evaluation_datasets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("expected_answer", sa.Text()),
        sa.Column("grading_criteria", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(question) > 0", name="ck_evaluation_case_question"),
        sa.CheckConstraint(
            "expected_answer IS NOT NULL OR grading_criteria IS NOT NULL",
            name="ck_evaluation_case_material",
        ),
    )
    op.create_index("ix_evaluation_cases_dataset_id", "evaluation_cases", ["dataset_id"])
    op.create_table(
        "evaluation_tasks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("dataset_id", sa.String(36), nullable=False),
        sa.Column("dataset_name", sa.String(100), nullable=False),
        sa.Column("agent_id", sa.String(36), nullable=False),
        sa.Column("agent_name", sa.String(100), nullable=False),
        sa.Column("scoring_model_id", sa.String(36), nullable=False),
        sa.Column("scoring_model_name", sa.String(100), nullable=False),
        sa.Column("scoring_model_identifier", sa.String(200), nullable=False),
        sa.Column("passing_score", sa.Float(), nullable=False),
        sa.Column("tools_allowed", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("agent_snapshot", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "passing_score >= 0 AND passing_score <= 100", name="ck_eval_passing_score"
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'interrupted')",
            name="ck_eval_task_status",
        ),
    )
    op.create_table(
        "evaluation_task_cases",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "task_id",
            sa.String(36),
            sa.ForeignKey("evaluation_tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_case_id", sa.String(36), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("expected_answer", sa.Text()),
        sa.Column("grading_criteria", sa.Text()),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column(
            "run_id", sa.String(36), sa.ForeignKey("chat_generations.id", ondelete="SET NULL")
        ),
        sa.Column("answer", sa.Text()),
        sa.Column("score", sa.Float()),
        sa.Column("reason", sa.Text()),
        sa.Column("error", sa.Text()),
        sa.Column("scoring_duration_ms", sa.Integer()),
        sa.Column("scoring_input_tokens", sa.Integer()),
        sa.Column("scoring_output_tokens", sa.Integer()),
        sa.Column("scoring_total_tokens", sa.Integer()),
        sa.Column("grading_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'executing', 'grading', 'passed', 'failed', "
            "'execution_failed', 'grading_failed')",
            name="ck_eval_case_status",
        ),
        sa.CheckConstraint("score IS NULL OR (score >= 0 AND score <= 100)", name="ck_eval_score"),
    )
    op.create_index("ix_evaluation_task_cases_task_id", "evaluation_task_cases", ["task_id"])


def downgrade() -> None:
    op.drop_index("ix_evaluation_task_cases_task_id", table_name="evaluation_task_cases")
    op.drop_table("evaluation_task_cases")
    op.drop_table("evaluation_tasks")
    op.drop_index("ix_evaluation_cases_dataset_id", table_name="evaluation_cases")
    op.drop_table("evaluation_cases")
    op.drop_index("uq_evaluation_dataset_stable_key", table_name="evaluation_datasets")
    op.drop_table("evaluation_datasets")
    with op.batch_alter_table("chat_generations") as batch:
        batch.drop_column("source")
        batch.alter_column("user_message_id", existing_type=sa.String(36), nullable=False)
        batch.alter_column("conversation_id", existing_type=sa.String(36), nullable=False)
