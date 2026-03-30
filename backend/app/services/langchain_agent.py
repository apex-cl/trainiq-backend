"""LangChain-basierter Coach Agent mit autonomen Tool-Aufrufen."""

import json
from datetime import date, timedelta, datetime, timezone
from typing import AsyncGenerator
from loguru import logger

from langchain_openai import ChatOpenAI
from langchain.agents import AgentExecutor, create_openai_tools_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, AIMessage
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, func

from app.core.config import settings
from app.models.conversation import Conversation
from app.models.training import TrainingPlan, UserGoal
from app.models.metrics import HealthMetric, DailyWellbeing
from app.models.nutrition import NutritionLog
from app.services.recovery_scorer import RecoveryScorer
from app.services.training_planner import TrainingPlanner
from app.services.ai_memory import AIMemoryService
from app.services.coach_prompts import (
    get_base_system_prompt,
    get_autonomous_system_prompt,
)


def _tool_status_message(tool_name: str) -> str:
    """Gibt eine lesbare Status-Nachricht für Tool-Aufrufe zurück."""
    STATUS_MAP = {
        "get_user_metrics": "📊 *Lade deine Gesundheitsmetriken...*\n\n",
        "get_training_plan": "🏃 *Lade deinen Trainingsplan...*\n\n",
        "set_rest_day": "😴 *Setze Ruhetag...*\n\n",
        "update_training_day": "✏️ *Passe Training an...*\n\n",
        "generate_new_week_plan": "📅 *Erstelle neuen Wochenplan...*\n\n",
        "get_nutrition_summary": "🥗 *Lade Ernährungsdaten...*\n\n",
        "create_weekly_meal_plan": "🍳 *Erstelle Wochenspeiseplan mit Rezepten...*\n\n",
        "get_user_goals": "🎯 *Lade deine Ziele...*\n\n",
        "get_daily_wellbeing": "💭 *Lade heutiges Befinden...*\n\n",
        "analyze_nutrition_gaps": "🔍 *Analysiere Nährstofflücken...*\n\n",
    }
    return STATUS_MAP.get(tool_name, "")


def _create_llm(streaming: bool = True) -> ChatOpenAI:
    """Erstellt ChatOpenAI-Instanz für unseren OpenAI-kompatiblen LLM-Provider."""
    return ChatOpenAI(
        model=settings.llm_model,
        api_key=settings.active_llm_api_key,
        base_url=settings.llm_base_url,
        streaming=streaming,
        temperature=0.7,
        max_tokens=2048,
    )


def _create_tools(user_id: str, db: AsyncSession) -> list:
    """
    Erstellt alle Agent-Tools mit injizierter DB-Session via Closure.
    WICHTIG: Tools sind async, da wir SQLAlchemy async nutzen.
    """

    @tool
    async def get_user_metrics() -> str:
        """Lädt Gesundheitsmetriken der letzten 7 Tage: HRV, Ruhepuls, Schlaf, Stress + Recovery Score. IMMER aufrufen wenn Gesundheitsdaten benötigt werden."""
        seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
        result = await db.execute(
            select(HealthMetric)
            .where(
                HealthMetric.user_id == user_id,
                HealthMetric.recorded_at >= seven_days_ago,
            )
            .order_by(HealthMetric.recorded_at.desc())
            .limit(14)
        )
        metrics = result.scalars().all()
        if not metrics:
            return "Keine Metriken vorhanden."
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
        latest = metrics[0]
        recovery = scorer.calculate_recovery_score(
            {
                "hrv": latest.hrv,
                "sleep_duration_min": latest.sleep_duration_min,
                "stress_score": latest.stress_score,
                "resting_hr": latest.resting_hr,
            },
            user_baseline=baseline,
        )
        data = {
            "recovery_score": recovery["score"],
            "recovery_label": recovery["label"],
            "metriken": [
                {
                    "datum": m.recorded_at.date().isoformat(),
                    "hrv_ms": m.hrv,
                    "ruhepuls": m.resting_hr,
                    "schlaf_min": m.sleep_duration_min,
                    "stress": m.stress_score,
                }
                for m in metrics
            ],
        }
        return json.dumps(data, ensure_ascii=False)

    @tool
    async def get_training_plan() -> str:
        """Lädt den Wochentrainingsplan (aktuelle Woche). Aufrufen bei Fragen zum Training."""
        today = date.today()
        week_start = today - timedelta(days=today.weekday())
        result = await db.execute(
            select(TrainingPlan)
            .where(
                TrainingPlan.user_id == user_id,
                TrainingPlan.date >= week_start,
                TrainingPlan.date < week_start + timedelta(days=7),
            )
            .order_by(TrainingPlan.date)
        )
        plans = result.scalars().all()
        if not plans:
            return "Kein Trainingsplan für diese Woche vorhanden."
        return json.dumps(
            [
                {
                    "datum": p.date.isoformat(),
                    "typ": p.workout_type,
                    "dauer_min": p.duration_min,
                    "zone": p.intensity_zone,
                    "status": p.status,
                    "beschreibung": p.description,
                }
                for p in plans
            ],
            ensure_ascii=False,
        )

    @tool
    async def set_rest_day(datum: str, grund: str) -> str:
        """Setzt einen Ruhetag im Trainingsplan. datum: ISO-Format 'YYYY-MM-DD'. grund: kurze Begründung."""
        try:
            plan_date = date.fromisoformat(datum)
            result = await db.execute(
                select(TrainingPlan).where(
                    TrainingPlan.user_id == user_id, TrainingPlan.date == plan_date
                )
            )
            plan = result.scalars().first()
            if not plan:
                return f"Kein Plan für {datum} gefunden."
            plan.workout_type = "rest"
            plan.duration_min = 0
            plan.intensity_zone = 1
            plan.target_hr_min = 0
            plan.target_hr_max = 0
            plan.description = f"Ruhetag — {grund}"
            plan.coach_reasoning = grund
            await db.flush()
            return f"✓ Ruhetag gesetzt für {datum}: {grund}"
        except Exception as e:
            return f"Fehler: {e}"

    @tool
    async def update_training_day(
        datum: str, workout_type: str, dauer_min: int, zone: int, beschreibung: str
    ) -> str:
        """Aktualisiert eine Trainingseinheit. workout_type: easy_run/tempo_run/interval/long_run/rest/cross_training/swim/bike. zone: 1-5."""
        try:
            plan_date = date.fromisoformat(datum)
            result = await db.execute(
                select(TrainingPlan).where(
                    TrainingPlan.user_id == user_id, TrainingPlan.date == plan_date
                )
            )
            plan = result.scalars().first()
            if not plan:
                return f"Kein Plan für {datum} gefunden."
            plan.workout_type = workout_type
            plan.duration_min = dauer_min
            plan.intensity_zone = zone
            plan.description = beschreibung
            await db.flush()
            return f"✓ Training aktualisiert: {datum} → {workout_type} ({dauer_min}min, Zone {zone})"
        except Exception as e:
            return f"Fehler: {e}"

    @tool
    async def generate_new_week_plan() -> str:
        """Generiert einen komplett neuen KI-Wochentrainingsplan basierend auf User-Zielen und Recovery. Nutze dies wenn der Plan komplett neu erstellt werden soll."""
        try:
            today = date.today()
            week_start = today - timedelta(days=today.weekday())
            planner = TrainingPlanner()
            plans = await planner.generate_week_plan(user_id, week_start, db)
            await db.flush()
            return (
                f"✓ Neuer Wochenplan erstellt: {len(plans)} Einheiten ab {week_start}"
            )
        except Exception as e:
            return f"Fehler: {e}"

    @tool
    async def get_nutrition_summary() -> str:
        """Lädt Ernährungsdaten der letzten 7 Tage (Kalorien, Protein, KH, Fett). Aufrufen bei Ernährungsfragen."""
        seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
        result = await db.execute(
            select(NutritionLog)
            .where(
                NutritionLog.user_id == user_id,
                NutritionLog.logged_at >= seven_days_ago,
            )
            .order_by(NutritionLog.logged_at.desc())
        )
        logs = result.scalars().all()
        if not logs:
            return "Keine Ernährungsdaten vorhanden."
        days = 7
        total_cal = sum(n.calories or 0 for n in logs)
        total_protein = sum(n.protein_g or 0 for n in logs)
        total_carbs = sum(n.carbs_g or 0 for n in logs)
        total_fat = sum(n.fat_g or 0 for n in logs)
        return json.dumps(
            {
                "zeitraum": "letzte 7 Tage",
                "mahlzeiten_gesamt": len(logs),
                "durchschnitt_täglich": {
                    "kalorien": round(total_cal / days),
                    "protein_g": round(total_protein / days, 1),
                    "kohlenhydrate_g": round(total_carbs / days, 1),
                    "fett_g": round(total_fat / days, 1),
                },
            },
            ensure_ascii=False,
        )

    @tool
    async def create_weekly_meal_plan(kalorien_ziel: int, protein_ziel_g: int) -> str:
        """Erstellt einen vollständigen 7-Tage Speiseplan mit Rezepten, angepasst an die Trainingsbelastung der Woche. kalorien_ziel: tägliches Kalorienziel. protein_ziel_g: tägliches Proteinziel in Gramm."""
        from app.services.meal_planner import MealPlanner

        # Trainingsplan der aktuellen Woche laden für Kontext
        today = date.today()
        week_start = today - timedelta(days=today.weekday())
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

        training_context = ""
        if plans:
            total_min = sum(p.duration_min or 0 for p in plans)
            high_intensity = [p for p in plans if (p.intensity_zone or 0) >= 4]
            training_context = (
                f"- Gesamtvolumen: {total_min} Minuten diese Woche\n"
                f"- Harte Einheiten (Zone 4-5): {len(high_intensity)}\n"
                f"- Details: "
                + ", ".join(
                    [
                        f"{p.date.strftime('%a')} {p.workout_type}({p.duration_min}min Z{p.intensity_zone})"
                        for p in plans
                    ]
                )
            )

        planner = MealPlanner()
        return await planner.generate_weekly_plan(
            user_id, kalorien_ziel, protein_ziel_g, training_context
        )

    @tool
    async def get_user_goals() -> str:
        """Lädt Sportziele und Fitnesslevel des Nutzers."""
        result = await db.execute(select(UserGoal).where(UserGoal.user_id == user_id))
        goals = result.scalars().all()
        if not goals:
            return "Keine Ziele gesetzt."
        g = goals[0]
        return json.dumps(
            {
                "sport": g.sport,
                "ziel": g.goal_description,
                "level": g.fitness_level,
                "wochenstunden": g.weekly_hours,
            },
            ensure_ascii=False,
        )

    @tool
    async def get_daily_wellbeing() -> str:
        """Lädt das heutige Befinden des Nutzers (Müdigkeit 1-10, Stimmung 1-10, Schmerzen)."""
        result = await db.execute(
            select(DailyWellbeing).where(
                DailyWellbeing.user_id == user_id, DailyWellbeing.date == date.today()
            )
        )
        wb = result.scalars().first()
        if not wb:
            return "Kein Befinden für heute eingetragen."
        return json.dumps(
            {
                "datum": date.today().isoformat(),
                "müdigkeit": wb.fatigue_score,
                "stimmung": wb.mood_score,
                "schmerzen": wb.pain_notes or "keine",
            },
            ensure_ascii=False,
        )

    @tool
    async def analyze_nutrition_gaps(
        kalorien_ziel: int = 2200, protein_ziel_g: int = 150
    ) -> str:
        """Analysiert Nährstoffmängel basierend auf den letzten 7 Tagen und gibt konkrete Lebensmittelempfehlungen."""
        from app.services.meal_planner import MealPlanner

        seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
        result = await db.execute(
            select(NutritionLog).where(
                NutritionLog.user_id == user_id,
                NutritionLog.logged_at >= seven_days_ago,
            )
        )
        logs = result.scalars().all()
        avg_cal = sum(n.calories or 0 for n in logs) / 7 if logs else 0
        avg_protein = sum(n.protein_g or 0 for n in logs) / 7 if logs else 0
        avg_carbs = sum(n.carbs_g or 0 for n in logs) / 7 if logs else 0
        avg_fat = sum(n.fat_g or 0 for n in logs) / 7 if logs else 0
        planner = MealPlanner()
        return await planner.analyze_nutrient_gaps(
            avg_cal, avg_protein, avg_carbs, avg_fat, kalorien_ziel, protein_ziel_g
        )

    return [
        get_user_metrics,
        get_training_plan,
        set_rest_day,
        update_training_day,
        generate_new_week_plan,
        get_nutrition_summary,
        create_weekly_meal_plan,
        get_user_goals,
        get_daily_wellbeing,
        analyze_nutrition_gaps,
    ]


class LangChainCoachAgent:
    """LangChain Agent mit Streaming-Support und autonomen Tool-Aufrufen."""

    def __init__(self):
        self.memory_service = AIMemoryService()

    def _build_executor(
        self, user_id: str, db: AsyncSession, streaming: bool = True
    ) -> AgentExecutor:
        llm = _create_llm(streaming=streaming)
        tools = _create_tools(user_id, db)
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", get_base_system_prompt()),
                MessagesPlaceholder("chat_history"),
                ("human", "{input}"),
                MessagesPlaceholder("agent_scratchpad"),
            ]
        )
        agent = create_openai_tools_agent(llm, tools, prompt)
        return AgentExecutor(
            agent=agent,
            tools=tools,
            verbose=False,
            max_iterations=6,
            return_intermediate_steps=False,
        )

    async def stream(
        self, message: str, user_id: str, db: AsyncSession
    ) -> AsyncGenerator[str, None]:
        """Streaming-Chat via LangChain Agent (SSE-Format: 'data: text\\n\\n')."""
        if not settings.active_llm_api_key:
            yield "data: Coach nicht verfügbar — LLM_API_KEY fehlt.\n\n"
            yield "data: [DONE]\n\n"
            return

        # Chat-Verlauf laden (letzte 20 Nachrichten)
        history_result = await db.execute(
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.created_at.desc())
            .limit(20)
        )
        history = list(reversed(history_result.scalars().all()))

        # User-Nachricht speichern
        user_conv = Conversation(user_id=user_id, role="user", content=message)
        db.add(user_conv)
        await db.flush()

        # Chat-History für LangChain
        chat_history = []
        for conv in history:
            if conv.role == "user":
                chat_history.append(HumanMessage(content=conv.content))
            else:
                chat_history.append(AIMessage(content=conv.content))

        full_response = ""
        tool_call_active = False  # Flag: Aktuell läuft ein Tool-Call

        try:
            executor = self._build_executor(user_id, db, streaming=True)
            async for event in executor.astream_events(
                {"input": message, "chat_history": chat_history},
                version="v1",
            ):
                event_name = event.get("event", "")

                # Tool-Call Start: Streaming pausieren
                if event_name == "on_tool_start":
                    tool_call_active = True
                    tool_name = event.get("name", "tool")
                    # Kurze Status-Info an User (einmalig, kein Stream-Chunk)
                    status_msg = _tool_status_message(tool_name)
                    if status_msg:
                        full_response += status_msg
                        yield f"data: {status_msg}\n\n"
                    continue

                # Tool-Call Ende: Streaming wieder freigeben
                if event_name == "on_tool_end":
                    tool_call_active = False
                    continue

                # Nur finale LLM-Antwort streamen (nicht während Tool-Calls)
                if event_name == "on_chat_model_stream" and not tool_call_active:
                    chunk = event.get("data", {}).get("chunk")
                    if chunk and hasattr(chunk, "content") and chunk.content:
                        text = chunk.content
                        # Reasoning/Thinking ignorieren (falls als Chunk-Attribut)
                        if hasattr(chunk, "additional_kwargs"):
                            reasoning = chunk.additional_kwargs.get("reasoning", "")
                            if reasoning and not text:
                                continue
                        full_response += text
                        # Newlines in SSE escapen
                        safe = text.replace("\n", "\ndata: ")
                        yield f"data: {safe}\n\n"

        except Exception as e:
            logger.error(f"LangChain stream failed | user={user_id} | error={e}")
            # Fallback auf CoachAgent
            from app.services.coach_agent import CoachAgent

            fallback = CoachAgent()
            async for chunk in fallback.stream(message, user_id, db):
                yield chunk
            return

        # Antwort + Memory speichern
        if full_response:
            db.add(
                Conversation(user_id=user_id, role="assistant", content=full_response)
            )
            await db.flush()
            await self.memory_service.extract_and_store(
                message, user_id, db, conversation_id=str(user_conv.id)
            )

        # Alte Conversations aufräumen (max 500)
        count_result = await db.execute(
            select(func.count(Conversation.id)).where(Conversation.user_id == user_id)
        )
        total = count_result.scalar() or 0
        if total > 500:
            oldest = await db.execute(
                select(Conversation.id)
                .where(Conversation.user_id == user_id)
                .order_by(Conversation.created_at.asc())
                .limit(total - 500)
            )
            old_ids = [r[0] for r in oldest.all()]
            if old_ids:
                await db.execute(
                    delete(Conversation).where(Conversation.id.in_(old_ids))
                )
                await db.flush()

        yield "data: [DONE]\n\n"

    async def run_autonomous(self, user_id: str, task: str, db: AsyncSession) -> str:
        """
        Führt den Agent autonom aus (kein Streaming) — für Hintergrund-Jobs.
        Gibt die finale Agent-Ausgabe zurück.
        """
        if not settings.active_llm_api_key:
            return "LLM nicht konfiguriert"
        try:
            llm = _create_llm(streaming=False)
            tools = _create_tools(user_id, db)
            prompt = ChatPromptTemplate.from_messages(
                [
                    ("system", get_autonomous_system_prompt()),
                    ("human", "{input}"),
                    MessagesPlaceholder("agent_scratchpad"),
                ]
            )
            agent = create_openai_tools_agent(llm, tools, prompt)
            executor = AgentExecutor(
                agent=agent, tools=tools, verbose=True, max_iterations=8
            )
            result = await executor.ainvoke({"input": task, "chat_history": []})
            return result.get("output", "Fertig")
        except Exception as e:
            logger.error(f"Autonomous run failed | user={user_id} | error={e}")
            return f"Fehler: {e}"
