import re
import json
import httpx
from datetime import date, timedelta, datetime, timezone
from typing import AsyncGenerator
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, func
from app.core.config import settings
from app.models.conversation import Conversation
from app.models.metrics import HealthMetric, DailyWellbeing
from app.models.training import TrainingPlan, UserGoal
from app.models.nutrition import NutritionLog
from app.services.recovery_scorer import RecoveryScorer
from app.services.ai_memory import AIMemoryService
from app.services.coach_prompts import get_base_system_prompt


class CoachAgent:
    """AI Coach agent powered by NVIDIA NIM."""

    def __init__(self):
        self.memory_service = AIMemoryService()
        self.llm_configured = bool(settings.active_llm_api_key)
        self.llm_headers = {
            "Authorization": f"Bearer {settings.active_llm_api_key}",
            "Content-Type": "application/json",
        }

    async def build_context(
        self, user_id: str, db: AsyncSession, query: str | None = None
    ) -> str:
        """Lädt und formatiert den Kontext für den Coach."""
        today = date.today()
        week_start = today - timedelta(days=today.weekday())

        # Letzte 7 Tage Metriken
        seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
        metrics_result = await db.execute(
            select(HealthMetric)
            .where(
                HealthMetric.user_id == user_id,
                HealthMetric.recorded_at >= seven_days_ago,
            )
            .order_by(HealthMetric.recorded_at.desc())
            .limit(14)
        )
        metrics = metrics_result.scalars().all()

        metrics_text = ""
        if metrics:
            for m in metrics:
                metrics_text += f"  {m.recorded_at.date()}: HRV={m.hrv}ms, Ruhe-HR={m.resting_hr}, Schlaf={m.sleep_duration_min}min, Stress={m.stress_score}\n"
        else:
            metrics_text = "  Keine Metriken verfügbar\n"

        # Recovery Score
        latest_metric = metrics[0] if metrics else None
        recovery_data = {"score": 0, "label": "KEINE DATEN"}
        if latest_metric:
            scorer = RecoveryScorer()
            metrics_data = [
                {
                    "hrv": m.hrv,
                    "sleep_duration_min": m.sleep_duration_min,
                    "stress_score": m.stress_score,
                    "resting_hr": m.resting_hr,
                }
                for m in metrics
            ]
            user_baseline = RecoveryScorer.compute_baseline(metrics_data)
            metric_dict = {
                "hrv": latest_metric.hrv,
                "sleep_duration_min": latest_metric.sleep_duration_min,
                "stress_score": latest_metric.stress_score,
                "resting_hr": latest_metric.resting_hr,
            }
            recovery_data = scorer.calculate_recovery_score(
                metric_dict, user_baseline=user_baseline
            )

        # Aktueller Wochenplan
        plan_result = await db.execute(
            select(TrainingPlan)
            .where(
                TrainingPlan.user_id == user_id,
                TrainingPlan.date >= week_start,
                TrainingPlan.date < week_start + timedelta(days=7),
            )
            .order_by(TrainingPlan.date)
        )
        plans = plan_result.scalars().all()

        plan_text = ""
        if plans:
            for p in plans:
                plan_text += f"  {p.date}: {p.workout_type} ({p.duration_min}min, Zone {p.intensity_zone}) - {p.status}\n"
        else:
            plan_text = "  Kein Plan für diese Woche\n"

        # Ernährung der letzten 48h
        two_days_ago = datetime.now(timezone.utc) - timedelta(hours=48)
        nutrition_result = await db.execute(
            select(NutritionLog)
            .where(
                NutritionLog.user_id == user_id,
                NutritionLog.logged_at >= two_days_ago,
            )
            .order_by(NutritionLog.logged_at.desc())
        )
        nutrition_logs = nutrition_result.scalars().all()

        total_cal = sum(n.calories or 0 for n in nutrition_logs)
        total_protein = sum(n.protein_g or 0 for n in nutrition_logs)
        total_carbs = sum(n.carbs_g or 0 for n in nutrition_logs)
        nutrition_text = f"  Letzte 48h: {round(total_cal)} kcal, {round(total_protein)}g Protein, {round(total_carbs)}g Carbs ({len(nutrition_logs)} Mahlzeiten)"

        # Befinden heute
        wellbeing_result = await db.execute(
            select(DailyWellbeing).where(
                DailyWellbeing.user_id == user_id,
                DailyWellbeing.date == today,
            )
        )
        wellbeing = wellbeing_result.scalars().first()
        wellbeing_text = "  Nicht eingetragen"
        if wellbeing:
            wellbeing_text = f"  Müdigkeit: {wellbeing.fatigue_score}/10, Stimmung: {wellbeing.mood_score}/10"
            if wellbeing.pain_notes:
                wellbeing_text += f", Schmerzen: {wellbeing.pain_notes}"

        # User-Ziele
        goals_result = await db.execute(
            select(UserGoal).where(UserGoal.user_id == user_id)
        )
        goals = goals_result.scalars().all()
        goals_text = "  Keine Ziele gesetzt"
        if goals:
            for g in goals:
                goals_text = f"  Sport: {g.sport}, Ziel: {g.goal_description}, Level: {g.fitness_level}, Wochenstunden: {g.weekly_hours}"

        # Langzeit-Erinnerungen (RAG)
        memories_text = ""
        if query:
            memories_text = await self.memory_service.retrieve_relevant(
                query, user_id, db
            )
        if memories_text:
            memories_text = f"\n{memories_text}\n"

        now = datetime.now(timezone.utc)
        weekday_de = [
            "Montag",
            "Dienstag",
            "Mittwoch",
            "Donnerstag",
            "Freitag",
            "Samstag",
            "Sonntag",
        ]

        context = f"""KONTEXT DES USERS:
Aktuell: {weekday_de[now.weekday()]}, {now.strftime("%H:%M")} UTC

Recovery Score: {recovery_data["score"]}/100 ({recovery_data["label"]})

Metriken (7 Tage):
{metrics_text}

Trainingsplan (aktuelle Woche):
{plan_text}

Ernährung:
{nutrition_text}

Befinden heute:
{wellbeing_text}

Ziele:
{goals_text}
{memories_text}"""
        return context

    async def stream(
        self, message: str, user_id: str, db: AsyncSession
    ) -> AsyncGenerator[str, None]:
        """Streaming Response für Chat."""
        logger.info(f"Coach stream started | user={user_id} | msg_len={len(message)}")

        if not self.llm_configured:
            logger.warning("Coach stream aborted | no LLM configured")
            yield "data: Coach nicht verfügbar — bitte NVIDIA_API_KEY in .env eintragen.\n\n"
            yield "data: [DONE]\n\n"
            return

        # Kontext laden
        context = await self.build_context(user_id, db, query=message)

        # Chat-Verlauf laden (letzte 20 Nachrichten)
        history_result = await db.execute(
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.created_at.desc())
            .limit(20)
        )
        history = list(reversed(history_result.scalars().all()))

        # User-Nachricht speichern
        user_conv = Conversation(
            user_id=user_id,
            role="user",
            content=message,
        )
        db.add(user_conv)
        await db.flush()

        full_message = f"{context}\n\nUser-Frage: {message}"

        full_response = ""
        try:
            async for text in self._llm_chunks(history, full_message):
                full_response += text
                yield f"data: {text}\n\n"
        except Exception as e:
            logger.error(f"Coach stream failed | user={user_id} | error={e}")
            yield "data: Ein interner Fehler ist aufgetreten. Bitte versuche es erneut.\n\n"
            yield "data: [DONE]\n\n"
            return

        # Antwort speichern
        assistant_conv = Conversation(
            user_id=user_id,
            role="assistant",
            content=full_response,
        )
        db.add(assistant_conv)
        await db.flush()

        # Langzeit-Memory extrahieren
        await self.memory_service.extract_and_store(
            message, user_id, db, conversation_id=str(user_conv.id)
        )

        # Action parsen und ausführen
        action = self.parse_action(full_response)
        if action:
            await self.execute_action(action, user_id, db)

        yield "data: [DONE]\n\n"

        # Alte Conversations aufräumen (max 500 pro User)
        count_result = await db.execute(
            select(func.count(Conversation.id)).where(Conversation.user_id == user_id)
        )
        total_count = count_result.scalar() or 0
        if total_count > 500:
            oldest_result = await db.execute(
                select(Conversation.id)
                .where(Conversation.user_id == user_id)
                .order_by(Conversation.created_at.asc())
                .limit(total_count - 500)
            )
            old_ids = [row[0] for row in oldest_result.all()]
            if old_ids:
                await db.execute(
                    delete(Conversation).where(Conversation.id.in_(old_ids))
                )
                await db.flush()

    async def _llm_chunks(
        self, history: list, full_message: str
    ) -> AsyncGenerator[str, None]:
        """Yields raw text chunks via LLM API (OpenAI-compatible streaming)."""
        messages = [{"role": "system", "content": get_base_system_prompt()}]
        for conv in history:
            role = conv.role if conv.role in ("user", "assistant") else "assistant"
            messages.append({"role": role, "content": conv.content})
        messages.append({"role": "user", "content": full_message})

        payload = {
            "model": settings.llm_model,
            "messages": messages,
            "stream": True,
            "max_tokens": 1024,
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream(
                "POST",
                f"{settings.llm_base_url}/chat/completions",
                headers=self.llm_headers,
                json=payload,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        delta = chunk["choices"][0].get("delta", {})

                        content = delta.get("content", "")
                        # reasoning/thinking tokens werden bewusst ignoriert — nur finaler Content wird gestreamt
                        if content:
                            yield content
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue

    def parse_action(self, response_text: str) -> dict | None:
        """Prüft ob Antwort eine JSON-Action enthält."""
        pattern = r'\{[^{}]*"action"\s*:\s*"[^"]+"[^{}]*\}'
        matches = re.findall(pattern, response_text)
        if matches:
            try:
                return json.loads(matches[-1])
            except json.JSONDecodeError:
                return None
        return None

    async def execute_action(self, action: dict, user_id: str, db: AsyncSession):
        """Führt Coach-Actions aus."""
        action_type = action.get("action")

        if action_type == "update_plan":
            try:
                plan_date = date.fromisoformat(action.get("date", ""))
            except ValueError:
                logger.warning(f"Invalid date in update_plan action: {action}")
                return
            changes = action.get("changes", {})
            result = await db.execute(
                select(TrainingPlan).where(
                    TrainingPlan.user_id == user_id,
                    TrainingPlan.date == plan_date,
                )
            )
            plan = result.scalars().first()
            if plan:
                for key, value in changes.items():
                    if hasattr(plan, key):
                        setattr(plan, key, value)
                await db.flush()

        elif action_type == "set_rest_day":
            try:
                plan_date = date.fromisoformat(action.get("date", ""))
            except ValueError:
                logger.warning(f"Invalid date in set_rest_day action: {action}")
                return
            result = await db.execute(
                select(TrainingPlan).where(
                    TrainingPlan.user_id == user_id,
                    TrainingPlan.date == plan_date,
                )
            )
            plan = result.scalars().first()
            if plan:
                plan.workout_type = "rest"
                plan.duration_min = 0
                plan.intensity_zone = 1
                plan.target_hr_min = 0
                plan.target_hr_max = 0
                plan.description = "Ruhetag (Coach-Empfehlung)"
                await db.flush()

        elif action_type == "log_goal":
            goal_text = action.get("goal", "")
            if goal_text:
                goal = UserGoal(
                    user_id=user_id,
                    sport="Allgemein",
                    goal_description=goal_text,
                )
                db.add(goal)
                await db.flush()

    async def get_history(self, user_id: str, db: AsyncSession) -> list[dict]:
        """Letzte 50 Conversations laden."""
        result = await db.execute(
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.created_at.desc())
            .limit(50)
        )
        conversations = list(reversed(result.scalars().all()))
        return [
            {
                "role": c.role,
                "content": c.content,
                "created_at": c.created_at.isoformat(),
            }
            for c in conversations
        ]

    async def clear_history(self, user_id: str, db: AsyncSession):
        """Alle Conversations löschen."""
        await db.execute(delete(Conversation).where(Conversation.user_id == user_id))
        await db.flush()
