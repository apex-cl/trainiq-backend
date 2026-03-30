"""change ai_memories embedding from vector(768) to vector(1024)

Revision ID: 004_vector_1024
Revises: 003_phase2_tables
Create Date: 2026-03-29

"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "004_vector_1024"
down_revision: Union[str, None] = "003_phase2_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Bestehende Embeddings löschen (Dimension ändert sich → inkompatibel)
    op.execute("UPDATE ai_memories SET embedding = NULL")
    # Index löschen, falls vorhanden
    op.execute("DROP INDEX IF EXISTS idx_ai_memories_embedding")
    # Spalte auf 1024 Dimensionen ändern
    op.execute("ALTER TABLE ai_memories ALTER COLUMN embedding TYPE vector(1024)")
    # Index neu erstellen für 1024 Dimensionen
    op.execute(
        "CREATE INDEX idx_ai_memories_embedding ON ai_memories USING ivfflat (embedding vector_cosine_ops) WITH (lists=100)"
    )


def downgrade() -> None:
    op.execute("UPDATE ai_memories SET embedding = NULL")
    op.execute("DROP INDEX IF EXISTS idx_ai_memories_embedding")
    op.execute("ALTER TABLE ai_memories ALTER COLUMN embedding TYPE vector(768)")
    op.execute(
        "CREATE INDEX idx_ai_memories_embedding ON ai_memories USING ivfflat (embedding vector_cosine_ops) WITH (lists=100)"
    )
