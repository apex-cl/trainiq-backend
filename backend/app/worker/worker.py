"""
ARQ Worker Runner

Startet den ARQ Background Worker.
Verwendung: python -m app.worker.worker
"""

import asyncio
from arq import create_pool
from arq.connections import RedisSettings
from loguru import logger
from app.core.config import settings
from app.worker.tasks import WorkerSettings, startup, shutdown


def get_redis_settings() -> RedisSettings:
    """Konstruiert RedisSettings aus der settings.redis_url."""
    # redis://localhost:6379 -> RedisSettings
    from urllib.parse import urlparse

    parsed = urlparse(
        settings.redis_settings
        if hasattr(settings, "redis_settings") and settings.redis_settings
        else settings.redis_url
    )
    return RedisSettings(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        database=int(parsed.path.lstrip("/"))
        if parsed.path and parsed.path != "/"
        else 0,
        password=parsed.password,
    )


async def main():
    """Startet den ARQ Worker."""
    from arq.worker import Worker

    redis_settings = get_redis_settings()

    worker = Worker(
        functions=WorkerSettings.functions,
        on_startup=startup,
        on_shutdown=shutdown,
        cron_jobs=WorkerSettings.cron_jobs,
        redis_settings=redis_settings,
    )

    logger.info("Starting ARQ worker...")
    await worker.async_run()


if __name__ == "__main__":
    asyncio.run(main())
