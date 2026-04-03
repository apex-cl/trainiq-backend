import asyncio
import json
from datetime import date, datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, cast, Date as SADate
from app.core.database import get_db
from app.api.dependencies import get_current_user
from app.models.user import User
from app.models.metrics import HealthMetric, DailyWellbeing
from app.services.recovery_scorer import RecoveryScorer
from app.core.config import settings

router = APIRouter()

# ─── Redis Cache Helpers ──────────────────────────────────────────────────────
from app.core.redis import cache_get as _cache_get, cache_set as _cache_set, cache_del as _cache_del


class WellbeingRequest(BaseModel):
    fatigue_score: int
    mood_score: int
    pain_notes: str | None = None

    @field_validator("fatigue_score", "mood_score")
    @classmethod
    def validate_scores(cls, v: int) -> int:
        if not 1 <= v <= 10:
            raise ValueError("Score muss zwischen 1 und 10 liegen")
        return v

    @field_validator("pain_notes")
    @classmethod
    def validate_pain_notes(cls, v: str | None) -> str | None:
        if v is not None and len(v) > 1000:
            raise ValueError("pain_notes darf maximal 1000 Zeichen lang sein")
        return v


@router.post("/wellbeing")
async def post_wellbeing(
    body: WellbeingRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Submit daily wellbeing data."""
    today = date.today()

    result = await db.execute(
        select(DailyWellbeing).where(
            DailyWellbeing.user_id == current_user.id,
            DailyWellbeing.date == today,
        )
    )
    existing = result.scalars().first()

    if existing:
        existing.fatigue_score = body.fatigue_score
        existing.mood_score = body.mood_score
        existing.pain_notes = body.pain_notes
        await db.flush()
        await _cache_del(f"recovery:{current_user.id}:{today.isoformat()}")
        return {
            "id": str(existing.id),
            "date": today.isoformat(),
            "fatigue_score": existing.fatigue_score,
            "mood_score": existing.mood_score,
            "pain_notes": existing.pain_notes,
        }

    wellbeing = DailyWellbeing(
        user_id=current_user.id,
        date=today,
        fatigue_score=body.fatigue_score,
        mood_score=body.mood_score,
        pain_notes=body.pain_notes,
    )
    db.add(wellbeing)
    await db.flush()
    await _cache_del(f"recovery:{current_user.id}:{today.isoformat()}")
    return {
        "id": str(wellbeing.id),
        "date": today.isoformat(),
        "fatigue_score": wellbeing.fatigue_score,
        "mood_score": wellbeing.mood_score,
        "pain_notes": wellbeing.pain_notes,
    }


@router.get("/today")
async def get_today(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return today's health metrics, falling back to the most recent available entry."""
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    result = await db.execute(
        select(HealthMetric)
        .where(
            HealthMetric.user_id == current_user.id,
            HealthMetric.recorded_at >= today_start,
        )
        .order_by(HealthMetric.recorded_at.desc())
        .limit(5)
    )
    metrics_today = result.scalars().all()

    # Pick the first entry that has at least one real metric value
    metric = None
    for m in metrics_today:
        if any([m.hrv, m.resting_hr, m.sleep_duration_min, m.stress_score, m.steps, m.vo2_max, m.spo2]):
            metric = m
            break

    # Fall back to most recent garmin/watch entry in the last 90 days
    if not metric:
        from sqlalchemy import or_
        ninety_days_ago = datetime.now(timezone.utc) - timedelta(days=90)
        fallback_result = await db.execute(
            select(HealthMetric)
            .where(
                HealthMetric.user_id == current_user.id,
                HealthMetric.recorded_at >= ninety_days_ago,
                HealthMetric.source != "no_data",
                or_(
                    HealthMetric.resting_hr.isnot(None),
                    HealthMetric.hrv.isnot(None),
                    HealthMetric.sleep_duration_min.isnot(None),
                    HealthMetric.stress_score.isnot(None),
                    HealthMetric.vo2_max.isnot(None),
                    HealthMetric.spo2.isnot(None),
                    HealthMetric.steps.isnot(None),
                ),
            )
            .order_by(HealthMetric.recorded_at.desc())
            .limit(1)
        )
        metric = fallback_result.scalars().first()

    if not metric:
        return {
            "hrv": None,
            "resting_hr": None,
            "sleep_duration_min": None,
            "sleep_quality_score": None,
            "stress_score": None,
            "steps": None,
            "spo2": None,
            "vo2_max": None,
            "source": "no_data",
        }

    return {
        "hrv": metric.hrv,
        "resting_hr": metric.resting_hr,
        "sleep_duration_min": metric.sleep_duration_min,
        "sleep_quality_score": metric.sleep_quality_score,
        "stress_score": metric.stress_score,
        "steps": metric.steps,
        "spo2": metric.spo2,
        "vo2_max": metric.vo2_max,
        "source": metric.source,
        "recorded_at": metric.recorded_at.isoformat(),
    }


@router.get("/week")
async def get_week(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return health metrics for the last 30 days, newest entry per day."""
    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)

    # Fetch all records for the last 30 days, then group by date in Python.
    # This is DB-agnostic (works with both PostgreSQL and SQLite for tests).
    result = await db.execute(
        select(HealthMetric)
        .where(
            HealthMetric.user_id == current_user.id,
            HealthMetric.recorded_at >= thirty_days_ago,
        )
        .order_by(HealthMetric.recorded_at.desc())
    )
    metrics = result.scalars().all()

    # Keep only the latest entry per calendar day
    seen_days: dict = {}
    for m in metrics:
        # Skip entries where all metric fields are null (empty sync placeholders)
        if not any([m.hrv, m.resting_hr, m.sleep_duration_min, m.stress_score, m.vo2_max, m.spo2, m.steps]):
            continue
        day = m.recorded_at.date() if hasattr(m.recorded_at, "date") else m.recorded_at
        if isinstance(day, str):
            day = date.fromisoformat(day[:10])
        if day not in seen_days:
            seen_days[day] = m

    return [
        {
            "date": d.isoformat(),
            "hrv": m.hrv,
            "resting_hr": m.resting_hr,
            "sleep_duration_min": m.sleep_duration_min,
            "sleep_quality_score": m.sleep_quality_score,
            "stress_score": m.stress_score,
            "steps": m.steps,
            "spo2": m.spo2,
            "vo2_max": m.vo2_max,
            "source": m.source,
        }
        for d, m in sorted(seen_days.items(), reverse=True)
    ]


@router.get("/recovery")
async def get_recovery(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Calculate and return the current recovery score. Cached in Redis for 5 min."""
    cache_key = f"recovery:{current_user.id}:{date.today().isoformat()}"
    cached = await _cache_get(cache_key)
    if cached:
        return cached

    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    ninety_days_ago = datetime.now(timezone.utc) - timedelta(days=90)

    # Run both queries in parallel
    today_q = db.execute(
        select(HealthMetric)
        .where(
            HealthMetric.user_id == current_user.id,
            HealthMetric.recorded_at >= today_start,
        )
        .order_by(HealthMetric.recorded_at.desc())
        .limit(1)
    )
    baseline_q = db.execute(
        select(HealthMetric)
        .where(
            HealthMetric.user_id == current_user.id,
            HealthMetric.recorded_at >= ninety_days_ago,
        )
        .order_by(HealthMetric.recorded_at.desc())
        .limit(28)
    )
    today_result, baseline_result = await asyncio.gather(today_q, baseline_q)

    metric = today_result.scalars().first()

    # Skip today's entry if all metric fields are null (empty sync placeholder)
    if metric and not any([metric.hrv, metric.resting_hr, metric.sleep_duration_min, metric.stress_score, metric.vo2_max, metric.spo2, metric.steps]):
        metric = None

    if not metric:
        # Fallback: last available metric with real data from baseline set
        all_baseline = baseline_result.scalars().all()
        for m in all_baseline:
            if any([m.hrv, m.resting_hr, m.sleep_duration_min, m.stress_score, m.vo2_max, m.spo2, m.steps]):
                metric = m
                break
        baseline_metrics = all_baseline
    else:
        baseline_metrics = baseline_result.scalars().all()

    if not metric:
        return {
            "score": 0,
            "label": "KEINE DATEN",
            "hrv_component": 0,
            "sleep_component": 0,
            "stress_component": 0,
            "hr_component": 0,
        }

    scorer = RecoveryScorer()
    metric_dict = {
        "hrv": metric.hrv,
        "sleep_duration_min": metric.sleep_duration_min,
        "stress_score": metric.stress_score,
        "resting_hr": metric.resting_hr,
    }

    baseline_data = [
        {
            "hrv": m.hrv,
            "sleep_duration_min": m.sleep_duration_min,
            "stress_score": m.stress_score,
            "resting_hr": m.resting_hr,
        }
        for m in baseline_metrics
    ]
    user_baseline = RecoveryScorer.compute_baseline(baseline_data)

    response = scorer.calculate_recovery_score(metric_dict, user_baseline=user_baseline)
    response["baseline"] = user_baseline

    # Tell the frontend which fields actually had real data (not just fallback defaults)
    has_hrv        = metric.hrv is not None
    has_resting_hr = metric.resting_hr is not None
    has_sleep      = metric.sleep_duration_min is not None
    has_stress     = metric.stress_score is not None
    response["has_hrv"]        = has_hrv
    response["has_resting_hr"] = has_resting_hr
    response["has_sleep"]      = has_sleep
    response["has_stress"]     = has_stress
    response["data_available"] = any([has_hrv, has_resting_hr, has_sleep, has_stress])

    # Cache for 5 minutes — recovery changes at most when new metrics arrive
    await _cache_set(cache_key, response, ttl=300)
    return response
