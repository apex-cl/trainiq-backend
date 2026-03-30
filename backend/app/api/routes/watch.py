"""
Watch/Fitness-Tracker Sync Routes
Unterstützt: Strava OAuth2, Webhooks, Manuelle Eingabe
"""

import secrets
import uuid as uuid_module
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, field_validator
from app.core.database import get_db
from app.api.dependencies import get_current_user
from app.models.user import User
from app.models.watch import WatchConnection
from app.models.training import TrainingPlan
from app.models.metrics import HealthMetric
from app.services.strava_service import StravaService
from app.services.garmin_service import GarminService
from app.core.config import settings

# CSRF-State TTL für OAuth-Flows (10 Minuten)
_OAUTH_STATE_TTL = 600


async def _store_oauth_state(state_token: str, user_id: str) -> None:
    """Speichert OAuth-State-Token in Redis mit TTL."""
    import redis.asyncio as aioredis

    r = aioredis.from_url(settings.redis_url)
    try:
        await r.set(f"oauth_state:{state_token}", user_id, ex=_OAUTH_STATE_TTL)
    finally:
        await r.aclose()


async def _consume_oauth_state(state_token: str) -> str | None:
    """Liest und löscht OAuth-State-Token aus Redis. Gibt user_id zurück oder None."""
    import redis.asyncio as aioredis

    r = aioredis.from_url(settings.redis_url)
    try:
        key = f"oauth_state:{state_token}"
        user_id = await r.getdel(key)
        return user_id.decode() if user_id else None
    finally:
        await r.aclose()

router = APIRouter()
strava = StravaService()
garmin = GarminService()


# ─── Status ───────────────────────────────────────────────────────────────────


@router.get("/status")
async def get_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Gibt Verbindungsstatus aller verknüpften Tracker zurück."""
    result = await db.execute(
        select(WatchConnection).where(
            WatchConnection.user_id == current_user.id,
            WatchConnection.is_active == True,
        )
    )
    connections = result.scalars().all()
    return {
        "connected": [
            {
                "provider": c.provider,
                "last_synced_at": c.last_synced_at.isoformat()
                if c.last_synced_at
                else None,
            }
            for c in connections
        ],
        "strava_available": bool(settings.strava_client_id),
        "garmin_available": bool(settings.garmin_client_id),
    }


# ─── Strava OAuth ──────────────────────────────────────────────────────────────


@router.get("/strava/connect")
async def strava_connect(
    current_user: User = Depends(get_current_user),
):
    """Leitet den User zur Strava OAuth-Seite weiter."""
    if not settings.strava_client_id:
        raise HTTPException(status_code=503, detail="Strava nicht konfiguriert")

    state = secrets.token_urlsafe(32)
    await _store_oauth_state(state, str(current_user.id))
    auth_url = strava.get_auth_url(state=state)
    return {"auth_url": auth_url}


@router.get("/strava/callback")
async def strava_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Strava leitet hierher weiter nach Authorization.
    Tauscht Code gegen Token und speichert Verbindung.
    """
    user_id_str = await _consume_oauth_state(state)
    if not user_id_str:
        raise HTTPException(status_code=400, detail="Ungültiger oder abgelaufener OAuth-State")

    try:
        target_user_id = uuid_module.UUID(user_id_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Ungültige User-ID im OAuth-State")

    try:
        token_data = await strava.exchange_code(code)
        athlete_data = await strava.get_athlete(token_data["access_token"])
    except Exception as e:
        raise HTTPException(
            status_code=400, detail="Strava-Authentifizierung fehlgeschlagen"
        )

    athlete_id = str(athlete_data.get("id", ""))

    result = await db.execute(
        select(WatchConnection).where(
            WatchConnection.user_id == target_user_id,
            WatchConnection.provider == "strava",
        )
    )
    connection = result.scalar_one_or_none()

    if connection:
        connection.access_token = token_data["access_token"]
        connection.refresh_token = token_data["refresh_token"]
        connection.provider_athlete_id = athlete_id
        connection.is_active = True
    else:
        connection = WatchConnection(
            user_id=target_user_id,
            provider="strava",
            provider_athlete_id=athlete_id,
            access_token=token_data["access_token"],
            refresh_token=token_data["refresh_token"],
            is_active=True,
        )
        db.add(connection)

    await db.commit()

    return RedirectResponse(url=f"{settings.frontend_url}/onboarding?strava=connected")


@router.post("/strava/disconnect")
async def strava_disconnect(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Trennt Strava-Verbindung."""
    result = await db.execute(
        select(WatchConnection).where(
            WatchConnection.user_id == current_user.id,
            WatchConnection.provider == "strava",
        )
    )
    connection = result.scalar_one_or_none()
    if connection:
        connection.is_active = False
        await db.commit()
    return {"ok": True}


# ─── Garmin OAuth ────────────────────────────────────────────────────────────


@router.get("/garmin/connect")
async def garmin_connect(
    current_user: User = Depends(get_current_user),
):
    """Leitet den User zur Garmin OAuth-Seite weiter."""
    if not settings.garmin_client_id:
        raise HTTPException(status_code=503, detail="Garmin nicht konfiguriert")

    state = secrets.token_urlsafe(32)
    await _store_oauth_state(state, str(current_user.id))
    auth_url = garmin.get_auth_url(state=state)
    return {"auth_url": auth_url}


@router.get("/garmin/callback")
async def garmin_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Garmin leitet hierher weiter nach Authorization."""
    user_id_str = await _consume_oauth_state(state)
    if not user_id_str:
        raise HTTPException(status_code=400, detail="Ungültiger oder abgelaufener OAuth-State")

    try:
        target_user_id = uuid_module.UUID(user_id_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Ungültige User-ID im OAuth-State")

    try:
        token_data = await garmin.exchange_code(code)
    except Exception as e:
        raise HTTPException(
            status_code=400, detail="Garmin-Authentifizierung fehlgeschlagen"
        )

    result = await db.execute(
        select(WatchConnection).where(
            WatchConnection.user_id == target_user_id,
            WatchConnection.provider == "garmin",
        )
    )
    connection = result.scalar_one_or_none()

    if connection:
        connection.access_token = token_data.get("access_token", "")
        connection.refresh_token = token_data.get("refresh_token", "")
        connection.is_active = True
    else:
        connection = WatchConnection(
            user_id=target_user_id,
            provider="garmin",
            provider_athlete_id=state,
            access_token=token_data.get("access_token", ""),
            refresh_token=token_data.get("refresh_token", ""),
            is_active=True,
        )
        db.add(connection)

    await db.commit()

    return RedirectResponse(url=f"{settings.frontend_url}/onboarding?garmin=connected")


@router.post("/garmin/disconnect")
async def garmin_disconnect(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Trennt Garmin-Verbindung."""
    result = await db.execute(
        select(WatchConnection).where(
            WatchConnection.user_id == current_user.id,
            WatchConnection.provider == "garmin",
        )
    )
    connection = result.scalar_one_or_none()
    if connection:
        connection.is_active = False
        await db.commit()
    return {"ok": True}


# ─── Sync ─────────────────────────────────────────────────────────────────────


@router.post("/sync")
async def sync(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Synchronisiert Aktivitäten von verbundenen Trackern.
    Unterstützt: Strava, Garmin → TrainingPlan-Updates
    """
    synced_count = 0
    providers = []

    # Strava-Verbindung laden
    result = await db.execute(
        select(WatchConnection).where(
            WatchConnection.user_id == current_user.id,
            WatchConnection.provider == "strava",
            WatchConnection.is_active == True,
        )
    )
    strava_conn = result.scalar_one_or_none()

    if strava_conn:
        try:
            activities = await strava.get_recent_activities(
                strava_conn.access_token, limit=10
            )
        except Exception:
            try:
                new_tokens = await strava.refresh_token(strava_conn.refresh_token)
                strava_conn.access_token = new_tokens["access_token"]
                strava_conn.refresh_token = new_tokens.get(
                    "refresh_token", strava_conn.refresh_token
                )
                activities = await strava.get_recent_activities(
                    strava_conn.access_token, limit=10
                )
            except Exception:
                activities = []

        if activities:
            from datetime import date

            for activity in activities:
                update = strava.activity_to_training_plan_update(activity)
                activity_date = date.fromisoformat(update["date"])
                plan_result = await db.execute(
                    select(TrainingPlan).where(
                        TrainingPlan.user_id == current_user.id,
                        TrainingPlan.date == activity_date,
                    )
                )
                plan = plan_result.scalar_one_or_none()
                if plan and plan.status != "completed":
                    plan.status = "completed"
                    if update.get("avg_hr"):
                        plan.target_hr_min = update["avg_hr"] - 10
                        plan.target_hr_max = update["avg_hr"] + 10
                    synced_count += 1

            strava_conn.last_synced_at = datetime.now(timezone.utc)
            providers.append("strava")

    # Garmin-Verbindung laden
    garmin_result = await db.execute(
        select(WatchConnection).where(
            WatchConnection.user_id == current_user.id,
            WatchConnection.provider == "garmin",
            WatchConnection.is_active == True,
        )
    )
    garmin_conn = garmin_result.scalar_one_or_none()

    if garmin_conn:
        try:
            from datetime import date, timedelta

            today = date.today().isoformat()
            activities = await garmin.get_activities(
                garmin_conn.access_token, today, today
            )
            if activities:
                for activity in activities:
                    metric = garmin.activity_to_metric(activity)
                    health_metric = HealthMetric(
                        user_id=current_user.id,
                        recorded_at=datetime.now(timezone.utc),
                        steps=metric.get("steps"),
                        source="garmin",
                    )
                    db.add(health_metric)
                    synced_count += 1

                garmin_conn.last_synced_at = datetime.now(timezone.utc)
                providers.append("garmin")
        except Exception:
            pass

    if strava_conn or garmin_conn:
        await db.commit()

    return {"synced": synced_count, "provider": providers if providers else None}


# ─── Apple Watch / HealthKit ───────────────────────────────────────────────────


@router.post("/apple/pair")
async def apple_watch_pair(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Erzeugt Pairing-Token für Apple Watch (iOS App erforderlich)."""
    import uuid

    pairing_token = secrets.token_urlsafe(32)

    result = await db.execute(
        select(WatchConnection).where(
            WatchConnection.user_id == current_user.id,
            WatchConnection.provider == "apple_watch",
        )
    )
    connection = result.scalar_one_or_none()

    if connection:
        connection.access_token = pairing_token
        connection.is_active = True
    else:
        connection = WatchConnection(
            user_id=current_user.id,
            provider="apple_watch",
            provider_athlete_id=str(uuid.uuid4()),
            access_token=pairing_token,
            is_active=True,
        )
        db.add(connection)

    await db.commit()
    return {"pairing_token": pairing_token}


class AppleHealthDataInput(BaseModel):
    recorded_at: datetime
    hrv: float | None = None
    resting_hr: int | None = None
    sleep_duration_min: int | None = None
    sleep_quality_score: float | None = None
    stress_score: float | None = None
    spo2: float | None = None
    steps: int | None = None
    workout_type: str | None = None
    workout_duration_min: int | None = None


@router.post("/apple/sync")
async def apple_health_sync(
    body: AppleHealthDataInput,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Empfängt HealthKit-Daten von der iOS App.
    Die iOS App muss mit dem Pairing-Token authentifiziert sein.
    """
    metric = HealthMetric(
        user_id=current_user.id,
        recorded_at=body.recorded_at,
        hrv=body.hrv,
        resting_hr=body.resting_hr,
        sleep_duration_min=body.sleep_duration_min,
        sleep_quality_score=body.sleep_quality_score,
        stress_score=body.stress_score,
        spo2=body.spo2,
        steps=body.steps,
        source="apple_watch",
    )
    db.add(metric)

    if body.workout_type and body.workout_duration_min:
        from datetime import date

        workout_date = body.recorded_at.date()
        result = await db.execute(
            select(TrainingPlan).where(
                TrainingPlan.user_id == current_user.id,
                TrainingPlan.date == workout_date,
            )
        )
        plan = result.scalar_one_or_none()
        if plan and plan.status != "completed":
            plan.status = "completed"

    await db.commit()
    return {"ok": True, "source": "apple_watch"}


@router.post("/apple/disconnect")
async def apple_watch_disconnect(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Trennt Apple Watch-Verbindung."""
    result = await db.execute(
        select(WatchConnection).where(
            WatchConnection.user_id == current_user.id,
            WatchConnection.provider == "apple_watch",
        )
    )
    connection = result.scalar_one_or_none()
    if connection:
        connection.is_active = False
        await db.commit()
    return {"ok": True}


# ─── Manuelle Eingabe ──────────────────────────────────────────────────────────


class ManualMetricInput(BaseModel):
    hrv: float | None = None
    resting_hr: int | None = None
    sleep_duration_min: int | None = None
    stress_score: float | None = None

    @field_validator("hrv")
    @classmethod
    def validate_hrv(cls, v: float | None) -> float | None:
        if v is not None and (v < 0 or v > 200):
            raise ValueError("HRV muss zwischen 0 und 200 liegen")
        return v


@router.post("/manual")
async def manual_input(
    body: ManualMetricInput,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Manuelle Eingabe von Gesundheitsmetriken (ohne Uhr)."""
    metric = HealthMetric(
        user_id=current_user.id,
        recorded_at=datetime.now(timezone.utc),
        hrv=body.hrv,
        resting_hr=body.resting_hr,
        sleep_duration_min=body.sleep_duration_min,
        stress_score=body.stress_score,
        source="manual",
    )
    db.add(metric)
    await db.commit()
    return {"ok": True, "source": "manual"}


# ─── Strava Webhooks ───────────────────────────────────────────────────────────


class StravaWebhookEvent(BaseModel):
    object_type: str
    object_id: int
    aspect_type: str
    owner_id: int  # Strava Athlete ID
    subscription_id: int
    event_time: int


@router.get("/strava/webhook")
async def strava_webhook_verify(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    """
    Strava Webhook Subscription Validation.
    Strava schickt einen GET-Request zur Verifizierung des Endpoints.
    """
    expected_token = getattr(settings, "strava_webhook_verify_token", "trainiq_webhook")

    if hub_mode == "subscribe" and hub_verify_token == expected_token:
        return {"hub.challenge": hub_challenge}

    raise HTTPException(status_code=403, detail="Verification failed")


@router.post("/strava/webhook")
async def strava_webhook_event(
    event: StravaWebhookEvent,
    db: AsyncSession = Depends(get_db),
):
    """
    Empfängt Strava Webhook Events.
    Bei neuen Aktivitäten wird ein Background-Task für die Verarbeitung enqueued.
    """
    from loguru import logger

    logger.info(
        f"Strava webhook received | type={event.aspect_type} "
        f"obj={event.object_id} owner={event.owner_id}"
    )

    # Nur Activity-Events verarbeiten
    if event.object_type != "activity":
        return {"status": "ignored", "reason": "not an activity"}

    # User anhand der Strava-Verbindung finden
    result = await db.execute(
        select(WatchConnection).where(
            WatchConnection.provider == "strava",
            WatchConnection.is_active == True,
        )
    )
    connections = result.scalars().all()

    # Finde die Verbindung, die zur owner_id passt
    target_connection = None
    owner_id_str = str(event.owner_id)
    for conn in connections:
        if conn.provider_athlete_id == owner_id_str:
            target_connection = conn
            break

    if not target_connection:
        return {"status": "ignored", "reason": "no matching connection for owner_id"}

    # Background-Task für die Verarbeitung enqueue
    try:
        from arq import create_pool
        from arq.connections import RedisSettings
        from urllib.parse import urlparse

        parsed = urlparse(settings.redis_url)
        redis_settings = RedisSettings(
            host=parsed.hostname or "localhost",
            port=parsed.port or 6379,
            database=int(parsed.path.lstrip("/"))
            if parsed.path and parsed.path != "/"
            else 0,
            password=parsed.password,
        )

        redis = await create_pool(redis_settings)
        try:
            await redis.enqueue_job(
                "process_strava_webhook_event",
                str(target_connection.user_id),
                event.object_id,
                event.aspect_type,
                event.event_time,
            )
        finally:
            await redis.close()
    except Exception as e:
        logger.error(f"Failed to enqueue webhook task | error={e}")
        # Fallback: synchron verarbeiten
        from app.worker.tasks import process_strava_webhook_event

        ctx = {"redis": None}
        try:
            import redis.asyncio as aioredis

            ctx["redis"] = aioredis.from_url(settings.redis_url)
            await process_strava_webhook_event(
                ctx,
                str(target_connection.user_id),
                event.object_id,
                event.aspect_type,
                event.event_time,
            )
        except Exception:
            pass

    return {"status": "received"}
