import json
import httpx
import uuid as uuid_module
from datetime import date, timedelta, datetime, timezone
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.config import settings
from app.models.training import TrainingPlan, UserGoal
from app.models.metrics import HealthMetric



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

        # ── Biometrie-Daten aus Garmin/Watch laden ──────────────────────────
        ninety_days_ago = datetime.now(timezone.utc) - timedelta(days=90)
        bio_result = await db.execute(
            select(HealthMetric)
            .where(
                HealthMetric.user_id == uid,
                HealthMetric.recorded_at >= ninety_days_ago,
            )
            .order_by(HealthMetric.recorded_at.desc())
            .limit(30)
        )
        bio_metrics = bio_result.scalars().all()

        # Durchschnitte berechnen
        resting_hrs = [m.resting_hr for m in bio_metrics if m.resting_hr]
        hrvs = [m.hrv for m in bio_metrics if m.hrv]
        vo2s = [m.vo2_max for m in bio_metrics if m.vo2_max]
        sleeps = [m.sleep_duration_min for m in bio_metrics if m.sleep_duration_min]
        stresses = [m.stress_score for m in bio_metrics if m.stress_score]

        avg_resting_hr = round(sum(resting_hrs) / len(resting_hrs)) if resting_hrs else None
        avg_hrv = round(sum(hrvs) / len(hrvs), 1) if hrvs else None
        vo2_max = round(max(vo2s), 1) if vo2s else None
        avg_sleep_h = round(sum(sleeps) / len(sleeps) / 60, 1) if sleeps else None
        avg_stress = round(sum(stresses) / len(stresses)) if stresses else None

        # Max HR aus Aktivitäten (letzter Monat) wenn verfügbar
        from app.models.analytics import ActivityDetail
        max_hr_result = await db.execute(
            select(ActivityDetail.max_heartrate)
            .where(
                ActivityDetail.user_id == uid,
                ActivityDetail.max_heartrate.isnot(None),
            )
            .order_by(ActivityDetail.max_heartrate.desc())
            .limit(1)
        )
        max_hr_row = max_hr_result.scalar_one_or_none()
        max_hr = None
        if max_hr_row:
            _max_hr_val = int(max_hr_row)
            if 100 <= _max_hr_val <= 250:
                max_hr = _max_hr_val
            else:
                logger.warning(f"Ignoring implausible max_hr={_max_hr_val} for user {uid}")

        # Biometrie-Block für Prompt
        bio_lines = []
        if avg_resting_hr:
            bio_lines.append(f"- Ruhepuls (Ø 90 Tage): {avg_resting_hr} bpm")
        if max_hr:
            bio_lines.append(f"- Maximale Herzfrequenz (gemessen): {max_hr} bpm")
        if avg_hrv:
            bio_lines.append(f"- HRV (Ø 90 Tage): {avg_hrv} ms")
        if vo2_max:
            bio_lines.append(f"- VO₂ max: {vo2_max} ml/kg/min")
        if avg_sleep_h:
            bio_lines.append(f"- Schlaf (Ø 90 Tage): {avg_sleep_h} h")
        if avg_stress:
            bio_lines.append(f"- Stresslevel (Ø 90 Tage): {avg_stress} / 100")
        bio_text = "\n".join(bio_lines) if bio_lines else "Keine Biometrie-Daten verfügbar"

        # HR-Zonen-Hilfe für den Prompt
        hr_zone_hint = ""
        if avg_resting_hr and max_hr:
            # Karvonen-Methode: Target HR = Resting HR + (Max HR - Resting HR) × Intensity%
            hr_reserve = max_hr - avg_resting_hr
            z1 = (avg_resting_hr + int(hr_reserve * 0.50), avg_resting_hr + int(hr_reserve * 0.60))
            z2 = (avg_resting_hr + int(hr_reserve * 0.60), avg_resting_hr + int(hr_reserve * 0.70))
            z3 = (avg_resting_hr + int(hr_reserve * 0.70), avg_resting_hr + int(hr_reserve * 0.80))
            z4 = (avg_resting_hr + int(hr_reserve * 0.80), avg_resting_hr + int(hr_reserve * 0.90))
            z5 = (avg_resting_hr + int(hr_reserve * 0.90), max_hr)
            hr_zone_hint = f"""
HR-Zonen des Users (Karvonen-Methode, BENUTZE DIESE WERTE):
  Zone 1 (Erholung): {z1[0]}–{z1[1]} bpm
  Zone 2 (Grundlage): {z2[0]}–{z2[1]} bpm
  Zone 3 (Tempo): {z3[0]}–{z3[1]} bpm
  Zone 4 (Schwelle): {z4[0]}–{z4[1]} bpm
  Zone 5 (Maximum): {z5[0]}–{z5[1]} bpm"""

        week_dates = [week_start + timedelta(days=i) for i in range(7)]
        dates_text = ", ".join([d.isoformat() for d in week_dates])

        # HR-Zonen-Lookup (Karvonen) – berechne EINMAL, nutze für Prompt + Override + Fallback
        hr_zones: dict[int, tuple[int, int]] = {}
        if avg_resting_hr and max_hr:
            hr_reserve = max_hr - avg_resting_hr
            hr_zones = {
                1: (avg_resting_hr + int(hr_reserve * 0.50), avg_resting_hr + int(hr_reserve * 0.60)),
                2: (avg_resting_hr + int(hr_reserve * 0.60), avg_resting_hr + int(hr_reserve * 0.70)),
                3: (avg_resting_hr + int(hr_reserve * 0.70), avg_resting_hr + int(hr_reserve * 0.80)),
                4: (avg_resting_hr + int(hr_reserve * 0.80), avg_resting_hr + int(hr_reserve * 0.90)),
                5: (avg_resting_hr + int(hr_reserve * 0.90), max_hr),
            }

        prompt = f"""Erstelle einen 7-Tage Trainingsplan basierend auf echten Biometrie-Daten des Users.

Kontext:
- Sport: {sport}
- Ziel: {goals_desc}
- Fitnesslevel: {fitness_level}
- Geplante Wochenstunden: {weekly_hours}
- Historie: {history_text}
- Wochentage: {dates_text}

Biometrie (von Sportuhr):
{bio_text}
{hr_zone_hint}

WICHTIG: Verwende die oben angegebenen HR-Zonen für target_hr_min und target_hr_max.
Wenn keine HR-Zonen angegeben sind, verwende KEINE Herzfrequenz-Werte (setze null).

Antworte NUR mit einem JSON Array (kein Markdown, kein Code-Block), genau 7 Einträge:
[
  {{
    "date": "2024-03-17",
    "sport": "{sport}",
    "workout_type": "easy_run",
    "duration_min": 45,
    "intensity_zone": 2,
    "target_hr_min": 125,
    "target_hr_max": 140,
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
                f"LLM plan generation failed, using deterministic fallback | user={user_id} | error={e}"
            )
            plans_data = self._deterministic_week(
                sport, weekly_hours, fitness_level, week_start, hr_zones,
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
        valid_dates = {(week_start + timedelta(days=i)).isoformat() for i in range(7)}
        for plan_data in plans_data[:7]:
            plan_date_str = plan_data.get("date", "")
            if plan_date_str not in valid_dates:
                logger.warning(
                    f"LLM returned out-of-range date '{plan_date_str}' for user={user_id}, skipping"
                )
                continue

            # Override HR zones from Karvonen calculation (don't trust LLM)
            zone = plan_data.get("intensity_zone")
            if zone is not None:
                try:
                    zone = int(zone)
                    plan_data["intensity_zone"] = zone
                except (ValueError, TypeError):
                    zone = None
            if zone and hr_zones and zone in hr_zones:
                plan_data["target_hr_min"] = hr_zones[zone][0]
                plan_data["target_hr_max"] = hr_zones[zone][1]

            plan = TrainingPlan(
                user_id=uid,
                date=date.fromisoformat(plan_date_str),
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

    @staticmethod
    def _deterministic_week(
        sport: str,
        weekly_hours: float,
        fitness_level: str,
        week_start: date,
        hr_zones: dict[int, tuple[int, int]],
    ) -> list[dict]:
        """Hard-coded 7-day template used when the LLM is unreachable."""
        templates = {
            "beginner": [
                ("rest", 0, 1),
                ("easy_run", 30, 1),
                ("rest", 0, 1),
                ("easy_run", 35, 2),
                ("rest", 0, 1),
                ("long_run", 40, 2),
                ("rest", 0, 1),
            ],
            "intermediate": [
                ("easy_run", 40, 2),
                ("interval", 35, 4),
                ("easy_run", 35, 1),
                ("tempo_run", 40, 3),
                ("rest", 0, 1),
                ("long_run", 60, 2),
                ("easy_run", 30, 1),
            ],
            "advanced": [
                ("easy_run", 45, 2),
                ("interval", 45, 4),
                ("easy_run", 40, 1),
                ("tempo_run", 50, 3),
                ("interval", 40, 4),
                ("long_run", 75, 2),
                ("easy_run", 30, 1),
            ],
        }
        template = templates.get(fitness_level, templates["intermediate"])

        # Scale durations so total matches weekly_hours
        total_template_min = sum(t[1] for t in template)
        target_min = weekly_hours * 60
        scale = target_min / total_template_min if total_template_min else 1

        descriptions = {
            "rest": "Ruhetag – aktive Erholung",
            "easy_run": "Lockerer Dauerlauf",
            "interval": "Intervalltraining",
            "tempo_run": "Tempolauf",
            "long_run": "Langer Dauerlauf",
            "cross_training": "Alternatives Training",
        }

        plans: list[dict] = []
        for i, (wtype, dur, zone) in enumerate(template):
            d = week_start + timedelta(days=i)
            hr_min, hr_max = hr_zones.get(zone, (None, None))  # type: ignore[assignment]
            scaled_dur = round(dur * scale) if dur else 0
            plans.append({
                "date": d.isoformat(),
                "sport": sport,
                "workout_type": wtype,
                "duration_min": scaled_dur,
                "intensity_zone": zone,
                "target_hr_min": hr_min,
                "target_hr_max": hr_max,
                "description": descriptions.get(wtype, wtype),
                "coach_reasoning": "Automatisch generiert (LLM nicht verfügbar)",
            })
        return plans

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
