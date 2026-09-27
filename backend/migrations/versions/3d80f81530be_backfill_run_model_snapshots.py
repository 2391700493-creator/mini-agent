"""backfill run model snapshots

Revision ID: 3d80f81530be
Revises: 44e95393fc87
Create Date: 2026-09-13 23:22:46.183235

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3d80f81530be"
down_revision: str | Sequence[str] | None = "44e95393fc87"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """旧 Run 只能按当前尚存配置尽力补齐；新 Run 始终在启动时保存精确快照。"""
    op.execute(
        sa.text(
            """
            UPDATE chat_generations
            SET model_id = (
                    SELECT agents.model_id FROM agents WHERE agents.id = chat_generations.agent_id
                ),
                model_name = (
                    SELECT language_models.display_name
                    FROM agents JOIN language_models ON language_models.id = agents.model_id
                    WHERE agents.id = chat_generations.agent_id
                ),
                model_identifier = (
                    SELECT language_models.model_id
                    FROM agents JOIN language_models ON language_models.id = agents.model_id
                    WHERE agents.id = chat_generations.agent_id
                ),
                end_reason = CASE status
                    WHEN 'completed' THEN '历史运行已完成。'
                    WHEN 'limit_reached' THEN '历史运行达到执行限制。'
                    WHEN 'cancelled' THEN '历史运行已取消。'
                    WHEN 'failed' THEN COALESCE(error, '历史运行失败。')
                    ELSE end_reason
                END
            WHERE model_id IS NULL
              AND EXISTS (SELECT 1 FROM agents WHERE agents.id = chat_generations.agent_id)
            """
        )
    )


def downgrade() -> None:
    """回填无法与升级后新写入的快照可靠区分，降级保留兼容字段数据。"""
