"""add provider_athlete_id to watch_connections

Revision ID: 008_watch_provider_athlete_id
Revises: 007_add_keycloak_id
Create Date: 2026-04-02

Adds the provider_athlete_id column (used for Strava/Garmin webhook routing)
and an index on (provider, provider_athlete_id, is_active) for fast webhook lookups.
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "008_watch_provider_athlete_id"
down_revision: Union[str, None] = "007_add_keycloak_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return any(c["name"] == column for c in insp.get_columns(table))


def _index_exists(index_name: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    for table_name in insp.get_table_names():
        for idx in insp.get_indexes(table_name):
            if idx["name"] == index_name:
                return True
    return False


def upgrade() -> None:
    # provider_athlete_id Spalte hinzufügen (nullable, da ältere Verbindungen sie nicht haben)
    if not _column_exists("watch_connections", "provider_athlete_id"):
        op.add_column(
            "watch_connections",
            sa.Column("provider_athlete_id", sa.String(), nullable=True),
        )

    # Kombinations-Index für schnelle Webhook-Lookups:
    # WHERE provider = 'strava' AND provider_athlete_id = '...' AND is_active = true
    if not _index_exists("ix_watch_connections_provider_athlete"):
        op.create_index(
            "ix_watch_connections_provider_athlete",
            "watch_connections",
            ["provider", "provider_athlete_id", "is_active"],
        )


def downgrade() -> None:
    if _index_exists("ix_watch_connections_provider_athlete"):
        op.drop_index("ix_watch_connections_provider_athlete", table_name="watch_connections")
    if _column_exists("watch_connections", "provider_athlete_id"):
        op.drop_column("watch_connections", "provider_athlete_id")
