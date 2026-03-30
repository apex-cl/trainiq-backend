"""add missing tables: ai_memories, password_reset_tokens, strava_webhook_subscriptions, training_plans unique constraint

Revision ID: 002_add_missing_tables
Revises: 001_initial_schema
Create Date: 2026-03-29

"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "002_add_missing_tables"
down_revision: Union[str, None] = "001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ai_memories (pgvector — skipped in SQLite, created manually in PG)
    op.create_table(
        "ai_memories",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("fact", sa.Text(), nullable=False),
        sa.Column("category", sa.String(), nullable=True),
        # embedding column is added separately in PostgreSQL via raw SQL
        sa.Column(
            "source_conversation_id",
            sa.Uuid(),
            sa.ForeignKey("conversations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    # password_reset_tokens
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token", sa.String(), unique=True, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "used", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    # strava_webhook_subscriptions
    op.create_table(
        "strava_webhook_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("strava_subscription_id", sa.Integer(), unique=True, nullable=True),
        sa.Column("callback_url", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    # unique constraint on training_plans (user_id, date)
    try:
        op.create_unique_constraint(
            "uq_training_plans_user_date", "training_plans", ["user_id", "date"]
        )
    except Exception:
        pass  # Already exists in some environments

    # pgvector embedding column (PostgreSQL only)
    try:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
        op.execute(
            "ALTER TABLE ai_memories ADD COLUMN IF NOT EXISTS embedding vector(768)"
        )
    except Exception:
        pass  # SQLite or extension not available


def downgrade() -> None:
    try:
        op.drop_constraint("uq_training_plans_user_date", "training_plans")
    except Exception:
        pass
    op.drop_table("strava_webhook_subscriptions")
    op.drop_table("password_reset_tokens")
    op.drop_table("ai_memories")
