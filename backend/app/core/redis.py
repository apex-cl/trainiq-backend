import redis.asyncio as aioredis
from app.core.config import settings

_redis: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis


async def cache_get(key: str) -> str | None:
    r = await get_redis()
    return await r.get(key)


async def cache_set(key: str, value: str, ttl: int = 300) -> None:
    r = await get_redis()
    await r.set(key, value, ex=ttl)


async def cache_del(key: str) -> None:
    r = await get_redis()
    await r.delete(key)
