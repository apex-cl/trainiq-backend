"""LangChain-basierter Coach Agent mit autonomen Tool-Aufrufen."""

import json
from datetime import date, timedelta, datetime, timezone
from typing import AsyncGenerator
from loguru import logger

from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage
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
    "get_vo2max_history": "📈 *Lade VO2max-Verlauf...*\n\n",
    "get_injury_history": "🩹 *Prüfe Verletzungshistorie...*\n\n",
    "get_sleep_trend": "🌙 *Analysiere Schlaftrend...*\n\n",
    "log_symptom": "📝 *Speichere Symptom...*\n\n",
    "calculate_training_zones": "⚙️ *Berechne Herzfrequenzzonen...*\n\n",
    "get_race_history": "🏅 *Lade Wettkampfhistorie...*\n\n",
}


def _tool_status_message(tool_name: str) -> str:
    """Gibt eine lesbare Status-Nachricht für Tool-Aufrufe zurück."""
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


def _create_tool_llm() -> ChatOpenAI:
    """Schnelle LLM-Instanz nur für Tool-Entscheidungen (weniger Tokens als finale Antwort)."""
    return ChatOpenAI(
        model=settings.llm_model,
        api_key=settings.active_llm_api_key,
        base_url=settings.llm_base_url,
        streaming=False,
        temperature=0.2,
        max_tokens=1024,
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
            plan.target_hr_min = None
            plan.target_hr_max = None
            plan.description = f"Ruhetag — {grund[:200]}"
            plan.coach_reasoning = grund[:500]
            await db.flush()
            return f"✓ Ruhetag gesetzt für {datum}: {grund}"
        except Exception as e:
            return f"Fehler: {e}"

    @tool
    async def update_training_day(
        datum: str, workout_type: str, dauer_min: int, zone: int, beschreibung: str
    ) -> str:
        """Aktualisiert eine Trainingseinheit. workout_type: easy_run/tempo_run/interval/long_run/rest/cross_training/swim/bike. zone: 1-5."""
        _VALID_TYPES = {
            "easy_run", "tempo_run", "interval", "long_run", "rest",
            "cross_training", "swim", "bike",
        }
        if workout_type not in _VALID_TYPES:
            return f"Fehler: ungültiger workout_type '{workout_type}'. Erlaubt: {', '.join(sorted(_VALID_TYPES))}"
        if not (1 <= zone <= 5):
            return f"Fehler: zone muss zwischen 1 und 5 liegen."
        if not (0 <= dauer_min <= 600):
            return f"Fehler: dauer_min muss zwischen 0 und 600 liegen."
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
            plan.description = beschreibung[:500]
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
            select(
                func.count(NutritionLog.id).label("cnt"),
                func.coalesce(func.sum(NutritionLog.calories), 0).label("cal"),
                func.coalesce(func.sum(NutritionLog.protein_g), 0).label("protein"),
                func.coalesce(func.sum(NutritionLog.carbs_g), 0).label("carbs"),
                func.coalesce(func.sum(NutritionLog.fat_g), 0).label("fat"),
            ).where(
                NutritionLog.user_id == user_id,
                NutritionLog.logged_at >= seven_days_ago,
            )
        )
        row = result.one()
        if row.cnt == 0:
            return "Keine Ernährungsdaten vorhanden."
        days = 7
        return json.dumps(
            {
                "zeitraum": "letzte 7 Tage",
                "mahlzeiten_gesamt": row.cnt,
                "durchschnitt_täglich": {
                    "kalorien": round(float(row.cal) / days),
                    "protein_g": round(float(row.protein) / days, 1),
                    "kohlenhydrate_g": round(float(row.carbs) / days, 1),
                    "fett_g": round(float(row.fat) / days, 1),
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
            select(
                func.coalesce(func.avg(NutritionLog.calories), 0).label("avg_cal"),
                func.coalesce(func.avg(NutritionLog.protein_g), 0).label("avg_protein"),
                func.coalesce(func.avg(NutritionLog.carbs_g), 0).label("avg_carbs"),
                func.coalesce(func.avg(NutritionLog.fat_g), 0).label("avg_fat"),
            ).where(
                NutritionLog.user_id == user_id,
                NutritionLog.logged_at >= seven_days_ago,
            )
        )
        row = result.one()
        avg_cal = float(row.avg_cal)
        avg_protein = float(row.avg_protein)
        avg_carbs = float(row.avg_carbs)
        avg_fat = float(row.avg_fat)
        planner = MealPlanner()
        return await planner.analyze_nutrient_gaps(
            avg_cal, avg_protein, avg_carbs, avg_fat, kalorien_ziel, protein_ziel_g
        )

    @tool
    async def get_vo2max_history() -> str:
        """Lädt den VO2max-Verlauf der letzten 90 Tage. Aufrufen bei Fragen zur Ausdauerleistung oder Fitness-Entwicklung."""
        from app.models.watch import WatchSync
        ninety_days_ago = datetime.now(timezone.utc) - timedelta(days=90)
        result = await db.execute(
            select(HealthMetric)
            .where(
                HealthMetric.user_id == user_id,
                HealthMetric.vo2_max.isnot(None),
                HealthMetric.recorded_at >= ninety_days_ago,
            )
            .order_by(HealthMetric.recorded_at.desc())
            .limit(20)
        )
        metrics = result.scalars().all()
        if not metrics:
            return "Keine VO2max-Daten vorhanden."
        values = [{"datum": m.recorded_at.date().isoformat(), "vo2max": m.vo2_max} for m in metrics]
        latest = values[0]["vo2max"]
        oldest = values[-1]["vo2max"] if len(values) > 1 else latest
        trend = round(latest - oldest, 1)
        return json.dumps({
            "aktuell": latest,
            "trend_90d": f"{'+' if trend >= 0 else ''}{trend} ml/kg/min",
            "verlauf": values[:10],
        }, ensure_ascii=False)

    @tool
    async def get_injury_history() -> str:
        """Lädt bekannte Verletzungen und Beschwerden aus dem Gedächtnis. Aufrufen bei Verletzungsfragen oder um Training anzupassen."""
        from app.services.ai_memory import AIMemoryService
        mem = AIMemoryService()
        result_text = await mem.retrieve_relevant("Verletzung Schmerzen Beschwerden Knie Rücken", user_id, db)
        if not result_text:
            return "Keine Verletzungshistorie im Gedächtnis gefunden."
        return result_text

    @tool
    async def get_sleep_trend() -> str:
        """Lädt detaillierte Schlafdaten der letzten 14 Tage: Dauer, Qualität, Einschlafzeit. Aufrufen bei Schlaffragen."""
        fourteen_days_ago = datetime.now(timezone.utc) - timedelta(days=14)
        result = await db.execute(
            select(HealthMetric)
            .where(
                HealthMetric.user_id == user_id,
                HealthMetric.sleep_duration_min.isnot(None),
                HealthMetric.recorded_at >= fourteen_days_ago,
            )
            .order_by(HealthMetric.recorded_at.desc())
            .limit(14)
        )
        metrics = result.scalars().all()
        if not metrics:
            return "Keine Schlafdaten vorhanden."
        durations = [m.sleep_duration_min for m in metrics if m.sleep_duration_min]
        avg_sleep_h = round(sum(durations) / len(durations) / 60, 1) if durations else 0
        return json.dumps({
            "ø_schlaf_stunden_14d": avg_sleep_h,
            "empfehlung_stunden": 8,
            "deficit_stunden": round(max(0, 8 - avg_sleep_h), 1),
            "verlauf": [
                {
                    "datum": m.recorded_at.date().isoformat(),
                    "schlaf_h": round(m.sleep_duration_min / 60, 1) if m.sleep_duration_min else None,
                }
                for m in metrics
            ],
        }, ensure_ascii=False)

    @tool
    async def log_symptom(symptom: str, schweregrad: int, bereich: str) -> str:
        """Speichert ein Symptom oder eine Beschwerde im Gedächtnis für zukünftige Referenz.
        symptom: Beschreibung des Symptoms.
        schweregrad: 1 (leicht) bis 10 (sehr stark).
        bereich: körperlicher Bereich (z.B. 'Knie links', 'Rücken', 'Kopf', 'allgemein')."""
        # Bounds check on tool inputs
        schweregrad = max(1, min(10, int(schweregrad)))
        symptom = str(symptom)[:500]
        bereich = str(bereich)[:200]
        from app.services.ai_memory import AIMemoryService
        mem = AIMemoryService()
        fact_text = f"Symptom: {symptom} | Schweregrad: {schweregrad}/10 | Bereich: {bereich} | Datum: {date.today().isoformat()}"
        # Als Injury-Fakt speichern
        from app.models.ai_memory import AIMemory
        import uuid
        entry = AIMemory(
            id=uuid.uuid4(),
            user_id=user_id,
            content=fact_text,
            category="injury",
        )
        db.add(entry)
        await db.flush()
        return f"✓ Symptom gespeichert: {fact_text}"

    @tool
    async def calculate_training_zones(max_hr: int, resting_hr: int, method: str = "karvonen") -> str:
        """Berechnet persönliche Herzfrequenztrainingszonen.
        max_hr: Maximale Herzfrequenz.
        resting_hr: Ruheherzfrequenz.
        method: 'karvonen' (Herzfrequenzreserve) oder 'percentage' (% von HRmax)."""
        hrr = max_hr - resting_hr
        if method == "karvonen":
            zones = {
                "Zone 1 (Regeneration)": (round(resting_hr + 0.50 * hrr), round(resting_hr + 0.60 * hrr)),
                "Zone 2 (Grundlage, aerob)": (round(resting_hr + 0.60 * hrr), round(resting_hr + 0.70 * hrr)),
                "Zone 3 (Tempo, aerob-anaerob)": (round(resting_hr + 0.70 * hrr), round(resting_hr + 0.80 * hrr)),
                "Zone 4 (Schwelle)": (round(resting_hr + 0.80 * hrr), round(resting_hr + 0.90 * hrr)),
                "Zone 5 (VO2max, maximal)": (round(resting_hr + 0.90 * hrr), max_hr),
            }
        else:
            zones = {
                "Zone 1 (Regeneration)": (round(max_hr * 0.50), round(max_hr * 0.60)),
                "Zone 2 (Grundlage, aerob)": (round(max_hr * 0.60), round(max_hr * 0.70)),
                "Zone 3 (Tempo)": (round(max_hr * 0.70), round(max_hr * 0.80)),
                "Zone 4 (Schwelle)": (round(max_hr * 0.80), round(max_hr * 0.90)),
                "Zone 5 (Maximal)": (round(max_hr * 0.90), max_hr),
            }
        return json.dumps({
            "methode": method,
            "max_hr": max_hr,
            "resting_hr": resting_hr,
            "zonen": {name: f"{low}–{high} bpm" for name, (low, high) in zones.items()},
        }, ensure_ascii=False)

    @tool
    async def get_race_history() -> str:
        """Lädt vergangene Wettkampfergebnisse und persönliche Bestzeiten aus dem Gedächtnis."""
        from app.services.ai_memory import AIMemoryService
        mem = AIMemoryService()
        result_text = await mem.retrieve_relevant("Wettkampf Rennen Marathon Halbmarathon Bestzeit Ergebnis km/h", user_id, db)
        if not result_text:
            return "Keine Wettkampfhistorie im Gedächtnis gefunden."
        return result_text

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
        get_vo2max_history,
        get_injury_history,
        get_sleep_trend,
        log_symptom,
        calculate_training_zones,
        get_race_history,
    ]


class LangChainCoachAgent:
    """LangChain Agent mit bind_tools-Pattern (LangChain ≥1.0), Streaming und autonomen Tool-Aufrufen."""

    def __init__(self):
        self.memory_service = AIMemoryService()

    def _build_llm(self, streaming: bool = True) -> ChatOpenAI:
        return _create_llm(streaming=streaming)

    async def _run_tool(self, tool_name: str, tool_args: dict, tools_by_name: dict) -> str:
        """Führt ein einzelnes Tool aus und gibt das Ergebnis als String zurück."""
        t = tools_by_name.get(tool_name)
        if not t:
            return f"Unbekanntes Tool: {tool_name}"
        try:
            result = await t.ainvoke(tool_args)
            return str(result)
        except Exception as e:
            logger.warning(f"Tool {tool_name} failed | args={tool_args} | error={e}")
            return f"Tool-Fehler ({tool_name}): {e}"

    async def stream(
        self, message: str, user_id: str, db: AsyncSession
    ) -> AsyncGenerator[str, None]:
        """Streaming-Chat via bind_tools Agent-Loop (SSE-Format: 'data: text\\n\\n')."""
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

        # Messages aufbauen
        lc_messages: list = [SystemMessage(content=get_base_system_prompt())]
        for conv in history:
            if conv.role == "user":
                lc_messages.append(HumanMessage(content=conv.content))
            else:
                lc_messages.append(AIMessage(content=conv.content))
        lc_messages.append(HumanMessage(content=message))

        # Tools vorbereiten
        tools_list = _create_tools(user_id, db)
        tools_by_name = {t.name: t for t in tools_list}
        llm_with_tools = _create_tool_llm().bind_tools(tools_list)
        llm_streaming = self._build_llm(streaming=True)

        full_response = ""
        thinking_sent = False

        try:
            # Agent-Loop: max 6 Tool-Runden
            for _round in range(6):
                # Sofortiges Feedback vor jedem LLM-Call (kein leerer Wartebildschirm)
                if not thinking_sent:
                    thinking_msg = "⌛ *Analysiere deine Anfrage...*\n\n"
                    full_response += thinking_msg
                    yield f"data: {thinking_msg}\n\n"
                    thinking_sent = True

                ai_msg = await llm_with_tools.ainvoke(lc_messages)
                tool_calls_list = ai_msg.tool_calls if hasattr(ai_msg, "tool_calls") else []

                if not tool_calls_list:
                    # Finale Antwort — erst versuchen ob content schon vorhanden
                    final_text = (ai_msg.content or "").strip()
                    if not final_text:
                        # Leer → explizit nach Antwort fragen (echtes Streaming)
                        lc_messages.append(ai_msg)
                        lc_messages.append(HumanMessage(content="Bitte gib jetzt deine Antwort auf Deutsch."))
                        async for chunk in llm_streaming.astream(lc_messages):
                            text = chunk.content or ""
                            if text:
                                full_response += text
                                safe = text.replace("\n", "\ndata: ")
                                yield f"data: {safe}\n\n"
                    else:
                        # Model hat bereits geantwortet — sende Text direkt
                        full_response += final_text
                        safe = final_text.replace("\n", "\ndata: ")
                        yield f"data: {safe}\n\n"
                    break

                # Tool-Calls ausführen
                lc_messages.append(ai_msg)
                for tc in tool_calls_list:
                    tool_name = tc["name"]
                    tool_args = tc.get("args", {})
                    status_msg = _tool_status_message(tool_name)
                    if status_msg:
                        full_response += status_msg
                        safe_status = status_msg.replace("\n", "\ndata: ")
                        yield f"data: {safe_status}\n\n"
                    tool_result = await self._run_tool(tool_name, tool_args, tools_by_name)
                    lc_messages.append(ToolMessage(
                        content=tool_result,
                        tool_call_id=tc["id"],
                    ))
            else:
                # Alle 6 Runden verbraucht ohne finale Antwort → erzwinge Antwort
                logger.warning(f"Agent loop exhausted without final answer | user={user_id}")
                lc_messages.append(HumanMessage(content="Bitte gib jetzt deine abschließende Antwort auf Deutsch."))
                async for chunk in llm_streaming.astream(lc_messages):
                    text = chunk.content or ""
                    if text:
                        full_response += text
                        safe = text.replace("\n", "\ndata: ")
                        yield f"data: {safe}\n\n"

        except Exception as e:
            logger.error(f"LangChain stream failed | user={user_id} | error={e}")
            error_msg = "Entschuldigung, ich konnte deine Anfrage gerade nicht verarbeiten. Bitte versuche es erneut."
            full_response += error_msg
            yield f"data: {error_msg}\n\n"

        # Antwort + Memory speichern (ohne Status-Nachrichten)
        if full_response:
            clean_response = full_response
            for status_val in STATUS_MAP.values():
                clean_response = clean_response.replace(status_val, "")
            clean_response = clean_response.replace("⌛ *Analysiere deine Anfrage...*\n\n", "").strip()
            save_content = clean_response if clean_response else full_response
            db.add(Conversation(user_id=user_id, role="assistant", content=save_content))
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
                await db.execute(delete(Conversation).where(Conversation.id.in_(old_ids)))
                await db.flush()

        yield "data: [DONE]\n\n"

    async def run_autonomous(self, user_id: str, task: str, db: AsyncSession) -> str:
        """Führt den Agent autonom aus (kein Streaming) — für Hintergrund-Jobs."""
        if not settings.active_llm_api_key:
            return "LLM nicht konfiguriert"
        try:
            tools_list = _create_tools(user_id, db)
            tools_by_name = {t.name: t for t in tools_list}
            llm = self._build_llm(streaming=False).bind_tools(tools_list)

            messages: list = [
                SystemMessage(content=get_autonomous_system_prompt()),
                HumanMessage(content=task),
            ]

            for _ in range(8):
                ai_msg = await llm.ainvoke(messages)
                tool_calls_list = ai_msg.tool_calls if hasattr(ai_msg, "tool_calls") else []
                if not tool_calls_list:
                    return (ai_msg.content or "Fertig").strip()
                messages.append(ai_msg)
                for tc in tool_calls_list:
                    result = await self._run_tool(tc["name"], tc.get("args", {}), tools_by_name)
                    messages.append(ToolMessage(content=result, tool_call_id=tc["id"]))

            # Finale Antwort anfordern
            final = await self._build_llm(streaming=False).ainvoke(messages)
            return (final.content or "Fertig").strip()
        except Exception as e:
            logger.error(f"Autonomous run failed | user={user_id} | error={e}")
            return f"Fehler: {e}"


def _split_into_chunks(text: str, size: int = 40) -> list[str]:
    """Teilt Text in Chunks auf für simuliertes Streaming."""
    return [text[i:i + size] for i in range(0, len(text), size)]
