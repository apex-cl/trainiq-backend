"""Sleep Coach — tägliche Schlaftipps und Morgen-Feedback."""

import httpx
from datetime import datetime, date, timezone
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import async_session
from app.models.user import User
from app.models.conversation import Conversation
from app.models.metrics import HealthMetric


async def _call_llm(prompt: str) -> str:
    """Einfacher LLM-Aufruf ohne Streaming."""
    if not settings.active_llm_api_key:
        return ""
    headers = {
        "Authorization": f"Bearer {settings.active_llm_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.llm_model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 512,
        "temperature": 0.7,
    }
    async with httpx.AsyncClient(timeout=45.0) as client:
        response = await client.post(
            f"{settings.llm_base_url}/chat/completions",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
        msg = data["choices"][0]["message"]
        return (msg.get("content") or msg.get("reasoning") or "").strip()


async def send_evening_sleep_tips():
    """
    Scheduler-Job — läuft täglich um 22:00.
    Sendet jedem User einen personalisierten Schlaftipp + Schlafdauer-Empfehlung.
    """
    logger.info("Sleep tip job started")

    async with async_session() as db:
        try:
            result = await db.execute(select(User))
            users = result.scalars().all()
            sent = 0

            for user in users:
                try:
                    # Letzte Metriken laden für personalisierung
                    latest_result = await db.execute(
                        select(HealthMetric)
                        .where(HealthMetric.user_id == user.id)
                        .order_by(HealthMetric.recorded_at.desc())
                        .limit(3)
                    )
                    latest_metrics = latest_result.scalars().all()

                    # Kontext-Nachricht
                    sleep_hours = 0
                    if latest_metrics:
                        avg_sleep = sum(
                            m.sleep_duration_min or 0 for m in latest_metrics
                        ) / len(latest_metrics)
                        sleep_hours = round(avg_sleep / 60, 1)

                    # Personalisierte LLM-Empfehlung generieren
                    tip_prompt = f"""Du bist ein Schlafcoach für Ausdauersportler. Schreibe EINEN kurzen, konkreten Schlaftipp für heute Abend.

Nutzer-Kontext:
- Durchschnittlicher Schlaf letzte Tage: {f"{sleep_hours}h" if latest_metrics else "unbekannt"}
- Aktueller Wochentag: {__import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%A")}

Regeln:
- 2-3 Sätze maximal
- Konkret und actionable (nicht "schlaf mehr")
- Wissenschaftlich fundiert
- Auf Deutsch
- KEIN Markdown-Bold, normaler Text

Schreibe nur den Tipp, keine Einleitung."""

                    tip = await _call_llm(tip_prompt)
                    if not tip:
                        tip = "Versuche heute 30 Minuten vor dem Schlafen alle Bildschirme auszuschalten und stattdessen ein Buch zu lesen. Das reduziert Cortisol und verbessert deine Einschlafzeit."

                    if latest_metrics:
                        if sleep_hours < 6:
                            context = f"⚠️ Dein Schlaf-Durchschnitt: nur {sleep_hours}h — Ziel sind 7-9h für optimale Regeneration."
                        elif sleep_hours >= 7.5:
                            context = f"✅ Dein Schlaf-Durchschnitt: {sleep_hours}h — weiter so!"
                        else:
                            context = f"📈 Dein Schlaf-Durchschnitt: {sleep_hours}h — noch etwas Potenzial nach oben."
                    else:
                        context = ""

                    message = f"🌙 **Schlaftipp für heute Nacht**\n\n{tip}"
                    if context:
                        message += f"\n\n📊 {context}"
                    message += (
                        "\n\n*Morgen früh gebe ich dir Feedback zu deiner Erholung.*"
                    )

                    conv = Conversation(
                        user_id=user.id, role="assistant", content=message
                    )
                    db.add(conv)
                    await db.flush()
                    sent += 1

                except Exception as e:
                    logger.warning(f"Sleep tip failed | user={user.id} | error={e}")
                    continue

            await db.commit()
            logger.info(f"Sleep tip job completed | sent={sent}/{len(users)}")

        except Exception as e:
            logger.error(f"Sleep tip job failed | error={e}")
            await db.rollback()


async def send_morning_health_feedback():
    """
    Scheduler-Job — läuft täglich um 07:00.
    Analysiert die Schlafmetriken der letzten Nacht und gibt personalisierten Morgen-Report.
    """
    logger.info("Morning feedback job started")

    async with async_session() as db:
        try:
            result = await db.execute(select(User))
            users = result.scalars().all()
            sent = 0

            for user in users:
                try:
                    # Heutige + gestrige Metriken
                    latest_result = await db.execute(
                        select(HealthMetric)
                        .where(HealthMetric.user_id == user.id)
                        .order_by(HealthMetric.recorded_at.desc())
                        .limit(7)
                    )
                    metrics = latest_result.scalars().all()

                    if not metrics:
                        # Kein Daten → generische Motivationsnachricht
                        message = (
                            "☀️ **Guten Morgen!**\n\n"
                            "Vergiss nicht, deine Gesundheitsdaten in der App zu tracken, "
                            "damit ich dir personalisierte Empfehlungen geben kann.\n\n"
                            "*Wie fühlst du dich heute?*"
                        )
                    else:
                        latest = metrics[0]
                        sleep_h = round((latest.sleep_duration_min or 0) / 60, 1)
                        hrv = latest.hrv or 0
                        rhr = latest.resting_hr or 0

                        from app.services.recovery_scorer import RecoveryScorer

                        scorer = RecoveryScorer()
                        baseline_data = [
                            {
                                "hrv": m.hrv,
                                "sleep_duration_min": m.sleep_duration_min,
                                "stress_score": m.stress_score,
                                "resting_hr": m.resting_hr,
                            }
                            for m in metrics
                        ]
                        baseline = RecoveryScorer.compute_baseline(baseline_data)
                        recovery = scorer.calculate_recovery_score(
                            {
                                "hrv": latest.hrv,
                                "sleep_duration_min": latest.sleep_duration_min,
                                "stress_score": latest.stress_score,
                                "resting_hr": latest.resting_hr,
                            },
                            user_baseline=baseline,
                        )
                        score = recovery["score"]
                        label = recovery["label"]

                        # LLM-Feedback generieren
                        prompt = f"""Schreibe eine kurze, motivierende Morgen-Gesundheitsnachricht für einen Ausdauersportler.

Heutige Metriken:
- Schlaf: {sleep_h}h
- HRV: {hrv}ms
- Ruhepuls: {rhr} bpm
- Recovery Score: {score}/100 ({label})

Regeln:
- Max 4 Sätze
- Konkrete Zahlen nennen
- Trainingsempfehlung für heute basierend auf Recovery Score
- Emoji am Anfang
- Auf Deutsch
- Frage am Ende: "Wie fühlst du dich heute?"

Schreibe NUR die Nachricht, keine Erklärung."""

                        try:
                            feedback_text = await _call_llm(prompt)
                        except Exception:
                            # Fallback
                            emoji = (
                                "🟢" if score >= 70 else ("🟡" if score >= 40 else "🔴")
                            )
                            feedback_text = (
                                f"{emoji} **Recovery Score: {score}/100 ({label})**\n\n"
                                f"Schlaf: {sleep_h}h | HRV: {hrv}ms | Ruhepuls: {rhr}bpm\n\n"
                                f"{'Heute ist ein guter Tag für intensives Training.' if score >= 70 else 'Heute lieber locker oder pausieren.'}\n\n"
                                f"*Wie fühlst du dich heute?*"
                            )

                        message = f"☀️ **Guten Morgen — dein Gesundheits-Check**\n\n{feedback_text}"

                    conv = Conversation(
                        user_id=user.id, role="assistant", content=message
                    )
                    db.add(conv)
                    await db.flush()
                    sent += 1

                except Exception as e:
                    logger.warning(
                        f"Morning feedback failed | user={user.id} | error={e}"
                    )
                    continue

            await db.commit()
            logger.info(f"Morning feedback job completed | sent={sent}/{len(users)}")

        except Exception as e:
            logger.error(f"Morning feedback job failed | error={e}")
            await db.rollback()
