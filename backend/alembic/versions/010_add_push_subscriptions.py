"""add push_subscriptions table

Revision ID: 010_add_push_subscriptions
Revises: 009_add_vo2_max
Create Date: 2026-04-02
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "010_add_push_subscriptions"
down_revision: Union[str, None] = "009_add_vo2_max"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return table in insp.get_table_names()


def upgrade() -> None:
    if not _table_exists("push_subscriptions"):
        op.create_table(
            "push_subscriptions",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("endpoint", sa.String(), nullable=False),
            sa.Column("p256dh", sa.String(), nullable=False),
            sa.Column("auth", sa.String(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("endpoint"),
        )
        op.create_index(
            "ix_push_subscriptions_user_id",
            "push_subscriptions",
            ["user_id"],
        )


def downgrade() -> None:
    if _table_exists("push_subscriptions"):
        op.drop_index("ix_push_subscriptions_user_id", table_name="push_subscriptions")
        op.drop_table("push_subscriptions")
