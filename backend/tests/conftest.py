import os
import uuid

# Set environment variables BEFORE any app imports
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["REDIS_URL"] = "redis://localhost:6379"
os.environ["JWT_SECRET"] = "test-secret-key"
os.environ["DEV_MODE"] = "true"
os.environ["DEMO_USER_ID"] = "00000000-0000-0000-0000-000000000001"
os.environ["LLM_API_KEY"] = ""
os.environ["CLOUDINARY_CLOUD_NAME"] = ""
os.environ["CLOUDINARY_API_KEY"] = ""
os.environ["CLOUDINARY_API_SECRET"] = ""

# Disable rate limiting BEFORE any slowapi imports
import slowapi.extension

_orig_async_wrapper_setup = None


def _patched_check(self, request, endpoint_func, in_middleware=True):
    request.state.view_rate_limit = None


slowapi.Limiter._check_request_limit = _patched_check

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture(scope="session")
async def client():
    import app.core.database as db_module

    test_engine = create_async_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    db_module.engine = test_engine
    db_module.async_session = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )

    async with test_engine.begin() as conn:
        from app.core.database import Base
        from app.models import (
            user,
            training,
            metrics,
            nutrition,
            conversation,
            watch,
            ai_memory,
            guest,
        )

        await conn.run_sync(Base.metadata.create_all)

    from main import app

    # Ensure demo user exists in test DB
    from app.core.security import hash_password
    from app.models.user import User
    from sqlalchemy import select

    demo_id = uuid.UUID(os.environ["DEMO_USER_ID"])
    async with db_module.async_session() as session:
        result = await session.execute(select(User).where(User.id == demo_id))
        if result.scalar_one_or_none() is None:
            demo_user = User(
                id=demo_id,
                email="demo@trainiq.app",
                name="Demo Athlete",
                password_hash=hash_password("demo1234"),
            )
            session.add(demo_user)
            await session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac

    await test_engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db(client):
    import app.core.database as db_module

    session_factory = async_sessionmaker(db_module.engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        # Delete test data created during the test
        from app.models.training import TrainingPlan, UserGoal
        from app.models.metrics import HealthMetric, DailyWellbeing
        from app.models.nutrition import NutritionLog
        from app.models.watch import WatchConnection
        from app.models.guest import GuestSession
        from sqlalchemy import delete

        for model in [
            TrainingPlan,
            UserGoal,
            HealthMetric,
            DailyWellbeing,
            NutritionLog,
            WatchConnection,
            GuestSession,
        ]:
            await session.execute(delete(model))
        await session.commit()


# NOTE: conftest always uses /auth/login for auth_headers fixture
# Register tests should create separate users and use the returned token directly


@pytest_asyncio.fixture
async def auth_headers(client: AsyncClient):
    email = f"test_{uuid.uuid4().hex[:8]}@test.com"
    await client.post(
        "/auth/register",
        json={"email": email, "password": "test1234", "name": "Test User"},
    )
    resp = await client.post(
        "/auth/login",
        json={"email": email, "password": "test1234"},
    )
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def guest_token(client: AsyncClient):
    """Erstellt eine Gast-Session und gibt das Token zurück."""
    resp = await client.post("/guest/session")
    data = resp.json()
    return data["guest_token"]
