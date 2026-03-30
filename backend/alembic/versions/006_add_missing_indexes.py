"""add missing indexes for conversations and nutrition_logs

Revision ID: 006_add_missing_indexes
Revises: 005_user_columns
Create Date: 2026-03-29

"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "006_add_missing_indexes"
down_revision: Union[str, None] = "005_user_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _index_exists(index_name: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    for table_name in insp.get_table_names():
        for idx in insp.get_indexes(table_name):
            if idx["name"] == index_name:
                return True
    return False


def upgrade() -> None:
    if not _index_exists("ix_conversations_user_created"):
        op.create_index(
            "ix_conversations_user_created",
            "conversations",
            ["user_id", "created_at"],
        )
    if not _index_exists("ix_nutrition_logs_user_logged"):
        op.create_index(
            "ix_nutrition_logs_user_logged",
            "nutrition_logs",
            ["user_id", "logged_at"],
        )


def downgrade() -> None:
    op.drop_index("ix_nutrition_logs_user_logged", table_name="nutrition_logs")
    op.drop_index("ix_conversations_user_created", table_name="conversations")
