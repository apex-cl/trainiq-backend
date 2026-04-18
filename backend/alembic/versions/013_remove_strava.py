"""remove strava_webhook_subscriptions table

Revision ID: 013_remove_strava
Revises: 012_native_analytics
Create Date: 2026-04-03
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "013_remove_strava"
down_revision: Union[str, None] = "012_native_analytics"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return table in insp.get_table_names()


def upgrade() -> None:
    if _table_exists("strava_webhook_subscriptions"):
        op.drop_table("strava_webhook_subscriptions")


def downgrade() -> None:
    op.create_table(
        "strava_webhook_subscriptions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("strava_subscription_id", sa.Integer(), nullable=True),
        sa.Column("callback_url", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("strava_subscription_id"),
    )
