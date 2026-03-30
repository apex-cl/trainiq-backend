"""add user profile and auth columns

Revision ID: 005_user_columns
Revises: 004_vector_1024
Create Date: 2026-03-29

"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "005_user_columns"
down_revision: Union[str, None] = "004_vector_1024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return any(c["name"] == column for c in insp.get_columns(table))


def _add_column_safe(table: str, column: sa.Column) -> None:
    if not _column_exists(table, column.name):
        op.add_column(table, column)


def upgrade() -> None:
    _add_column_safe("users", sa.Column("avatar_url", sa.String(), nullable=True))
    _add_column_safe("users", sa.Column("birth_date", sa.Date(), nullable=True))
    _add_column_safe("users", sa.Column("gender", sa.String(), nullable=True))
    _add_column_safe("users", sa.Column("weight_kg", sa.Float(), nullable=True))
    _add_column_safe("users", sa.Column("height_cm", sa.Integer(), nullable=True))
    _add_column_safe(
        "users", sa.Column("preferred_language", sa.String(), server_default="de")
    )
    _add_column_safe(
        "users", sa.Column("notification_settings", sa.JSON(), nullable=True)
    )
    _add_column_safe(
        "users", sa.Column("marketing_consent", sa.Boolean(), server_default="false")
    )
    _add_column_safe(
        "users", sa.Column("email_verified", sa.Boolean(), server_default="false")
    )
    _add_column_safe(
        "users", sa.Column("verification_token", sa.String(), nullable=True)
    )
    _add_column_safe(
        "users",
        sa.Column("verification_expires", sa.DateTime(timezone=True), nullable=True),
    )
    _add_column_safe(
        "users", sa.Column("two_factor_enabled", sa.Boolean(), server_default="false")
    )
    _add_column_safe(
        "users", sa.Column("two_factor_secret", sa.String(), nullable=True)
    )
    _add_column_safe(
        "users", sa.Column("two_factor_backup_codes", sa.JSON(), nullable=True)
    )
    _add_column_safe(
        "users", sa.Column("stripe_customer_id", sa.String(), nullable=True)
    )
    _add_column_safe(
        "users", sa.Column("subscription_tier", sa.String(), server_default="free")
    )
    _add_column_safe(
        "users",
        sa.Column("subscription_expires", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "subscription_expires")
    op.drop_column("users", "subscription_tier")
    op.drop_column("users", "stripe_customer_id")
    op.drop_column("users", "two_factor_backup_codes")
    op.drop_column("users", "two_factor_secret")
    op.drop_column("users", "two_factor_enabled")
    op.drop_column("users", "verification_expires")
    op.drop_column("users", "verification_token")
    op.drop_column("users", "email_verified")
    op.drop_column("users", "marketing_consent")
    op.drop_column("users", "notification_settings")
    op.drop_column("users", "preferred_language")
    op.drop_column("users", "height_cm")
    op.drop_column("users", "weight_kg")
    op.drop_column("users", "gender")
    op.drop_column("users", "birth_date")
    op.drop_column("users", "avatar_url")
