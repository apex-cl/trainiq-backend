"""add vo2_max to health_metrics

Revision ID: 009_add_vo2_max
Revises: 008_watch_provider_athlete_id
Create Date: 2026-04-02
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "009_add_vo2_max"
down_revision: Union[str, None] = "008_watch_provider_athlete_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return any(c["name"] == column for c in insp.get_columns(table))


def upgrade() -> None:
    if not _column_exists("health_metrics", "vo2_max"):
        op.add_column(
            "health_metrics",
            sa.Column("vo2_max", sa.Float(), nullable=True),
        )


def downgrade() -> None:
    if _column_exists("health_metrics", "vo2_max"):
        op.drop_column("health_metrics", "vo2_max")
