"""
Async Redis client singleton.

Used for:
- AgentQL selector cache (24h TTL, ~60% token savings)
- Distributed concurrency lock (prevents NextGen race conditions across workers)
"""

import os
import logging

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

_redis_client: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    """Return the shared async Redis client, initializing it on first call."""
    global _redis_client
    if _redis_client is None:
        url = os.environ.get("REDIS_URL", "redis://localhost:6379")
        _redis_client = aioredis.from_url(url, encoding="utf-8", decode_responses=True)
        logger.info("Redis client initialized")
    return _redis_client


async def close_redis() -> None:
    """Close the Redis connection. Called on app shutdown."""
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None
        logger.info("Redis client closed")
