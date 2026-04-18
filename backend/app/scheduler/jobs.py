from datetime import date, timedelta, datetime, timezone
from sqlalchemy import select, exists
from loguru import logger
from app.core.database import async_session
from app.models.user import User
from app.models.training import TrainingPlan
from app.models.watch import WatchConnection
from app.services.watch_sync import WatchSync
from app.services.training_planner import TrainingPlanner


async def sync_watch_data_for_all_users():
    """Sync watch data for users WITHOUT a real watch connection (demo/fallback). Runs every 1 hour."""
    async with async_session() as db:
        try:
            # Nur User ohne aktive Watch-Verbindung (für die gibt es Webhook-Push)
            result = await db.execute(
                select(User).where(
                    ~exists().where(
                        WatchConnection.user_id == User.id,
                        WatchConnection.is_active == True,
                    )
                )
            )
            users = result.scalars().all()
            watch = WatchSync()
            logger.info(f"Watch sync started | users_without_connection={len(users)}")
            synced = 0

            for user in users:
                try:
                    await watch.get_demo_data(str(user.id), db)
                    synced += 1
                except Exception as e:
                    logger.warning(f"Watch sync failed | user={user.id} | error={e}")
                    continue

            await db.commit()
            logger.info(f"Watch sync completed | synced={synced}/{len(users)}")
        except Exception as e:
            logger.error(f"Watch sync job failed | error={e}")
            try:
                await db.rollback()
            except Exception:
                pass


async def generate_tomorrow_plans():
    """Generate tomorrow's training plan for all users. Runs daily at 21:00."""
    async with async_session() as db:
        try:
            tomorrow = date.today() + timedelta(days=1)
            week_start = tomorrow - timedelta(days=tomorrow.weekday())

            # Single query: find users who have no plan for tomorrow
            # AND no plans for the entire week (so we generate the whole week)
            users_need_plan = await db.execute(
                select(User).where(
                    User.email.isnot(None),
                    User.email.contains("@"),
                    ~exists().where(
                        TrainingPlan.user_id == User.id,
                        TrainingPlan.date >= week_start,
                        TrainingPlan.date < week_start + timedelta(days=7),
                    )
                )
            )
            users = users_need_plan.scalars().all()
            planner = TrainingPlanner()
            logger.info(
                f"Plan generation started | users_needing_plans={len(users)} | tomorrow={tomorrow}"
            )
            generated = 0

            for user in users:
                try:
                    await planner.generate_week_plan(str(user.id), week_start, db)
                    generated += 1
                except Exception as e:
                    logger.warning(
                        f"Plan generation failed | user={user.id} | error={e}"
                    )
                    continue

            await db.commit()
            logger.info(
                f"Plan generation completed | generated={generated}/{len(users)}"
            )
        except Exception as e:
            logger.error(f"Plan generation job failed | error={e}")
            try:
                await db.rollback()
            except Exception:
                pass


async def sync_oauth_providers_for_all_users():
    """Syncs all OAuth-connected providers (Strava, Wahoo, Fitbit, Suunto, Withings, COROS,
    Zepp, WHOOP, Samsung Health, Google Fit, Polar) for all users. Runs every hour."""
    import time as _time
    import datetime as _dt
    from datetime import date as _date, timedelta as _td, timezone as _tz
    from sqlalchemy import select as _select
    from app.models.metrics import HealthMetric
    from app.services.strava_service import StravaService
    from app.services.wahoo_service import WahooService
    from app.services.fitbit_service import FitbitService
    from app.services.suunto_service import SuuntoService
    from app.services.withings_service import WithingsService
    from app.services.coros_service import CorosService
    from app.services.zepp_service import ZeppService
    from app.services.whoop_service import WhoopService
    from app.services.samsung_health_service import SamsungHealthService
    from app.services.google_fit_service import GoogleFitService
    from app.services.polar_service import PolarService

    OAUTH_PROVIDERS = {
        "strava",
        "wahoo", "fitbit", "suunto", "withings",
        "coros", "zepp", "whoop", "samsung_health", "google_fit", "polar",
    }

    strava_svc = StravaService()
    wahoo_svc = WahooService()
    fitbit_svc = FitbitService()
    suunto_svc = SuuntoService()
    withings_svc = WithingsService()
    coros_svc = CorosService()
    zepp_svc = ZeppService()
    whoop_svc = WhoopService()
    samsung_svc = SamsungHealthService()
    google_fit_svc = GoogleFitService()
    polar_svc = PolarService()

    now = _dt.datetime.now(_tz.utc)
    week_ago_unix = int(_time.time()) - 7 * 86400
    since_ms = week_ago_unix * 1000
    now_ms = int(now.timestamp() * 1000)
    week_ago_iso = (now - _td(days=7)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    now_iso = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    async with async_session() as db:
        try:
            result = await db.execute(
                _select(WatchConnection).where(
                    WatchConnection.is_active == True,
                    WatchConnection.provider.in_(OAUTH_PROVIDERS),
                )
            )
            connections = result.scalars().all()
            logger.info(f"OAuth hourly sync started | connections={len(connections)}")
            synced = 0

            for conn in connections:
                try:
                    access = conn.access_token
                    items_with_update: list[dict] = []

                    if conn.provider == "strava":
                        # Refresh token if expired
                        if conn.refresh_token:
                            try:
                                new_tk = await strava_svc.refresh_token(conn.refresh_token)
                                conn.access_token = new_tk["access_token"]
                                conn.refresh_token = new_tk.get("refresh_token", conn.refresh_token)
                                access = conn.access_token
                            except Exception:
                                pass
                        acts = await strava_svc.get_activities(
                            access, after_unix=week_ago_unix, limit=50
                        )
                        items_with_update = [strava_svc.activity_to_training_plan_update(a) for a in acts]
                    elif conn.provider == "wahoo":
                        works = await wahoo_svc.get_workouts(access, limit=10)
                        items_with_update = [wahoo_svc.workout_to_training_plan_update(w) for w in works]
                    elif conn.provider == "fitbit":
                        yest = (_date.today() - _td(days=1)).isoformat()
                        acts = await fitbit_svc.get_activity_log(access, yest, limit=10)
                        items_with_update = [fitbit_svc.activity_to_training_plan_update(a) for a in acts]
                    elif conn.provider == "suunto":
                        works = await suunto_svc.get_workouts(access, limit=10, since=since_ms)
                        items_with_update = [suunto_svc.workout_to_training_plan_update(w) for w in works]
                    elif conn.provider == "withings":
                        works = await withings_svc.get_workouts(access, start_unix=week_ago_unix, end_unix=int(_time.time()))
                        items_with_update = [withings_svc.workout_to_training_plan_update(w) for w in works]
                    elif conn.provider == "coros" and conn.provider_athlete_id:
                        sports = await coros_svc.get_sport_list(access, conn.provider_athlete_id, size=10)
                        items_with_update = [coros_svc.sport_to_training_plan_update(s) for s in sports]
                    elif conn.provider == "zepp" and conn.provider_athlete_id:
                        works = await zepp_svc.get_workouts(access, conn.provider_athlete_id, from_time=week_ago_unix, limit=10)
                        items_with_update = [zepp_svc.workout_to_training_plan_update(w) for w in works]
                    elif conn.provider == "whoop":
                        works = await whoop_svc.get_workout_collection(access, start=week_ago_iso, end=now_iso, limit=10)
                        items_with_update = [whoop_svc.workout_to_training_plan_update(w) for w in works]
                    elif conn.provider == "samsung_health":
                        exs = await samsung_svc.get_exercises(access, start_time=since_ms, end_time=now_ms)
                        items_with_update = [samsung_svc.exercise_to_training_plan_update(e) for e in exs]
                    elif conn.provider == "google_fit":
                        sessions = await google_fit_svc.get_sessions(access, start_time_ms=since_ms, end_time_ms=now_ms)
                        items_with_update = [google_fit_svc.session_to_training_plan_update(s) for s in sessions]
                    elif conn.provider == "polar" and conn.provider_athlete_id:
                        exs = await polar_svc.list_exercises(access, int(conn.provider_athlete_id))
                        items_with_update = [polar_svc.exercise_to_metric(e) for e in exs if e]

                    for update in items_with_update:
                        if not update or not update.get("date"):
                            continue
                        plan_date = _date.fromisoformat(update["date"])
                        plan_result = await db.execute(
                            _select(TrainingPlan).where(
                                TrainingPlan.user_id == conn.user_id,
                                TrainingPlan.date == plan_date,
                            )
                        )
                        plan = plan_result.scalar_one_or_none()
                        if plan:
                            if plan.status != "completed":
                                plan.status = "completed"
                            if update.get("avg_hr"):
                                plan.target_hr_min = update["avg_hr"] - 10
                                plan.target_hr_max = update["avg_hr"] + 10
                            if update.get("duration_min"):
                                plan.duration_min = update["duration_min"]
                        else:
                            db.add(TrainingPlan(
                                user_id=conn.user_id,
                                date=plan_date,
                                sport=update.get("sport_type") or "other",
                                workout_type="imported",
                                duration_min=update.get("duration_min"),
                                target_hr_min=update["avg_hr"] - 10 if update.get("avg_hr") else None,
                                target_hr_max=update["avg_hr"] + 10 if update.get("avg_hr") else None,
                                status="completed",
                                completed_at=_dt.datetime.now(_tz.utc),
                                description=update.get("activity_name") or None,
                            ))

                    conn.last_synced_at = _dt.datetime.now(_tz.utc)
                    synced += 1
                except Exception as e:
                    logger.warning(
                        f"OAuth hourly sync failed | provider={conn.provider} | user={conn.user_id} | error={e}"
                    )
                    continue

            await db.commit()
            logger.info(f"OAuth hourly sync completed | synced={synced}/{len(connections)}")
        except Exception as e:
            logger.error(f"OAuth hourly sync job failed | error={e}")
            try:
                await db.rollback()
            except Exception:
                pass


async def autonomous_monitor_job():
    """Erkennt Nutzer-Probleme in Gesprächen und passt Pläne autonom an. Läuft alle 30 Min."""
    from app.services.autonomous_monitor import run_autonomous_monitor

    await run_autonomous_monitor()


async def sync_garmin_for_all_users():
    """Syncs Garmin data (today's stats, sleep, activities) for all users with an active
    Garmin connection. Runs every hour."""
    from app.services.garmin_service import GarminService
    from app.models.metrics import HealthMetric
    import asyncio as _asyncio

    garmin_svc = GarminService()
    today = date.today().isoformat()

    async with async_session() as db:
        try:
            result = await db.execute(
                select(WatchConnection).where(
                    WatchConnection.is_active == True,
                    WatchConnection.provider == "garmin",
                )
            )
            connections = result.scalars().all()
            logger.info(f"Garmin hourly sync started | connections={len(connections)}")
            synced = 0

            for conn in connections:
                if not conn.access_token:
                    continue
                try:
                    daily_task = garmin_svc.get_stats(conn.access_token, today)
                    sleep_task = garmin_svc.get_sleep_data(conn.access_token, today)
                    activities_task = garmin_svc.get_activities_by_date(conn.access_token, today, today)
                    vo2_task = garmin_svc.get_max_metrics(conn.access_token, today)
                    hrv_task = garmin_svc.get_hrv_data(conn.access_token, today)
                    daily_data, sleep_data, activities, vo2_data, hrv_data = await _asyncio.gather(
                        daily_task, sleep_task, activities_task, vo2_task, hrv_task,
                        return_exceptions=True,
                    )
                    # Log any API errors from gather
                    for name, val in [("daily", daily_data), ("sleep", sleep_data), ("activities", activities), ("vo2", vo2_data), ("hrv", hrv_data)]:
                        if isinstance(val, Exception):
                            logger.debug(f"Garmin {name} fetch failed | user={conn.user_id} | error={val}")

                    summary = garmin_svc.parse_daily_stats(daily_data) if isinstance(daily_data, dict) else {}
                    sleep_info = garmin_svc.parse_sleep(sleep_data) if isinstance(sleep_data, dict) else {}
                    vo2_max_val = garmin_svc.parse_vo2_max(vo2_data)
                    hrv_val = garmin_svc.parse_hrv(hrv_data) if isinstance(hrv_data, dict) else None
                    spo2_val = summary.get("spo2")

                    resting_hr = summary.get("resting_hr") or sleep_info.get("sleep_avg_hr")
                    steps = summary.get("steps")
                    stress = summary.get("stress_score")
                    if stress is not None and stress < 0:
                        stress = None
                    sleep_min = sleep_info.get("sleep_duration_min")
                    sleep_stages = sleep_info.get("sleep_stages")

                    # Only upsert if there is something new to save
                    if any(v is not None for v in [resting_hr, steps, stress, sleep_min, vo2_max_val, hrv_val, spo2_val]):
                        today_date = date.today()
                        from datetime import timezone as _tz
                        day_start = datetime(today_date.year, today_date.month, today_date.day, 0, 0, 0, tzinfo=_tz.utc)
                        day_end = datetime(today_date.year, today_date.month, today_date.day, 23, 59, 59, tzinfo=_tz.utc)
                        existing = await db.execute(
                            select(HealthMetric).where(
                                HealthMetric.user_id == conn.user_id,
                                HealthMetric.recorded_at >= day_start,
                                HealthMetric.recorded_at <= day_end,
                                HealthMetric.source == "garmin",
                            )
                        )
                        existing_metric = existing.scalar_one_or_none()
                        if existing_metric:
                            # Update existing metric
                            if resting_hr is not None:
                                existing_metric.resting_hr = resting_hr
                            if steps is not None:
                                existing_metric.steps = steps
                            if stress is not None:
                                existing_metric.stress_score = stress
                            if sleep_min is not None:
                                existing_metric.sleep_duration_min = sleep_min
                            if sleep_stages is not None:
                                existing_metric.sleep_stages = sleep_stages
                            if vo2_max_val is not None:
                                existing_metric.vo2_max = vo2_max_val
                            if hrv_val is not None:
                                existing_metric.hrv = hrv_val
                            if spo2_val is not None:
                                existing_metric.spo2 = spo2_val
                        else:
                            metric = HealthMetric(
                                user_id=conn.user_id,
                                recorded_at=datetime.now(_tz.utc),
                                resting_hr=resting_hr,
                                steps=steps,
                                stress_score=stress,
                                sleep_duration_min=sleep_min,
                                sleep_stages=sleep_stages,
                                vo2_max=vo2_max_val,
                                hrv=hrv_val,
                                spo2=spo2_val,
                                source="garmin",
                            )
                            db.add(metric)

                    # Sync activities → TrainingPlan
                    if isinstance(activities, list):
                        for activity in activities:
                            upd = garmin_svc.activity_to_training_plan_update(activity)
                            if not upd or not upd.get("date"):
                                continue
                            try:
                                act_date = date.fromisoformat(upd["date"])
                            except ValueError:
                                continue
                            plan_result = await db.execute(
                                select(TrainingPlan).where(
                                    TrainingPlan.user_id == conn.user_id,
                                    TrainingPlan.date == act_date,
                                )
                            )
                            plan = plan_result.scalar_one_or_none()
                            if plan:
                                if plan.status != "completed":
                                    plan.status = "completed"
                                if upd.get("avg_hr"):
                                    plan.target_hr_min = upd["avg_hr"] - 10
                                    plan.target_hr_max = upd["avg_hr"] + 10
                                if upd.get("duration_min"):
                                    plan.duration_min = upd["duration_min"]
                            else:
                                plan = TrainingPlan(
                                    user_id=conn.user_id,
                                    date=act_date,
                                    sport=upd.get("sport_type") or "other",
                                    workout_type="imported",
                                    duration_min=upd.get("duration_min"),
                                    target_hr_min=upd["avg_hr"] - 10 if upd.get("avg_hr") else None,
                                    target_hr_max=upd["avg_hr"] + 10 if upd.get("avg_hr") else None,
                                    status="completed",
                                    completed_at=datetime.now(timezone.utc),
                                    description=upd.get("activity_name") or None,
                                )
                                db.add(plan)

                    conn.last_synced_at = datetime.now(timezone.utc)
                    synced += 1
                except Exception as e:
                    logger.warning(
                        f"Garmin hourly sync failed | user={conn.user_id} | error={e}"
                    )
                    continue

            await db.commit()
            logger.info(f"Garmin hourly sync completed | synced={synced}/{len(connections)}")
        except Exception as e:
            logger.error(f"Garmin hourly sync job failed | error={e}")
            try:
                await db.rollback()
            except Exception:
                pass


async def send_sleep_tips_job():
    """Sendet tägliche Schlaftipps um 22:00."""
    from app.services.sleep_coach import send_evening_sleep_tips

    await send_evening_sleep_tips()


async def send_morning_feedback_job():
    """Sendet morgendliches Gesundheits-Feedback um 07:00."""
    from app.services.sleep_coach import send_morning_health_feedback

    await send_morning_health_feedback()
