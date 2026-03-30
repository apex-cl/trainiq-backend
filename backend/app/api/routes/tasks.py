"""
Task Queue Routes

Ermöglicht das Enqueuen von Background-Tasks und SSE-Streaming für Task-Status.
"""

import json
from typing import AsyncGenerator
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address
from app.api.dependencies import get_current_user
from app.models.user import User
from app.core.config import settings

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


class EnqueuePlanRequest(BaseModel):
    week_start: str  # ISO date


async def _get_arq_redis():
    """Holt die ARQ Redis-Verbindung."""
    import redis.asyncio as aioredis

    return aioredis.from_url(settings.redis_url)


@router.post("/generate-plan")
@limiter.limit("5/minute")
async def enqueue_training_plan(
    request: Request,
    body: EnqueuePlanRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Enqueut die Generierung eines Trainingsplans im Hintergrund.
    Gibt eine task_id zurück, über die der Status via SSE verfolgt werden kann.
    """
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
        job = await redis.enqueue_job(
            "generate_training_plan",
            str(current_user.id),
            body.week_start,
        )
        task_id = f"plan_gen:{current_user.id}:{body.week_start}"
        return {
            "task_id": task_id,
            "job_id": job.job_id,
            "status": "enqueued",
        }
    finally:
        await redis.close()


@router.post("/sync-strava")
@limiter.limit("5/minute")
async def enqueue_strava_sync(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """Enqueut eine Strava-Sync im Hintergrund."""
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
        job = await redis.enqueue_job(
            "sync_strava_activities",
            str(current_user.id),
        )
        task_id = f"strava_sync:{current_user.id}"
        return {
            "task_id": task_id,
            "job_id": job.job_id,
            "status": "enqueued",
        }
    finally:
        await redis.close()


@router.get("/status/{task_id}")
async def task_status_sse(
    task_id: str,
    current_user: User = Depends(get_current_user),
):
    """
    SSE-Stream für Task-Status-Updates.
    Streamt Events bis der Task abgeschlossen ist.
    """
    return StreamingResponse(
        _stream_task_status(task_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


async def _stream_task_status(task_id: str) -> AsyncGenerator[str, None]:
    """SSE-Stream für Task-Status via Redis Pub/Sub."""
    import redis.asyncio as aioredis

    redis_client = aioredis.from_url(settings.redis_url)
    pubsub = redis_client.pubsub()

    try:
        await pubsub.subscribe(f"task:{task_id}")

        # Erstes Event: Verbindung bestätigen
        yield f"data: {json.dumps({'task_id': task_id, 'status': 'listening'})}\n\n"

        async for message in pubsub.listen():
            if message["type"] == "message":
                data = message["data"]
                if isinstance(data, bytes):
                    data = data.decode()
                yield f"data: {data}\n\n"

                # Prüfen ob Task fertig ist
                try:
                    parsed = json.loads(data)
                    if parsed.get("status") in ("completed", "failed", "skipped"):
                        break
                except json.JSONDecodeError:
                    pass

    except Exception as e:
        yield f"data: {json.dumps({'task_id': task_id, 'status': 'error', 'error': str(e)})}\n\n"
    finally:
        await pubsub.unsubscribe(f"task:{task_id}")
        await pubsub.close()
        await redis_client.close()
