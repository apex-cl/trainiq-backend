"""
Long-Term AI Memory Service (RAG mit pgvector)

Extrahiert wichtige Fakten aus User-Chats, speichert sie als Vektor-Embeddings
und holt relevante Erinnerungen bei jedem Chat-Aufruf.

LLM und Embeddings werden via LLM_* Env-Vars konfiguriert (OpenAI-kompatibel).
Wenn LLM_EMBEDDING_MODEL nicht gesetzt ist, werden Erinnerungen ohne
Vektor-Ähnlichkeitssuche gespeichert und abgerufen.
"""

import json
import uuid
import httpx
from datetime import datetime, timezone
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, text
from app.core.config import settings
from app.models.ai_memory import AIMemory


# Kategorien für Memory-Fakten
MEMORY_CATEGORIES = [
    "injury",  # Verletzungen
    "preference",  # Vorlieben (Essen, Training)
    "goal",  # Ziele
    "constraint",  # Einschränkungen (Zeit, Ort, Ausrüstung)
    "history",  # Sportliche Vergangenheit
    "feedback",  # Feedback zu Trainings
    "general",  # Allgemein
]


class AIMemoryService:
    """Verwaltet das Langzeit-Gedächtnis der KI."""

    EXTRACTION_PROMPT = """Analysiere die folgende User-Nachricht und extrahiere wichtige, dauerhaft relevante Fakten über den User.

Kategorien: injury (Verletzung), preference (Vorliebe), goal (Ziel), constraint (Einschränkung), history (Vergangenheit), feedback (Feedback), general (Allgemein)

Antworte NUR mit einem JSON-Array von Objekten. Jedes Objekt hat: "fact" (string, der extrahierte Fakt) und "category" (eine der oben genannten Kategorien).

Wenn keine relevanten Fakten extrahiert werden können, antworte mit einem leeren Array: []

User-Nachricht:
{message}

JSON:"""

    SIMILARITY_THRESHOLD = 0.75
    MAX_MEMORIES = 5

    def __init__(self):
        self.llm_configured = bool(settings.active_llm_api_key)
        self.embeddings_configured = bool(
            settings.active_embedding_api_key and settings.llm_embedding_model
        )
        self._headers = {
            "Authorization": f"Bearer {settings.active_llm_api_key}",
            "Content-Type": "application/json",
        }
        self._embedding_headers = {
            "Authorization": f"Bearer {settings.active_embedding_api_key}",
            "Content-Type": "application/json",
        }

    async def _generate_embedding(
        self, text_content: str, input_type: str = "passage"
    ) -> list[float] | None:
        """Generiert Embedding via OpenAI-kompatiblem Embeddings-Endpoint.
        input_type: 'passage' für zu speichernde Texte, 'query' für Suchanfragen.
        """
        if not self.embeddings_configured:
            return None
        try:
            payload = {
                "model": settings.llm_embedding_model,
                "input": text_content,
                "input_type": input_type,
                "encoding_format": "float",
            }
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{settings.active_embedding_base_url}/embeddings",
                    headers=self._embedding_headers,
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
                return data["data"][0]["embedding"]
        except Exception as e:
            logger.error(f"Embedding generation failed | error={e}")
            return None

    async def _generate_query_embedding(self, query: str) -> list[float] | None:
        """Generiert Embedding für eine Suchanfrage."""
        return await self._generate_embedding(query, input_type="query")

    async def extract_and_store(
        self,
        message: str,
        user_id: str,
        db: AsyncSession,
        conversation_id: str | None = None,
    ):
        """Extrahiert Fakten aus einer Nachricht und speichert sie."""
        if not self.llm_configured:
            return

        try:
            prompt = self.EXTRACTION_PROMPT.format(message=message)
            payload = {
                "model": settings.llm_model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 512,
            }
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{settings.llm_base_url}/chat/completions",
                    headers=self._headers,
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
                msg = data["choices"][0]["message"]
                # Reasoning-Modelle (kimi-k2.5, deepseek-r1) geben content manchmal null
                response_text = (
                    msg.get("content") or msg.get("reasoning") or ""
                ).strip()

            # JSON parsen (kann mit ```json ... ``` eingerahmt sein)
            if response_text.startswith("```"):
                parts = response_text.split("```")
                if len(parts) >= 2:
                    response_text = parts[1]
                    if response_text.startswith("json"):
                        response_text = response_text[4:]
                    response_text = response_text.strip()
                else:
                    return

            facts = json.loads(response_text)
            if not isinstance(facts, list):
                return

            for fact_item in facts:
                fact_text = fact_item.get("fact", "").strip()
                category = fact_item.get("category", "general")

                if not fact_text or category not in MEMORY_CATEGORIES:
                    continue

                embedding = await self._generate_embedding(fact_text)

                # Ähnliche existierende Fakten finden (nur wenn Embeddings verfügbar)
                similar = None
                if embedding is not None:
                    similar = await self._find_similar_memory(user_id, embedding, db)

                if similar:
                    # Bestehenden Fakt aktualisieren
                    similar.fact = fact_text
                    similar.embedding = embedding
                    similar.updated_at = datetime.now(timezone.utc)
                    logger.info(
                        f"Memory updated | user={user_id} | category={category}"
                    )
                else:
                    conv_uuid = None
                    if conversation_id:
                        try:
                            conv_uuid = uuid.UUID(conversation_id)
                        except ValueError:
                            pass

                    memory = AIMemory(
                        user_id=uuid.UUID(user_id),
                        fact=fact_text,
                        category=category,
                        embedding=embedding,
                        source_conversation_id=conv_uuid,
                    )
                    db.add(memory)
                    logger.info(
                        f"Memory stored | user={user_id} | category={category} | fact={fact_text[:50]}"
                    )

                await db.flush()

        except json.JSONDecodeError:
            logger.warning("Memory extraction: invalid JSON response")
        except Exception as e:
            logger.error(f"Memory extraction failed | error={e}")

    async def _find_similar_memory(
        self, user_id: str, embedding: list[float], db: AsyncSession
    ) -> AIMemory | None:
        """Findet einen ähnlichen existierenden Memory-Eintrag via pgvector."""
        try:
            vec_str = "[" + ",".join(str(x) for x in embedding) + "]"
            query = text("""
                SELECT id,
                       1 - (embedding <=> CAST(:vec AS vector)) AS similarity
                FROM ai_memories
                WHERE user_id = CAST(:user_id AS uuid)
                  AND embedding IS NOT NULL
                  AND 1 - (embedding <=> CAST(:vec AS vector)) > :threshold
                ORDER BY embedding <=> CAST(:vec AS vector)
                LIMIT 1
            """)
            result = await db.execute(
                query,
                {
                    "vec": vec_str,
                    "user_id": str(user_id),
                    "threshold": self.SIMILARITY_THRESHOLD,
                },
            )
            row = result.first()
            if row:
                return await db.get(AIMemory, row.id)
            return None
        except Exception as e:
            logger.warning(f"Similarity search failed | error={e}")
            return None

    async def retrieve_relevant(
        self, query: str, user_id: str, db: AsyncSession
    ) -> str:
        """Holt relevante Erinnerungen für eine Chat-Anfrage."""
        try:
            if self.embeddings_configured:
                # Embedding-basierte Ähnlichkeitssuche
                query_embedding = await self._generate_query_embedding(query)
                if query_embedding is not None:
                    vec_str = "[" + ",".join(str(x) for x in query_embedding) + "]"
                    result = await db.execute(
                        text("""
                            SELECT id, fact, category, created_at,
                                   1 - (embedding <=> CAST(:vec AS vector)) AS similarity
                            FROM ai_memories
                            WHERE user_id = CAST(:user_id AS uuid)
                              AND embedding IS NOT NULL
                            ORDER BY embedding <=> CAST(:vec AS vector)
                            LIMIT :limit
                        """),
                        {
                            "vec": vec_str,
                            "user_id": str(user_id),
                            "limit": self.MAX_MEMORIES,
                        },
                    )
                    rows = result.fetchall()
                    if rows:
                        memories_text = "ERINNERUNGEN (aus vorherigen Gesprächen):\n"
                        for row in rows:
                            memories_text += f"- [{row.category}] {row.fact}\n"
                        return memories_text
                    return ""

            # Fallback: neueste Erinnerungen ohne Embedding-Suche
            result = await db.execute(
                select(AIMemory)
                .where(AIMemory.user_id == user_id)
                .order_by(AIMemory.updated_at.desc())
                .limit(self.MAX_MEMORIES)
            )
            memories = result.scalars().all()

            if not memories:
                return ""

            memories_text = "ERINNERUNGEN (aus vorherigen Gesprächen):\n"
            for m in memories:
                memories_text += f"- [{m.category}] {m.fact}\n"
            return memories_text

        except Exception as e:
            logger.warning(f"Memory retrieval failed | error={e}")
            return ""

    async def get_all_memories(self, user_id: str, db: AsyncSession) -> list[dict]:
        """Gibt alle Memories eines Users zurück."""
        result = await db.execute(
            select(AIMemory)
            .where(AIMemory.user_id == user_id)
            .order_by(AIMemory.updated_at.desc())
        )
        memories = result.scalars().all()
        return [
            {
                "id": str(m.id),
                "fact": m.fact,
                "category": m.category,
                "created_at": m.created_at.isoformat(),
                "updated_at": m.updated_at.isoformat(),
            }
            for m in memories
        ]

    async def delete_memory(self, memory_id: str, user_id: str, db: AsyncSession):
        """Löscht eine spezifische Erinnerung."""
        await db.execute(
            delete(AIMemory).where(
                AIMemory.id == uuid.UUID(memory_id),
                AIMemory.user_id == uuid.UUID(user_id),
            )
        )
        await db.flush()

    async def clear_all_memories(self, user_id: str, db: AsyncSession):
        """Löscht alle Erinnerungen eines Users."""
        await db.execute(delete(AIMemory).where(AIMemory.user_id == uuid.UUID(user_id)))
        await db.flush()
