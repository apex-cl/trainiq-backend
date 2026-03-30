from datetime import date, timedelta, datetime, timezone
import uuid as uuid_module
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.core.database import get_db
from app.api.dependencies import get_current_user
from app.models.user import User
from app.models.training import TrainingPlan
from app.services.training_planner import TrainingPlanner
from app.services.recovery_scorer import RecoveryScorer
from app.models.metrics import HealthMetric, DailyWellbeing

router = APIRouter()


def plan_to_dict(plan: TrainingPlan) -> dict:
    return {
        "id": str(plan.id),
        "date": plan.date.isoformat(),
        "sport": plan.sport,
        "workout_type": plan.workout_type,
        "duration_min": plan.duration_min,
        "intensity_zone": plan.intensity_zone,
        "target_hr_min": plan.target_hr_min,
        "target_hr_max": plan.target_hr_max,
        "description": plan.description,
        "coach_reasoning": plan.coach_reasoning,
        "status": plan.status,
    }


@router.get("/plan")
async def get_week_plan(
    week: str = Query(default=None, description="Week start date, e.g. 2024-03-17"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the training plan for the specified week (7 days)."""
    today = date.today()
    if week:
        week_start = date.fromisoformat(week)
    else:
        # Aktuelle Woche (Montag als Start)
        week_start = today - timedelta(days=today.weekday())

    week_end = week_start + timedelta(days=7)

    # Plan aus DB laden
    result = await db.execute(
        select(TrainingPlan)
        .where(
            TrainingPlan.user_id == current_user.id,
            TrainingPlan.date >= week_start,
            TrainingPlan.date < week_end,
        )
        .order_by(TrainingPlan.date)
    )
    plans = result.scalars().all()

    # Falls kein Plan existiert: automatisch erstellen
    if not plans:
        planner = TrainingPlanner()
        plans = await planner.generate_week_plan(str(current_user.id), week_start, db)

    # Recovery Score laden für Anpassungen
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    metric_result = await db.execute(
        select(HealthMetric)
        .where(
            HealthMetric.user_id == current_user.id,
            HealthMetric.recorded_at >= today_start,
        )
        .order_by(HealthMetric.recorded_at.desc())
        .limit(1)
    )
    metric = metric_result.scalars().first()
    recovery_score = 70  # Default
    if metric:
        scorer = RecoveryScorer()
        recovery_result = scorer.calculate_recovery_score(
            {
                "hrv": metric.hrv,
                "sleep_duration_min": metric.sleep_duration_min,
                "stress_score": metric.stress_score,
                "resting_hr": metric.resting_hr,
            }
        )
        recovery_score = recovery_result["score"]

    # Plan mit Recovery Score anpassen
    planner = TrainingPlanner()
    output = []
    for plan in plans:
        plan_dict = plan_to_dict(plan)
        if plan.date == today:
            plan_dict = await planner.adjust_for_recovery(plan_dict, recovery_score)
        output.append(plan_dict)

    return output


@router.get("/plan/{plan_date}")
async def get_day_plan(
    plan_date: date,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the training plan for a specific date."""
    result = await db.execute(
        select(TrainingPlan).where(
            TrainingPlan.user_id == current_user.id,
            TrainingPlan.date == plan_date,
        )
    )
    plan = result.scalars().first()

    if not plan:
        raise HTTPException(
            status_code=404, detail="Kein Plan für dieses Datum gefunden"
        )

    return plan_to_dict(plan)


@router.post("/complete/{plan_id}")
async def mark_complete(
    plan_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark a training session as completed."""
    plan_uuid = uuid_module.UUID(plan_id)
    result = await db.execute(
        select(TrainingPlan).where(
            TrainingPlan.id == plan_uuid,
            TrainingPlan.user_id == current_user.id,
        )
    )
    plan = result.scalars().first()

    if not plan:
        raise HTTPException(status_code=404, detail="Plan nicht gefunden")

    plan.status = "completed"
    await db.flush()
    return {"status": "completed", "id": str(plan.id)}


class SkipRequest(BaseModel):
    reason: str = ""


@router.post("/skip/{plan_id}")
async def skip_workout(
    plan_id: str,
    body: SkipRequest = SkipRequest(),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Skip a training session with an optional reason."""
    plan_uuid = uuid_module.UUID(plan_id)
    result = await db.execute(
        select(TrainingPlan).where(
            TrainingPlan.id == plan_uuid,
            TrainingPlan.user_id == current_user.id,
        )
    )
    plan = result.scalars().first()

    if not plan:
        raise HTTPException(status_code=404, detail="Plan nicht gefunden")

    plan.status = "skipped"
    if body.reason:
        plan.coach_reasoning = f"Übersprungen: {body.reason}"
    await db.flush()
    return {"status": "skipped", "id": str(plan.id)}


@router.get("/stats")
async def get_training_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Return training statistics for the last 4 weeks.
    Includes completion rate, total volume, and weekly breakdown.
    """
    today = date.today()
    four_weeks_ago = today - timedelta(days=28)

    # Alle Pläne der letzten 4 Wochen laden
    result = await db.execute(
        select(TrainingPlan).where(
            TrainingPlan.user_id == current_user.id,
            TrainingPlan.date >= four_weeks_ago,
            TrainingPlan.date <= today,
        )
    )
    plans = result.scalars().all()

    if not plans:
        return {
            "completion_rate": 0.0,
            "total_planned": 0,
            "total_completed": 0,
            "total_skipped": 0,
            "total_duration_min": 0,
            "by_sport": {},
            "weekly_volume": [],
        }

    total_planned = len(plans)
    total_completed = sum(1 for p in plans if p.status == "completed")
    total_skipped = sum(1 for p in plans if p.status == "skipped")
    total_duration = sum(
        (p.duration_min or 0) for p in plans if p.status == "completed"
    )
    completion_rate = (
        round(total_completed / total_planned, 2) if total_planned > 0 else 0.0
    )

    # Sport-Verteilung (nur abgeschlossene)
    by_sport: dict[str, int] = {}
    for p in plans:
        if p.status == "completed":
            sport = p.sport or "other"
            by_sport[sport] = by_sport.get(sport, 0) + 1

    # Wöchentliches Volumen (4 Wochen, jeweils Montag als Wochenstart)
    weekly_volume = []
    for week_offset in range(3, -1, -1):  # 3, 2, 1, 0 → älteste zuerst
        week_monday = (
            today - timedelta(days=today.weekday()) - timedelta(weeks=week_offset)
        )
        week_sunday = week_monday + timedelta(days=6)

        week_plans = [p for p in plans if week_monday <= p.date <= week_sunday]
        week_completed = sum(1 for p in week_plans if p.status == "completed")
        week_planned = len(week_plans)
        week_duration = sum(
            (p.duration_min or 0) for p in week_plans if p.status == "completed"
        )

        weekly_volume.append(
            {
                "week_start": week_monday.isoformat(),
                "planned": week_planned,
                "completed": week_completed,
                "duration_min": week_duration,
            }
        )

    return {
        "completion_rate": completion_rate,
        "total_planned": total_planned,
        "total_completed": total_completed,
        "total_skipped": total_skipped,
        "total_duration_min": total_duration,
        "by_sport": by_sport,
        "weekly_volume": weekly_volume,
    }


@router.get("/streak")
async def get_streak(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the current and longest training streak (consecutive completed days)."""
    result = await db.execute(
        select(TrainingPlan)
        .where(
            TrainingPlan.user_id == current_user.id,
            TrainingPlan.status == "completed",
        )
        .order_by(TrainingPlan.date.desc())
    )
    completed = result.scalars().all()

    if not completed:
        return {"current_streak": 0, "longest_streak": 0, "last_active": ""}

    # Deduplicate dates (one day can have multiple plans)
    completed_dates = sorted({p.date for p in completed}, reverse=True)

    today = date.today()
    yesterday = today - timedelta(days=1)

    # Current streak: consecutive days ending at today or yesterday
    current_streak = 0
    if completed_dates and completed_dates[0] in (today, yesterday):
        current_streak = 1
        prev = completed_dates[0]
        for d in completed_dates[1:]:
            if (prev - d).days == 1:
                current_streak += 1
                prev = d
            else:
                break

    # Longest streak
    longest_streak = 0
    streak = 1
    for i in range(1, len(completed_dates)):
        if (completed_dates[i - 1] - completed_dates[i]).days == 1:
            streak += 1
            longest_streak = max(longest_streak, streak)
        else:
            streak = 1
    longest_streak = max(longest_streak, streak if completed_dates else 0)

    last_active = completed_dates[0].isoformat() if completed_dates else ""
    return {
        "current_streak": current_streak,
        "longest_streak": longest_streak,
        "last_active": last_active,
    }


ACHIEVEMENT_DEFINITIONS = [
    {
        "id": "first_workout",
        "title": "Erster Schritt",
        "description": "Erstes Training abgeschlossen",
        "icon": "🏅",
    },
    {
        "id": "streak_3",
        "title": "Dreifachstart",
        "description": "3 Tage in Folge trainiert",
        "icon": "🔥",
    },
    {
        "id": "streak_7",
        "title": "Wochensieg",
        "description": "7 Tage in Folge trainiert",
        "icon": "⚡",
    },
    {
        "id": "streak_30",
        "title": "Eiserner Wille",
        "description": "30 Tage in Folge trainiert",
        "icon": "💪",
    },
    {
        "id": "recovery_master",
        "title": "Recovery Master",
        "description": "7 Tage perfekte Recovery",
        "icon": "🧘",
    },
    {
        "id": "early_bird",
        "title": "Früher Vogel",
        "description": "5 Workouts vor 8 Uhr morgens",
        "icon": "🌅",
    },
    {
        "id": "volume_10h",
        "title": "Zeitmeister",
        "description": "10 Stunden Trainingsvolumen in einer Woche",
        "icon": "⏱️",
    },
    {
        "id": "plan_complete",
        "title": "Perfekte Woche",
        "description": "Alle Workouts einer Woche abgeschlossen",
        "icon": "✅",
    },
]


@router.get("/achievements")
async def get_achievements(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return achievements with unlock status based on training history."""
    result = await db.execute(
        select(TrainingPlan)
        .where(TrainingPlan.user_id == current_user.id)
        .order_by(TrainingPlan.date.asc())
    )
    all_plans = result.scalars().all()

    completed = [p for p in all_plans if p.status == "completed"]
    completed_dates = sorted({p.date for p in completed})

    # Streak calculation
    max_streak = 0
    streak = 1
    for i in range(1, len(completed_dates)):
        if (completed_dates[i] - completed_dates[i - 1]).days == 1:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 1
    max_streak = max(max_streak, streak if completed_dates else 0)

    # Weekly volume check: any week with >= 600 min completed
    weekly_600 = False
    for i in range(0, len(completed)):
        week_start_d = completed[i].date - timedelta(days=completed[i].date.weekday())
        week_end_d = week_start_d + timedelta(days=7)
        week_vol = sum(
            (p.duration_min or 0)
            for p in completed
            if week_start_d <= p.date < week_end_d
        )
        if week_vol >= 600:
            weekly_600 = True
            break

    # Perfect week: all plans in any week were completed
    perfect_week = False
    if all_plans:
        from collections import defaultdict
        weeks: dict[date, list] = defaultdict(list)
        for p in all_plans:
            ws = p.date - timedelta(days=p.date.weekday())
            weeks[ws].append(p)
        for ws, wplans in weeks.items():
            if wplans and all(p.status == "completed" for p in wplans):
                perfect_week = True
                break

    # Map achievement id → first_unlocked_date
    unlock_dates: dict[str, str | None] = {d["id"]: None for d in ACHIEVEMENT_DEFINITIONS}

    if completed:
        first_completed_date = completed_dates[0].isoformat() if completed_dates else None
        unlock_dates["first_workout"] = first_completed_date

    # Streak-based
    streak_tmp = 1
    for i in range(1, len(completed_dates)):
        if (completed_dates[i] - completed_dates[i - 1]).days == 1:
            streak_tmp += 1
            if streak_tmp >= 3 and unlock_dates["streak_3"] is None:
                unlock_dates["streak_3"] = completed_dates[i].isoformat()
            if streak_tmp >= 7 and unlock_dates["streak_7"] is None:
                unlock_dates["streak_7"] = completed_dates[i].isoformat()
            if streak_tmp >= 30 and unlock_dates["streak_30"] is None:
                unlock_dates["streak_30"] = completed_dates[i].isoformat()
        else:
            streak_tmp = 1

    # High-recovery days: wellbeing mood >= 8 for 7 consecutive days
    wellbeing_result = await db.execute(
        select(DailyWellbeing)
        .where(DailyWellbeing.user_id == current_user.id)
        .order_by(DailyWellbeing.date.asc())
    )
    wellbeing_rows = wellbeing_result.scalars().all()
    good_recovery_days = sorted(
        {w.date for w in wellbeing_rows if (w.mood_score or 0) >= 8}
    )
    recovery_streak = 1
    for i in range(1, len(good_recovery_days)):
        if (good_recovery_days[i] - good_recovery_days[i - 1]).days == 1:
            recovery_streak += 1
            if recovery_streak >= 7:
                unlock_dates["recovery_master"] = good_recovery_days[i].isoformat()
                break
        else:
            recovery_streak = 1

    if weekly_600:
        unlock_dates["volume_10h"] = completed[-1].date.isoformat() if completed else None

    if perfect_week:
        unlock_dates["plan_complete"] = completed[-1].date.isoformat() if completed else None

    return [
        {
            **defn,
            "unlocked_at": unlock_dates.get(defn["id"]),
        }
        for defn in ACHIEVEMENT_DEFINITIONS
    ]
