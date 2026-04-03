"""add guest_sessions table

Revision ID: 014_guest_sessions
Revises: 013_remove_strava
Create Date: 2026-04-03
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "014_guest_sessions"
down_revision: Union[str, None] = "013_remove_strava"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "guest_sessions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("message_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("photo_count", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_table("guest_sessions")
