from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from typing import AsyncGenerator
from app.core.config import settings


_db_url = settings.database_url.replace("postgresql://", "postgresql+asyncpg://")
_engine_kwargs: dict = {"echo": False, "pool_pre_ping": True}
if "postgresql" in _db_url:
    _engine_kwargs.update(
        pool_size=20,           # was 10 — handle more concurrent requests
        max_overflow=30,        # was 20 — burst capacity
        pool_recycle=1800,      # recycle connections every 30 min (was 1 hour)
        pool_timeout=30,        # wait max 30s for a connection
        connect_args={
            "statement_cache_size": 500,   # asyncpg prepared statement cache
            "command_timeout": 60,
        },
    )

engine = create_async_engine(_db_url, **_engine_kwargs)

# Schema wird durch Alembic-Migrationen verwaltet
# alembic upgrade head

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
