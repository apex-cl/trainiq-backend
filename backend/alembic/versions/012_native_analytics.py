"""replace strava tables with native analytics tables

Replaces strava_activities/gear/fitness_snapshots/personal_records
with native activity_details/gear_items/fitness_snapshots/personal_records
(calculated from our own watch data — no Strava API needed).

Revision ID: 012_native_analytics
Revises: 011_add_completed_at_training
Create Date: 2026-04-03
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "012_native_analytics"
down_revision: Union[str, None] = "011_add_completed_at_training"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return table in insp.get_table_names()


def upgrade() -> None:
    # Alte Strava-Tabellen entfernen falls vorhanden
    for old_table in [
        "strava_personal_records",
        "strava_fitness_snapshots",
        "strava_gear",
        "strava_activities",
    ]:
        if _table_exists(old_table):
            op.drop_table(old_table)

    # gear_items muss vor activity_details existieren (FK)
    if not _table_exists("gear_items"):
        op.create_table(
            "gear_items",
            sa.Column("id", sa.UUID(), nullable=False,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("user_id", sa.UUID(), nullable=False),
            sa.Column("gear_type", sa.String(), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("brand", sa.String(), nullable=True),
            sa.Column("model", sa.String(), nullable=True),
            sa.Column("purchase_date", sa.String(), nullable=True),
            sa.Column("initial_km", sa.Float(), nullable=False, server_default="0"),
            sa.Column("retired", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.text("now()")),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_gear_items_user", "gear_items", ["user_id"])

    if not _table_exists("activity_details"):
        op.create_table(
            "activity_details",
            sa.Column("id", sa.UUID(), nullable=False,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("user_id", sa.UUID(), nullable=False),
            sa.Column("source", sa.String(), nullable=False),
            sa.Column("external_id", sa.String(), nullable=True),
            sa.Column("name", sa.String(), nullable=True),
            sa.Column("sport_type", sa.String(), nullable=True),
            sa.Column("activity_date", sa.String(), nullable=True),
            sa.Column("distance_m", sa.Float(), nullable=True),
            sa.Column("elapsed_time_s", sa.Integer(), nullable=True),
            sa.Column("moving_time_s", sa.Integer(), nullable=True),
            sa.Column("average_watts", sa.Float(), nullable=True),
            sa.Column("normalized_power", sa.Float(), nullable=True),
            sa.Column("max_watts", sa.Float(), nullable=True),
            sa.Column("kilojoules", sa.Float(), nullable=True),
            sa.Column("average_cadence", sa.Float(), nullable=True),
            sa.Column("average_stride_length", sa.Float(), nullable=True),
            sa.Column("average_heartrate", sa.Float(), nullable=True),
            sa.Column("max_heartrate", sa.Float(), nullable=True),
            sa.Column("gear_id", sa.UUID(), nullable=True),
            sa.Column("laps", sa.JSON(), nullable=True),
            sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.text("now()")),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["gear_id"], ["gear_items.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_activity_details_user_date", "activity_details",
                        ["user_id", "activity_date"])

    if not _table_exists("fitness_snapshots"):
        op.create_table(
            "fitness_snapshots",
            sa.Column("id", sa.UUID(), nullable=False,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("user_id", sa.UUID(), nullable=False),
            sa.Column("snapshot_date", sa.String(), nullable=False),
            sa.Column("ctl", sa.Float(), nullable=False, server_default="0"),
            sa.Column("atl", sa.Float(), nullable=False, server_default="0"),
            sa.Column("tsb", sa.Float(), nullable=False, server_default="0"),
            sa.Column("tss", sa.Float(), nullable=False, server_default="0"),
            sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.text("now()")),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_fitness_snapshots_user_date", "fitness_snapshots",
                        ["user_id", "snapshot_date"])

    if not _table_exists("personal_records"):
        op.create_table(
            "personal_records",
            sa.Column("id", sa.UUID(), nullable=False,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("user_id", sa.UUID(), nullable=False),
            sa.Column("distance_label", sa.String(), nullable=False),
            sa.Column("elapsed_time_s", sa.Integer(), nullable=False),
            sa.Column("achieved_date", sa.String(), nullable=True),
            sa.Column("source", sa.String(), nullable=False, server_default="manual"),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.text("now()")),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_personal_records_user_distance", "personal_records",
                        ["user_id", "distance_label"])


def downgrade() -> None:
    op.drop_table("personal_records")
    op.drop_table("fitness_snapshots")
    op.drop_table("activity_details")
    op.drop_table("gear_items")
