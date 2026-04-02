import time
import uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.responses import ORJSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text
from app.core.logging import setup_logging
from app.api.routes import (
    auth,
    auth_keycloak,
    coach,
    training,
    metrics,
    nutrition,
    watch,
    user,
    tasks,
    notifications,
    billing,
    guest,
)
from app.scheduler.runner import start_scheduler
from app.core.config import settings
from app.core.database import async_session

log = setup_logging()

# Sentry Error Tracking (nur aktiv wenn DSN gesetzt)
if settings.sentry_dsn:
    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        integrations=[FastApiIntegration()],
        traces_sample_rate=0.1,
        environment="production" if not settings.dev_mode else "development",
    )
    log.info("Sentry Error Tracking aktiviert")

limiter = Limiter(key_func=get_remote_address)


async def _ensure_demo_user():
    """Legt beim Start einen festen Demo-User an falls er noch nicht existiert."""
    import random
    from datetime import datetime, timedelta, timezone
    from app.core.security import hash_password
    from app.models.user import User
    from app.models.metrics import HealthMetric
    from sqlalchemy import select

    async with async_session() as db:
        demo_id = uuid.UUID(settings.demo_user_id)
        result = await db.execute(select(User).where(User.id == demo_id))
        if result.scalar_one_or_none() is None:
            demo_user = User(
                id=demo_id,
                email="demo@trainiq.app",
                name="Demo Athlete",
                password_hash=hash_password("demo1234"),
            )
            db.add(demo_user)
            await db.flush()

            # Demo-Metriken für die letzten 7 Tage generieren
            now = datetime.now(timezone.utc)
            base_hrv = round(random.uniform(38.0, 48.0), 1)
            base_sleep = random.randint(390, 480)
            base_stress = round(random.uniform(30.0, 45.0), 1)

            for day_offset in range(7):
                day = now - timedelta(days=day_offset)
                metric = HealthMetric(
                    user_id=demo_id,
                    recorded_at=day,
                    hrv=round(base_hrv + random.uniform(-5.0, 5.0), 1),
                    resting_hr=random.randint(55, 70),
                    sleep_duration_min=base_sleep + random.randint(-30, 30),
                    sleep_quality_score=round(random.uniform(60.0, 95.0), 1),
                    stress_score=round(base_stress + random.uniform(-8.0, 8.0), 1),
                    spo2=round(random.uniform(95.0, 99.0), 1),
                    steps=random.randint(5000, 15000),
                    source="demo",
                )
                db.add(metric)

            # Demo-Trainingsplan generieren
            from datetime import date
            from app.services.training_planner import TrainingPlanner
            from app.models.training import UserGoal, TrainingPlan

            # Demo-Ziel anlegen falls keins vorhanden
            goal_result = await db.execute(
                select(UserGoal).where(UserGoal.user_id == demo_id)
            )
            if not goal_result.scalars().first():
                demo_goal = UserGoal(
                    user_id=demo_id,
                    sport="running",
                    goal_description="Halbmarathon unter 2 Stunden in 6 Monaten",
                    weekly_hours=6,
                    fitness_level="intermediate",
                )
                db.add(demo_goal)
                await db.flush()

            # Trainingsplan für aktuelle Woche generieren falls keiner vorhanden
            today = date.today()
            week_start = today - timedelta(days=today.weekday())
            plan_result = await db.execute(
                select(TrainingPlan).where(
                    TrainingPlan.user_id == demo_id,
                    TrainingPlan.date >= week_start,
                    TrainingPlan.date < week_start + timedelta(days=7),
                )
            )
            if not plan_result.scalars().first():
                planner = TrainingPlanner()
                try:
                    await planner.generate_week_plan(str(demo_id), week_start, db)
                except Exception as e:
                    log.warning(f"Demo plan generation failed | error={e}")

            await db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Demo-User sicherstellen (nur im Dev-Modus sinnvoll)
    if settings.dev_mode:
        try:
            await _ensure_demo_user()
        except Exception as e:
            log.warning(f"Demo-User konnte nicht erstellt werden: {e}")

    try:
        start_scheduler()
        log.info("Scheduler started")
    except Exception as e:
        log.error(f"Scheduler failed to start | error={e}")

    yield

    from app.scheduler.runner import scheduler

    if scheduler.running:
        scheduler.shutdown(wait=False)


app = FastAPI(
    title="TrainIQ API",
    version="1.0.0",
    lifespan=lifespan,
    default_response_class=ORJSONResponse,  # ~2-3× faster JSON serialization
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

if settings.dev_mode:
    _origins = [
        "http://localhost",
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:8000",
    ]
else:
    # Production: only the explicitly configured frontend URL is allowed
    _origins = [settings.frontend_url] if settings.frontend_url else []
if settings.frontend_url and settings.frontend_url not in _origins:
    _origins.append(settings.frontend_url)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Guest-Token", "X-Request-ID"],
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=()"
        )
        if not settings.dev_mode:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
        # Correlation ID für Tracing / Logs
        req_id = request.headers.get("X-Request-ID", "")
        if req_id:
            response.headers["X-Request-ID"] = req_id
        return response


app.add_middleware(SecurityHeadersMiddleware)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    duration = round((time.time() - start) * 1000)
    log.info(
        f"{request.method} {request.url.path} -> {response.status_code} ({duration}ms)"
    )
    return response


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    log.error(f"Unhandled exception | path={request.url.path} | error={exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Interner Serverfehler"},
    )


app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(
    auth_keycloak.router, prefix="/auth/keycloak", tags=["auth-keycloak"]
)
app.include_router(coach.router, prefix="/coach", tags=["coach"])
app.include_router(training.router, prefix="/training", tags=["training"])
app.include_router(metrics.router, prefix="/metrics", tags=["metrics"])
app.include_router(nutrition.router, prefix="/nutrition", tags=["nutrition"])
app.include_router(watch.router, prefix="/watch", tags=["watch"])
app.include_router(user.router, prefix="/user", tags=["user"])
app.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
app.include_router(
    notifications.router, prefix="/notifications", tags=["notifications"]
)
app.include_router(billing.router, prefix="/billing", tags=["billing"])
app.include_router(guest.router, prefix="/guest", tags=["guest"])


@app.get("/health")
async def health():
    db_ok = False
    redis_ok = False
    llm_ok = None
    strava_ok = None

    try:
        async with async_session() as db:
            await db.execute(text("SELECT 1"))
            db_ok = True
    except Exception:
        pass

    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(settings.redis_url)
        try:
            result = await r.ping()
            if result is True:
                redis_ok = True
        except Exception:
            pass
        await r.aclose()
    except Exception:
        log.warning("Health check: Redis nicht erreichbar")

    if settings.active_llm_api_key:
        try:
            import httpx

            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(
                    f"{settings.llm_base_url}/models",
                    headers={"Authorization": f"Bearer {settings.active_llm_api_key}"},
                )
                llm_ok = "ok" if response.status_code == 200 else "error"
        except Exception as e:
            llm_ok = "error"
            log.warning(f"Health check: LLM API nicht erreichbar | error={e}")

    if settings.strava_client_id:
        strava_ok = "configured"  # Key is set — actual connectivity not checked here

    all_ok = db_ok and redis_ok
    return {
        "status": "ok" if all_ok else "degraded",
        "db": "ok" if db_ok else "error",
        "redis": "ok" if redis_ok else "error",
        "llm": llm_ok,
        "strava": strava_ok,
        "version": "1.0.0",
    }
