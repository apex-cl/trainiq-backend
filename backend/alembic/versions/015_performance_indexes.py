"""add missing performance indexes

Revision ID: 015_performance_indexes
Revises: 014_guest_sessions
Create Date: 2026-04-03
"""

from typing import Sequence, Union
from alembic import op

revision: str = "015_performance_indexes"
down_revision: Union[str, None] = "014_guest_sessions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_health_metrics_user_recorded",
        "health_metrics",
        ["user_id", "recorded_at"],
    )
    op.create_index(
        "ix_health_metrics_user_source",
        "health_metrics",
        ["user_id", "source"],
    )
    op.create_index(
        "ix_training_plans_user_status",
        "training_plans",
        ["user_id", "status"],
    )
    op.create_index(
        "ix_daily_wellbeing_user_date",
        "daily_wellbeing",
        ["user_id", "date"],
    )


def downgrade() -> None:
    op.drop_index("ix_daily_wellbeing_user_date", table_name="daily_wellbeing")
    op.drop_index("ix_training_plans_user_status", table_name="training_plans")
    op.drop_index("ix_health_metrics_user_source", table_name="health_metrics")
    op.drop_index("ix_health_metrics_user_recorded", table_name="health_metrics")
