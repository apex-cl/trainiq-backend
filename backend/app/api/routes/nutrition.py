import asyncio
import uuid as uuid_module
from datetime import datetime, timezone
from typing import Union
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func, cast, Date as SADate
import cloudinary
import cloudinary.uploader
from slowapi import Limiter
from slowapi.util import get_remote_address
from app.core.database import get_db
from app.api.dependencies import get_current_user, get_current_user_or_guest
from app.models.user import User
from app.models.guest import GuestSession
from app.models.nutrition import NutritionLog
from app.services.nutrition_analyzer import NutritionAnalyzer
from app.core.config import settings
from loguru import logger

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)

if settings.cloudinary_api_key:
    cloudinary.config(
        cloud_name=settings.cloudinary_cloud_name,
        api_key=settings.cloudinary_api_key,
        api_secret=settings.cloudinary_api_secret,
        secure=True,
    )


_IMAGE_MAGIC_BYTES: list[tuple[bytes, str]] = [
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"RIFF", "image/webp"),  # WebP: RIFF????WEBP
]


def _is_valid_image(data: bytes) -> bool:
    """Prüft ob Bytes eine gültige Bildsignatur (Magic Bytes) enthalten."""
    for magic, _ in _IMAGE_MAGIC_BYTES:
        if data[:len(magic)] == magic:
            if magic == b"RIFF":
                return len(data) >= 12 and data[8:12] == b"WEBP"
            return True
    return False


@router.post("/upload")
@limiter.limit("10/minute")
async def upload(
    request: Request,
    file: UploadFile = File(...),
    meal_type: str = Form(default="unbekannt"),
    current: Union[User, GuestSession] = Depends(get_current_user_or_guest),
    db: AsyncSession = Depends(get_db),
):
    """Upload a food photo for analysis. Gäste haben Foto-Limit (max 2)."""
    # 1. Content-Type Header prüfen (erste Hürde)
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Nur Bilder sind erlaubt")

    is_guest = isinstance(current, GuestSession)

    # 2. Gast-Limit prüfen
    if is_guest:
        if current.photo_count >= settings.guest_max_photos:
            raise HTTPException(
                status_code=403,
                detail=f"Gast-Limit erreicht ({settings.guest_max_photos} Fotos). Bitte registrieren für mehr.",
            )

    image_bytes = await file.read()

    # 3. Dateigröße prüfen (max 10 MB)
    if len(image_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Datei zu groß (max 10 MB)")

    # 4. Magic-Bytes validieren (verhindert Content-Type-Spoofing)
    if not _is_valid_image(image_bytes):
        raise HTTPException(status_code=400, detail="Ungültiges Bildformat")
    user_id = current.id if not is_guest else f"guest:{current.id}"

    # 4+5. Cloudinary-Upload und KI-Analyse parallel – beide brauchen nur image_bytes
    async def _maybe_upload() -> str | None:
        if not settings.cloudinary_api_key:
            return None
        try:
            result = await asyncio.to_thread(
                cloudinary.uploader.upload,
                image_bytes,
                folder=f"trainiq/{user_id}",
                resource_type="image",
            )
            return result.get("secure_url")
        except Exception as e:
            logger.warning(f"Cloudinary upload failed | user={user_id} | error={e}")
            return None

    analyzer = NutritionAnalyzer()
    try:
        image_url, analysis = await asyncio.gather(
            _maybe_upload(),
            analyzer.analyze_image(image_bytes, meal_type),
        )
    except Exception as e:
        logger.error(f"Nutrition photo analysis failed | user={user_id} | error={e}")
        raise HTTPException(
            status_code=502,
            detail="Bild-Analyse fehlgeschlagen. Bitte versuche es erneut.",
        )

    # 6. Gast-Counter NACH erfolgreicher Analyse atomar inkrementieren (verhindert Race-Condition)
    if is_guest:
        res = await db.execute(
            update(GuestSession)
            .where(
                GuestSession.id == current.id,
                GuestSession.photo_count < settings.guest_max_photos,
            )
            .values(photo_count=GuestSession.photo_count + 1)
        )
        await db.commit()
        if res.rowcount == 0:
            raise HTTPException(
                status_code=403,
                detail=f"Gast-Limit erreicht ({settings.guest_max_photos} Fotos). Bitte registrieren für mehr.",
            )
        new_count = current.photo_count + 1
        return {
            "meal_name": analysis["meal_name"],
            "calories": analysis["calories"],
            "protein_g": analysis["protein_g"],
            "carbs_g": analysis["carbs_g"],
            "fat_g": analysis["fat_g"],
            "image_url": image_url,
            "confidence": analysis["confidence"],
            "photos_remaining": settings.guest_max_photos - new_count,
        }

    # In DB speichern (nur für registrierte User)
    log = NutritionLog(
        user_id=current.id,
        meal_type=meal_type,
        image_url=image_url,
        calories=analysis["calories"],
        protein_g=analysis["protein_g"],
        carbs_g=analysis["carbs_g"],
        fat_g=analysis["fat_g"],
        analysis_raw=analysis,
    )
    db.add(log)
    await db.flush()

    return {
        "id": str(log.id),
        "meal_name": analysis["meal_name"],
        "calories": analysis["calories"],
        "protein_g": analysis["protein_g"],
        "carbs_g": analysis["carbs_g"],
        "fat_g": analysis["fat_g"],
        "image_url": image_url,
        "confidence": analysis["confidence"],
    }


@router.get("/today")
async def get_today(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return today's total nutrition values and individual meal logs."""
    from app.models.training import UserGoal
    from app.services.nutrition_targets import NutritionTargetCalculator

    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    # All 3 queries in parallel
    logs_result, totals_result, goals_result = await asyncio.gather(
        db.execute(
            select(NutritionLog)
            .where(
                NutritionLog.user_id == current_user.id,
                NutritionLog.logged_at >= today_start,
            )
            .order_by(NutritionLog.logged_at.desc())
        ),
        db.execute(
            select(
                func.coalesce(func.sum(NutritionLog.calories), 0).label("cal"),
                func.coalesce(func.sum(NutritionLog.protein_g), 0).label("protein"),
                func.coalesce(func.sum(NutritionLog.carbs_g), 0).label("carbs"),
                func.coalesce(func.sum(NutritionLog.fat_g), 0).label("fat"),
            ).where(
                NutritionLog.user_id == current_user.id,
                NutritionLog.logged_at >= today_start,
            )
        ),
        db.execute(
            select(UserGoal).where(UserGoal.user_id == current_user.id).limit(1)
        ),
    )

    logs = logs_result.scalars().all()
    row = totals_result.one()
    total_calories, total_protein, total_carbs, total_fat = row.cal, row.protein, row.carbs, row.fat

    calc = NutritionTargetCalculator()
    goal = goals_result.scalars().first()
    if goal:
        targets = calc.calculate(goal.sport, goal.weekly_hours or 5, goal.fitness_level or "intermediate")
    else:
        targets = calc.default_targets()

    return {
        "logs": [
            {
                "id": str(l.id),
                "meal_type": l.meal_type,
                "calories": l.calories,
                "protein_g": l.protein_g,
                "carbs_g": l.carbs_g,
                "fat_g": l.fat_g,
                "image_url": l.image_url,
                "logged_at": l.logged_at.isoformat(),
                "meal_name": (l.analysis_raw or {}).get("meal_name", l.meal_type),
            }
            for l in logs
        ],
        "totals": {
            "calories": round(total_calories, 1),
            "protein_g": round(total_protein, 1),
            "carbs_g": round(total_carbs, 1),
            "fat_g": round(total_fat, 1),
        },
        "targets": {
            **targets,
            "target_cal": targets["calories"],
            "target_protein": targets["protein_g"],
            "target_carbs": targets["carbs_g"],
            "target_fat": targets["fat_g"],
        },
    }


@router.get("/gaps")
async def get_gaps(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Analyze nutritional gaps based on today's intake."""
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    # Direkt aggregieren – keine Row-Objekte laden
    result = await db.execute(
        select(
            func.coalesce(func.sum(NutritionLog.calories), 0).label("cal"),
            func.coalesce(func.sum(NutritionLog.protein_g), 0).label("protein"),
            func.coalesce(func.sum(NutritionLog.carbs_g), 0).label("carbs"),
            func.coalesce(func.sum(NutritionLog.fat_g), 0).label("fat"),
        ).where(
            NutritionLog.user_id == current_user.id,
            NutritionLog.logged_at >= today_start,
        )
    )
    row = result.one()
    totals = {
        "calories": float(row.cal),
        "protein_g": float(row.protein),
        "carbs_g": float(row.carbs),
        "fat_g": float(row.fat),
    }

    analyzer = NutritionAnalyzer()
    gaps = await analyzer.get_daily_gaps(totals)
    return gaps


@router.get("/targets")
async def get_targets(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return personalized daily nutrition targets based on user goals."""
    from app.models.training import UserGoal
    from app.services.nutrition_targets import NutritionTargetCalculator

    goals_result = await db.execute(
        select(UserGoal).where(UserGoal.user_id == current_user.id)
    )
    goals = goals_result.scalars().all()

    calc = NutritionTargetCalculator()

    if not goals:
        return calc.default_targets()

    g = goals[0]
    return calc.calculate(
        sport=g.sport,
        weekly_hours=g.weekly_hours or 5,
        fitness_level=g.fitness_level or "intermediate",
    )


@router.get("/history")
async def get_history(
    days: int = 7,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return nutrition logs for the last N days, grouped by date."""
    from datetime import timedelta

    days = min(days, 30)  # Maximal 30 Tage
    start = datetime.now(timezone.utc) - timedelta(days=days)

    # GROUP BY direkt in SQL – kein Python-seitiges dict-Building
    result = await db.execute(
        select(
            cast(NutritionLog.logged_at, SADate).label("day"),
            func.round(func.coalesce(func.sum(NutritionLog.calories), 0), 1).label("total_calories"),
            func.round(func.coalesce(func.sum(NutritionLog.protein_g), 0), 1).label("total_protein_g"),
            func.round(func.coalesce(func.sum(NutritionLog.carbs_g), 0), 1).label("total_carbs_g"),
            func.round(func.coalesce(func.sum(NutritionLog.fat_g), 0), 1).label("total_fat_g"),
            func.count(NutritionLog.id).label("meal_count"),
        )
        .where(
            NutritionLog.user_id == current_user.id,
            NutritionLog.logged_at >= start,
        )
        .group_by(cast(NutritionLog.logged_at, SADate))
        .order_by(cast(NutritionLog.logged_at, SADate).desc())
    )
    rows = result.all()
    return [
        {
            "date": row.day.isoformat(),
            "total_calories": float(row.total_calories),
            "total_protein_g": float(row.total_protein_g),
            "total_carbs_g": float(row.total_carbs_g),
            "total_fat_g": float(row.total_fat_g),
            "meal_count": row.meal_count,
        }
        for row in rows
    ]


@router.delete("/meal/{meal_id}")
async def delete_meal(
    meal_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a specific nutrition log entry."""
    try:
        meal_uuid = uuid_module.UUID(meal_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Ungültige Mahlzeiten-ID")

    result = await db.execute(
        select(NutritionLog).where(
            NutritionLog.id == meal_uuid,
            NutritionLog.user_id == current_user.id,
        )
    )
    meal = result.scalar_one_or_none()
    if not meal:
        raise HTTPException(status_code=404, detail="Mahlzeit nicht gefunden")

    await db.delete(meal)
    await db.flush()
    return {"ok": True}
