from datetime import date, timedelta, datetime, timezone
import asyncio
import json
import uuid as uuid_module
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update, case, literal_column
from app.core.database import get_db
from app.api.dependencies import get_current_user
from app.models.user import User
from app.models.training import TrainingPlan
from app.services.training_planner import TrainingPlanner
from app.services.recovery_scorer import RecoveryScorer
from app.models.metrics import HealthMetric, DailyWellbeing
from app.core.config import settings

router = APIRouter()

# ─── Redis Cache Helpers ──────────────────────────────────────────────────────
from app.core.redis import cache_get as _cache_get, cache_set as _cache_set, cache_del as _cache_del


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
    """Return the training plan for the specified week (7 days). Cached in Redis."""
    today = date.today()
    if week:
        try:
            week_start = date.fromisoformat(week)
        except ValueError:
            raise HTTPException(
                status_code=422, detail="Ungültiges Datumsformat. Erwartet: YYYY-MM-DD"
            )
    else:
        week_start = today - timedelta(days=today.weekday())

    week_end = week_start + timedelta(days=7)
    cache_key = f"plan:{current_user.id}:{week_start.isoformat()}"

    # Only use cache for current/future weeks (past weeks don't change)
    use_cache = week_start >= today - timedelta(days=today.weekday())
    if use_cache:
        cached = await _cache_get(cache_key)
        if cached:
            return cached

    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    # Run plan + today's metric queries in parallel
    plan_q = db.execute(
        select(TrainingPlan)
        .where(
            TrainingPlan.user_id == current_user.id,
            TrainingPlan.date >= week_start,
            TrainingPlan.date < week_end,
        )
        .order_by(TrainingPlan.date)
    )
    metric_q = db.execute(
        select(HealthMetric)
        .where(
            HealthMetric.user_id == current_user.id,
            HealthMetric.recorded_at >= today_start,
        )
        .order_by(HealthMetric.recorded_at.desc())
        .limit(1)
    )
    plan_result, metric_result = await asyncio.gather(plan_q, metric_q)

    plans = plan_result.scalars().all()
    metric = metric_result.scalars().first()

    planner = TrainingPlanner()

    # Generate plan if it doesn't exist yet
    if not plans:
        plans = await planner.generate_week_plan(str(current_user.id), week_start, db)

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
    output = []
    for plan in plans:
        plan_dict = plan_to_dict(plan)
        if plan.date == today:
            plan_dict = await planner.adjust_for_recovery(plan_dict, recovery_score)
        output.append(plan_dict)

    if use_cache:
        # Cache for 5 minutes; invalidated on complete/skip mutations
        await _cache_set(cache_key, output, ttl=300)
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
    try:
        plan_uuid = uuid_module.UUID(plan_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Plan nicht gefunden")

    # Direct UPDATE — avoids SELECT + ORM load round-trip
    date_q = await db.execute(
        select(TrainingPlan.date).where(
            TrainingPlan.id == plan_uuid,
            TrainingPlan.user_id == current_user.id,
        )
    )
    plan_date = date_q.scalar_one_or_none()
    if plan_date is None:
        raise HTTPException(status_code=404, detail="Plan nicht gefunden")

    await db.execute(
        update(TrainingPlan)
        .where(TrainingPlan.id == plan_uuid)
        .values(status="completed", completed_at=datetime.now(timezone.utc))
    )
    await db.flush()
    week_start = plan_date - timedelta(days=plan_date.weekday())
    await _cache_del(
        f"plan:{current_user.id}:{week_start.isoformat()}",
        f"achievements:{current_user.id}",
    )
    return {"status": "completed", "id": str(plan_uuid)}


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
    try:
        plan_uuid = uuid_module.UUID(plan_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Plan nicht gefunden")

    # Fetch only the date column needed for cache-key generation
    date_q = await db.execute(
        select(TrainingPlan.date).where(
            TrainingPlan.id == plan_uuid,
            TrainingPlan.user_id == current_user.id,
        )
    )
    plan_date = date_q.scalar_one_or_none()
    if plan_date is None:
        raise HTTPException(status_code=404, detail="Plan nicht gefunden")

    values: dict = {"status": "skipped"}
    if body.reason:
        values["coach_reasoning"] = f"Übersprungen: {body.reason}"
    await db.execute(
        update(TrainingPlan)
        .where(TrainingPlan.id == plan_uuid)
        .values(**values)
    )
    await db.flush()
    week_start = plan_date - timedelta(days=plan_date.weekday())
    await _cache_del(
        f"plan:{current_user.id}:{week_start.isoformat()}",
        f"achievements:{current_user.id}",
    )
    return {"status": "skipped", "id": str(plan_uuid)}


@router.get("/stats")
async def get_training_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Return training statistics for the last 4 weeks.
    All aggregations are pushed to the DB — no Python-side loops over ORM objects.
    """
    today = date.today()
    four_weeks_ago = today - timedelta(days=28)

    # Single SQL query: count/sum per status + per sport in one pass
    agg_result = await db.execute(
        select(
            func.count().label("total_planned"),
            func.sum(
                case((TrainingPlan.status == "completed", 1), else_=0)
            ).label("total_completed"),
            func.sum(
                case((TrainingPlan.status == "skipped", 1), else_=0)
            ).label("total_skipped"),
            func.sum(
                case(
                    (TrainingPlan.status == "completed", func.coalesce(TrainingPlan.duration_min, 0)),
                    else_=0,
                )
            ).label("total_duration_min"),
        ).where(
            TrainingPlan.user_id == current_user.id,
            TrainingPlan.date >= four_weeks_ago,
            TrainingPlan.date <= today,
        )
    )
    agg = agg_result.one()
    total_planned = agg.total_planned or 0

    if total_planned == 0:
        return {
            "completion_rate": 0.0,
            "total_planned": 0,
            "total_completed": 0,
            "total_skipped": 0,
            "total_duration_min": 0,
            "by_sport": {},
            "weekly_volume": [],
        }

    total_completed = int(agg.total_completed or 0)
    total_skipped = int(agg.total_skipped or 0)
    total_duration = int(agg.total_duration_min or 0)
    completion_rate = round(total_completed / total_planned, 2) if total_planned > 0 else 0.0

    # Sport breakdown — aggregate completed counts per sport in DB
    sport_col = TrainingPlan.sport
    sport_result = await db.execute(
        select(
            sport_col,
            func.count().label("cnt"),
        )
        .where(
            TrainingPlan.user_id == current_user.id,
            TrainingPlan.date >= four_weeks_ago,
            TrainingPlan.date <= today,
            TrainingPlan.status == "completed",
        )
        .group_by(sport_col)
    )
    by_sport = {row.sport: row.cnt for row in sport_result}

    # Weekly volume — only need date + status + duration_min columns
    # Use a minimal-column query to reduce data transfer
    week_rows_result = await db.execute(
        select(TrainingPlan.date, TrainingPlan.status, TrainingPlan.duration_min)
        .where(
            TrainingPlan.user_id == current_user.id,
            TrainingPlan.date >= four_weeks_ago,
            TrainingPlan.date <= today,
        )
    )
    today_monday = today - timedelta(days=today.weekday())
    week_buckets: dict[str, dict] = {}
    for offset in range(4):
        wm = today_monday - timedelta(weeks=offset)
        week_buckets[wm.isoformat()] = {"week_start": wm.isoformat(), "planned": 0, "completed": 0, "duration_min": 0}
    for row in week_rows_result:
        p_monday = row.date - timedelta(days=row.date.weekday())
        key = p_monday.isoformat()
        if key in week_buckets:
            week_buckets[key]["planned"] += 1
            if row.status == "completed":
                week_buckets[key]["completed"] += 1
                week_buckets[key]["duration_min"] += row.duration_min or 0

    weekly_volume = sorted(week_buckets.values(), key=lambda w: w["week_start"])

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
    # Only SELECT the date column — no need to load all fields
    result = await db.execute(
        select(TrainingPlan.date)
        .where(
            TrainingPlan.user_id == current_user.id,
            TrainingPlan.status == "completed",
        )
        .order_by(TrainingPlan.date.desc())
    )
    rows = result.scalars().all()

    if not rows:
        return {"current_streak": 0, "longest_streak": 0, "last_active": ""}

    # Deduplicate dates
    completed_dates = sorted(set(rows), reverse=True)

    today = date.today()
    yesterday = today - timedelta(days=1)

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
        "icon": "Trophy",
    },
    {
        "id": "streak_3",
        "title": "Dreifachstart",
        "description": "3 Tage in Folge trainiert",
        "icon": "Flame",
    },
    {
        "id": "streak_7",
        "title": "Wochensieg",
        "description": "7 Tage in Folge trainiert",
        "icon": "Zap",
    },
    {
        "id": "streak_30",
        "title": "Eiserner Wille",
        "description": "30 Tage in Folge trainiert",
        "icon": "Dumbbell",
    },
    {
        "id": "recovery_master",
        "title": "Recovery Master",
        "description": "7 Tage perfekte Recovery",
        "icon": "Heart",
    },
    {
        "id": "early_bird",
        "title": "Früher Vogel",
        "description": "5 Workouts vor 8 Uhr morgens",
        "icon": "Sunrise",
    },
    {
        "id": "volume_10h",
        "title": "Zeitmeister",
        "description": "10 Stunden Trainingsvolumen in einer Woche",
        "icon": "Timer",
    },
    {
        "id": "plan_complete",
        "title": "Perfekte Woche",
        "description": "Alle Workouts einer Woche abgeschlossen",
        "icon": "CheckCircle2",
    },
]


@router.get("/achievements")
async def get_achievements(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return achievements with unlock status. Cached in Redis for 10 min."""
    cache_key = f"achievements:{current_user.id}"
    cached = await _cache_get(cache_key)
    if cached:
        return cached

    # Fetch training plans and wellbeing in parallel
    plans_q = db.execute(
        select(TrainingPlan)
        .where(TrainingPlan.user_id == current_user.id)
        .order_by(TrainingPlan.date.asc())
    )
    wellbeing_q = db.execute(
        select(DailyWellbeing)
        .where(DailyWellbeing.user_id == current_user.id)
        .order_by(DailyWellbeing.date.asc())
    )
    plans_result, wellbeing_result = await asyncio.gather(plans_q, wellbeing_q)

    all_plans = plans_result.scalars().all()
    wellbeing_rows = wellbeing_result.scalars().all()

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

    # Weekly volume check: any week with >= 600 min completed  (O(n) statt O(n²))
    weekly_600 = False
    _vol_by_week: dict[date, int] = {}
    for p in completed:
        ws = p.date - timedelta(days=p.date.weekday())
        _vol_by_week[ws] = _vol_by_week.get(ws, 0) + (p.duration_min or 0)
    weekly_600 = any(v >= 600 for v in _vol_by_week.values())

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

    unlock_dates: dict[str, str | None] = {d["id"]: None for d in ACHIEVEMENT_DEFINITIONS}

    if completed:
        unlock_dates["first_workout"] = completed_dates[0].isoformat() if completed_dates else None

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

    # Early bird: 5 workouts completed before 8:00 local time (use UTC hour as proxy)
    early_bird_count = 0
    early_bird_date: str | None = None
    for p in sorted(completed, key=lambda x: x.completed_at or datetime.min.replace(tzinfo=timezone.utc)):
        if p.completed_at is not None:
            hour = p.completed_at.astimezone(timezone.utc).hour
            if hour < 8:
                early_bird_count += 1
                if early_bird_count >= 5:
                    early_bird_date = p.completed_at.date().isoformat()
                    break
    if early_bird_date:
        unlock_dates["early_bird"] = early_bird_date

    if weekly_600:
        unlock_dates["volume_10h"] = completed[-1].date.isoformat() if completed else None
    if perfect_week:
        unlock_dates["plan_complete"] = completed[-1].date.isoformat() if completed else None

    result = [
        {**defn, "unlocked_at": unlock_dates.get(defn["id"])}
        for defn in ACHIEVEMENT_DEFINITIONS
    ]
    await _cache_set(cache_key, result, ttl=600)
    return result
