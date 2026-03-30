import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.scheduler.jobs import (
    sync_watch_data_for_all_users,
    generate_tomorrow_plans,
    autonomous_monitor_job,
    send_sleep_tips_job,
    send_morning_feedback_job,
)

scheduler = AsyncIOScheduler()

scheduler.add_job(
    sync_watch_data_for_all_users,
    "interval",
    hours=4,
    id="watch_sync",
    replace_existing=True,
)
scheduler.add_job(
    generate_tomorrow_plans,
    "cron",
    hour=21,
    minute=0,
    id="plan_gen",
    replace_existing=True,
)
scheduler.add_job(
    autonomous_monitor_job,
    "interval",
    minutes=30,
    id="autonomous_monitor",
    replace_existing=True,
)
scheduler.add_job(
    send_sleep_tips_job,
    "cron",
    hour=22,
    minute=0,
    id="sleep_tips",
    replace_existing=True,
)
scheduler.add_job(
    send_morning_feedback_job,
    "cron",
    hour=7,
    minute=0,
    id="morning_feedback",
    replace_existing=True,
)


def start_scheduler():
    """Wird vom FastAPI Lifespan aufgerufen."""
    if not scheduler.running:
        scheduler.start()


if __name__ == "__main__":
    scheduler.start()
    asyncio.get_event_loop().run_forever()
