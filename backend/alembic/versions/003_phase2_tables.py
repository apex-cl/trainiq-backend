"""add ai memories embedding indexes and cleanup

Revision ID: 003_phase2_tables
Revises: 002_add_missing_tables
Create Date: 2026-03-29

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "003_phase2_tables"
down_revision: Union[str, None] = "002_add_missing_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Tables already created by 002 — only add indexes/fixes here

    # Ensure pgvector extension exists
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Fix ai_memories.embedding to proper vector(768) type
    # (002 adds it as vector(768), but this ensures consistency)
    op.execute(
        "ALTER TABLE ai_memories ALTER COLUMN embedding TYPE vector(768) USING embedding::vector(768)"
    )

    # Indexes (IF NOT EXISTS to be safe)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ai_memories_embedding ON ai_memories USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ai_memories_user ON ai_memories (user_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_token ON password_reset_tokens (token)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_ai_memories_embedding")
    op.execute("DROP INDEX IF EXISTS idx_ai_memories_user")
    op.execute("DROP INDEX IF EXISTS idx_password_reset_tokens_token")
