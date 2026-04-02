"""add completed_at to training_plans

Revision ID: 011_add_completed_at_training
Revises: 010_add_push_subscriptions
Create Date: 2026-04-02
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "011_add_completed_at_training"
down_revision: Union[str, None] = "010_add_push_subscriptions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return any(c["name"] == column for c in insp.get_columns(table))


def upgrade() -> None:
    if not _column_exists("training_plans", "completed_at"):
        op.add_column(
            "training_plans",
            sa.Column(
                "completed_at",
                sa.DateTime(timezone=True),
                nullable=True,
                server_default=None,
            ),
        )


def downgrade() -> None:
    op.drop_column("training_plans", "completed_at")
