# TrainIQ — Autonomes LangChain Agent System: Implementierungsanleitung

> **Für den implementierenden Agent:** Dieses Dokument ist die vollständige Spezifikation. Implementiere **exakt** so wie beschrieben. Alle Pfade sind relativ zu `/Users/abu/Projekt/trainiq/`. Lese vor jeder Dateiänderung die bestehende Datei zuerst.

---

## 0. Was bereits getan wurde (NICHT nochmal machen)

- `backend/requirements.txt`: `langchain>=0.3.0`, `langchain-openai>=0.2.0`, `langchain-core>=0.3.0` sind bereits am Ende hinzugefügt.
- `backend/app/services/meal_planner.py`: Wurde bereits erstellt — lies sie zuerst, dann entscheide ob Änderungen nötig sind.

---

## 1. Überblick & Ziel

**Was fehlt:** Der bestehende `CoachAgent` (`app/services/coach_agent.py`) macht nur einfache LLM-Aufrufe + manuelle JSON-Action-Parsierung. Es gibt keinen echten agentischen Loop, keine autonome Hintergrundüberwachung, keinen Wochenspeiseplan mit Rezepten und keinen Schlaf-Coach.

**Was gebaut wird:**

```
backend/app/services/
├── coach_agent.py          ← BLEIBT UNVERÄNDERT (Fallback)
├── langchain_agent.py      ← NEU: LangChain Agent mit 9 Tools
├── autonomous_monitor.py   ← NEU: Hintergrundmonitor (erkennt schlechte Stimmung, fehlende Trainings)
├── meal_planner.py         ← BEREITS ERSTELLT (ggf. anpassen)
└── sleep_coach.py          ← NEU: Tägliche Schlaftipps + Morgen-Feedback

backend/app/scheduler/
├── jobs.py                 ← ERWEITERN: 3 neue Jobs hinzufügen
└── runner.py               ← ERWEITERN: neue Jobs registrieren

backend/app/api/routes/
└── coach.py                ← ERWEITERN: 3 neue Endpoints
```

---

## 2. Technischer Kontext (wichtig zum Verstehen)

### LLM-Konfiguration (aus `app/core/config.py`)
```python
settings.active_llm_api_key  # LLM_API_KEY env var (oder NVIDIA_API_KEY als Fallback)
settings.llm_base_url         # z.B. "https://integrate.api.nvidia.com/v1"
settings.llm_model            # z.B. "moonshotai/kimi-k2-instruct"
```

### Datenbank-Session-Pattern
```python
# Für Routes (via FastAPI Dependency):
from app.core.database import get_db
db: AsyncSession = Depends(get_db)

# Für Background-Jobs / Scheduler (eigene Session):
from app.core.database import async_session
async with async_session() as db:
    ...
    await db.commit()
```

### Relevante Models
```python
from app.models.conversation import Conversation
# Felder: id (UUID), user_id (UUID), role (str: "user"/"assistant"), content (str), created_at

from app.models.training import TrainingPlan, UserGoal
# TrainingPlan Felder: id, user_id, date (Date), sport, workout_type, duration_min,
#                      intensity_zone (1-5), target_hr_min, target_hr_max,
#                      description, coach_reasoning, status ("planned"/"completed"/"skipped")
# UserGoal Felder: id, user_id, sport, goal_description, weekly_hours, fitness_level

from app.models.metrics import HealthMetric, DailyWellbeing
# HealthMetric Felder: id, user_id, recorded_at (DateTime), hrv, resting_hr,
#                      sleep_duration_min, stress_score
# DailyWellbeing Felder: id, user_id, date, fatigue_score (1-10), mood_score (1-10), pain_notes

from app.models.nutrition import NutritionLog
# Felder: id, user_id, logged_at (DateTime), meal_type, calories, protein_g, carbs_g, fat_g, meal_name
```

### Bestehende Services (dürfen importiert werden)
```python
from app.services.recovery_scorer import RecoveryScorer
# RecoveryScorer.compute_baseline(metrics_list) -> dict
# scorer.calculate_recovery_score(metric_dict, user_baseline) -> {"score": int, "label": str}

from app.services.training_planner import TrainingPlanner
# planner.generate_week_plan(user_id: str, week_start: date, db) -> list[TrainingPlan]

from app.services.ai_memory import AIMemoryService
# memory_service.extract_and_store(message, user_id, db, conversation_id)
# memory_service.retrieve_relevant(query, user_id, db) -> str
```

---

## 3. Datei 1: `app/services/langchain_agent.py` (NEU ERSTELLEN)

**Zweck:** LangChain Agent mit 9 Tools. Ersetzt `CoachAgent.stream()` als primäre Chat-Implementierung. Fällt auf `CoachAgent` zurück wenn LangChain einen Fehler wirft.

**Vollständige Implementierung:**

```python
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


SYSTEM_PROMPT = """Du bist TrainIQ Coach — ein KI-Assistent mit 4 Expertisen:

🏃 TRAININGSCOACH: Personalisierte Trainingspläne für Ausdauersportler, Anpassung an Recovery
🥗 ERNÄHRUNGSBERATER: Nährstoffanalyse, Identifikation von Mängeln, Wochenspeisepläne mit Rezepten
💤 SCHLAFCOACH: Tägliche Schlaftipps abends, Schlafqualitäts-Analyse morgens
🏥 GESUNDHEITSBERATER: HRV, Ruhepuls, Stress analysieren, Übertraining erkennen

REGELN:
1. Nutze IMMER die verfügbaren Tools — lade echte Daten, bevor du antwortest
2. Erkenne automatisch: "Nutzer fühlt sich schlecht" → set_rest_day aufrufen
3. Erkenne automatisch: "Training nicht abgeschlossen/verpasst" → update_training_day anpassen
4. HRV < 20% unter Durchschnitt ODER Schlaf < 360min → Ruhetag empfehlen UND setzen
5. Bei Ernährungsfragen: create_weekly_meal_plan aufrufen mit konkreten Zielen
6. Antworte auf Deutsch, direkt, mit echten Zahlen (nicht "deine HRV ist gut" sondern "deine HRV ist 42ms")
7. Max 4 Sätze außer bei Plänen/Rezepten

PERSONAS: Wechsle automatisch je nach Thema zwischen Trainer / Ernährungsberater / Schlafcoach / Arzt."""


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
            .where(HealthMetric.user_id == user_id, HealthMetric.recorded_at >= seven_days_ago)
            .order_by(HealthMetric.recorded_at.desc())
            .limit(14)
        )
        metrics = result.scalars().all()
        if not metrics:
            return "Keine Metriken vorhanden."
        scorer = RecoveryScorer()
        baseline_data = [
            {"hrv": m.hrv, "sleep_duration_min": m.sleep_duration_min,
             "stress_score": m.stress_score, "resting_hr": m.resting_hr}
            for m in metrics
        ]
        baseline = RecoveryScorer.compute_baseline(baseline_data)
        latest = metrics[0]
        recovery = scorer.calculate_recovery_score(
            {"hrv": latest.hrv, "sleep_duration_min": latest.sleep_duration_min,
             "stress_score": latest.stress_score, "resting_hr": latest.resting_hr},
            user_baseline=baseline,
        )
        data = {
            "recovery_score": recovery["score"],
            "recovery_label": recovery["label"],
            "metriken": [
                {"datum": m.recorded_at.date().isoformat(), "hrv_ms": m.hrv,
                 "ruhepuls": m.resting_hr, "schlaf_min": m.sleep_duration_min,
                 "stress": m.stress_score}
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
            .where(TrainingPlan.user_id == user_id, TrainingPlan.date >= week_start,
                   TrainingPlan.date < week_start + timedelta(days=7))
            .order_by(TrainingPlan.date)
        )
        plans = result.scalars().all()
        if not plans:
            return "Kein Trainingsplan für diese Woche vorhanden."
        return json.dumps(
            [{"datum": p.date.isoformat(), "typ": p.workout_type, "dauer_min": p.duration_min,
              "zone": p.intensity_zone, "status": p.status, "beschreibung": p.description}
             for p in plans],
            ensure_ascii=False,
        )

    @tool
    async def set_rest_day(datum: str, grund: str) -> str:
        """Setzt einen Ruhetag im Trainingsplan. datum: ISO-Format 'YYYY-MM-DD'. grund: kurze Begründung."""
        try:
            plan_date = date.fromisoformat(datum)
            result = await db.execute(
                select(TrainingPlan).where(TrainingPlan.user_id == user_id, TrainingPlan.date == plan_date)
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
    async def update_training_day(datum: str, workout_type: str, dauer_min: int, zone: int, beschreibung: str) -> str:
        """Aktualisiert eine Trainingseinheit. workout_type: easy_run/tempo_run/interval/long_run/rest/cross_training/swim/bike. zone: 1-5."""
        try:
            plan_date = date.fromisoformat(datum)
            result = await db.execute(
                select(TrainingPlan).where(TrainingPlan.user_id == user_id, TrainingPlan.date == plan_date)
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
            return f"✓ Neuer Wochenplan erstellt: {len(plans)} Einheiten ab {week_start}"
        except Exception as e:
            return f"Fehler: {e}"

    @tool
    async def get_nutrition_summary() -> str:
        """Lädt Ernährungsdaten der letzten 7 Tage (Kalorien, Protein, KH, Fett). Aufrufen bei Ernährungsfragen."""
        seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
        result = await db.execute(
            select(NutritionLog)
            .where(NutritionLog.user_id == user_id, NutritionLog.logged_at >= seven_days_ago)
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
        return json.dumps({
            "zeitraum": "letzte 7 Tage",
            "mahlzeiten_gesamt": len(logs),
            "durchschnitt_täglich": {
                "kalorien": round(total_cal / days),
                "protein_g": round(total_protein / days, 1),
                "kohlenhydrate_g": round(total_carbs / days, 1),
                "fett_g": round(total_fat / days, 1),
            },
        }, ensure_ascii=False)

    @tool
    async def create_weekly_meal_plan(kalorien_ziel: int, protein_ziel_g: int) -> str:
        """Erstellt einen vollständigen 7-Tage Speiseplan mit Rezepten. kalorien_ziel: tägliches Kalorienziel. protein_ziel_g: tägliches Proteinziel in Gramm."""
        from app.services.meal_planner import MealPlanner
        planner = MealPlanner()
        return await planner.generate_weekly_plan(user_id, kalorien_ziel, protein_ziel_g)

    @tool
    async def get_user_goals() -> str:
        """Lädt Sportziele und Fitnesslevel des Nutzers."""
        result = await db.execute(select(UserGoal).where(UserGoal.user_id == user_id))
        goals = result.scalars().all()
        if not goals:
            return "Keine Ziele gesetzt."
        g = goals[0]
        return json.dumps({"sport": g.sport, "ziel": g.goal_description,
                           "level": g.fitness_level, "wochenstunden": g.weekly_hours},
                          ensure_ascii=False)

    @tool
    async def get_daily_wellbeing() -> str:
        """Lädt das heutige Befinden des Nutzers (Müdigkeit 1-10, Stimmung 1-10, Schmerzen)."""
        result = await db.execute(
            select(DailyWellbeing).where(DailyWellbeing.user_id == user_id, DailyWellbeing.date == date.today())
        )
        wb = result.scalars().first()
        if not wb:
            return "Kein Befinden für heute eingetragen."
        return json.dumps({"datum": date.today().isoformat(), "müdigkeit": wb.fatigue_score,
                           "stimmung": wb.mood_score, "schmerzen": wb.pain_notes or "keine"},
                          ensure_ascii=False)

    @tool
    async def analyze_nutrition_gaps(kalorien_ziel: int = 2200, protein_ziel_g: int = 150) -> str:
        """Analysiert Nährstoffmängel basierend auf den letzten 7 Tagen und gibt konkrete Lebensmittelempfehlungen."""
        from app.services.meal_planner import MealPlanner
        seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
        result = await db.execute(
            select(NutritionLog)
            .where(NutritionLog.user_id == user_id, NutritionLog.logged_at >= seven_days_ago)
        )
        logs = result.scalars().all()
        avg_cal = sum(n.calories or 0 for n in logs) / 7 if logs else 0
        avg_protein = sum(n.protein_g or 0 for n in logs) / 7 if logs else 0
        avg_carbs = sum(n.carbs_g or 0 for n in logs) / 7 if logs else 0
        avg_fat = sum(n.fat_g or 0 for n in logs) / 7 if logs else 0
        planner = MealPlanner()
        return await planner.analyze_nutrient_gaps(avg_cal, avg_protein, avg_carbs, avg_fat,
                                                    kalorien_ziel, protein_ziel_g)

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

    def _build_executor(self, user_id: str, db: AsyncSession, streaming: bool = True) -> AgentExecutor:
        llm = _create_llm(streaming=streaming)
        tools = _create_tools(user_id, db)
        prompt = ChatPromptTemplate.from_messages([
            ("system", SYSTEM_PROMPT),
            MessagesPlaceholder("chat_history"),
            ("human", "{input}"),
            MessagesPlaceholder("agent_scratchpad"),
        ])
        agent = create_openai_tools_agent(llm, tools, prompt)
        return AgentExecutor(agent=agent, tools=tools, verbose=False, max_iterations=6,
                             return_intermediate_steps=False)

    async def stream(self, message: str, user_id: str, db: AsyncSession) -> AsyncGenerator[str, None]:
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
        try:
            executor = self._build_executor(user_id, db, streaming=True)
            async for event in executor.astream_events(
                {"input": message, "chat_history": chat_history},
                version="v1",
            ):
                if event.get("event") == "on_chat_model_stream":
                    chunk = event.get("data", {}).get("chunk")
                    if chunk and hasattr(chunk, "content") and chunk.content:
                        full_response += chunk.content
                        # Newlines in SSE escapen
                        safe = chunk.content.replace("\n", "\ndata: ")
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
            db.add(Conversation(user_id=user_id, role="assistant", content=full_response))
            await db.flush()
            await self.memory_service.extract_and_store(message, user_id, db,
                                                         conversation_id=str(user_conv.id))

        # Alte Conversations aufräumen (max 500)
        count_result = await db.execute(
            select(func.count(Conversation.id)).where(Conversation.user_id == user_id)
        )
        total = count_result.scalar() or 0
        if total > 500:
            oldest = await db.execute(
                select(Conversation.id).where(Conversation.user_id == user_id)
                .order_by(Conversation.created_at.asc()).limit(total - 500)
            )
            old_ids = [r[0] for r in oldest.all()]
            if old_ids:
                await db.execute(delete(Conversation).where(Conversation.id.in_(old_ids)))
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
            prompt = ChatPromptTemplate.from_messages([
                ("system", SYSTEM_PROMPT + "\n\nDu arbeitest autonom im Hintergrund. Führe die nötigen Aktionen direkt aus, ohne zu fragen."),
                ("human", "{input}"),
                MessagesPlaceholder("agent_scratchpad"),
            ])
            agent = create_openai_tools_agent(llm, tools, prompt)
            executor = AgentExecutor(agent=agent, tools=tools, verbose=True, max_iterations=8)
            result = await executor.ainvoke({"input": task, "chat_history": []})
            return result.get("output", "Fertig")
        except Exception as e:
            logger.error(f"Autonomous run failed | user={user_id} | error={e}")
            return f"Fehler: {e}"
```

---

## 4. Datei 2: `app/services/autonomous_monitor.py` (NEU ERSTELLEN)

**Zweck:** Background-Service der alle 30 Minuten läuft. Liest die letzten Gespräche jedes Users, erkennt via LLM ob der User sich schlecht fühlt oder Training verpasst hat, und lässt den LangChain Agent autonom den Plan anpassen.

**Vollständige Implementierung:**

```python
"""Autonomer Hintergrundmonitor — erkennt Nutzer-Probleme und passt Pläne autonom an."""

import json
import httpx
from datetime import datetime, timedelta, timezone
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import async_session
from app.models.user import User
from app.models.conversation import Conversation


DETECTION_PROMPT = """Analysiere die folgenden Chat-Nachrichten eines Sportlers mit seinem KI-Coach.

Erkenne ob eines dieser Ereignisse vorliegt:
1. "bad_feeling" — Nutzer sagt dass er sich krank/schlecht/erschöpft/müde fühlt
2. "skipped_training" — Nutzer hat ein Training ausgelassen/nicht geschafft/übersprungen
3. "injury" — Nutzer hat eine Verletzung erwähnt
4. "normal" — Nichts Besonderes, kein Handlungsbedarf

Antworte NUR mit einem JSON-Objekt:
{{
  "event": "bad_feeling" | "skipped_training" | "injury" | "normal",
  "confidence": "high" | "medium" | "low",
  "detail": "kurze Erklärung auf Deutsch"
}}

Chat-Nachrichten (neueste zuerst):
{messages}

JSON:"""


async def _classify_conversation(messages: list[dict]) -> dict:
    """Nutzt LLM um zu klassifizieren ob Handlungsbedarf besteht."""
    if not settings.active_llm_api_key or not messages:
        return {"event": "normal", "confidence": "low", "detail": ""}

    # Nur User-Nachrichten der letzten 24h analysieren
    messages_text = "\n".join([
        f"[{m['role'].upper()}]: {m['content'][:200]}"
        for m in messages[:10]
    ])

    try:
        headers = {
            "Authorization": f"Bearer {settings.active_llm_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": settings.llm_model,
            "messages": [{"role": "user", "content": DETECTION_PROMPT.format(messages=messages_text)}],
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
            result = await db.execute(select(User))
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

                    messages = [{"role": c.role, "content": c.content} for c in convs]
                    classification = await _classify_conversation(messages)

                    event = classification.get("event", "normal")
                    confidence = classification.get("confidence", "low")
                    detail = classification.get("detail", "")

                    # Nur bei hoher/mittlerer Konfidenz und echtem Event handeln
                    if event == "normal" or confidence == "low":
                        continue

                    logger.info(f"Monitor detected event | user={user.id} | event={event} | confidence={confidence} | detail={detail}")

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
                    logger.info(f"Monitor action completed | user={user.id} | result={action_result[:100]}")

                    # Coach-Nachricht in Conversation speichern (sichtbar im Chat)
                    note = Conversation(
                        user_id=user.id,
                        role="assistant",
                        content=f"🤖 *Coach-Anpassung (automatisch)*: {action_result}",
                    )
                    db.add(note)
                    await db.flush()
                    processed += 1

                except Exception as e:
                    logger.warning(f"Monitor failed for user | user={user.id} | error={e}")
                    continue

            await db.commit()
            logger.info(f"Autonomous monitor completed | processed={processed}/{len(users)}")

        except Exception as e:
            logger.error(f"Autonomous monitor job failed | error={e}")
            await db.rollback()
```

---

## 5. Datei 3: `app/services/sleep_coach.py` (NEU ERSTELLEN)

**Zweck:** Sendet jeden Abend um 22:00 einen Schlaftipp als Coach-Nachricht. Fragt jeden Morgen um 07:00 nach der Schlafqualität und gibt Feedback basierend auf den gespeicherten Metriken.

**Vollständige Implementierung:**

```python
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


SLEEP_TIPS = [
    "Versuche heute Abend **1 Stunde vor dem Schlafen kein Bildschirmlicht** mehr zu nutzen. Das blaue Licht hemmt die Melatonin-Produktion.",
    "Halte die **Schlafzimmertemperatur zwischen 16-18°C**. Kühlere Temperaturen fördern den Tiefschlaf und verbessern deine HRV.",
    "Trinke heute Abend **keine Koffein-Getränke mehr** (Kaffee, Energy-Drinks, Cola) — Koffein hat eine Halbwertszeit von ~6 Stunden.",
    "Mache 10 Minuten **4-7-8 Atemübungen** vor dem Schlaf: 4s einatmen, 7s halten, 8s ausatmen. Aktiviert das parasympathische System.",
    "Gehe heute **zur gleichen Zeit ins Bett** wie gestern. Konsistente Schlafzeiten sind der wichtigste Faktor für HRV-Verbesserung.",
    "Schreibe vor dem Schlafen **3 Dinge auf die dich morgen erwarten** — das reduziert Gedankenkarussell und verbessert die Schlafqualität.",
    "Meide heute Abend **intensives Training nach 20 Uhr** — es erhöht Cortisol und Körpertemperatur, was das Einschlafen erschwert.",
]


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
    import random

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

                    # Personalisierten Tipp generieren
                    tip = random.choice(SLEEP_TIPS)

                    if latest_metrics:
                        avg_sleep = sum(m.sleep_duration_min or 0 for m in latest_metrics) / len(latest_metrics)
                        sleep_hours = round(avg_sleep / 60, 1)

                        if sleep_hours < 6:
                            context = f"Dein Durchschnitt der letzten Tage: nur {sleep_hours}h Schlaf — das ist zu wenig für Regeneration."
                        elif sleep_hours >= 7.5:
                            context = f"Dein Schlaf-Durchschnitt: {sleep_hours}h — gut! Halte diese Konstanz."
                        else:
                            context = f"Dein Schlaf-Durchschnitt: {sleep_hours}h — noch etwas Luft nach oben."
                    else:
                        context = ""

                    message = f"🌙 **Schlaftipp für heute Nacht**\n\n{tip}"
                    if context:
                        message += f"\n\n📊 {context}"
                    message += "\n\n*Morgen früh gebe ich dir Feedback zu deiner Erholung.*"

                    conv = Conversation(user_id=user.id, role="assistant", content=message)
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
                            {"hrv": m.hrv, "sleep_duration_min": m.sleep_duration_min,
                             "stress_score": m.stress_score, "resting_hr": m.resting_hr}
                            for m in metrics
                        ]
                        baseline = RecoveryScorer.compute_baseline(baseline_data)
                        recovery = scorer.calculate_recovery_score(
                            {"hrv": latest.hrv, "sleep_duration_min": latest.sleep_duration_min,
                             "stress_score": latest.stress_score, "resting_hr": latest.resting_hr},
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
                            emoji = "🟢" if score >= 70 else ("🟡" if score >= 40 else "🔴")
                            feedback_text = (
                                f"{emoji} **Recovery Score: {score}/100 ({label})**\n\n"
                                f"Schlaf: {sleep_h}h | HRV: {hrv}ms | Ruhepuls: {rhr}bpm\n\n"
                                f"{'Heute ist ein guter Tag für intensives Training.' if score >= 70 else 'Heute lieber locker oder pausieren.'}\n\n"
                                f"*Wie fühlst du dich heute?*"
                            )

                        message = f"☀️ **Guten Morgen — dein Gesundheits-Check**\n\n{feedback_text}"

                    conv = Conversation(user_id=user.id, role="assistant", content=message)
                    db.add(conv)
                    await db.flush()
                    sent += 1

                except Exception as e:
                    logger.warning(f"Morning feedback failed | user={user.id} | error={e}")
                    continue

            await db.commit()
            logger.info(f"Morning feedback job completed | sent={sent}/{len(users)}")

        except Exception as e:
            logger.error(f"Morning feedback job failed | error={e}")
            await db.rollback()
```

---

## 6. `app/services/meal_planner.py` — Prüfen und ggf. Vervollständigen

Diese Datei wurde bereits erstellt. **Lese sie zuerst** (`Read` Tool auf `backend/app/services/meal_planner.py`).

Stelle sicher dass sie diese beiden async Methoden enthält:

### Methode 1: `generate_weekly_plan(user_id, kalorien_ziel, protein_ziel_g) -> str`
- Ruft LLM auf via httpx (gleich wie TrainingPlanner)
- LLM-URL: `f"{settings.llm_base_url}/chat/completions"`
- Headers: `{"Authorization": f"Bearer {settings.active_llm_api_key}", "Content-Type": "application/json"}`
- Prompt: Fordert einen 7-Tage Speiseplan mit Markdown-Format, Frühstück/Mittagessen/Abendessen/Snacks, vollständige Rezepte (Zutaten + 3-5 Schritte), Nährwerte pro Mahlzeit
- max_tokens: 4096 (wichtig — Rezepte sind lang!)
- timeout: 120.0 Sekunden
- Gibt den generierten Markdown-Text zurück

### Methode 2: `analyze_nutrient_gaps(avg_calories, avg_protein_g, avg_carbs_g, avg_fat_g, target_calories, target_protein_g) -> str`
- Ruft LLM auf mit Nährstoff-Vergleich
- Prompt: Analysiere Ist vs. Soll-Werte, identifiziere Mängel, gib 5-7 konkrete Lebensmittel-Empfehlungen
- max_tokens: 1024

**Falls die Datei diese Methoden nicht vollständig hat, ergänze sie.**

---

## 7. `app/scheduler/jobs.py` — ERWEITERN

**Lese die Datei zuerst.** Dann füge am Ende dieser Datei hinzu (NICHT die bestehenden Funktionen verändern):

```python
async def autonomous_monitor_job():
    """Erkennt Nutzer-Probleme in Gesprächen und passt Pläne autonom an. Läuft alle 30 Min."""
    from app.services.autonomous_monitor import run_autonomous_monitor
    await run_autonomous_monitor()


async def send_sleep_tips_job():
    """Sendet tägliche Schlaftipps um 22:00."""
    from app.services.sleep_coach import send_evening_sleep_tips
    await send_evening_sleep_tips()


async def send_morning_feedback_job():
    """Sendet morgendliches Gesundheits-Feedback um 07:00."""
    from app.services.sleep_coach import send_morning_health_feedback
    await send_morning_health_feedback()
```

**Wichtig:** Imports werden lazy (innerhalb der Funktionen) gemacht um zirkuläre Imports zu vermeiden.

---

## 8. `app/scheduler/runner.py` — ERWEITERN

**Lese die Datei zuerst.** Dann:

1. Import-Zeile oben anpassen — füge die 3 neuen Job-Funktionen hinzu:
```python
from app.scheduler.jobs import (
    sync_watch_data_for_all_users,
    generate_tomorrow_plans,
    autonomous_monitor_job,
    send_sleep_tips_job,
    send_morning_feedback_job,
)
```

2. Nach den bestehenden `scheduler.add_job(...)` Aufrufen die 3 neuen Jobs hinzufügen:
```python
scheduler.add_job(
    autonomous_monitor_job,
    "interval",
    minutes=30,
    id="autonomous_monitor",
    replace_existing=True,
)
scheduler.add_job(
    send_sleep_tips_job,
    "cron",
    hour=22,
    minute=0,
    id="sleep_tips",
    replace_existing=True,
)
scheduler.add_job(
    send_morning_feedback_job,
    "cron",
    hour=7,
    minute=0,
    id="morning_feedback",
    replace_existing=True,
)
```

---

## 9. `app/api/routes/coach.py` — ERWEITERN

**Lese die Datei zuerst.** Dann:

### 9a. Chat-Endpoint auf LangChain umstellen

Ersetze in `_stream_with_own_session` den `CoachAgent()` durch `LangChainCoachAgent()`:

```python
# Am Anfang der Datei hinzufügen (nach bestehenden Imports):
from app.services.langchain_agent import LangChainCoachAgent
```

```python
# _stream_with_own_session Funktion — agent = CoachAgent() → agent = LangChainCoachAgent()
async def _stream_with_own_session(
    message: str, user_id: str, extra_context: str | None = None
) -> AsyncGenerator[str, None]:
    async with async_session() as db:
        agent = LangChainCoachAgent()   # ← HIER ändern (war: CoachAgent())
        full_message = message
        if extra_context:
            full_message = f"{message}\n\n[Zusatz-Kontext für den Coach]:\n{extra_context}"
        async for chunk in agent.stream(full_message, user_id, db):
            yield chunk
        await db.commit()
```

### 9b. 3 neue Endpoints hinzufügen (am Ende der Datei, vor dem letzten `@router.delete`):

```python
# ─── Meal Plan ────────────────────────────────────────────────────────────────

class MealPlanRequest(BaseModel):
    kalorien_ziel: int = 2200
    protein_ziel_g: int = 150


@router.post("/meal-plan")
@limiter.limit("5/minute")
async def generate_meal_plan(
    request: Request,
    meal_request: MealPlanRequest,
    current_user: User = Depends(get_current_user),
):
    """Generiert einen 7-Tage Speiseplan mit Rezepten via KI."""
    if not settings.active_llm_api_key:
        raise HTTPException(status_code=503, detail="Coach nicht konfiguriert")
    from app.services.meal_planner import MealPlanner
    planner = MealPlanner()
    meal_plan = await planner.generate_weekly_plan(
        str(current_user.id), meal_request.kalorien_ziel, meal_request.protein_ziel_g
    )
    return {"meal_plan": meal_plan}


@router.get("/nutrition-gaps")
async def get_nutrition_gaps(
    kalorien_ziel: int = 2200,
    protein_ziel_g: int = 150,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Analysiert Nährstofflücken und gibt Lebensmittelempfehlungen."""
    from app.services.meal_planner import MealPlanner
    from app.models.nutrition import NutritionLog
    from datetime import datetime, timedelta, timezone
    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
    result = await db.execute(
        select(NutritionLog).where(
            NutritionLog.user_id == current_user.id,
            NutritionLog.logged_at >= seven_days_ago,
        )
    )
    logs = result.scalars().all()
    days = 7
    avg_cal = sum(n.calories or 0 for n in logs) / days
    avg_protein = sum(n.protein_g or 0 for n in logs) / days
    avg_carbs = sum(n.carbs_g or 0 for n in logs) / days
    avg_fat = sum(n.fat_g or 0 for n in logs) / days
    planner = MealPlanner()
    analysis = await planner.analyze_nutrient_gaps(
        avg_cal, avg_protein, avg_carbs, avg_fat, kalorien_ziel, protein_ziel_g
    )
    return {"analysis": analysis, "averages": {
        "kalorien": round(avg_cal), "protein_g": round(avg_protein, 1),
        "kohlenhydrate_g": round(avg_carbs, 1), "fett_g": round(avg_fat, 1),
    }}


@router.post("/trigger-monitor")
async def trigger_monitor(
    current_user: User = Depends(get_current_user),
):
    """Triggert den autonomen Monitor manuell (für Tests). Nur im Dev-Modus verfügbar."""
    if not settings.dev_mode:
        raise HTTPException(status_code=403, detail="Nur im Dev-Modus verfügbar")
    from app.services.autonomous_monitor import run_autonomous_monitor
    import asyncio
    asyncio.create_task(run_autonomous_monitor())
    return {"status": "Monitor gestartet (läuft im Hintergrund)"}
```

**Außerdem:** Den `select` Import oben in `coach.py` hinzufügen falls nicht vorhanden:
```python
from sqlalchemy import select
```

---

## 10. Implementierungsreihenfolge

Implementiere in **genau dieser Reihenfolge**:

1. **Prüfe `meal_planner.py`** — lies sie, stelle sicher beide Methoden sind vollständig implementiert
2. **Erstelle `app/services/langchain_agent.py`** — komplette neue Datei
3. **Erstelle `app/services/autonomous_monitor.py`** — komplette neue Datei
4. **Erstelle `app/services/sleep_coach.py`** — komplette neue Datei
5. **Erweitere `app/scheduler/jobs.py`** — 3 Funktionen am Ende hinzufügen
6. **Erweitere `app/scheduler/runner.py`** — Import + 3 add_job Aufrufe
7. **Erweitere `app/api/routes/coach.py`** — LangChainCoachAgent + 3 neue Endpoints

---

## 11. Wichtige Hinweise für den implementierenden Agent

### LangChain Tool-Kompatibilität
- Das aktuelle Modell (`moonshotai/kimi-k2-instruct`) unterstützt Function Calling via OpenAI-API.
- `create_openai_tools_agent` ist der richtige Choice — nicht `create_react_agent`.
- Falls das Modell kein Tool Calling kann → Der Fallback in `LangChainCoachAgent.stream()` greift automatisch auf den alten `CoachAgent` zurück.

### Async Tools in LangChain
- LangChain's `@tool` Decorator unterstützt async Funktionen.
- Die DB-Session wird via Closure injiziert — das ist korrekt und sicher.

### SSE Streaming Format
- Der Frontend erwartet: `data: <text>\n\n` und `data: [DONE]\n\n`
- Newlines im Text müssen escaped werden: `text.replace("\n", "\ndata: ")`
- Das ist bereits im `langchain_agent.py` Code implementiert.

### Docker Restart nach Änderungen
- Nach jeder Code-Änderung: `docker-compose restart backend`
- Der Backend-Container hat kein automatisches Hot-Reload auf macOS/Docker.

### Zirkuläre Imports vermeiden
- Lazy Imports (innerhalb der Funktionen) in `jobs.py` verwenden — wie oben gezeigt.
- `LangChainCoachAgent` importiert `MealPlanner` nur wenn das Tool aufgerufen wird — das ist bereits so implementiert.

### requirements.txt
- `langchain>=0.3.0`, `langchain-openai>=0.2.0`, `langchain-core>=0.3.0` sind bereits hinzugefügt.
- Docker-Image muss neu gebaut werden: `docker-compose build backend`

---

## 12. Test-Checkliste

Nach der Implementierung diese Tests durchführen:

```bash
# 1. Docker bauen & starten
docker-compose build backend
docker-compose up -d

# 2. Backend-Logs prüfen (kein ImportError?)
docker-compose logs backend --tail=50

# 3. Scheduler-Jobs prüfen
docker-compose logs scheduler --tail=20

# 4. Chat testen (LangChain Agent)
curl -X POST http://localhost/api/coach/chat \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"message": "Wie sehen meine heutigen Metriken aus?"}' \
  --no-buffer

# 5. Meal Plan testen
curl -X POST http://localhost/api/coach/meal-plan \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"kalorien_ziel": 2200, "protein_ziel_g": 150}'

# 6. Nutrition Gaps testen
curl http://localhost/api/coach/nutrition-gaps \
  -H "Authorization: Bearer <TOKEN>"

# 7. Monitor manuell triggern (nur DEV)
curl -X POST http://localhost/api/coach/trigger-monitor \
  -H "Authorization: Bearer <TOKEN>"
```

**Erwartetes Verhalten:**
- Chat Endpoint streamt SSE-Chunks, Agent ruft Tools auf (in Logs sichtbar bei verbose=True)
- Meal Plan gibt Markdown-Text mit 7 Tagen Speiseplan und Rezepten zurück
- Kein `ImportError`, kein `AttributeError`

---

## 13. Dateistruktur nach Implementierung

```
backend/app/services/
├── coach_agent.py          ← UNVERÄNDERT (Fallback)
├── langchain_agent.py      ← NEU ✓
├── autonomous_monitor.py   ← NEU ✓
├── sleep_coach.py          ← NEU ✓
├── meal_planner.py         ← BEREITS ERSTELLT, evtl. vervollständigt
├── ai_memory.py            ← UNVERÄNDERT
├── training_planner.py     ← UNVERÄNDERT
├── recovery_scorer.py      ← UNVERÄNDERT
└── ...

backend/app/scheduler/
├── jobs.py                 ← ERWEITERT (3 neue Funktionen)
└── runner.py               ← ERWEITERT (Import + 3 add_job)

backend/app/api/routes/
└── coach.py                ← ERWEITERT (LangChain + 3 neue Endpoints)

backend/
└── requirements.txt        ← BEREITS ERWEITERT (langchain Packages)
```
