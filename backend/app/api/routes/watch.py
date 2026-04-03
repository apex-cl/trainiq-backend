"""
Watch/Fitness-Tracker Sync Routes
Unterstützt: Garmin, Polar, Wahoo, Fitbit, Suunto, Withings, COROS, Zepp, WHOOP, Samsung Health, Google Fit, Apple Watch, Manuelle Eingabe
"""

import asyncio
import json
import secrets
import uuid as uuid_module
from datetime import datetime, timezone
from loguru import logger
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
from app.services.garmin_service import GarminService
from app.services.strava_service import StravaService
from app.services.fit_import_service import FitImportService, TcxImportService, GpxImportService, CsvImportService
from app.core.config import settings
from app.core.redis import get_redis

# CSRF-State TTL für OAuth-Flows (10 Minuten)
_OAUTH_STATE_TTL = 600


def _get_redis():
    return get_redis()


async def _store_oauth_state(state_token: str, user_id: str) -> None:
    """Speichert OAuth-State-Token in Redis mit TTL."""
    r = _get_redis()
    await r.set(f"oauth_state:{state_token}", user_id, ex=_OAUTH_STATE_TTL)


async def _consume_oauth_state(state_token: str) -> str | None:
    """Liest und löscht OAuth-State-Token aus Redis. Gibt user_id zurück oder None."""
    try:
        r = _get_redis()
        key = f"oauth_state:{state_token}"
        return await r.getdel(key)  # str with decode_responses=True
    except Exception:
        return None


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
garmin = GarminService()
strava = StravaService()
fit_importer = FitImportService()
tcx_importer = TcxImportService()
gpx_importer = GpxImportService()
csv_importer = CsvImportService()


# ─── 12-Monats Hintergrund-Import nach OAuth-Verbindung ───────────────────────

async def _start_initial_import(
    user_id_str: str,
    provider: str,
    access_token: str,
    open_id: str | None = None,
) -> None:
    """
    Importiert die letzten 12 Monate Aktivitäten nach erfolgreicher OAuth-Verbindung.
    Läuft als asyncio.create_task(), blockiert nie den Request.
    """
    import time as _time
    import datetime as _dt
    from datetime import date as _date, timedelta as _td, timezone as _tz
    from app.core.database import async_session as _sessions

    now = _dt.datetime.now(_tz.utc)
    year_ago = now - _td(days=365)
    user_uuid = uuid_module.UUID(user_id_str)
    year_ago_unix = int(year_ago.timestamp())
    now_unix = int(now.timestamp())
    year_ago_ms = year_ago_unix * 1000
    now_ms = now_unix * 1000
    year_ago_iso = year_ago.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    now_iso = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    items_with_update: list[dict] = []
    raw_activities: list[dict] = []
    try:
        if provider == "strava":
            raw_activities = await strava.get_activities(access_token, after_unix=year_ago_unix, limit=200)
            items_with_update = [strava.activity_to_training_plan_update(a) for a in raw_activities]
    except Exception:
        return  # Verbindung ist gespeichert — stündlicher Scheduler holt den Rest

    now_utc = _dt.datetime.now(_tz.utc)
    async with _sessions() as db:
        try:
            for idx, update in enumerate(items_with_update):
                if not update or not update.get("date"):
                    continue
                try:
                    plan_date = _date.fromisoformat(update["date"])
                except (ValueError, TypeError):
                    continue
                pr = await db.execute(
                    select(TrainingPlan).where(
                        TrainingPlan.user_id == user_uuid,
                        TrainingPlan.date == plan_date,
                    )
                )
                plan = pr.scalar_one_or_none()
                if plan:
                    plan.status = "completed"
                    if update.get("avg_hr"):
                        plan.target_hr_min = update["avg_hr"] - 10
                        plan.target_hr_max = update["avg_hr"] + 10
                else:
                    db.add(TrainingPlan(
                        user_id=user_uuid,
                        date=plan_date,
                        sport=update.get("sport_type") or update.get("sport") or "other",
                        workout_type="imported",
                        duration_min=update.get("duration_min"),
                        target_hr_min=update["avg_hr"] - 10 if update.get("avg_hr") else None,
                        target_hr_max=update["avg_hr"] + 10 if update.get("avg_hr") else None,
                        status="completed",
                        description=update.get("activity_name") or update.get("sport") or None,
                    ))

                # Save ActivityDetail for PR / Bestzeiten calculation
                if idx < len(raw_activities):
                    from app.models.analytics import ActivityDetail as _AD
                    _raw = raw_activities[idx]
                    _ext_id = str(_raw.get("id") or "")
                    _dist = _raw.get("distance")
                    _elapsed = _raw.get("elapsed_time") or _raw.get("moving_time")
                    if _ext_id and _dist and _elapsed:
                        _ex = await db.execute(
                            select(_AD).where(
                                _AD.user_id == user_uuid,
                                _AD.external_id == _ext_id,
                                _AD.source == "strava",
                            )
                        )
                        if not _ex.scalar_one_or_none():
                            db.add(_AD(
                                user_id=user_uuid,
                                source="strava",
                                external_id=_ext_id,
                                name=_raw.get("name"),
                                sport_type=update.get("sport_type") or "other",
                                activity_date=update["date"],
                                distance_m=float(_dist),
                                elapsed_time_s=int(_elapsed),
                                moving_time_s=int(_raw["moving_time"]) if _raw.get("moving_time") else None,
                                average_heartrate=_raw.get("average_heartrate"),
                                max_heartrate=_raw.get("max_heartrate"),
                            ))
            wc_res = await db.execute(
                select(WatchConnection).where(
                    WatchConnection.user_id == user_uuid,
                    WatchConnection.provider == provider,
                    WatchConnection.is_active == True,
                )
            )
            wc = wc_res.scalar_one_or_none()
            if wc:
                wc.last_synced_at = now_utc
            await db.commit()
        except Exception:
            try:
                await db.rollback()
            except Exception:
                pass

    # Bust Redis caches so the frontend sees the imported data immediately
    try:
        _r = _get_redis()
        _plan_keys = await _r.keys(f"plan:{user_uuid}:*")
        if _plan_keys:
            await _r.delete(*_plan_keys)
        _recovery_keys = await _r.keys(f"recovery:{user_uuid}:*")
        if _recovery_keys:
            await _r.delete(*_recovery_keys)
        await _r.delete(f"achievements:{user_uuid}")
        await _r.publish(
            f"watch_events:{user_uuid}",
            json.dumps({"event": "activity_synced", "provider": provider}),
        )
    except Exception:
        pass


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
        "garmin_available": True,   # garminconnect SSO — kein API-Key nötig
        "strava_available": bool(settings.strava_client_id),
        "apple_watch_available": True,  # Koppelcode — kein API-Key nötig
    }


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
    Login + automatischer Import der letzten 12 Monate.
    Kein Enterprise-API-Key nötig — nutzt garminconnect-Library (Android-App-SSO).
    """
    try:
        token_data = await garmin.login(body.email, body.password)
    except Exception as e:
        logger.warning(f"Garmin login failed | user={current_user.id} | error={e}")
        raise HTTPException(
            status_code=400,
            detail="Garmin-Login fehlgeschlagen. Prüfe E-Mail und Passwort.",
        )

    tokens_json = token_data.get("tokens_json", "")
    display_name = token_data.get("display_name", "")

    # Save connection
    result = await db.execute(
        select(WatchConnection).where(
            WatchConnection.user_id == current_user.id,
            WatchConnection.provider == "garmin",
        )
    )
    connection = result.scalar_one_or_none()
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
    conn_id = connection.id

    # Auto-import last 12 months in background (don't block login response)
    async def _import_background():
        from datetime import date as _date, timedelta as _td
        from app.core.database import async_session as _sf
        today = _date.today()
        from_date = (today - _td(days=365)).isoformat()
        to_date = today.isoformat()
        logger.info(f"Garmin background import started | user={current_user.id} | range={from_date}…{to_date}")
        try:
            activities = await garmin.get_activities_by_date(tokens_json, from_date, to_date)
        except Exception as _e:
            logger.warning(f"Garmin get_activities failed | user={current_user.id} | error={_e}")
            return
        if not isinstance(activities, list):
            logger.warning(f"Garmin get_activities returned non-list | user={current_user.id} | got={type(activities)}")
            return
        logger.info(f"Garmin fetched {len(activities)} activities | user={current_user.id}")

        # Collect all unique dates to fetch stats for:
        # - Last 90 days (to ensure recent data is always fresh)
        # - All activity dates (so stress/steps are saved for real training days)
        _stats_dates: set[str] = set()
        for _i in range(90):
            _stats_dates.add((today - _td(days=_i)).isoformat())
        for _act in activities:
            _st = (_act.get("startTimeLocal") or "")[:10]
            if len(_st) == 10:
                _stats_dates.add(_st)
        logger.info(f"Garmin fetching daily stats for {len(_stats_dates)} dates | user={current_user.id}")

        # Fetch stats per day (4 calls in parallel per day) to avoid Garmin rate limits
        _daily_stats: dict[str, dict] = {}
        for _day_iso in sorted(_stats_dates, reverse=True):
            try:
                _stats_raw, _sleep_raw, _vo2_raw, _hrv_raw = await asyncio.gather(
                    garmin.get_stats(tokens_json, _day_iso),
                    garmin.get_sleep_data(tokens_json, _day_iso),
                    garmin.get_max_metrics(tokens_json, _day_iso),
                    garmin.get_hrv_data(tokens_json, _day_iso),
                    return_exceptions=True,
                )
                _summary = garmin.parse_daily_stats(_stats_raw) if isinstance(_stats_raw, dict) else {}
                # stress_score=-1 means "insufficient data" → treat as null
                if _summary.get("stress_score") is not None and _summary["stress_score"] < 0:
                    _summary["stress_score"] = None
                _sleep_parsed = garmin.parse_sleep(_sleep_raw) if isinstance(_sleep_raw, dict) else {}
                _daily_stats[_day_iso] = {
                    "summary": _summary,
                    "sleep": _sleep_parsed,
                    "vo2_max": garmin.parse_vo2_max(_vo2_raw),
                    "hrv": garmin.parse_hrv(_hrv_raw) if isinstance(_hrv_raw, dict) else None,
                }
            except Exception:
                continue

        now = datetime.now(timezone.utc)
        async with _sf() as s:
            for activity in activities:
                upd = garmin.activity_to_training_plan_update(activity)
                if not upd or not upd.get("date"):
                    continue
                try:
                    act_date = _date.fromisoformat(upd["date"])
                except ValueError:
                    continue

                # Upsert TrainingPlan
                pr = await s.execute(
                    select(TrainingPlan).where(
                        TrainingPlan.user_id == current_user.id,
                        TrainingPlan.date == act_date,
                    )
                )
                plan = pr.scalar_one_or_none()
                if plan:
                    plan.status = "completed"
                    plan.completed_at = now
                    if upd.get("avg_hr"):
                        plan.target_hr_min = upd["avg_hr"] - 10
                        plan.target_hr_max = upd["avg_hr"] + 10
                    if upd.get("duration_min"):
                        plan.duration_min = upd["duration_min"]
                else:
                    plan = TrainingPlan(
                        user_id=current_user.id,
                        date=act_date,
                        sport=upd.get("sport_type") or "other",
                        workout_type="imported",
                        duration_min=upd.get("duration_min"),
                        target_hr_min=upd["avg_hr"] - 10 if upd.get("avg_hr") else None,
                        target_hr_max=upd["avg_hr"] + 10 if upd.get("avg_hr") else None,
                        status="completed",
                        completed_at=now,
                        description=upd.get("activity_name") or None,
                    )
                    s.add(plan)

                # Save HealthMetric from activity data (only steps — avg_hr is exercise HR, not resting HR)
                steps = activity.get("steps")
                if steps is not None:
                    # Use noon on that day as recorded_at so it doesn't clash with daily-stats entries
                    from datetime import timezone as _tz
                    recorded_at = datetime(act_date.year, act_date.month, act_date.day, 12, 0, 0, tzinfo=_tz.utc)
                    # Check if we already have a garmin metric for this day
                    existing_metric = await s.execute(
                        select(HealthMetric).where(
                            HealthMetric.user_id == current_user.id,
                            HealthMetric.recorded_at >= datetime(act_date.year, act_date.month, act_date.day, 0, 0, 0, tzinfo=_tz.utc),
                            HealthMetric.recorded_at < datetime(act_date.year, act_date.month, act_date.day, 23, 59, 59, tzinfo=_tz.utc),
                            HealthMetric.source == "garmin",
                        )
                    )
                    existing_metric = existing_metric.scalar_one_or_none()
                    if existing_metric:
                        if existing_metric.steps is None:
                            existing_metric.steps = int(steps)
                    else:
                        s.add(HealthMetric(
                            user_id=current_user.id,
                            recorded_at=recorded_at,
                            steps=int(steps),
                            source="garmin",
                        ))

                # Save ActivityDetail for PR / Bestzeiten calculation
                from app.models.analytics import ActivityDetail
                _ext_id = str(activity.get("activityId") or "")
                _dist = activity.get("distance")
                _elapsed = activity.get("elapsedDuration") or activity.get("duration")
                if _ext_id and _dist and _elapsed:
                    _existing_ad = await s.execute(
                        select(ActivityDetail).where(
                            ActivityDetail.user_id == current_user.id,
                            ActivityDetail.external_id == _ext_id,
                            ActivityDetail.source == "garmin",
                        )
                    )
                    if not _existing_ad.scalar_one_or_none():
                        s.add(ActivityDetail(
                            user_id=current_user.id,
                            source="garmin",
                            external_id=_ext_id,
                            name=activity.get("activityName"),
                            sport_type=upd.get("sport_type") or "other",
                            activity_date=upd["date"],
                            distance_m=float(_dist),
                            elapsed_time_s=int(float(_elapsed)),
                            moving_time_s=int(float(activity["movingDuration"])) if activity.get("movingDuration") else None,
                            average_heartrate=activity.get("averageHR"),
                            max_heartrate=activity.get("maxHR"),
                            average_cadence=activity.get("averageRunningCadenceInStepsPerMinute"),
                            average_stride_length=activity.get("avgStrideLength"),
                        ))

            # Upsert 14-day daily stats (resting HR, sleep, stress, HRV, VO₂, SpO₂) for recovery scores
            from datetime import timezone as _tz2
            for _day_iso, _day_data in _daily_stats.items():
                _summary = _day_data["summary"]
                _sleep_info = _day_data["sleep"]
                _vo2 = _day_data.get("vo2_max")
                _hrv = _day_data.get("hrv")
                _spo2 = _summary.get("spo2")
                # Use sleep overnight resting HR as fallback if daytime resting HR is missing
                _resting_hr = _summary.get("resting_hr") or _sleep_info.get("sleep_avg_hr")
                if not any([
                    _resting_hr, _summary.get("steps"),
                    _summary.get("stress_score"), _sleep_info.get("sleep_duration_min"),
                    _vo2, _hrv, _spo2,
                ]):
                    continue
                _ddt = _date.fromisoformat(_day_iso)
                _d_start = datetime(_ddt.year, _ddt.month, _ddt.day, 0, 0, 0, tzinfo=_tz2.utc)
                _d_end = datetime(_ddt.year, _ddt.month, _ddt.day, 23, 59, 59, tzinfo=_tz2.utc)
                _em = await s.execute(
                    select(HealthMetric).where(
                        HealthMetric.user_id == current_user.id,
                        HealthMetric.recorded_at >= _d_start,
                        HealthMetric.recorded_at <= _d_end,
                        HealthMetric.source == "garmin",
                    )
                )
                _em = _em.scalar_one_or_none()
                if _em:
                    if _resting_hr is not None:
                        _em.resting_hr = _resting_hr
                    if _summary.get("steps") is not None:
                        _em.steps = _summary["steps"]
                    if _summary.get("stress_score") is not None:
                        _em.stress_score = _summary["stress_score"]
                    if _sleep_info.get("sleep_duration_min") is not None:
                        _em.sleep_duration_min = _sleep_info["sleep_duration_min"]
                    if _sleep_info.get("sleep_stages") is not None:
                        _em.sleep_stages = _sleep_info["sleep_stages"]
                    if _vo2 is not None:
                        _em.vo2_max = _vo2
                    if _hrv is not None:
                        _em.hrv = _hrv
                    if _spo2 is not None:
                        _em.spo2 = _spo2
                else:
                    _noon = datetime(_ddt.year, _ddt.month, _ddt.day, 12, 0, 0, tzinfo=_tz2.utc)
                    s.add(HealthMetric(
                        user_id=current_user.id,
                        recorded_at=_noon,
                        resting_hr=_resting_hr,
                        steps=_summary.get("steps"),
                        stress_score=_summary.get("stress_score"),
                        sleep_duration_min=_sleep_info.get("sleep_duration_min"),
                        sleep_stages=_sleep_info.get("sleep_stages"),
                        vo2_max=_vo2,
                        hrv=_hrv,
                        spo2=_spo2,
                        source="garmin",
                    ))

            wc = await s.execute(select(WatchConnection).where(WatchConnection.id == conn_id))
            wc = wc.scalar_one_or_none()
            if wc:
                wc.last_synced_at = datetime.now(timezone.utc)
            await s.commit()
            logger.info(f"Garmin background import committed | user={current_user.id}")

            # Recalculate fitness snapshots (CTL/ATL/TSB) from the newly imported data
            try:
                from app.services.activity_analytics import save_fitness_snapshots
                _fit_uid = uuid_module.UUID(str(current_user.id))
                await save_fitness_snapshots(_fit_uid, s, days=365)
                logger.info(f"Garmin fitness snapshots recalculated | user={current_user.id}")
            except Exception as _fe:
                logger.warning(f"Garmin fitness snapshot recalc failed | user={current_user.id} | error={_fe}")

        # Bust ALL Redis caches so the frontend sees the imported data immediately
        try:
            _r = _get_redis()
            _plan_keys = await _r.keys(f"plan:{current_user.id}:*")
            if _plan_keys:
                await _r.delete(*_plan_keys)
            _recovery_keys = await _r.keys(f"recovery:{current_user.id}:*")
            if _recovery_keys:
                await _r.delete(*_recovery_keys)
            await _r.delete(f"achievements:{current_user.id}")
            # Notify the frontend SSE stream so all widgets reload automatically
            await _r.publish(
                f"watch_events:{current_user.id}",
                json.dumps({"event": "activity_synced", "provider": "garmin"}),
            )
            logger.info(f"Garmin import: cache cleared + SSE event published | user={current_user.id}")
        except Exception as _ce:
            logger.warning(f"Garmin import: cache/publish failed | user={current_user.id} | error={_ce}")

    asyncio.create_task(_import_background())

    return {"ok": True, "display_name": display_name, "importing": True, "redirect_url": f"{settings.frontend_url}/einstellungen?provider=garmin"}


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


# ─── Strava OAuth ──────────────────────────────────────────────────────────────
# Strava ist ein kostenloser Hub für alle Uhren.
# Einmalige Registrierung unter https://www.strava.com/settings/api
# deckt ab: Polar, Wahoo, Fitbit, Suunto, COROS, Zepp/Amazfit,
#           Samsung Health, WHOOP, Google Fit (Wear OS), Apple Watch


@router.get("/strava/connect")
async def strava_connect(
    current_user: User = Depends(get_current_user),
):
    """Leitet den User zur Strava OAuth2-Seite weiter."""
    if not settings.strava_client_id:
        raise HTTPException(
            status_code=503,
            detail="Strava: Bitte STRAVA_CLIENT_ID und STRAVA_CLIENT_SECRET in der .env setzen. "
                   "Kostenlose Registrierung unter https://www.strava.com/settings/api",
        )
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
    """Strava leitet hierher weiter nach Authorization."""
    user_id_str = await _consume_oauth_state(state)
    if not user_id_str:
        raise HTTPException(status_code=400, detail="Ungültiger oder abgelaufener OAuth-State")

    try:
        target_user_id = uuid_module.UUID(user_id_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Ungültige User-ID im OAuth-State")

    try:
        token_data = await strava.exchange_code(code)
    except Exception:
        raise HTTPException(status_code=400, detail="Strava-Authentifizierung fehlgeschlagen")

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
        connection.provider_athlete_id = token_data.get("athlete_id")
        connection.is_active = True
    else:
        connection = WatchConnection(
            user_id=target_user_id,
            provider="strava",
            provider_athlete_id=token_data.get("athlete_id"),
            access_token=token_data["access_token"],
            refresh_token=token_data["refresh_token"],
            is_active=True,
        )
        db.add(connection)

    await db.commit()
    asyncio.create_task(
        _start_initial_import(user_id_str, "strava", token_data["access_token"])
    )
    return RedirectResponse(
        url=f"{settings.frontend_url}/einstellungen?provider=strava"
    )


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


class GarminSyncRangeRequest(BaseModel):
    from_date: str  # YYYY-MM-DD
    to_date: str    # YYYY-MM-DD


@router.post("/garmin/sync-range")
async def garmin_sync_range(
    body: GarminSyncRangeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Importiert Garmin-Aktivitäten für einen Zeitraum."""
    # Step 1: Fetch token from DB — do NOT hold the session open during the Garmin API call
    conn_result = await db.execute(
        select(WatchConnection).where(
            WatchConnection.user_id == current_user.id,
            WatchConnection.provider == "garmin",
        )
    )
    conn = conn_result.scalar_one_or_none()
    if not conn or not conn.access_token:
        raise HTTPException(status_code=400, detail="Garmin nicht verbunden. Bitte zuerst einloggen.")

    tokens_json = conn.access_token
    conn_id = conn.id

    # Step 2: Call Garmin API outside any DB transaction (can take a while)
    try:
        activities = await garmin.get_activities_by_date(tokens_json, body.from_date, body.to_date)
    except Exception as e:
        logger.warning(f"Garmin sync-range failed | user={current_user.id} | error={e}")
        raise HTTPException(status_code=400, detail="Garmin-Import fehlgeschlagen. Bitte versuche es erneut.")

    if not isinstance(activities, list):
        activities = []

    # Step 3: Write results in a fresh DB session (avoids long-lived connection problem)
    from datetime import date as date_type
    from app.core.database import async_session as _session_factory

    imported_count = 0
    async with _session_factory() as fresh_db:
        for activity in activities:
            update = garmin.activity_to_training_plan_update(activity)
            if not update or not update.get("date"):
                continue
            try:
                activity_date = date_type.fromisoformat(update["date"])
            except ValueError:
                continue
            plan_result = await fresh_db.execute(
                select(TrainingPlan).where(
                    TrainingPlan.user_id == current_user.id,
                    TrainingPlan.date == activity_date,
                )
            )
            plan = plan_result.scalar_one_or_none()
            if plan:
                plan.status = "completed"
                if update.get("avg_hr"):
                    plan.target_hr_min = update["avg_hr"] - 10
                    plan.target_hr_max = update["avg_hr"] + 10
                if update.get("duration_min"):
                    plan.duration_min = update["duration_min"]
            else:
                plan = TrainingPlan(
                    user_id=current_user.id,
                    date=activity_date,
                    sport=update.get("sport_type") or "other",
                    workout_type="imported",
                    duration_min=update.get("duration_min"),
                    target_hr_min=update["avg_hr"] - 10 if update.get("avg_hr") else None,
                    target_hr_max=update["avg_hr"] + 10 if update.get("avg_hr") else None,
                    status="completed",
                    description=update.get("activity_name") or None,
                )
                fresh_db.add(plan)
            imported_count += 1

        # Update the WatchConnection as active
        wc_result = await fresh_db.execute(
            select(WatchConnection).where(WatchConnection.id == conn_id)
        )
        wc = wc_result.scalar_one_or_none()
        if wc:
            wc.is_active = True
            wc.last_synced_at = datetime.now(timezone.utc)

        await fresh_db.commit()

        # Recalculate fitness snapshots (CTL/ATL/TSB) from the newly imported data
        try:
            from app.services.activity_analytics import save_fitness_snapshots
            _fit_uid = uuid_module.UUID(str(current_user.id))
            await save_fitness_snapshots(_fit_uid, fresh_db, days=365)
        except Exception:
            pass

    # Bust ALL Redis caches so the frontend sees the synced data immediately
    try:
        _r = _get_redis()
        _plan_keys = await _r.keys(f"plan:{current_user.id}:*")
        if _plan_keys:
            await _r.delete(*_plan_keys)
        _recovery_keys = await _r.keys(f"recovery:{current_user.id}:*")
        if _recovery_keys:
            await _r.delete(*_recovery_keys)
        await _r.delete(f"achievements:{current_user.id}")
        # Notify the frontend SSE stream so all widgets reload automatically
        await _r.publish(
            f"watch_events:{current_user.id}",
            json.dumps({"event": "activity_synced", "provider": "garmin"}),
        )
    except Exception:
        pass

    return {"ok": True, "imported": imported_count}


# ─── Sync ─────────────────────────────────────────────────────────────────────


@router.post("/sync")
async def sync(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Synchronisiert Aktivitäten von verbundenen Trackern.
    Unterstützt: Garmin (SSO), Strava (Hub für alle anderen Uhren), Apple Watch.
    """
    synced_count = 0
    providers = []
    any_conn = False

    # ── Garmin ────────────────────────────────────────────────────────────────
    garmin_result = await db.execute(
        select(WatchConnection).where(
            WatchConnection.user_id == current_user.id,
            WatchConnection.provider == "garmin",
            WatchConnection.is_active == True,
        )
    )
    garmin_conn = garmin_result.scalar_one_or_none()

    if garmin_conn:
        any_conn = True
        _refreshed = False
        while True:
            try:
                from datetime import date, timedelta

                today = date.today().isoformat()
                daily_task = garmin.get_stats(garmin_conn.access_token, today)
                sleep_task = garmin.get_sleep_data(garmin_conn.access_token, today)
                activities_task = garmin.get_activities_by_date(garmin_conn.access_token, today, today)
                vo2_task = garmin.get_max_metrics(garmin_conn.access_token, today)
                hrv_task = garmin.get_hrv_data(garmin_conn.access_token, today)
                daily_data, sleep_data, activities, vo2_data, hrv_data = await asyncio.gather(
                    daily_task, sleep_task, activities_task, vo2_task, hrv_task,
                    return_exceptions=True,
                )

                summary = garmin.parse_daily_stats(daily_data) if isinstance(daily_data, dict) else {}
                sleep_info = garmin.parse_sleep(sleep_data) if isinstance(sleep_data, dict) else {}
                vo2_max_val = garmin.parse_vo2_max(vo2_data)
                hrv_val = garmin.parse_hrv(hrv_data) if isinstance(hrv_data, dict) else None
                spo2_val = summary.get("spo2")
                resting_hr_val = summary.get("resting_hr") or sleep_info.get("sleep_avg_hr")

                from datetime import date as _date_sync, timezone as _tz_sync
                _today = _date_sync.today()
                _day_start = datetime(_today.year, _today.month, _today.day, 0, 0, 0, tzinfo=_tz_sync.utc)
                _day_end = datetime(_today.year, _today.month, _today.day, 23, 59, 59, tzinfo=_tz_sync.utc)
                _existing_m = await db.execute(
                    select(HealthMetric).where(
                        HealthMetric.user_id == current_user.id,
                        HealthMetric.recorded_at >= _day_start,
                        HealthMetric.recorded_at <= _day_end,
                        HealthMetric.source == "garmin",
                    )
                )
                _existing_m = _existing_m.scalar_one_or_none()
                if _existing_m:
                    if resting_hr_val is not None:
                        _existing_m.resting_hr = resting_hr_val
                    if summary.get("steps") is not None:
                        _existing_m.steps = summary["steps"]
                    if summary.get("stress_score") is not None:
                        _existing_m.stress_score = summary["stress_score"]
                    if sleep_info.get("sleep_duration_min") is not None:
                        _existing_m.sleep_duration_min = sleep_info["sleep_duration_min"]
                    if sleep_info.get("sleep_stages") is not None:
                        _existing_m.sleep_stages = sleep_info["sleep_stages"]
                    if vo2_max_val is not None:
                        _existing_m.vo2_max = vo2_max_val
                    if hrv_val is not None:
                        _existing_m.hrv = hrv_val
                    if spo2_val is not None:
                        _existing_m.spo2 = spo2_val
                else:
                    db.add(HealthMetric(
                        user_id=current_user.id,
                        recorded_at=datetime.now(timezone.utc),
                        resting_hr=resting_hr_val,
                        steps=summary.get("steps"),
                        stress_score=summary.get("stress_score"),
                        sleep_duration_min=sleep_info.get("sleep_duration_min"),
                        sleep_stages=sleep_info.get("sleep_stages"),
                        vo2_max=vo2_max_val,
                        hrv=hrv_val,
                        spo2=spo2_val,
                        source="garmin",
                    ))
                synced_count += 1

                if isinstance(activities, list):
                    for activity in activities:
                        update = garmin.activity_to_training_plan_update(activity)
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

    # ── Strava ────────────────────────────────────────────────────────────────
    strava_result = await db.execute(
        select(WatchConnection).where(
            WatchConnection.user_id == current_user.id,
            WatchConnection.provider == "strava",
            WatchConnection.is_active == True,
        )
    )
    strava_conn = strava_result.scalar_one_or_none()

    if strava_conn:
        any_conn = True
        _refreshed = False
        while True:
            try:
                from datetime import date, timedelta, timezone as _tz_s
                yesterday = (date.today() - timedelta(days=1))
                after_unix = int(datetime(yesterday.year, yesterday.month, yesterday.day, tzinfo=_tz_s.utc).timestamp())
                activities = await strava.get_activities(strava_conn.access_token, after_unix=after_unix, limit=20)
                for activity in activities:
                    update = strava.activity_to_training_plan_update(activity)
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
                    elif not plan:
                        db.add(TrainingPlan(
                            user_id=current_user.id,
                            date=activity_date,
                            sport=update.get("sport_type") or "other",
                            workout_type="imported",
                            duration_min=update.get("duration_min"),
                            target_hr_min=update["avg_hr"] - 10 if update.get("avg_hr") else None,
                            target_hr_max=update["avg_hr"] + 10 if update.get("avg_hr") else None,
                            status="completed",
                        ))
                    synced_count += 1
                strava_conn.last_synced_at = datetime.now(timezone.utc)
                providers.append("strava")
                break
            except Exception:
                if not _refreshed and await _refresh_token_for(strava_conn, strava):
                    _refreshed = True
                    continue
                break

    if any_conn:
        await db.commit()

    return {"synced": synced_count, "provider": providers if providers else None}


# ─── Apple Watch / HealthKit ───────────────────────────────────────────────────
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

    # Bust Redis caches so the frontend sees the new health data immediately
    try:
        _r = _get_redis()
        _recovery_keys = await _r.keys(f"recovery:{current_user.id}:*")
        if _recovery_keys:
            await _r.delete(*_recovery_keys)
        await _r.publish(
            f"watch_events:{current_user.id}",
            json.dumps({"event": "activity_synced", "provider": "apple_watch"}),
        )
    except Exception:
        pass

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
        if v is not None and (v < 5 or v > 200):
            raise ValueError("HRV muss zwischen 5 und 200 ms liegen")
        return v

    @field_validator("resting_hr")
    @classmethod
    def validate_resting_hr(cls, v: int | None) -> int | None:
        if v is not None and (v < 30 or v > 120):
            raise ValueError("Ruhepuls muss zwischen 30 und 120 bpm liegen")
        return v

    @field_validator("sleep_duration_min")
    @classmethod
    def validate_sleep(cls, v: int | None) -> int | None:
        if v is not None and (v < 0 or v > 720):
            raise ValueError("Schlafdauer muss zwischen 0 und 720 Minuten liegen")
        return v

    @field_validator("stress_score")
    @classmethod
    def validate_stress(cls, v: float | None) -> float | None:
        if v is not None and (v < 0 or v > 100):
            raise ValueError("Stresslevel muss zwischen 0 und 100 liegen")
        return v

    @field_validator("spo2")
    @classmethod
    def validate_spo2(cls, v: float | None) -> float | None:
        if v is not None and (v < 70 or v > 100):
            raise ValueError("SpO₂ muss zwischen 70 und 100 % liegen")
        return v

    @field_validator("steps")
    @classmethod
    def validate_steps(cls, v: int | None) -> int | None:
        if v is not None and (v < 0 or v > 100_000):
            raise ValueError("Schritte müssen zwischen 0 und 100.000 liegen")
        return v

    @field_validator("vo2_max")
    @classmethod
    def validate_vo2(cls, v: float | None) -> float | None:
        if v is not None and (v < 10 or v > 90):
            raise ValueError("VO₂ max muss zwischen 10 und 90 ml/kg/min liegen")
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
    import defusedxml.ElementTree as ET
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
    except Exception:
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


# ─── Datei-Import (.fit / .tcx / .gpx / .csv) ────────────────────────────────
# Kein API-Key nötig — funktioniert mit allen Uhr-Marken die Dateien exportieren:
# Garmin, Polar, Suunto, COROS, Zepp/Amazfit, Samsung, Wahoo, WHOOP, Apple Watch,
# Fitbit, Withings, Oura, uvm.

_MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB


@router.post("/import/file")
async def import_file(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Importiert Trainingsdaten aus einer Datei.
    Unterstützte Formate: .fit, .tcx, .gpx, .csv

    Kein API-Key nötig — User exportiert Datei direkt von der Uhr/App:
      Garmin: Garmin Connect → Aktivität → "Original exportieren" (.fit)
      Polar:  Polar Flow → Aktivität → Export (.tcx)
      Suunto: Suunto App → Aktivität → "FIT-Datei exportieren" (.fit)
      COROS:  COROS App → Aktivität → Teilen → .fit
      Apple:  Health-App → "Alle Gesundheitsdaten exportieren" → workout.gpx
      Fitbit: Fitbit Dashboard → fitbit.com/export → .csv
      Zepp:   Zepp App → Profil → "Daten exportieren" → .csv
    """
    filename = (file.filename or "").lower()
    if not filename:
        raise HTTPException(status_code=400, detail="Dateiname fehlt")

    content = await file.read()
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Datei zu groß. Maximal {_MAX_UPLOAD_BYTES // (1024*1024)} MB erlaubt.",
        )

    # Format erkennen
    if filename.endswith(".fit"):
        try:
            activities = fit_importer.parse(content)
        except RuntimeError as e:
            raise HTTPException(status_code=500, detail=str(e))
        except Exception:
            raise HTTPException(
                status_code=400,
                detail="FIT-Datei konnte nicht gelesen werden. Bitte eine gültige .fit Datei hochladen.",
            )
    elif filename.endswith(".tcx"):
        try:
            activities = tcx_importer.parse(content)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    elif filename.endswith(".gpx"):
        try:
            activities = gpx_importer.parse(content)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    elif filename.endswith(".csv"):
        activities = csv_importer.parse(content)
    else:
        raise HTTPException(
            status_code=415,
            detail="Nicht unterstütztes Format. Bitte .fit, .tcx, .gpx oder .csv hochladen.",
        )

    if not activities:
        return {"imported": 0, "message": "Keine Aktivitäten in der Datei gefunden."}

    from datetime import date as _date, timezone as _tz
    import datetime as _dt

    user_uuid = current_user.id
    now_utc = _dt.datetime.now(_tz.utc)
    imported = 0

    for activity in activities:
        if not activity.get("date"):
            continue
        try:
            plan_date = _date.fromisoformat(activity["date"])
        except (ValueError, TypeError):
            continue

        duration_min = activity.get("duration_min")
        if not duration_min:
            continue

        pr = await db.execute(
            select(TrainingPlan).where(
                TrainingPlan.user_id == user_uuid,
                TrainingPlan.date == plan_date,
            )
        )
        plan = pr.scalar_one_or_none()
        sport = activity.get("sport_type") or "other"
        avg_hr = activity.get("avg_hr")

        if plan:
            plan.status = "completed"
            if avg_hr:
                plan.target_hr_min = avg_hr - 10
                plan.target_hr_max = avg_hr + 10
            imported += 1
        else:
            db.add(
                TrainingPlan(
                    user_id=user_uuid,
                    date=plan_date,
                    status="completed",
                    sport_type=sport,
                    duration_min=duration_min,
                    target_hr_min=avg_hr - 10 if avg_hr else None,
                    target_hr_max=avg_hr + 10 if avg_hr else None,
                    notes=f"Importiert aus {filename}",
                    created_at=now_utc,
                    updated_at=now_utc,
                )
            )
            imported += 1

    await db.commit()

    source_label = filename.rsplit(".", 1)[-1].upper()
    return {
        "imported": imported,
        "total_found": len(activities),
        "message": f"{imported} Aktivität(en) aus {source_label}-Datei importiert.",
    }

