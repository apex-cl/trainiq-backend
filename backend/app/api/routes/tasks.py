"""
Task Queue Routes

Ermöglicht das Enqueuen von Background-Tasks und SSE-Streaming für Task-Status.
"""

import asyncio
import json
from datetime import date
from typing import AsyncGenerator
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator
from slowapi import Limiter
from slowapi.util import get_remote_address
from app.api.dependencies import get_current_user, _get_user_by_id, _get_user_by_keycloak_id
from app.core.database import get_db
from app.models.user import User
from app.core.config import settings
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


class EnqueuePlanRequest(BaseModel):
    week_start: str  # ISO date

    @field_validator("week_start")
    @classmethod
    def validate_week_start(cls, v: str) -> str:
        try:
            date.fromisoformat(v)
        except ValueError:
            raise ValueError("week_start muss ein gültiges ISO-Datum sein (YYYY-MM-DD)")
        return v


# ─── ARQ shared pool ────────────────────────────────────────────────────────
# URL-Parsing + Pool-Aufbau einmalig pro Worker — nie pro Request.
_arq_settings = None
_arq_pool = None
_arq_pool_lock = asyncio.Lock()


def _get_arq_settings():
    global _arq_settings
    if _arq_settings is None:
        from arq.connections import RedisSettings
        from urllib.parse import urlparse
        p = urlparse(settings.redis_url)
        _arq_settings = RedisSettings(
            host=p.hostname or "localhost",
            port=p.port or 6379,
            database=int(p.path.lstrip("/")) if p.path and p.path != "/" else 0,
            password=p.password,
        )
    return _arq_settings


async def _get_arq_pool():
    global _arq_pool
    if _arq_pool is not None:
        return _arq_pool
    async with _arq_pool_lock:
        if _arq_pool is None:
            try:
                from arq import create_pool
                _arq_pool = await asyncio.wait_for(create_pool(_get_arq_settings()), timeout=3.0)
            except (asyncio.TimeoutError, Exception):
                _arq_pool = None
                raise
    return _arq_pool


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
    try:
        redis = await _get_arq_pool()
        job = await redis.enqueue_job(
            "generate_training_plan",
            str(current_user.id),
            body.week_start,
        )
    except (asyncio.TimeoutError, Exception) as exc:
        raise HTTPException(status_code=503, detail="Task-Queue nicht verfügbar") from exc
    task_id = f"plan_gen:{current_user.id}:{body.week_start}"
    return {
        "task_id": task_id,
        "job_id": job.job_id,
        "status": "enqueued",
    }


@router.post("/sync-strava")
@limiter.limit("5/minute")
async def enqueue_strava_sync(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """Enqueut eine Strava-Sync im Hintergrund."""
    try:
        redis = await _get_arq_pool()
        job = await redis.enqueue_job(
            "sync_strava_activities",
            str(current_user.id),
        )
    except (asyncio.TimeoutError, Exception) as exc:
        raise HTTPException(status_code=503, detail="Task-Queue nicht verfügbar") from exc
    task_id = f"strava_sync:{current_user.id}"
    return {
        "task_id": task_id,
        "job_id": job.job_id,
        "status": "enqueued",
    }


@router.get("/status/{task_id}")
async def task_status_sse(
    task_id: str,
    current_user: User = Depends(get_current_user),
):
    """
    SSE-Stream für Task-Status-Updates.
    Streamt Events bis der Task abgeschlossen ist.
    """
    # Ownership-Check: task_id beginnt immer mit plan_gen:<user_id>: oder strava_sync:<user_id>
    user_prefix = str(current_user.id)
    if not (task_id.startswith(f"plan_gen:{user_prefix}:") or
            task_id.startswith(f"strava_sync:{user_prefix}")):
        raise HTTPException(status_code=403, detail="Kein Zugriff auf diesen Task")

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

    redis_client = aioredis.from_url(
        settings.redis_url,
        socket_connect_timeout=3,
        socket_timeout=3,
    )
    pubsub = redis_client.pubsub()

    try:
        await asyncio.wait_for(pubsub.subscribe(f"task:{task_id}"), timeout=3.0)

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

    except Exception:
        yield f"data: {json.dumps({'task_id': task_id, 'status': 'error'})}\n\n"
    finally:
        await pubsub.unsubscribe(f"task:{task_id}")
        await pubsub.aclose()
        await redis_client.aclose()


# ─── Watch Echtzeit-Stream ──────────────────────────────────────────────────


@router.get("/watch-stream")
async def watch_events_sse(
    request: Request,
    token: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    """
    Persistenter SSE-Stream für Uhr-Sync-Events.
    Akzeptiert Auth-Token als Bearer-Header ODER als ?token= Query-Param
    (EventSource API im Browser unterstützt keine Custom-Headers).
    Sobald Strava/Garmin eine Aktivität synchronisiert, sendet der Server ein Event
    und das Frontend lädt Metriken + Trainingsplan automatisch neu.
    """
    from app.core.security import verify_token as _verify_token

    # Token aus Query-Param (EventSource) oder Authorization-Header
    raw_token = token
    if not raw_token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            raw_token = auth_header[7:]

    if not raw_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    # Keycloak-Token versuchen, dann lokalen JWT
    user: User | None = None
    if settings.keycloak_enabled:
        try:
            from app.services.keycloak_jwt_service import keycloak_jwt_service
            payload = await keycloak_jwt_service.verify_keycloak_token(raw_token)
            keycloak_id = payload.get("sub")
            if keycloak_id:
                user = await _get_user_by_keycloak_id(keycloak_id, db)
        except Exception:
            pass

    if not user:
        try:
            payload = _verify_token(raw_token)
            user_id_str = payload.get("sub")
            if user_id_str:
                user = await _get_user_by_id(user_id_str, db)
        except Exception:
            pass

    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    return StreamingResponse(
        _stream_watch_events(str(user.id)),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


async def _stream_watch_events(user_id: str) -> AsyncGenerator[str, None]:
    """Lauscht auf watch_events:{user_id} Channel und streamt Events ans Frontend."""
    import redis.asyncio as aioredis

    redis_client = aioredis.from_url(
        settings.redis_url,
        socket_connect_timeout=3,
        socket_timeout=3,
    )
    pubsub = redis_client.pubsub()

    try:
        await asyncio.wait_for(pubsub.subscribe(f"watch_events:{user_id}"), timeout=3.0)
        # Verbindung bestätigen
        yield f"data: {json.dumps({'event': 'connected', 'user_id': user_id})}\n\n"

        # Keepalive alle 25 Sekunden (Nginx/Browser trennen sonst die Verbindung)
        keepalive_interval = 25
        last_keepalive = asyncio.get_running_loop().time()

        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            now = asyncio.get_running_loop().time()

            if message and message["type"] == "message":
                data = message["data"]
                if isinstance(data, bytes):
                    data = data.decode()
                yield f"data: {data}\n\n"

            if now - last_keepalive >= keepalive_interval:
                yield ": keepalive\n\n"
                last_keepalive = now

    except Exception:
        yield f"data: {json.dumps({'event': 'error'})}\n\n"
    finally:
        await pubsub.unsubscribe(f"watch_events:{user_id}")
        await pubsub.aclose()
        await redis_client.aclose()
