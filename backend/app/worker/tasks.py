"""
ARQ Background Tasks

Async tasks that run outside the request/response cycle.
Tasks publish status updates to Redis pub/sub for SSE consumers.
"""

import json
import uuid as uuid_module
from datetime import date, timedelta, datetime, timezone
from arq import cron
from loguru import logger
from app.core.database import async_session
from app.core.config import settings


async def _publish_status(redis, task_id: str, status: str, data: dict | None = None):
    """Publisht Task-Status an Redis Pub/Sub für SSE."""
    message = {
        "task_id": task_id,
        "status": status,
        "data": data or {},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    await redis.publish(f"task:{task_id}", json.dumps(message))
    # Auch allgemeinen Channel publishen
    await redis.publish("tasks:all", json.dumps(message))


async def generate_training_plan(ctx: dict, user_id: str, week_start: str):
    """
    Generiert einen Trainingsplan im Hintergrund.
    week_start: ISO-Format Datum (z.B. "2024-03-18")
    """
    redis = ctx["redis"]
    task_id = f"plan_gen:{user_id}:{week_start}"

    await _publish_status(redis, task_id, "started")
    logger.info(
        f"Background plan generation started | user={user_id} | week={week_start}"
    )

    try:
        from app.services.training_planner import TrainingPlanner
        from app.models.training import TrainingPlan
        from sqlalchemy import select

        try:
            week_date = date.fromisoformat(week_start)
        except ValueError:
            await _publish_status(redis, task_id, "failed", {"error": "Invalid week_start format"})
            return

        try:
            user_uuid = uuid_module.UUID(user_id)
        except ValueError:
            await _publish_status(redis, task_id, "failed", {"error": "Invalid user_id format"})
            return

        async with async_session() as db:
            # Prüfen ob Plan bereits existiert
            result = await db.execute(
                select(TrainingPlan).where(
                    TrainingPlan.user_id == user_uuid,
                    TrainingPlan.date >= week_date,
                    TrainingPlan.date < week_date + timedelta(days=7),
                )
            )
            if result.scalars().all():
                await _publish_status(
                    redis, task_id, "skipped", {"reason": "Plan existiert bereits"}
                )
                logger.info(f"Plan already exists | user={user_id} | week={week_start}")
                return

            planner = TrainingPlanner()
            await planner.generate_week_plan(user_id, week_date, db)
            await db.commit()

        await _publish_status(redis, task_id, "completed", {"week_start": week_start})
        logger.info(
            f"Background plan generation completed | user={user_id} | week={week_start}"
        )

    except Exception as e:
        await _publish_status(redis, task_id, "failed", {"error": str(e)})
        logger.error(f"Background plan generation failed | user={user_id} | error={e}")


async def send_weekly_report(ctx: dict):
    """Generiert und versendet wöchentliche Reports für alle User."""
    redis = ctx["redis"]
    task_id = "weekly_report:all"

    await _publish_status(redis, task_id, "started")
    logger.info("Weekly report generation started")

    try:
        from app.models.user import User
        from app.models.metrics import HealthMetric
        from app.models.training import TrainingPlan
        from app.services.email_service import EmailService
        from sqlalchemy import select

        email_service = EmailService()
        sent_count = 0

        async with async_session() as db:
            import uuid as _uuid
            demo_uuid = _uuid.UUID(settings.demo_user_id)
            result = await db.execute(
                select(User).where(
                    User.id != demo_uuid,
                    User.email.isnot(None),
                    User.email.contains("@"),
                )
            )
            users = result.scalars().all()

            today = date.today()
            week_start = today - timedelta(days=today.weekday())

            demo_id = settings.demo_user_id
            for user in users:
                try:
                    # Metriken der Woche laden
                    metrics_result = await db.execute(
                        select(HealthMetric).where(
                            HealthMetric.user_id == user.id,
                            HealthMetric.recorded_at
                            >= datetime.now(timezone.utc) - timedelta(days=7),
                        )
                    )
                    metrics = metrics_result.scalars().all()

                    # Trainings laden
                    plan_result = await db.execute(
                        select(TrainingPlan).where(
                            TrainingPlan.user_id == user.id,
                            TrainingPlan.date >= week_start,
                            TrainingPlan.date < week_start + timedelta(days=7),
                        )
                    )
                    plans = plan_result.scalars().all()

                    completed = [p for p in plans if p.status == "completed"]
                    total_training_min = sum(p.duration_min or 0 for p in completed)
                    avg_hrv = (
                        round(sum(m.hrv or 0 for m in metrics) / len(metrics), 1)
                        if metrics
                        else 0
                    )

                    stats = {
                        "completed_workouts": len(completed),
                        "total_workouts": len(plans),
                        "total_training_min": total_training_min,
                        "avg_hrv": avg_hrv,
                        "week_start": week_start.isoformat(),
                    }

                    await email_service.send_weekly_report(user.email, user.name, stats)
                    sent_count += 1

                except Exception as e:
                    logger.warning(
                        f"Weekly report failed for user | user={user.id} | error={e}"
                    )
                    continue

        await _publish_status(redis, task_id, "completed", {"sent": sent_count})
        logger.info(f"Weekly report completed | sent={sent_count}/{len(users)}")

    except Exception as e:
        await _publish_status(redis, task_id, "failed", {"error": str(e)})
        logger.error(f"Weekly report failed | error={e}")


# ─── ARQ Worker Settings ───────────────────────────────────────────────────────


async def startup(ctx: dict):
    """Wird beim Start des ARQ-Workers aufgerufen."""
    import redis.asyncio as aioredis

    ctx["redis"] = aioredis.from_url(settings.redis_url)
    logger.info("ARQ worker started")


async def shutdown(ctx: dict):
    """Wird beim Stoppen des ARQ-Workers aufgerufen."""
    await ctx["redis"].close()
    logger.info("ARQ worker stopped")


class WorkerSettings:
    """ARQ Worker Konfiguration."""

    functions = [
        generate_training_plan,
        send_weekly_report,
    ]

    on_startup = startup
    on_shutdown = shutdown

    # Cron-Job: Wöchentlicher Report jeden Sonntag um 20:00
    cron_jobs = [
        cron(send_weekly_report, weekday=6, hour=20, minute=0, job_id="weekly_report"),
    ]

    # Redis Verbindung
    redis_settings = None  # wird dynamisch aus settings.redis_url konstruiert
