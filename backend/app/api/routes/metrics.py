from datetime import date, datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.core.database import get_db
from app.api.dependencies import get_current_user
from app.models.user import User
from app.models.metrics import HealthMetric, DailyWellbeing
from app.services.recovery_scorer import RecoveryScorer

router = APIRouter()


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
    """Return today's health metrics."""
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
        .limit(1)
    )
    metric = result.scalars().first()

    if not metric:
        return {
            "hrv": None,
            "resting_hr": None,
            "sleep_duration_min": None,
            "sleep_quality_score": None,
            "stress_score": None,
            "steps": None,
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
        "source": metric.source,
        "recorded_at": metric.recorded_at.isoformat(),
    }


@router.get("/week")
async def get_week(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return health metrics for the last 7 days."""
    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)

    result = await db.execute(
        select(HealthMetric)
        .where(
            HealthMetric.user_id == current_user.id,
            HealthMetric.recorded_at >= seven_days_ago,
        )
        .order_by(HealthMetric.recorded_at.desc())
    )
    metrics = result.scalars().all()

    # Gruppiert nach Datum, jeweils neuester Eintrag pro Tag
    by_date = {}
    for m in metrics:
        date_key = m.recorded_at.date().isoformat()
        if date_key not in by_date:
            by_date[date_key] = {
                "date": date_key,
                "hrv": m.hrv,
                "resting_hr": m.resting_hr,
                "sleep_duration_min": m.sleep_duration_min,
                "sleep_quality_score": m.sleep_quality_score,
                "stress_score": m.stress_score,
                "steps": m.steps,
                "source": m.source,
            }

    return list(by_date.values())


@router.get("/recovery")
async def get_recovery(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Calculate and return the current recovery score."""
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
        .limit(1)
    )
    metric = result.scalars().first()

    if not metric:
        # Versuche letzte verfügbare Metrik
        fallback_result = await db.execute(
            select(HealthMetric)
            .where(HealthMetric.user_id == current_user.id)
            .order_by(HealthMetric.recorded_at.desc())
            .limit(1)
        )
        metric = fallback_result.scalars().first()

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

    # Persönliche Baseline aus letzten 14 Tagen berechnen
    fourteen_days_ago = datetime.now(timezone.utc) - timedelta(days=14)
    baseline_result = await db.execute(
        select(HealthMetric)
        .where(
            HealthMetric.user_id == current_user.id,
            HealthMetric.recorded_at >= fourteen_days_ago,
        )
        .order_by(HealthMetric.recorded_at.desc())
        .limit(28)
    )
    baseline_metrics = baseline_result.scalars().all()
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

    result = scorer.calculate_recovery_score(metric_dict, user_baseline=user_baseline)
    return {**result, "baseline": user_baseline}
