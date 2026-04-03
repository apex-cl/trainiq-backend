"""add indexes for watch_connections and ai_memories

Revision ID: 016_watch_memory_indexes
Revises: 015_performance_indexes
Create Date: 2026-04-03
"""

from typing import Sequence, Union
from alembic import op

revision: str = "016_watch_memory_indexes"
down_revision: Union[str, None] = "015_performance_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_watch_connections_user_id",
        "watch_connections",
        ["user_id"],
    )
    op.create_index(
        "ix_watch_connections_user_active",
        "watch_connections",
        ["user_id", "is_active"],
    )
    op.create_index(
        "ix_ai_memories_user_id",
        "ai_memories",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_ai_memories_user_id", table_name="ai_memories")
    op.drop_index("ix_watch_connections_user_active", table_name="watch_connections")
    op.drop_index("ix_watch_connections_user_id", table_name="watch_connections")
