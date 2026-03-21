"""
Redis-backed cache for AgentQL-resolved DOM selectors (HEDIS PRD §10.7).

Key format: agentql:selector:{clinic_id}:{element_name}
TTL: 86400 seconds (24 hours)
"""

from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from Clinic_app.common.redis import get_redis

logger = logging.getLogger(__name__)

SELECTOR_CACHE_PREFIX = "agentql:selector"
SELECTOR_CACHE_TTL_SECONDS = 86_400  # 24 hours


def _cache_key(clinic_id: UUID, element_name: str) -> str:
    """Build tenant-scoped cache key (must match tests/test_playwright_validation.py)."""
    return f"{SELECTOR_CACHE_PREFIX}:{clinic_id}:{element_name}"


async def get_cached_selector(clinic_id: UUID, element_name: str) -> Optional[str]:
    """Return cached CSS/XPath selector string, or None if missing."""
    r = await get_redis()
    key = _cache_key(clinic_id, element_name)
    val = await r.get(key)
    if val is None:
        return None
    return str(val)


async def set_cached_selector(clinic_id: UUID, element_name: str, selector: str) -> None:
    """Store selector with 24h TTL."""
    r = await get_redis()
    key = _cache_key(clinic_id, element_name)
    await r.set(key, selector, ex=SELECTOR_CACHE_TTL_SECONDS)


async def invalidate_clinic_selectors(clinic_id: UUID) -> int:
    """
    Delete all cached selectors for a clinic (e.g. after credential or URL change).

    Returns the number of keys removed.
    """
    r = await get_redis()
    pattern = f"{SELECTOR_CACHE_PREFIX}:{clinic_id}:*"
    deleted = 0
    async for key in r.scan_iter(match=pattern):
        await r.delete(key)
        deleted += 1
    if deleted:
        logger.info("Invalidated %s AgentQL selector cache keys for clinic %s", deleted, clinic_id)
    return deleted
