import json
import httpx
import uuid as uuid_module
from datetime import date, timedelta
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.config import settings
from app.models.training import TrainingPlan, UserGoal



class TrainingPlanner:
    """Generates daily and weekly training plans based on user goals and recovery data."""

    WEEKDAYS_DE = [
        "Montag",
        "Dienstag",
        "Mittwoch",
        "Donnerstag",
        "Freitag",
        "Samstag",
        "Sonntag",
    ]

    async def generate_week_plan(
        self, user_id: str, week_start: date, db: AsyncSession
    ) -> list[dict]:
        """Generiert Trainingsplan für eine Woche via LLM."""
        uid = uuid_module.UUID(user_id) if isinstance(user_id, str) else user_id
        logger.info(
            f"Generating training plan | user={user_id} | week_start={week_start}"
        )
        # User-Ziele laden
        goals_result = await db.execute(select(UserGoal).where(UserGoal.user_id == uid))
        goals = goals_result.scalars().all()

        if not goals:
            goals_desc = "Allgemeines Ausdauertraining, 5 Stunden/Woche, intermediate"
            sport = "Laufen"
            weekly_hours = 5
            fitness_level = "intermediate"
        else:
            g = goals[0]
            sport = g.sport
            weekly_hours = g.weekly_hours
            fitness_level = g.fitness_level
            goals_desc = g.goal_description

        # Letzte 2 Wochen Historie laden
        two_weeks_ago = week_start - timedelta(days=14)
        history_result = await db.execute(
            select(TrainingPlan).where(
                TrainingPlan.user_id == uid,
                TrainingPlan.date >= two_weeks_ago,
                TrainingPlan.date < week_start,
            )
        )
        history = history_result.scalars().all()
        history_text = (
            ", ".join(
                [
                    f"{h.date}: {h.workout_type} ({h.duration_min}min)"
                    for h in history[-10:]
                ]
            )
            or "Keine bisherige Historie"
        )

        week_dates = [week_start + timedelta(days=i) for i in range(7)]
        dates_text = ", ".join([d.isoformat() for d in week_dates])

        prompt = f"""Erstelle einen 7-Tage Trainingsplan.

Kontext:
- Sport: {sport}
- Ziel: {goals_desc}
- Fitnesslevel: {fitness_level}
- Geplante Wochenstunden: {weekly_hours}
- Historie: {history_text}
- Wochentage: {dates_text}

Antworte NUR mit einem JSON Array (kein Markdown, kein Code-Block), genau 7 Einträge:
[
  {{
    "date": "2024-03-17",
    "sport": "{sport}",
    "workout_type": "easy_run",
    "duration_min": 45,
    "intensity_zone": 2,
    "target_hr_min": 130,
    "target_hr_max": 145,
    "description": "Lockerer Dauerlauf",
    "coach_reasoning": "Erholungseinheit nach intensivem Training"
  }}
]

workout_type Werte: easy_run, tempo_run, interval, long_run, rest, cross_training, swim, bike
intensity_zone: 1-5 (1=sehr leicht, 5=maximal)"""

        plans_data = []
        try:
            if not settings.active_llm_api_key:
                raise RuntimeError("LLM not configured")

            headers = {
                "Authorization": f"Bearer {settings.active_llm_api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": settings.llm_model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 1024,
            }
            async with httpx.AsyncClient(timeout=60.0) as client:
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

            plans_data = json.loads(text)
        except Exception as e:
            logger.warning(
                f"Plan generation failed, using fallback | user={user_id} | error={e}"
            )
            # Fallback: Standard-Plan
            for i, d in enumerate(week_dates):
                if i in [0, 3, 5]:  # Mo, Do, Sa
                    wt = "easy_run" if i != 5 else "long_run"
                    dur = 40 if i != 5 else 75
                elif i == 1:  # Di
                    wt = "cross_training"
                    dur = 30
                elif i == 2:  # Mi
                    wt = "tempo_run"
                    dur = 50
                elif i == 4:  # Fr
                    wt = "rest"
                    dur = 0
                else:  # So
                    wt = "rest"
                    dur = 0

                plans_data.append(
                    {
                        "date": d.isoformat(),
                        "sport": sport,
                        "workout_type": wt,
                        "duration_min": dur,
                        "intensity_zone": 1
                        if wt == "rest"
                        else (4 if wt == "tempo_run" else 2),
                        "target_hr_min": 0 if wt == "rest" else 120,
                        "target_hr_max": 0 if wt == "rest" else 145,
                        "description": "Ruhetag"
                        if wt == "rest"
                        else f"{wt.replace('_', ' ').title()}",
                        "coach_reasoning": "Erholung"
                        if wt == "rest"
                        else "Standard Training",
                    }
                )

        # Bestehenden Plan für diese Woche löschen
        existing_result = await db.execute(
            select(TrainingPlan).where(
                TrainingPlan.user_id == uid,
                TrainingPlan.date >= week_start,
                TrainingPlan.date < week_start + timedelta(days=7),
            )
        )
        for existing in existing_result.scalars():
            await db.delete(existing)
        await db.flush()

        # Neuen Plan speichern
        created = []
        for plan_data in plans_data[:7]:
            plan = TrainingPlan(
                user_id=uid,
                date=date.fromisoformat(plan_data["date"]),
                sport=plan_data.get("sport", sport),
                workout_type=plan_data["workout_type"],
                duration_min=plan_data.get("duration_min", 0),
                intensity_zone=plan_data.get("intensity_zone"),
                target_hr_min=plan_data.get("target_hr_min"),
                target_hr_max=plan_data.get("target_hr_max"),
                description=plan_data.get("description", ""),
                coach_reasoning=plan_data.get("coach_reasoning", ""),
                status="planned",
            )
            db.add(plan)
            created.append(plan)

        await db.flush()
        return created

    async def adjust_for_recovery(self, plan_dict: dict, recovery_score: int) -> dict:
        """Passt einen Trainingsplan basierend auf Recovery Score an."""
        if recovery_score < 40:
            plan_dict["workout_type"] = "rest"
            plan_dict["duration_min"] = 0
            plan_dict["intensity_zone"] = 1
            plan_dict["target_hr_min"] = 0
            plan_dict["target_hr_max"] = 0
            plan_dict["description"] = "Ruhetag - Erholung priorisieren"
            plan_dict["_adjusted"] = True
            plan_dict["_adjustment_reason"] = "Recovery Score unter 40"
        elif recovery_score < 60:
            if plan_dict.get("intensity_zone") and plan_dict["intensity_zone"] > 1:
                plan_dict["intensity_zone"] = max(1, plan_dict["intensity_zone"] - 1)
            if plan_dict.get("duration_min") and plan_dict["duration_min"] > 0:
                plan_dict["duration_min"] = int(plan_dict["duration_min"] * 0.7)
            plan_dict["_adjusted"] = True
            plan_dict["_adjustment_reason"] = (
                "Recovery Score 40-60: Intensität reduziert"
            )
        else:
            plan_dict["_adjusted"] = False

        return plan_dict
