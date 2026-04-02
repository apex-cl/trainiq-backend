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
    """Sync watch data for users WITHOUT a real watch connection (demo/fallback). Runs every 4 hours."""
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
            result = await db.execute(
                select(User).where(
                    User.email.isnot(None),
                    User.email.contains("@"),
                )
            )
            users = result.scalars().all()
            planner = TrainingPlanner()
            tomorrow = date.today() + timedelta(days=1)
            week_start = tomorrow - timedelta(days=tomorrow.weekday())
            logger.info(
                f"Plan generation started | users={len(users)} | tomorrow={tomorrow}"
            )
            generated = 0

            for user in users:
                try:
                    existing = await db.execute(
                        select(TrainingPlan).where(
                            TrainingPlan.user_id == user.id,
                            TrainingPlan.date == tomorrow,
                        )
                    )
                    if existing.scalars().first():
                        continue

                    week_result = await db.execute(
                        select(TrainingPlan).where(
                            TrainingPlan.user_id == user.id,
                            TrainingPlan.date >= week_start,
                            TrainingPlan.date < week_start + timedelta(days=7),
                        )
                    )
                    if not week_result.scalars().all():
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


async def autonomous_monitor_job():
    """Erkennt Nutzer-Probleme in Gesprächen und passt Pläne autonom an. Läuft alle 30 Min."""
    from app.services.autonomous_monitor import run_autonomous_monitor

    await run_autonomous_monitor()


async def send_sleep_tips_job():
    """Sendet tägliche Schlaftipps um 22:00."""
    from app.services.sleep_coach import send_evening_sleep_tips

    await send_evening_sleep_tips()


async def send_morning_feedback_job():
    """Sendet morgendliches Gesundheits-Feedback um 07:00."""
    from app.services.sleep_coach import send_morning_health_feedback

    await send_morning_health_feedback()
