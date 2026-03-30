"""add keycloak_id to users table

Revision ID: 007_add_keycloak_id
Revises: 006_add_missing_indexes
Create Date: 2026-03-30

"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "007_add_keycloak_id"
down_revision: Union[str, None] = "006_add_missing_indexes"
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
    if not _column_exists("users", "keycloak_id"):
        op.add_column("users", sa.Column("keycloak_id", sa.String(), nullable=True))

    if not _index_exists("ix_users_keycloak_id"):
        op.create_index("ix_users_keycloak_id", "users", ["keycloak_id"])


def downgrade() -> None:
    if _index_exists("ix_users_keycloak_id"):
        op.drop_index("ix_users_keycloak_id", table_name="users")
    if _column_exists("users", "keycloak_id"):
        op.drop_column("users", "keycloak_id")
