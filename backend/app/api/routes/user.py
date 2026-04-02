import asyncio
from datetime import date, datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, field_validator
from typing import Optional
from app.core.database import get_db
from app.api.dependencies import get_current_user
from app.models.user import User
from app.models.training import UserGoal

router = APIRouter()


class ProfileUpdateRequest(BaseModel):
    name: Optional[str] = None
    avatar_url: Optional[str] = None
    birth_date: Optional[str] = None
    gender: Optional[str] = None
    weight_kg: Optional[float] = None
    height_cm: Optional[int] = None
    preferred_language: Optional[str] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if len(v) < 1 or len(v) > 100:
                raise ValueError("Name muss zwischen 1 und 100 Zeichen lang sein")
        return v

    @field_validator("preferred_language")
    @classmethod
    def validate_language(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in {"de", "en", "fr", "es", "it"}:
            raise ValueError("Sprache muss eine der folgenden sein: de, en, fr, es, it")
        return v

    @field_validator("avatar_url")
    @classmethod
    def validate_avatar_url(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not (v.startswith("https://") or v.startswith("/")):
            raise ValueError("avatar_url muss eine https:// URL oder ein relativer Pfad sein")
        return v

    @field_validator("birth_date")
    @classmethod
    def validate_birth_date(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            try:
                date.fromisoformat(v)
            except ValueError:
                raise ValueError("Ungültiges Datumsformat. Erwartet: YYYY-MM-DD")
        return v

    @field_validator("weight_kg")
    @classmethod
    def validate_weight(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and (v < 20 or v > 300):
            raise ValueError("Gewicht muss zwischen 20 und 300 kg liegen")
        return v

    @field_validator("height_cm")
    @classmethod
    def validate_height(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and (v < 50 or v > 250):
            raise ValueError("Größe muss zwischen 50 und 250 cm liegen")
        return v


class NotificationSettingsRequest(BaseModel):
    training_reminders: Optional[bool] = True
    recovery_alerts: Optional[bool] = True
    achievement_notifications: Optional[bool] = True
    weekly_summary: Optional[bool] = True
    marketing_emails: Optional[bool] = False


@router.get("/profile")
async def get_profile(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return user profile with goals."""
    goals_result = await db.execute(
        select(UserGoal).where(UserGoal.user_id == current_user.id)
    )
    goals = goals_result.scalars().all()
    return {
        "id": str(current_user.id),
        "email": current_user.email,
        "name": current_user.name,
        "avatar_url": current_user.avatar_url,
        "birth_date": current_user.birth_date.isoformat()
        if current_user.birth_date
        else None,
        "gender": current_user.gender,
        "weight_kg": current_user.weight_kg,
        "height_cm": current_user.height_cm,
        "preferred_language": current_user.preferred_language,
        "age": current_user.age,
        "created_at": current_user.created_at.isoformat(),
        "has_goals": len(goals) > 0,
        "goals": [
            {
                "id": str(g.id),
                "sport": g.sport,
                "goal_description": g.goal_description,
                "target_date": g.target_date.isoformat() if g.target_date else None,
                "weekly_hours": g.weekly_hours,
                "fitness_level": g.fitness_level,
            }
            for g in goals
        ],
    }


@router.put("/profile")
async def update_profile(
    body: ProfileUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update user profile information."""
    if body.name is not None:
        current_user.name = body.name
    if body.avatar_url is not None:
        current_user.avatar_url = body.avatar_url
    if body.birth_date is not None:
        current_user.birth_date = date.fromisoformat(body.birth_date)
    if body.gender is not None:
        current_user.gender = body.gender
    if body.weight_kg is not None:
        current_user.weight_kg = body.weight_kg
    if body.height_cm is not None:
        current_user.height_cm = body.height_cm
    if body.preferred_language is not None:
        current_user.preferred_language = body.preferred_language

    await db.flush()

    return {
        "id": str(current_user.id),
        "name": current_user.name,
        "avatar_url": current_user.avatar_url,
        "birth_date": current_user.birth_date.isoformat()
        if current_user.birth_date
        else None,
        "gender": current_user.gender,
        "weight_kg": current_user.weight_kg,
        "height_cm": current_user.height_cm,
        "preferred_language": current_user.preferred_language,
        "age": current_user.age,
    }


@router.get("/settings/notifications")
async def get_notification_settings(
    current_user: User = Depends(get_current_user),
):
    """Get user notification preferences."""
    settings = current_user.notification_settings or {
        "training_reminders": True,
        "recovery_alerts": True,
        "achievement_notifications": True,
        "weekly_summary": True,
        "marketing_emails": False,
    }
    return settings


@router.put("/settings/notifications")
async def update_notification_settings(
    body: NotificationSettingsRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update user notification preferences."""
    current_user.notification_settings = {
        "training_reminders": body.training_reminders,
        "recovery_alerts": body.recovery_alerts,
        "achievement_notifications": body.achievement_notifications,
        "weekly_summary": body.weekly_summary,
        "marketing_emails": body.marketing_emails,
    }

    if body.marketing_emails is not None:
        current_user.marketing_consent = body.marketing_emails

    await db.flush()

    return current_user.notification_settings


ALLOWED_SPORTS = {"running", "cycling", "swimming", "triathlon"}
ALLOWED_LEVELS = {"beginner", "intermediate", "advanced"}


class GoalsRequest(BaseModel):
    sport: str
    goal_description: str
    target_date: str | None = None
    weekly_hours: int | None = None
    fitness_level: str | None = None

    @field_validator("goal_description")
    @classmethod
    def validate_goal_description(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Ziel-Beschreibung darf nicht leer sein")
        if len(v) > 500:
            raise ValueError("Ziel-Beschreibung darf maximal 500 Zeichen lang sein")
        return v

    @field_validator("sport")
    @classmethod
    def validate_sport(cls, v: str) -> str:
        if v not in ALLOWED_SPORTS:
            raise ValueError(f"Sport muss einer von {ALLOWED_SPORTS} sein")
        return v

    @field_validator("fitness_level")
    @classmethod
    def validate_fitness_level(cls, v: str | None) -> str | None:
        if v is not None and v not in ALLOWED_LEVELS:
            raise ValueError(f"Fitnesslevel muss einer von {ALLOWED_LEVELS} sein")
        return v

    @field_validator("target_date")
    @classmethod
    def validate_target_date(cls, v: str | None) -> str | None:
        if v is not None:
            try:
                date.fromisoformat(v)
            except ValueError:
                raise ValueError("Ungültiges Datumsformat für target_date. Erwartet: YYYY-MM-DD")
        return v

    @field_validator("weekly_hours")
    @classmethod
    def validate_weekly_hours(cls, v: int | None) -> int | None:
        if v is not None and (v < 1 or v > 30):
            raise ValueError("Wochenstunden müssen zwischen 1 und 30 liegen")
        return v


@router.post("/goals")
async def save_goals(
    body: GoalsRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Save or update a user goal (UPSERT by user_id + sport)."""
    result = await db.execute(
        select(UserGoal).where(
            UserGoal.user_id == current_user.id,
            UserGoal.sport == body.sport,
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        existing.goal_description = body.goal_description
        if body.target_date is not None:
            existing.target_date = date.fromisoformat(body.target_date)
        if body.weekly_hours is not None:
            existing.weekly_hours = body.weekly_hours
        if body.fitness_level is not None:
            existing.fitness_level = body.fitness_level
        goal = existing
    else:
        goal = UserGoal(
            user_id=current_user.id,
            sport=body.sport,
            goal_description=body.goal_description,
            target_date=date.fromisoformat(body.target_date)
            if body.target_date
            else None,
            weekly_hours=body.weekly_hours if body.weekly_hours is not None else 5,
            fitness_level=body.fitness_level
            if body.fitness_level is not None
            else "intermediate",
        )
        db.add(goal)

    await db.flush()

    return {
        "id": str(goal.id),
        "sport": goal.sport,
        "goal_description": goal.goal_description,
        "target_date": goal.target_date.isoformat() if goal.target_date else None,
        "weekly_hours": goal.weekly_hours,
        "fitness_level": goal.fitness_level,
    }


@router.get("/goals")
async def get_goals(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all goals for the current user."""
    result = await db.execute(
        select(UserGoal).where(UserGoal.user_id == current_user.id)
    )
    goals = result.scalars().all()
    return [
        {
            "id": str(g.id),
            "sport": g.sport,
            "goal_description": g.goal_description,
            "target_date": g.target_date.isoformat() if g.target_date else None,
            "weekly_hours": g.weekly_hours,
            "fitness_level": g.fitness_level,
        }
        for g in goals
    ]


@router.delete("/account")
async def delete_account(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete user account and all associated data (GDPR compliance)."""
    await db.delete(current_user)
    await db.commit()
    return {"status": "deleted", "message": "Account und alle Daten wurden gelöscht"}


@router.get("/export")
async def export_user_data(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Export all user data (GDPR Art. 15 - Right to Data Portability)."""
    from app.models.metrics import HealthMetric
    from app.models.training import TrainingPlan
    from app.models.watch import WatchConnection
    from app.models.nutrition import NutritionLog

    (
        goals_result,
        metrics_result,
        plans_result,
        connections_result,
        nutrition_result,
    ) = await asyncio.gather(
        db.execute(select(UserGoal).where(UserGoal.user_id == current_user.id)),
        db.execute(select(HealthMetric).where(HealthMetric.user_id == current_user.id)),
        db.execute(select(TrainingPlan).where(TrainingPlan.user_id == current_user.id)),
        db.execute(select(WatchConnection).where(WatchConnection.user_id == current_user.id)),
        db.execute(select(NutritionLog).where(NutritionLog.user_id == current_user.id)),
    )
    goals = goals_result.scalars().all()
    metrics = metrics_result.scalars().all()
    plans = plans_result.scalars().all()
    connections = connections_result.scalars().all()
    nutrition = nutrition_result.scalars().all()

    export_data = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "user": {
            "id": str(current_user.id),
            "email": current_user.email,
            "name": current_user.name,
            "created_at": current_user.created_at.isoformat(),
        },
        "goals": [
            {
                "sport": g.sport,
                "goal_description": g.goal_description,
                "target_date": g.target_date.isoformat() if g.target_date else None,
                "weekly_hours": g.weekly_hours,
                "fitness_level": g.fitness_level,
            }
            for g in goals
        ],
        "health_metrics": [
            {
                "recorded_at": m.recorded_at.isoformat(),
                "hrv": m.hrv,
                "resting_hr": m.resting_hr,
                "sleep_duration_min": m.sleep_duration_min,
                "sleep_quality_score": m.sleep_quality_score,
                "stress_score": m.stress_score,
                "spo2": m.spo2,
                "steps": m.steps,
                "vo2_max": m.vo2_max,
                "source": m.source,
            }
            for m in metrics
        ],
        "training_plans": [
            {
                "date": p.date.isoformat(),
                "sport": p.sport,
                "workout_type": p.workout_type,
                "duration_min": p.duration_min,
                "intensity_zone": p.intensity_zone,
                "status": p.status,
            }
            for p in plans
        ],
        "watch_connections": [
            {
                "provider": c.provider,
                "is_active": c.is_active,
                "last_synced_at": c.last_synced_at.isoformat()
                if c.last_synced_at
                else None,
            }
            for c in connections
        ],
        "nutrition_logs": [
            {
                "logged_at": n.logged_at.isoformat(),
                "meal_type": n.meal_type,
                "food_name": n.analysis_raw.get("meal_name")
                if n.analysis_raw
                else None,
                "calories": n.calories,
                "protein_g": n.protein_g,
                "carbs_g": n.carbs_g,
                "fat_g": n.fat_g,
            }
            for n in nutrition
        ],
    }

    return export_data
