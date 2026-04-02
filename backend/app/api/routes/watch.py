"""
Watch/Fitness-Tracker Sync Routes
Unterstützt: Strava OAuth2, Webhooks, Manuelle Eingabe
"""

import asyncio
import secrets
import uuid as uuid_module
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, File, Form
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
from app.services.polar_service import PolarService
from app.services.wahoo_service import WahooService
from app.services.fitbit_service import FitbitService
from app.services.suunto_service import SuuntoService
from app.services.withings_service import WithingsService
from app.services.coros_service import CorosService
from app.services.zepp_service import ZeppService
from app.services.whoop_service import WhoopService
from app.services.samsung_health_service import SamsungHealthService
from app.services.google_fit_service import GoogleFitService
from app.core.config import settings
import redis.asyncio as aioredis

# CSRF-State TTL für OAuth-Flows (10 Minuten)
_OAUTH_STATE_TTL = 600
_redis_client: aioredis.Redis | None = None


def _get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(settings.redis_url)
    return _redis_client


async def _store_oauth_state(state_token: str, user_id: str) -> None:
    """Speichert OAuth-State-Token in Redis mit TTL."""
    r = _get_redis()
    await r.set(f"oauth_state:{state_token}", user_id, ex=_OAUTH_STATE_TTL)


async def _consume_oauth_state(state_token: str) -> str | None:
    """Liest und löscht OAuth-State-Token aus Redis. Gibt user_id zurück oder None."""
    r = _get_redis()
    key = f"oauth_state:{state_token}"
    user_id = await r.getdel(key)
    return user_id.decode() if user_id else None


async def _refresh_token_for(conn: WatchConnection, service) -> bool:
    """
    Versucht Token-Refresh für eine WatchConnection.
    Aktualisiert access_token + refresh_token direkt am Objekt.
    Gibt True zurück wenn erfolgreich, False wenn kein refresh_token
    vorhanden oder der Refresh-Request fehlschlägt.
    """
    if not conn.refresh_token:
        return False
    try:
        new_tokens = await service.refresh_token(conn.refresh_token)
        conn.access_token = new_tokens["access_token"]
        conn.refresh_token = new_tokens.get("refresh_token", conn.refresh_token)
        return True
    except Exception:
        return False


router = APIRouter()
strava = StravaService()
garmin = GarminService()
polar = PolarService()
wahoo = WahooService()
fitbit = FitbitService()
suunto = SuuntoService()
withings = WithingsService()
coros = CorosService()
zepp = ZeppService()
whoop = WhoopService()
samsung_health = SamsungHealthService()
google_fit = GoogleFitService()


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
        "polar_available": bool(settings.polar_client_id),
        "wahoo_available": bool(settings.wahoo_client_id),
        "fitbit_available": bool(settings.fitbit_client_id),
        "suunto_available": bool(settings.suunto_client_id),
        "withings_available": bool(settings.withings_client_id),
        "coros_available": bool(settings.coros_client_id),
        "zepp_available": bool(settings.zepp_client_id),
        "whoop_available": bool(settings.whoop_client_id),
        "samsung_health_available": bool(settings.samsung_health_client_id),
        "google_fit_available": bool(settings.google_fit_client_id),
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


# ─── Garmin Credential-Login ─────────────────────────────────────────────────


class GarminLoginRequest(BaseModel):
    email: str
    password: str


@router.post("/garmin/login")
async def garmin_login(
    body: GarminLoginRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Login mit Garmin-Connect-Zugangsdaten.
    Kein Enterprise-API-Key nötig — nutzt garminconnect-Library (Android-App-SSO).
    """
    try:
        token_data = await garmin.login(body.email, body.password)
    except Exception as e:
        import logging
        logging.getLogger("garmin").error(f"Garmin login failed: {e}")
        raise HTTPException(
            status_code=400,
            detail=f"Garmin-Login fehlgeschlagen: {str(e) or 'Prüfe E-Mail und Passwort.'}",
        )

    result = await db.execute(
        select(WatchConnection).where(
            WatchConnection.user_id == current_user.id,
            WatchConnection.provider == "garmin",
        )
    )
    connection = result.scalar_one_or_none()

    tokens_json = token_data.get("tokens_json", "")
    display_name = token_data.get("display_name", "")

    if connection:
        connection.access_token = tokens_json
        connection.refresh_token = None
        connection.provider_athlete_id = display_name or connection.provider_athlete_id
        connection.is_active = True
    else:
        connection = WatchConnection(
            user_id=current_user.id,
            provider="garmin",
            provider_athlete_id=display_name or None,
            access_token=tokens_json,
            refresh_token=None,
            is_active=True,
        )
        db.add(connection)

    await db.commit()
    return {"ok": True, "display_name": display_name}


@router.get("/garmin/connect")
async def garmin_connect_info(
    current_user: User = Depends(get_current_user),
):
    """Gibt Hinweis zurück, dass Garmin über Credential-Login verbunden wird."""
    return {"method": "credentials", "detail": "Garmin nutzt direkten Login (kein OAuth)."}


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
    Unterstützt: Strava, Garmin, Polar, Wahoo, Fitbit, Suunto, Withings,
    COROS, Zepp/Amazfit, WHOOP, Samsung Health, Google Fit, Apple Watch.
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
                if not update["date"]:
                    continue
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
        _refreshed = False
        while True:
            try:
                from datetime import date, timedelta

                today = date.today().isoformat()
                # Fetch daily summary + sleep in parallel for full health data
                daily_task = garmin.get_daily_summary(garmin_conn.access_token, today)
                sleep_task = garmin.get_sleep_data(garmin_conn.access_token, today)
                activities_task = garmin.get_activities(garmin_conn.access_token, today, today)
                daily_data, sleep_data, activities = await asyncio.gather(
                    daily_task, sleep_task, activities_task,
                    return_exceptions=True,
                )

                summary = garmin.parse_daily_summary(daily_data) if isinstance(daily_data, dict) else {}
                sleep_info = garmin.parse_sleep(sleep_data) if isinstance(sleep_data, dict) else {}

                health_metric = HealthMetric(
                    user_id=current_user.id,
                    recorded_at=datetime.now(timezone.utc),
                    resting_hr=summary.get("resting_hr"),
                    steps=summary.get("steps"),
                    stress_score=summary.get("stress_score"),
                    sleep_duration_min=sleep_info.get("sleep_duration_min"),
                    sleep_stages=sleep_info.get("sleep_stages"),
                    source="garmin",
                )
                db.add(health_metric)
                synced_count += 1

                if isinstance(activities, list):
                    for activity in activities:
                        update = garmin.activity_to_training_plan_update(activity) if hasattr(garmin, "activity_to_training_plan_update") else {}
                        if not update.get("date"):
                            continue
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

                garmin_conn.last_synced_at = datetime.now(timezone.utc)
                providers.append("garmin")
                break
            except Exception:
                if not _refreshed and await _refresh_token_for(garmin_conn, garmin):
                    _refreshed = True
                    continue
                break

    # Polar-Verbindung laden
    polar_result = await db.execute(
        select(WatchConnection).where(
            WatchConnection.user_id == current_user.id,
            WatchConnection.provider == "polar",
            WatchConnection.is_active == True,
        )
    )
    polar_conn = polar_result.scalar_one_or_none()

    if polar_conn and polar_conn.provider_athlete_id:
        _refreshed = False
        while True:
            try:
                polar_user_id = int(polar_conn.provider_athlete_id)
                exercises = await polar.list_exercises(polar_conn.access_token, polar_user_id)
                if exercises:
                    from datetime import date

                    for exercise in exercises:
                        metric_data = polar.exercise_to_metric(exercise)
                        exercise_date = date.fromisoformat(metric_data["date"]) if metric_data["date"] else date.today()
                        plan_result = await db.execute(
                            select(TrainingPlan).where(
                                TrainingPlan.user_id == current_user.id,
                                TrainingPlan.date == exercise_date,
                            )
                        )
                        plan = plan_result.scalar_one_or_none()
                        if plan and plan.status != "completed":
                            plan.status = "completed"
                            if metric_data.get("avg_hr"):
                                plan.target_hr_min = metric_data["avg_hr"] - 10
                                plan.target_hr_max = metric_data["avg_hr"] + 10
                            synced_count += 1

                    polar_conn.last_synced_at = datetime.now(timezone.utc)
                    providers.append("polar")
                break
            except Exception:
                if not _refreshed and await _refresh_token_for(polar_conn, polar):
                    _refreshed = True
                    continue
                break

    # Wahoo-Verbindung laden
    wahoo_result = await db.execute(
        select(WatchConnection).where(
            WatchConnection.user_id == current_user.id,
            WatchConnection.provider == "wahoo",
            WatchConnection.is_active == True,
        )
    )
    wahoo_conn = wahoo_result.scalar_one_or_none()

    if wahoo_conn:
        _refreshed = False
        while True:
            try:
                workouts = await wahoo.get_workouts(wahoo_conn.access_token, limit=10)
                if workouts:
                    from datetime import date

                    for workout in workouts:
                        update = wahoo.workout_to_training_plan_update(workout)
                        if not update["date"]:
                            continue
                        workout_date = date.fromisoformat(update["date"])
                        plan_result = await db.execute(
                            select(TrainingPlan).where(
                                TrainingPlan.user_id == current_user.id,
                                TrainingPlan.date == workout_date,
                            )
                        )
                        plan = plan_result.scalar_one_or_none()
                        if plan and plan.status != "completed":
                            plan.status = "completed"
                            if update.get("avg_hr"):
                                plan.target_hr_min = update["avg_hr"] - 10
                                plan.target_hr_max = update["avg_hr"] + 10
                            synced_count += 1

                    wahoo_conn.last_synced_at = datetime.now(timezone.utc)
                    providers.append("wahoo")
                break
            except Exception:
                if not _refreshed and await _refresh_token_for(wahoo_conn, wahoo):
                    _refreshed = True
                    continue
                break

    # Fitbit-Verbindung laden
    fitbit_result = await db.execute(
        select(WatchConnection).where(
            WatchConnection.user_id == current_user.id,
            WatchConnection.provider == "fitbit",
            WatchConnection.is_active == True,
        )
    )
    fitbit_conn = fitbit_result.scalar_one_or_none()

    if fitbit_conn:
        _refreshed = False
        while True:
            try:
                from datetime import date, timedelta

                today = date.today().isoformat()
                yesterday = (date.today() - timedelta(days=1)).isoformat()

                activities = await fitbit.get_activity_log(fitbit_conn.access_token, yesterday, limit=10)
                hr_data = await fitbit.get_heart_rate_today(fitbit_conn.access_token, today)
                sleep_data = await fitbit.get_sleep_today(fitbit_conn.access_token, today)

                resting_hr = fitbit.parse_resting_hr(hr_data)
                sleep_info = fitbit.parse_sleep(sleep_data)

                health_metric = HealthMetric(
                    user_id=current_user.id,
                    recorded_at=datetime.now(timezone.utc),
                    resting_hr=resting_hr,
                    sleep_duration_min=sleep_info.get("sleep_duration_min"),
                    source="fitbit",
                )
                db.add(health_metric)

                for activity in activities:
                    update = fitbit.activity_to_training_plan_update(activity)
                    if not update["date"]:
                        continue
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

                fitbit_conn.last_synced_at = datetime.now(timezone.utc)
                providers.append("fitbit")
                break
            except Exception:
                if not _refreshed and await _refresh_token_for(fitbit_conn, fitbit):
                    _refreshed = True
                    continue
                break

    # Suunto-Verbindung laden
    suunto_result = await db.execute(
        select(WatchConnection).where(
            WatchConnection.user_id == current_user.id,
            WatchConnection.provider == "suunto",
            WatchConnection.is_active == True,
        )
    )
    suunto_conn = suunto_result.scalar_one_or_none()

    if suunto_conn:
        import time as _time
        _refreshed = False
        while True:
            try:
                from datetime import date, timedelta

                since_ms = int((_time.time() - 7 * 86400) * 1000)
                workouts = await suunto.get_workouts(suunto_conn.access_token, limit=10, since=since_ms)
                if workouts:
                    for workout in workouts:
                        update = suunto.workout_to_training_plan_update(workout)
                        if not update["date"]:
                            continue
                        workout_date = date.fromisoformat(update["date"])
                        plan_result = await db.execute(
                            select(TrainingPlan).where(
                                TrainingPlan.user_id == current_user.id,
                                TrainingPlan.date == workout_date,
                            )
                        )
                        plan = plan_result.scalar_one_or_none()
                        if plan and plan.status != "completed":
                            plan.status = "completed"
                            if update.get("avg_hr"):
                                plan.target_hr_min = update["avg_hr"] - 10
                                plan.target_hr_max = update["avg_hr"] + 10
                            synced_count += 1

                    suunto_conn.last_synced_at = datetime.now(timezone.utc)
                    providers.append("suunto")
                break
            except Exception:
                if not _refreshed and await _refresh_token_for(suunto_conn, suunto):
                    _refreshed = True
                    continue
                break

    # Withings-Verbindung laden
    withings_result = await db.execute(
        select(WatchConnection).where(
            WatchConnection.user_id == current_user.id,
            WatchConnection.provider == "withings",
            WatchConnection.is_active == True,
        )
    )
    withings_conn = withings_result.scalar_one_or_none()

    if withings_conn:
        import time as _time
        _refreshed = False
        while True:
            try:
                from datetime import date, timedelta

                today = date.today().isoformat()
                yesterday = (date.today() - timedelta(days=1)).isoformat()
                now_unix = int(_time.time())
                week_ago_unix = now_unix - 7 * 86400

                workouts = await withings.get_workouts(
                    withings_conn.access_token,
                    start_unix=week_ago_unix,
                    end_unix=now_unix,
                )
                for workout in workouts:
                    update = withings.workout_to_training_plan_update(workout)
                    if not update["date"]:
                        continue
                    workout_date = date.fromisoformat(update["date"])
                    plan_result = await db.execute(
                        select(TrainingPlan).where(
                            TrainingPlan.user_id == current_user.id,
                            TrainingPlan.date == workout_date,
                        )
                    )
                    plan = plan_result.scalar_one_or_none()
                    if plan and plan.status != "completed":
                        plan.status = "completed"
                        if update.get("avg_hr"):
                            plan.target_hr_min = update["avg_hr"] - 10
                            plan.target_hr_max = update["avg_hr"] + 10
                        synced_count += 1

                sleep_raw = await withings.get_sleep(
                    withings_conn.access_token,
                    start_unix=week_ago_unix,
                    end_unix=now_unix,
                )
                sleep_info = withings.sleep_to_metric(sleep_raw)

                activity_list = await withings.get_activity(
                    withings_conn.access_token, yesterday, today
                )
                steps = None
                if activity_list:
                    steps = activity_list[0].get("steps")

                health_metric = HealthMetric(
                    user_id=current_user.id,
                    recorded_at=datetime.now(timezone.utc),
                    resting_hr=sleep_info.get("resting_hr"),
                    sleep_duration_min=sleep_info.get("sleep_duration_min"),
                    sleep_quality_score=sleep_info.get("sleep_quality_score"),
                    steps=steps,
                    source="withings",
                )
                db.add(health_metric)

                withings_conn.last_synced_at = datetime.now(timezone.utc)
                providers.append("withings")
                break
            except Exception:
                if not _refreshed and await _refresh_token_for(withings_conn, withings):
                    _refreshed = True
                    continue
                break

    # COROS-Verbindung laden
    coros_result = await db.execute(
        select(WatchConnection).where(
            WatchConnection.user_id == current_user.id,
            WatchConnection.provider == "coros",
            WatchConnection.is_active == True,
        )
    )
    coros_conn = coros_result.scalar_one_or_none()

    if coros_conn and coros_conn.provider_athlete_id:
        # COROS refresh benutzt open_id zusätzlich zum refresh_token
        _refreshed = False
        while True:
            try:
                from datetime import date

                sports = await coros.get_sport_list(
                    coros_conn.access_token, coros_conn.provider_athlete_id, size=10
                )
                if sports:
                    for sport in sports:
                        update = coros.sport_to_training_plan_update(sport)
                        if not update["date"]:
                            continue
                        sport_date = date.fromisoformat(update["date"])
                        plan_result = await db.execute(
                            select(TrainingPlan).where(
                                TrainingPlan.user_id == current_user.id,
                                TrainingPlan.date == sport_date,
                            )
                        )
                        plan = plan_result.scalar_one_or_none()
                        if plan and plan.status != "completed":
                            plan.status = "completed"
                            if update.get("avg_hr"):
                                plan.target_hr_min = update["avg_hr"] - 10
                                plan.target_hr_max = update["avg_hr"] + 10
                            synced_count += 1

                    coros_conn.last_synced_at = datetime.now(timezone.utc)
                    providers.append("coros")
                break
            except Exception:
                if not _refreshed and coros_conn.refresh_token:
                    try:
                        new_tokens = await coros.refresh_token(
                            coros_conn.refresh_token,
                            coros_conn.provider_athlete_id,
                        )
                        coros_conn.access_token = new_tokens["access_token"]
                        coros_conn.refresh_token = new_tokens.get(
                            "refresh_token", coros_conn.refresh_token
                        )
                        _refreshed = True
                        continue
                    except Exception:
                        pass
                break

    # Zepp/Amazfit-Verbindung laden
    zepp_result = await db.execute(
        select(WatchConnection).where(
            WatchConnection.user_id == current_user.id,
            WatchConnection.provider == "zepp",
            WatchConnection.is_active == True,
        )
    )
    zepp_conn = zepp_result.scalar_one_or_none()

    if zepp_conn and zepp_conn.provider_athlete_id:
        import time as _time
        _refreshed = False
        while True:
            try:
                from datetime import date

                week_ago = int(_time.time()) - 7 * 86400
                workouts = await zepp.get_workouts(
                    zepp_conn.access_token,
                    zepp_conn.provider_athlete_id,
                    from_time=week_ago,
                    limit=10,
                )
                if workouts:
                    for workout in workouts:
                        update = zepp.workout_to_training_plan_update(workout)
                        if not update["date"]:
                            continue
                        workout_date = date.fromisoformat(update["date"])
                        plan_result = await db.execute(
                            select(TrainingPlan).where(
                                TrainingPlan.user_id == current_user.id,
                                TrainingPlan.date == workout_date,
                            )
                        )
                        plan = plan_result.scalar_one_or_none()
                        if plan and plan.status != "completed":
                            plan.status = "completed"
                            if update.get("avg_hr"):
                                plan.target_hr_min = update["avg_hr"] - 10
                                plan.target_hr_max = update["avg_hr"] + 10
                            synced_count += 1

                    zepp_conn.last_synced_at = datetime.now(timezone.utc)
                    providers.append("zepp")
                break
            except Exception:
                if not _refreshed and await _refresh_token_for(zepp_conn, zepp):
                    _refreshed = True
                    continue
                break

    # WHOOP-Verbindung laden
    whoop_result = await db.execute(
        select(WatchConnection).where(
            WatchConnection.user_id == current_user.id,
            WatchConnection.provider == "whoop",
            WatchConnection.is_active == True,
        )
    )
    whoop_conn = whoop_result.scalar_one_or_none()

    if whoop_conn:
        _refreshed = False
        while True:
            try:
                from datetime import date, timedelta, timezone as _tz
                import datetime as _dt

                week_ago_iso = (
                    _dt.datetime.now(_tz.utc) - timedelta(days=7)
                ).strftime("%Y-%m-%dT%H:%M:%S.000Z")
                now_iso = _dt.datetime.now(_tz.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

                workouts = await whoop.get_workout_collection(
                    whoop_conn.access_token, start=week_ago_iso, end=now_iso, limit=10
                )
                for workout in workouts:
                    update = whoop.workout_to_training_plan_update(workout)
                    if not update["date"]:
                        continue
                    workout_date = date.fromisoformat(update["date"])
                    plan_result = await db.execute(
                        select(TrainingPlan).where(
                            TrainingPlan.user_id == current_user.id,
                            TrainingPlan.date == workout_date,
                        )
                    )
                    plan = plan_result.scalar_one_or_none()
                    if plan and plan.status != "completed":
                        plan.status = "completed"
                        if update.get("avg_hr"):
                            plan.target_hr_min = update["avg_hr"] - 10
                            plan.target_hr_max = update["avg_hr"] + 10
                        synced_count += 1

                recoveries = await whoop.get_recovery_collection(
                    whoop_conn.access_token, start=week_ago_iso, end=now_iso, limit=5
                )
                for recovery in recoveries:
                    rec_metric = whoop.recovery_to_metric(recovery)
                    health_metric = HealthMetric(
                        user_id=current_user.id,
                        recorded_at=datetime.now(timezone.utc),
                        hrv=rec_metric.get("hrv"),
                        resting_hr=rec_metric.get("resting_hr"),
                        spo2=rec_metric.get("spo2"),
                        source="whoop",
                    )
                    db.add(health_metric)

                sleeps = await whoop.get_sleep_collection(
                    whoop_conn.access_token, start=week_ago_iso, end=now_iso, limit=5
                )
                for sleep in sleeps:
                    sleep_info = whoop.sleep_to_metric(sleep)
                    health_metric = HealthMetric(
                        user_id=current_user.id,
                        recorded_at=datetime.now(timezone.utc),
                        sleep_duration_min=sleep_info.get("sleep_duration_min"),
                        sleep_quality_score=sleep_info.get("sleep_quality_score"),
                        source="whoop",
                    )
                    db.add(health_metric)

                whoop_conn.last_synced_at = datetime.now(timezone.utc)
                providers.append("whoop")
                break
            except Exception:
                if not _refreshed and await _refresh_token_for(whoop_conn, whoop):
                    _refreshed = True
                    continue
                break

    # Samsung Health-Verbindung laden
    samsung_result = await db.execute(
        select(WatchConnection).where(
            WatchConnection.user_id == current_user.id,
            WatchConnection.provider == "samsung_health",
            WatchConnection.is_active == True,
        )
    )
    samsung_conn = samsung_result.scalar_one_or_none()

    if samsung_conn:
        import time as _time
        _refreshed = False
        while True:
            try:
                from datetime import date, timedelta

                now_ms = int(_time.time() * 1000)
                week_ago_ms = now_ms - 7 * 86400 * 1000

                exercises = await samsung_health.get_exercises(
                    samsung_conn.access_token, week_ago_ms, now_ms, limit=10
                )
                for exercise in exercises:
                    update = samsung_health.exercise_to_training_plan_update(exercise)
                    if not update["date"]:
                        continue
                    ex_date = date.fromisoformat(update["date"])
                    plan_result = await db.execute(
                        select(TrainingPlan).where(
                            TrainingPlan.user_id == current_user.id,
                            TrainingPlan.date == ex_date,
                        )
                    )
                    plan = plan_result.scalar_one_or_none()
                    if plan and plan.status != "completed":
                        plan.status = "completed"
                        if update.get("avg_hr"):
                            plan.target_hr_min = update["avg_hr"] - 10
                            plan.target_hr_max = update["avg_hr"] + 10
                        synced_count += 1

                sleeps = await samsung_health.get_sleep(
                    samsung_conn.access_token, week_ago_ms, now_ms
                )
                if sleeps:
                    sleep_info = samsung_health.sleep_to_metric(sleeps[-1])
                    health_metric = HealthMetric(
                        user_id=current_user.id,
                        recorded_at=datetime.now(timezone.utc),
                        sleep_duration_min=sleep_info.get("sleep_duration_min"),
                        sleep_quality_score=sleep_info.get("sleep_quality_score"),
                        source="samsung_health",
                    )
                    db.add(health_metric)

                samsung_conn.last_synced_at = datetime.now(timezone.utc)
                providers.append("samsung_health")
                break
            except Exception:
                if not _refreshed and await _refresh_token_for(samsung_conn, samsung_health):
                    _refreshed = True
                    continue
                break

    # Google Fit-Verbindung laden (Nothing Watch, Wear OS, OnePlus Watch, ...)
    googlefit_result = await db.execute(
        select(WatchConnection).where(
            WatchConnection.user_id == current_user.id,
            WatchConnection.provider == "google_fit",
            WatchConnection.is_active == True,
        )
    )
    googlefit_conn = googlefit_result.scalar_one_or_none()

    if googlefit_conn:
        import time as _time
        _refreshed = False
        while True:
            try:
                from datetime import date, timedelta

                now_ms = int(_time.time() * 1000)
                week_ago_ms = now_ms - 7 * 86400 * 1000

                sessions = await google_fit.get_sessions(
                    googlefit_conn.access_token, week_ago_ms, now_ms
                )
                for session in sessions:
                    update = google_fit.session_to_training_plan_update(session)
                    if not update["date"]:
                        continue
                    session_date = date.fromisoformat(update["date"])
                    plan_result = await db.execute(
                        select(TrainingPlan).where(
                            TrainingPlan.user_id == current_user.id,
                            TrainingPlan.date == session_date,
                        )
                    )
                    plan = plan_result.scalar_one_or_none()
                    if plan and plan.status != "completed":
                        plan.status = "completed"
                        synced_count += 1

                sleep_summary = await google_fit.get_sleep_summary(
                    googlefit_conn.access_token, week_ago_ms, now_ms
                )
                resting_hr = await google_fit.get_resting_heart_rate(
                    googlefit_conn.access_token, week_ago_ms, now_ms
                )
                steps = await google_fit.get_daily_steps(
                    googlefit_conn.access_token, week_ago_ms, now_ms
                )

                health_metric = HealthMetric(
                    user_id=current_user.id,
                    recorded_at=datetime.now(timezone.utc),
                    sleep_duration_min=sleep_summary.get("sleep_duration_min"),
                    resting_hr=int(resting_hr) if resting_hr else None,
                    steps=steps or None,
                    source="google_fit",
                )
                db.add(health_metric)

                googlefit_conn.last_synced_at = datetime.now(timezone.utc)
                providers.append("google_fit")
                break
            except Exception:
                if not _refreshed and await _refresh_token_for(googlefit_conn, google_fit):
                    _refreshed = True
                    continue
                break

    if strava_conn or garmin_conn or polar_conn or wahoo_conn or fitbit_conn or suunto_conn or withings_conn or coros_conn or zepp_conn or whoop_conn or samsung_conn or googlefit_conn:
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
    vo2_max: float | None = None
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
        vo2_max=body.vo2_max,
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
    spo2: float | None = None
    steps: int | None = None
    vo2_max: float | None = None

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
        spo2=body.spo2,
        steps=body.steps,
        vo2_max=body.vo2_max,
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

    if hub_mode == "subscribe" and secrets.compare_digest(
        hub_verify_token or "", expected_token
    ):
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

    # User anhand der Strava Athlete-ID direkt in SQL finden (kein Full-Table-Scan)
    result = await db.execute(
        select(WatchConnection).where(
            WatchConnection.provider == "strava",
            WatchConnection.provider_athlete_id == str(event.owner_id),
            WatchConnection.is_active == True,
        )
    )
    target_connection = result.scalar_one_or_none()

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


@router.post("/strava/webhook/subscribe")
async def strava_webhook_subscribe(
    current_user: User = Depends(get_current_user),
):
    """
    Registriert unseren Webhook bei Strava (einmalig nötig).
    Strava validiert den Endpoint sofort mit einem GET-Request.
    Callback-URL muss öffentlich erreichbar sein (kein localhost).
    """
    if not settings.strava_client_id:
        raise HTTPException(status_code=503, detail="Strava nicht konfiguriert")

    callback_url = f"{settings.frontend_url.rstrip('/')}/api/watch/strava/webhook"
    # Wenn frontend_url localhost ist, schlägt die Strava-Validierung fehl
    if "localhost" in callback_url or "127.0.0.1" in callback_url:
        raise HTTPException(
            status_code=400,
            detail="Strava Webhooks benötigen eine öffentlich erreichbare URL. "
                   "Setze FRONTEND_URL auf deine Produktions-Domain.",
        )

    # Prüfen ob bereits eine Subscription existiert
    existing = await strava.get_webhook_subscription()
    if existing:
        return {
            "status": "already_subscribed",
            "subscription_id": existing.get("id"),
            "callback_url": existing.get("callback_url"),
        }

    try:
        result = await strava.subscribe_webhook(callback_url)
        return {
            "status": "subscribed",
            "subscription_id": result.get("id"),
            "callback_url": callback_url,
        }
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Webhook-Registrierung fehlgeschlagen: {e}",
        )


@router.get("/strava/webhook/subscription")
async def strava_webhook_subscription_status(
    current_user: User = Depends(get_current_user),
):
    """Gibt den Status der aktuellen Strava Webhook Subscription zurück."""
    if not settings.strava_client_id:
        raise HTTPException(status_code=503, detail="Strava nicht konfiguriert")

    subscription = await strava.get_webhook_subscription()
    if subscription:
        return {"active": True, "subscription": subscription}
    return {"active": False, "subscription": None}


@router.delete("/strava/webhook/subscription")
async def strava_webhook_unsubscribe(
    current_user: User = Depends(get_current_user),
):
    """Löscht die Strava Webhook Subscription."""
    if not settings.strava_client_id:
        raise HTTPException(status_code=503, detail="Strava nicht konfiguriert")

    subscription = await strava.get_webhook_subscription()
    if not subscription:
        raise HTTPException(status_code=404, detail="Keine aktive Subscription gefunden")

    await strava.delete_webhook_subscription(subscription["id"])
    return {"status": "unsubscribed", "deleted_id": subscription["id"]}


# ─── Datei-Upload (GPX / TCX) ─────────────────────────────────────────────────


@router.post("/upload-gpx")
async def upload_gpx(
    provider: str = Form(..., description="polar | apple | garmin | other"),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Importiert eine GPX- oder TCX-Datei.
    Polar Flow: sport.polar.com > Export GPX
    Apple Health: iOS Health App > Profil > Alle Gesundheitssdaten exportieren (dann GPX)
    """
    import xml.etree.ElementTree as ET
    from datetime import date as date_type

    if not file.filename or not file.filename.lower().endswith((".gpx", ".tcx", ".xml")):
        raise HTTPException(status_code=400, detail="Nur GPX-, TCX- oder XML-Dateien erlaubt.")

    raw = await file.read()
    if len(raw) > 10 * 1024 * 1024:  # 10 MB Limit
        raise HTTPException(status_code=400, detail="Datei zu groß (max. 10 MB).")

    try:
        root = ET.fromstring(raw.decode("utf-8", errors="replace"))
    except ET.ParseError:
        raise HTTPException(status_code=400, detail="Ungültige XML/GPX-Datei.")

    # Namespace-agnostisches Element-Suchen
    def find_text(el: ET.Element, *tags: str) -> str | None:
        for tag in tags:
            for child in el.iter():
                if child.tag.split("}")[-1] == tag and child.text:
                    return child.text.strip()
        return None

    activity_name = find_text(root, "name", "Activity") or file.filename
    time_str = find_text(root, "time", "Time", "StartTime")
    activity_date: date_type | None = None
    if time_str:
        try:
            activity_date = datetime.fromisoformat(time_str.replace("Z", "+00:00")).date()
        except ValueError:
            pass
    if not activity_date:
        activity_date = date_type.today()

    # Distanz + Dauer aus trackpoints schätzen
    trkpts = [el for el in root.iter() if el.tag.split("}")[-1] in ("trkpt", "Trackpoint")]
    duration_min: int | None = None
    if len(trkpts) >= 2:
        def pt_time(el: ET.Element) -> datetime | None:
            t = find_text(el, "time", "Time")
            if t:
                try:
                    return datetime.fromisoformat(t.replace("Z", "+00:00"))
                except ValueError:
                    pass
            return None
        t_start = pt_time(trkpts[0])
        t_end = pt_time(trkpts[-1])
        if t_start and t_end:
            duration_min = max(1, int((t_end - t_start).total_seconds() / 60))

    # Training in DB anlegen / updaten
    plan_result = await db.execute(
        select(TrainingPlan).where(
            TrainingPlan.user_id == current_user.id,
            TrainingPlan.date == activity_date,
        )
    )
    plan = plan_result.scalar_one_or_none()
    if plan:
        plan.status = "completed"
        if duration_min:
            plan.duration_min = duration_min
    else:
        plan = TrainingPlan(
            user_id=current_user.id,
            date=activity_date,
            title=activity_name[:200],
            sport="other",
            status="completed",
            duration_min=duration_min or 30,
        )
        db.add(plan)

    # Provider-Verbindung als "aktiv" markieren (damit Status-Check es anzeigt)
    conn_result = await db.execute(
        select(WatchConnection).where(
            WatchConnection.user_id == current_user.id,
            WatchConnection.provider == provider,
        )
    )
    conn = conn_result.scalar_one_or_none()
    if not conn:
        conn = WatchConnection(
            user_id=current_user.id,
            provider=provider,
            is_active=True,
            last_synced_at=datetime.now(timezone.utc),
        )
        db.add(conn)
    else:
        conn.is_active = True
        conn.last_synced_at = datetime.now(timezone.utc)

    await db.commit()

    return {
        "ok": True,
        "activity_date": activity_date.isoformat(),
        "activity_name": activity_name,
        "duration_min": duration_min,
    }


# ─── Polar AccessLink OAuth ────────────────────────────────────────────────────


@router.get("/polar/connect")
async def polar_connect(
    current_user: User = Depends(get_current_user),
):
    """Polar nutzt GPX-Dateiupload — kein OAuth-Key nötig."""
    return {"method": "file_upload", "detail": "Polar: GPX aus sport.polar.com exportieren und hochladen."}



@router.get("/polar/callback")
async def polar_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Polar leitet hierher weiter nach Authorization.
    Tauscht Code gegen Token, registriert User in AccessLink und speichert Verbindung.
    """
    user_id_str = await _consume_oauth_state(state)
    if not user_id_str:
        raise HTTPException(status_code=400, detail="Ungültiger oder abgelaufener OAuth-State")

    try:
        target_user_id = uuid_module.UUID(user_id_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Ungültige User-ID im OAuth-State")

    try:
        token_data = await polar.exchange_code(code)
    except Exception:
        raise HTTPException(status_code=400, detail="Polar-Authentifizierung fehlgeschlagen")

    polar_user_id = token_data.get("x_user_id")  # Polar liefert x_user_id im Token-Response

    # User in AccessLink registrieren (einmalig, 409 = bereits registriert → ok)
    if polar_user_id:
        try:
            await polar.register_user(token_data["access_token"], polar_user_id)
        except Exception:
            pass  # 409 Conflict ist kein Fehler

    result = await db.execute(
        select(WatchConnection).where(
            WatchConnection.user_id == target_user_id,
            WatchConnection.provider == "polar",
        )
    )
    connection = result.scalar_one_or_none()

    if connection:
        connection.access_token = token_data["access_token"]
        connection.refresh_token = token_data.get("refresh_token", "")
        connection.provider_athlete_id = str(polar_user_id) if polar_user_id else None
        connection.is_active = True
    else:
        connection = WatchConnection(
            user_id=target_user_id,
            provider="polar",
            provider_athlete_id=str(polar_user_id) if polar_user_id else None,
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token", ""),
            is_active=True,
        )
        db.add(connection)

    await db.commit()
    return RedirectResponse(url=f"{settings.frontend_url}/onboarding?polar=connected")


@router.post("/polar/disconnect")
async def polar_disconnect(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Trennt Polar-Verbindung."""
    result = await db.execute(
        select(WatchConnection).where(
            WatchConnection.user_id == current_user.id,
            WatchConnection.provider == "polar",
        )
    )
    connection = result.scalar_one_or_none()
    if connection:
        connection.is_active = False
        await db.commit()
    return {"ok": True}


# ─── Wahoo OAuth ───────────────────────────────────────────────────────────────


@router.get("/wahoo/connect")
async def wahoo_connect(
    current_user: User = Depends(get_current_user),
):
    """Leitet den User zur Wahoo OAuth2-Seite weiter."""
    if not settings.wahoo_client_id:
        raise HTTPException(status_code=503, detail="Wahoo nicht konfiguriert")

    state = secrets.token_urlsafe(32)
    await _store_oauth_state(state, str(current_user.id))
    auth_url = wahoo.get_auth_url(state=state)
    return {"auth_url": auth_url}


@router.get("/wahoo/callback")
async def wahoo_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Wahoo leitet hierher weiter nach Authorization."""
    user_id_str = await _consume_oauth_state(state)
    if not user_id_str:
        raise HTTPException(status_code=400, detail="Ungültiger oder abgelaufener OAuth-State")

    try:
        target_user_id = uuid_module.UUID(user_id_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Ungültige User-ID im OAuth-State")

    try:
        token_data = await wahoo.exchange_code(code)
        user_info = await wahoo.get_user(token_data["access_token"])
    except Exception:
        raise HTTPException(status_code=400, detail="Wahoo-Authentifizierung fehlgeschlagen")

    wahoo_user_id = str(user_info.get("id", ""))

    result = await db.execute(
        select(WatchConnection).where(
            WatchConnection.user_id == target_user_id,
            WatchConnection.provider == "wahoo",
        )
    )
    connection = result.scalar_one_or_none()

    if connection:
        connection.access_token = token_data["access_token"]
        connection.refresh_token = token_data.get("refresh_token", "")
        connection.provider_athlete_id = wahoo_user_id
        connection.is_active = True
    else:
        connection = WatchConnection(
            user_id=target_user_id,
            provider="wahoo",
            provider_athlete_id=wahoo_user_id,
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token", ""),
            is_active=True,
        )
        db.add(connection)

    await db.commit()
    return RedirectResponse(url=f"{settings.frontend_url}/onboarding?wahoo=connected")


@router.post("/wahoo/disconnect")
async def wahoo_disconnect(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Trennt Wahoo-Verbindung."""
    result = await db.execute(
        select(WatchConnection).where(
            WatchConnection.user_id == current_user.id,
            WatchConnection.provider == "wahoo",
        )
    )
    connection = result.scalar_one_or_none()
    if connection:
        connection.is_active = False
        await db.commit()
    return {"ok": True}


# ─── Fitbit OAuth ──────────────────────────────────────────────────────────────


@router.get("/fitbit/connect")
async def fitbit_connect(
    current_user: User = Depends(get_current_user),
):
    """Leitet den User zur Fitbit OAuth2-Seite weiter."""
    if not settings.fitbit_client_id:
        raise HTTPException(status_code=503, detail="Fitbit nicht konfiguriert")

    state = secrets.token_urlsafe(32)
    await _store_oauth_state(state, str(current_user.id))
    auth_url = fitbit.get_auth_url(state=state)
    return {"auth_url": auth_url}


@router.get("/fitbit/callback")
async def fitbit_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Fitbit leitet hierher weiter nach Authorization."""
    user_id_str = await _consume_oauth_state(state)
    if not user_id_str:
        raise HTTPException(status_code=400, detail="Ungültiger oder abgelaufener OAuth-State")

    try:
        target_user_id = uuid_module.UUID(user_id_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Ungültige User-ID im OAuth-State")

    try:
        token_data = await fitbit.exchange_code(code)
        profile = await fitbit.get_profile(token_data["access_token"])
    except Exception:
        raise HTTPException(status_code=400, detail="Fitbit-Authentifizierung fehlgeschlagen")

    fitbit_user_id = profile.get("encodedId", "")

    result = await db.execute(
        select(WatchConnection).where(
            WatchConnection.user_id == target_user_id,
            WatchConnection.provider == "fitbit",
        )
    )
    connection = result.scalar_one_or_none()

    if connection:
        connection.access_token = token_data["access_token"]
        connection.refresh_token = token_data.get("refresh_token", "")
        connection.provider_athlete_id = fitbit_user_id
        connection.is_active = True
    else:
        connection = WatchConnection(
            user_id=target_user_id,
            provider="fitbit",
            provider_athlete_id=fitbit_user_id,
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token", ""),
            is_active=True,
        )
        db.add(connection)

    await db.commit()
    return RedirectResponse(url=f"{settings.frontend_url}/onboarding?fitbit=connected")


@router.post("/fitbit/disconnect")
async def fitbit_disconnect(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Trennt Fitbit-Verbindung."""
    result = await db.execute(
        select(WatchConnection).where(
            WatchConnection.user_id == current_user.id,
            WatchConnection.provider == "fitbit",
        )
    )
    connection = result.scalar_one_or_none()
    if connection:
        connection.is_active = False
        await db.commit()
    return {"ok": True}


# ─── Suunto OAuth ─────────────────────────────────────────────────────────────


@router.get("/suunto/connect")
async def suunto_connect(
    current_user: User = Depends(get_current_user),
):
    """Leitet den User zur Suunto OAuth2-Seite weiter."""
    if not settings.suunto_client_id:
        raise HTTPException(status_code=503, detail="Suunto nicht konfiguriert")

    state = secrets.token_urlsafe(32)
    await _store_oauth_state(state, str(current_user.id))
    auth_url = suunto.get_auth_url(state=state)
    return {"auth_url": auth_url}


@router.get("/suunto/callback")
async def suunto_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Suunto leitet hierher weiter nach Authorization."""
    user_id_str = await _consume_oauth_state(state)
    if not user_id_str:
        raise HTTPException(status_code=400, detail="Ungültiger oder abgelaufener OAuth-State")

    try:
        target_user_id = uuid_module.UUID(user_id_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Ungültige User-ID im OAuth-State")

    try:
        token_data = await suunto.exchange_code(code)
        user_info = await suunto.get_user(token_data["access_token"])
    except Exception:
        raise HTTPException(status_code=400, detail="Suunto-Authentifizierung fehlgeschlagen")

    suunto_username = user_info.get("username") or user_info.get("userId", "")

    result = await db.execute(
        select(WatchConnection).where(
            WatchConnection.user_id == target_user_id,
            WatchConnection.provider == "suunto",
        )
    )
    connection = result.scalar_one_or_none()

    if connection:
        connection.access_token = token_data["access_token"]
        connection.refresh_token = token_data.get("refresh_token", "")
        connection.provider_athlete_id = str(suunto_username)
        connection.is_active = True
    else:
        connection = WatchConnection(
            user_id=target_user_id,
            provider="suunto",
            provider_athlete_id=str(suunto_username),
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token", ""),
            is_active=True,
        )
        db.add(connection)

    await db.commit()
    return RedirectResponse(url=f"{settings.frontend_url}/onboarding?suunto=connected")


@router.post("/suunto/disconnect")
async def suunto_disconnect(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Trennt Suunto-Verbindung."""
    result = await db.execute(
        select(WatchConnection).where(
            WatchConnection.user_id == current_user.id,
            WatchConnection.provider == "suunto",
        )
    )
    connection = result.scalar_one_or_none()
    if connection:
        connection.is_active = False
        await db.commit()
    return {"ok": True}


# ─── Withings OAuth ───────────────────────────────────────────────────────────


@router.get("/withings/connect")
async def withings_connect(
    current_user: User = Depends(get_current_user),
):
    """Leitet den User zur Withings OAuth2-Seite weiter."""
    if not settings.withings_client_id:
        raise HTTPException(status_code=503, detail="Withings nicht konfiguriert")

    state = secrets.token_urlsafe(32)
    await _store_oauth_state(state, str(current_user.id))
    auth_url = withings.get_auth_url(state=state)
    return {"auth_url": auth_url}


@router.get("/withings/callback")
async def withings_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Withings leitet hierher weiter nach Authorization."""
    user_id_str = await _consume_oauth_state(state)
    if not user_id_str:
        raise HTTPException(status_code=400, detail="Ungültiger oder abgelaufener OAuth-State")

    try:
        target_user_id = uuid_module.UUID(user_id_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Ungültige User-ID im OAuth-State")

    try:
        token_data = await withings.exchange_code(code)
    except Exception:
        raise HTTPException(status_code=400, detail="Withings-Authentifizierung fehlgeschlagen")

    withings_user_id = str(token_data.get("userid", ""))

    result = await db.execute(
        select(WatchConnection).where(
            WatchConnection.user_id == target_user_id,
            WatchConnection.provider == "withings",
        )
    )
    connection = result.scalar_one_or_none()

    if connection:
        connection.access_token = token_data["access_token"]
        connection.refresh_token = token_data.get("refresh_token", "")
        connection.provider_athlete_id = withings_user_id
        connection.is_active = True
    else:
        connection = WatchConnection(
            user_id=target_user_id,
            provider="withings",
            provider_athlete_id=withings_user_id,
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token", ""),
            is_active=True,
        )
        db.add(connection)

    await db.commit()
    return RedirectResponse(url=f"{settings.frontend_url}/onboarding?withings=connected")


@router.post("/withings/disconnect")
async def withings_disconnect(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Trennt Withings-Verbindung."""
    result = await db.execute(
        select(WatchConnection).where(
            WatchConnection.user_id == current_user.id,
            WatchConnection.provider == "withings",
        )
    )
    connection = result.scalar_one_or_none()
    if connection:
        connection.is_active = False
        await db.commit()
    return {"ok": True}


# ─── COROS OAuth ──────────────────────────────────────────────────────────────


@router.get("/coros/connect")
async def coros_connect(
    current_user: User = Depends(get_current_user),
):
    """Leitet den User zur COROS OAuth2-Seite weiter."""
    if not settings.coros_client_id:
        raise HTTPException(status_code=503, detail="COROS nicht konfiguriert")

    state = secrets.token_urlsafe(32)
    await _store_oauth_state(state, str(current_user.id))
    auth_url = coros.get_auth_url(state=state)
    return {"auth_url": auth_url}


@router.get("/coros/callback")
async def coros_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """COROS leitet hierher weiter nach Authorization."""
    user_id_str = await _consume_oauth_state(state)
    if not user_id_str:
        raise HTTPException(status_code=400, detail="Ungültiger oder abgelaufener OAuth-State")

    try:
        target_user_id = uuid_module.UUID(user_id_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Ungültige User-ID im OAuth-State")

    try:
        token_data = await coros.exchange_code(code)
    except Exception:
        raise HTTPException(status_code=400, detail="COROS-Authentifizierung fehlgeschlagen")

    open_id = token_data.get("open_id", "")

    result = await db.execute(
        select(WatchConnection).where(
            WatchConnection.user_id == target_user_id,
            WatchConnection.provider == "coros",
        )
    )
    connection = result.scalar_one_or_none()

    if connection:
        connection.access_token = token_data["access_token"]
        connection.refresh_token = token_data.get("refresh_token", "")
        connection.provider_athlete_id = open_id
        connection.is_active = True
    else:
        connection = WatchConnection(
            user_id=target_user_id,
            provider="coros",
            provider_athlete_id=open_id,
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token", ""),
            is_active=True,
        )
        db.add(connection)

    await db.commit()
    return RedirectResponse(url=f"{settings.frontend_url}/onboarding?coros=connected")


@router.post("/coros/disconnect")
async def coros_disconnect(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Trennt COROS-Verbindung."""
    result = await db.execute(
        select(WatchConnection).where(
            WatchConnection.user_id == current_user.id,
            WatchConnection.provider == "coros",
        )
    )
    connection = result.scalar_one_or_none()
    if connection:
        connection.is_active = False
        await db.commit()
    return {"ok": True}


# ─── Zepp / Amazfit OAuth ──────────────────────────────────────────────────────


@router.get("/zepp/connect")
async def zepp_connect(
    current_user: User = Depends(get_current_user),
):
    """Leitet den User zur Zepp (Amazfit) OAuth2-Seite weiter."""
    if not settings.zepp_client_id:
        raise HTTPException(status_code=503, detail="Zepp/Amazfit nicht konfiguriert")

    state = secrets.token_urlsafe(32)
    await _store_oauth_state(state, str(current_user.id))
    auth_url = zepp.get_auth_url(state=state)
    return {"auth_url": auth_url}


@router.get("/zepp/callback")
async def zepp_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Zepp leitet hierher weiter nach Authorization."""
    user_id_str = await _consume_oauth_state(state)
    if not user_id_str:
        raise HTTPException(status_code=400, detail="Ungültiger oder abgelaufener OAuth-State")

    try:
        target_user_id = uuid_module.UUID(user_id_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Ungültige User-ID im OAuth-State")

    try:
        token_data = await zepp.exchange_code(code)
    except Exception:
        raise HTTPException(status_code=400, detail="Zepp-Authentifizierung fehlgeschlagen")

    open_id = token_data.get("open_id", "")

    result = await db.execute(
        select(WatchConnection).where(
            WatchConnection.user_id == target_user_id,
            WatchConnection.provider == "zepp",
        )
    )
    connection = result.scalar_one_or_none()

    if connection:
        connection.access_token = token_data["access_token"]
        connection.refresh_token = token_data.get("refresh_token", "")
        connection.provider_athlete_id = open_id
        connection.is_active = True
    else:
        connection = WatchConnection(
            user_id=target_user_id,
            provider="zepp",
            provider_athlete_id=open_id,
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token", ""),
            is_active=True,
        )
        db.add(connection)

    await db.commit()
    return RedirectResponse(url=f"{settings.frontend_url}/onboarding?zepp=connected")


@router.post("/zepp/disconnect")
async def zepp_disconnect(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Trennt Zepp/Amazfit-Verbindung."""
    result = await db.execute(
        select(WatchConnection).where(
            WatchConnection.user_id == current_user.id,
            WatchConnection.provider == "zepp",
        )
    )
    connection = result.scalar_one_or_none()
    if connection:
        connection.is_active = False
        await db.commit()
    return {"ok": True}


# ─── WHOOP OAuth ──────────────────────────────────────────────────────────────


@router.get("/whoop/connect")
async def whoop_connect(
    current_user: User = Depends(get_current_user),
):
    """Leitet den User zur WHOOP OAuth2-Seite weiter."""
    if not settings.whoop_client_id:
        raise HTTPException(status_code=503, detail="WHOOP nicht konfiguriert")

    state = secrets.token_urlsafe(32)
    await _store_oauth_state(state, str(current_user.id))
    auth_url = whoop.get_auth_url(state=state)
    return {"auth_url": auth_url}


@router.get("/whoop/callback")
async def whoop_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """WHOOP leitet hierher weiter nach Authorization."""
    user_id_str = await _consume_oauth_state(state)
    if not user_id_str:
        raise HTTPException(status_code=400, detail="Ungültiger oder abgelaufener OAuth-State")

    try:
        target_user_id = uuid_module.UUID(user_id_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Ungültige User-ID im OAuth-State")

    try:
        token_data = await whoop.exchange_code(code)
        profile = await whoop.get_profile(token_data["access_token"])
    except Exception:
        raise HTTPException(status_code=400, detail="WHOOP-Authentifizierung fehlgeschlagen")

    whoop_user_id = str(profile.get("user_id", ""))

    result = await db.execute(
        select(WatchConnection).where(
            WatchConnection.user_id == target_user_id,
            WatchConnection.provider == "whoop",
        )
    )
    connection = result.scalar_one_or_none()

    if connection:
        connection.access_token = token_data["access_token"]
        connection.refresh_token = token_data.get("refresh_token", "")
        connection.provider_athlete_id = whoop_user_id
        connection.is_active = True
    else:
        connection = WatchConnection(
            user_id=target_user_id,
            provider="whoop",
            provider_athlete_id=whoop_user_id,
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token", ""),
            is_active=True,
        )
        db.add(connection)

    await db.commit()
    return RedirectResponse(url=f"{settings.frontend_url}/onboarding?whoop=connected")


@router.post("/whoop/disconnect")
async def whoop_disconnect(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Trennt WHOOP-Verbindung."""
    result = await db.execute(
        select(WatchConnection).where(
            WatchConnection.user_id == current_user.id,
            WatchConnection.provider == "whoop",
        )
    )
    connection = result.scalar_one_or_none()
    if connection:
        connection.is_active = False
        await db.commit()
    return {"ok": True}


# ─── Samsung Health OAuth ───────────────────────────────────────────────────


@router.get("/samsung/connect")
async def samsung_connect(
    current_user: User = Depends(get_current_user),
):
    """Leitet den User zur Samsung Account OAuth2-Seite weiter."""
    if not settings.samsung_health_client_id:
        raise HTTPException(status_code=503, detail="Samsung Health nicht konfiguriert")

    state = secrets.token_urlsafe(32)
    await _store_oauth_state(state, str(current_user.id))
    auth_url = samsung_health.get_auth_url(state=state)
    return {"auth_url": auth_url}


@router.get("/samsung/callback")
async def samsung_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Samsung leitet hierher weiter nach Authorization."""
    user_id_str = await _consume_oauth_state(state)
    if not user_id_str:
        raise HTTPException(status_code=400, detail="Ungültiger oder abgelaufener OAuth-State")

    try:
        target_user_id = uuid_module.UUID(user_id_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Ungültige User-ID im OAuth-State")

    try:
        token_data = await samsung_health.exchange_code(code)
        profile = await samsung_health.get_user_profile(token_data["access_token"])
    except Exception:
        raise HTTPException(status_code=400, detail="Samsung-Authentifizierung fehlgeschlagen")

    samsung_user_id = str(profile.get("user_id") or profile.get("userId", ""))

    result = await db.execute(
        select(WatchConnection).where(
            WatchConnection.user_id == target_user_id,
            WatchConnection.provider == "samsung_health",
        )
    )
    connection = result.scalar_one_or_none()

    if connection:
        connection.access_token = token_data["access_token"]
        connection.refresh_token = token_data.get("refresh_token", "")
        connection.provider_athlete_id = samsung_user_id
        connection.is_active = True
    else:
        connection = WatchConnection(
            user_id=target_user_id,
            provider="samsung_health",
            provider_athlete_id=samsung_user_id,
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token", ""),
            is_active=True,
        )
        db.add(connection)

    await db.commit()
    return RedirectResponse(url=f"{settings.frontend_url}/onboarding?samsung=connected")


@router.post("/samsung/disconnect")
async def samsung_disconnect(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Trennt Samsung Health-Verbindung."""
    result = await db.execute(
        select(WatchConnection).where(
            WatchConnection.user_id == current_user.id,
            WatchConnection.provider == "samsung_health",
        )
    )
    connection = result.scalar_one_or_none()
    if connection:
        connection.is_active = False
        await db.commit()
    return {"ok": True}


# ─── Google Fit / Health Connect OAuth (Nothing Watch, Wear OS, ...) ──────────────


@router.get("/googlefit/connect")
async def googlefit_connect(
    current_user: User = Depends(get_current_user),
):
    """
    Leitet den User zur Google OAuth2-Seite weiter.
    Deckt ab: Nothing Watch Pro, CMF Watch Pro, OnePlus Watch, alle Wear OS Uhren.
    """
    if not settings.google_fit_client_id:
        raise HTTPException(status_code=503, detail="Google Fit nicht konfiguriert")

    state = secrets.token_urlsafe(32)
    await _store_oauth_state(state, str(current_user.id))
    auth_url = google_fit.get_auth_url(state=state)
    return {"auth_url": auth_url}


@router.get("/googlefit/callback")
async def googlefit_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Google leitet hierher weiter nach Authorization."""
    user_id_str = await _consume_oauth_state(state)
    if not user_id_str:
        raise HTTPException(status_code=400, detail="Ungültiger oder abgelaufener OAuth-State")

    try:
        target_user_id = uuid_module.UUID(user_id_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Ungültige User-ID im OAuth-State")

    try:
        token_data = await google_fit.exchange_code(code)
    except Exception:
        raise HTTPException(status_code=400, detail="Google-Authentifizierung fehlgeschlagen")

    # Google liefert keine numeric user ID hier — sub aus id_token wäre nötig,
    # wir speichern den Token selbst als Identifier
    google_user_id = token_data.get("sub", "google")

    result = await db.execute(
        select(WatchConnection).where(
            WatchConnection.user_id == target_user_id,
            WatchConnection.provider == "google_fit",
        )
    )
    connection = result.scalar_one_or_none()

    if connection:
        connection.access_token = token_data["access_token"]
        connection.refresh_token = token_data.get("refresh_token", connection.refresh_token or "")
        connection.provider_athlete_id = google_user_id
        connection.is_active = True
    else:
        connection = WatchConnection(
            user_id=target_user_id,
            provider="google_fit",
            provider_athlete_id=google_user_id,
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token", ""),
            is_active=True,
        )
        db.add(connection)

    await db.commit()
    return RedirectResponse(url=f"{settings.frontend_url}/onboarding?googlefit=connected")


@router.post("/googlefit/disconnect")
async def googlefit_disconnect(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Trennt Google Fit-Verbindung."""
    result = await db.execute(
        select(WatchConnection).where(
            WatchConnection.user_id == current_user.id,
            WatchConnection.provider == "google_fit",
        )
    )
    connection = result.scalar_one_or_none()
    if connection:
        connection.is_active = False
        await db.commit()
    return {"ok": True}
