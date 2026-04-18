"""Autonomer Hintergrundmonitor — erkennt Nutzer-Probleme und passt Pläne autonom an."""

import json
import httpx
from datetime import datetime, timedelta, timezone
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import redis.asyncio as aioredis
from app.core.config import settings
from app.core.database import async_session
from app.models.user import User
from app.models.conversation import Conversation
from app.services.coach_prompts import get_detection_prompt
from app.core.redis import get_redis


# Mindest-Abstand zwischen zwei autonomen Aktionen pro User
COOLDOWN_HOURS = 6
COOLDOWN_KEY_PREFIX = "autonomous_monitor_last_action:"


def _get_redis() -> aioredis.Redis:
    """Shared Redis-Verbindung."""
    return get_redis()


async def _is_in_cooldown(user_id: str) -> bool:
    """Prüft ob User in Cooldown-Phase ist (letzte Aktion < COOLDOWN_HOURS ago)."""
    try:
        r = _get_redis()
        key = f"{COOLDOWN_KEY_PREFIX}{user_id}"
        exists = await r.exists(key)
        return bool(exists)
    except Exception:
        return False  # Bei Redis-Fehler: kein Cooldown (fail open)


async def _set_cooldown(user_id: str):
    """Setzt Cooldown für User (COOLDOWN_HOURS Stunden)."""
    try:
        r = _get_redis()
        key = f"{COOLDOWN_KEY_PREFIX}{user_id}"
        await r.setex(key, COOLDOWN_HOURS * 3600, "1")
    except Exception:
        pass


async def _classify_conversation(messages: list[dict]) -> dict:
    """Nutzt LLM um zu klassifizieren ob Handlungsbedarf besteht."""
    if not settings.active_llm_api_key or not messages:
        return {"event": "normal", "confidence": "low", "detail": ""}

    # Nur User-Nachrichten der letzten 24h analysieren
    messages_text = "\n".join(
        [f"[{m['role'].upper()}]: {m['content'][:200]}" for m in messages[:10]]
    )

    try:
        headers = {
            "Authorization": f"Bearer {settings.active_llm_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": settings.llm_model,
            "messages": [
                {
                    "role": "user",
                    "content": get_detection_prompt(messages_text),
                }
            ],
            "max_tokens": 256,
            "temperature": 0.1,
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{settings.llm_base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            msg = data["choices"][0]["message"]
            text = (msg.get("content") or msg.get("reasoning") or "").strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            return json.loads(text)
    except Exception as e:
        logger.warning(f"Conversation classification failed | error={e}")
        return {"event": "normal", "confidence": "low", "detail": ""}


async def run_autonomous_monitor():
    """
    Hauptfunktion des Monitors — wird vom Scheduler aufgerufen.
    Läuft durch alle User, analysiert Gespräche, reagiert autonom.
    """
    logger.info("Autonomous monitor started")
    from app.services.langchain_agent import LangChainCoachAgent

    async with async_session() as db:
        try:
            result = await db.execute(
                select(User).where(
                    User.email.isnot(None),
                    User.email.contains("@"),
                )
            )
            users = result.scalars().all()

            processed = 0
            for user in users:
                try:
                    # Letzte 24h Gespräche laden
                    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
                    conv_result = await db.execute(
                        select(Conversation)
                        .where(
                            Conversation.user_id == user.id,
                            Conversation.created_at >= cutoff,
                        )
                        .order_by(Conversation.created_at.desc())
                        .limit(15)
                    )
                    convs = conv_result.scalars().all()

                    if not convs:
                        continue

                    # Cooldown prüfen — nicht mehr als 1x alle 6h handeln
                    if await _is_in_cooldown(str(user.id)):
                        continue

                    messages = [{"role": c.role, "content": c.content} for c in convs]
                    classification = await _classify_conversation(messages)

                    event = classification.get("event", "normal")
                    confidence = classification.get("confidence", "low")
                    detail = classification.get("detail", "")

                    # Nur bei hoher/mittlerer Konfidenz und echtem Event handeln
                    if event == "normal" or confidence == "low":
                        continue

                    logger.info(
                        f"Monitor detected event | user={user.id} | event={event} | confidence={confidence} | detail={detail}"
                    )

                    # Autonome Aufgabe für den Agent formulieren
                    agent = LangChainCoachAgent()

                    if event == "bad_feeling":
                        task = f"""Der Nutzer hat in den letzten 24h gemeldet dass es ihm nicht gut geht: "{detail}".
Lade seine aktuellen Metriken, setze heute und morgen als Ruhetage falls sinnvoll,
und speichere eine kurze Nachricht als Coach-Erinnerung im Chat."""

                    elif event == "skipped_training":
                        task = f"""Der Nutzer hat ein Training ausgelassen: "{detail}".
Lade seinen Trainingsplan, passe die verpasste Einheit an (z.B. verschieben oder leichter machen),
und stelle sicher dass das Wochenziel realistisch bleibt."""

                    elif event == "injury":
                        task = f"""Der Nutzer hat eine Verletzung gemeldet: "{detail}".
Setze alle Trainings der nächsten 3 Tage auf Ruhetag, lade die Metriken
und erstelle eine angepasste Empfehlung für sanfte Rehabilitation."""

                    else:
                        continue

                    action_result = await agent.run_autonomous(str(user.id), task, db)
                    logger.info(
                        f"Monitor action completed | user={user.id} | result={action_result[:100]}"
                    )

                    # Coach-Nachricht in Conversation speichern (sichtbar im Chat)
                    note = Conversation(
                        user_id=user.id,
                        role="assistant",
                        content=f"🤖 *Coach-Anpassung (automatisch)*: {action_result}",
                    )
                    db.add(note)
                    await db.flush()

                    # Cooldown setzen
                    await _set_cooldown(str(user.id))

                    processed += 1

                except Exception as e:
                    logger.warning(
                        f"Monitor failed for user | user={user.id} | error={e}"
                    )
                    continue

            await db.commit()
            logger.info(
                f"Autonomous monitor completed | processed={processed}/{len(users)}"
            )

        except Exception as e:
            logger.error(f"Autonomous monitor job failed | error={e}")
            await db.rollback()
