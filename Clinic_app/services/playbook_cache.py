"""
Redis-backed slot cache for EHR automation (HIPAA T-01 remediation: AgentQL → Browser-Use).

Key schema
----------
ehr:slots:{clinic_id}:{provider}   TTL: 90s  — Next available slots (pre-fetched by SlotPrefetchWorker)

Multi-tenant isolation: all keys include clinic_id — one shared Redis, no cross-clinic reads.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional
from uuid import UUID

from Clinic_app.common.redis import get_redis

logger = logging.getLogger(__name__)

SLOT_CACHE_PREFIX = "ehr:slots"
SLOT_CACHE_TTL_SECONDS = 90  # SlotPrefetchWorker runs every 60s; buffer of 30s


def _slot_key(clinic_id: UUID, provider_name: str) -> str:
    safe_provider = provider_name.replace(" ", "_").lower()
    return f"{SLOT_CACHE_PREFIX}:{clinic_id}:{safe_provider}"


async def get_cached_slots(
    clinic_id: UUID, provider_name: str
) -> Optional[list[dict[str, Any]]]:
    """Return pre-fetched slot list, or None on cache miss."""
    r = await get_redis()
    key = _slot_key(clinic_id, provider_name)
    val = await r.get(key)
    if val is None:
        return None
    try:
        return json.loads(val)
    except json.JSONDecodeError:
        logger.warning("Corrupt slot cache for clinic %s provider %s — ignoring", clinic_id, provider_name)
        return None


async def set_cached_slots(
    clinic_id: UUID, provider_name: str, slots: list[dict[str, Any]]
) -> None:
    """Cache slot list with 90s TTL."""
    r = await get_redis()
    key = _slot_key(clinic_id, provider_name)
    await r.set(key, json.dumps(slots), ex=SLOT_CACHE_TTL_SECONDS)
    logger.debug(
        "Cached %d slots for clinic %s provider '%s' (TTL=%ds)",
        len(slots), clinic_id, provider_name, SLOT_CACHE_TTL_SECONDS,
    )


async def invalidate_clinic_ehr_cache(clinic_id: UUID) -> int:
    """
    Delete all cached slots for a clinic.
    Called after EHR config change or when slots are known stale.
    Returns the number of keys removed.
    """
    r = await get_redis()
    deleted = 0
    pattern = f"{SLOT_CACHE_PREFIX}:{clinic_id}:*"
    async for key in r.scan_iter(match=pattern):
        await r.delete(key)
        deleted += 1
    if deleted:
        logger.info("Invalidated %d slot cache keys for clinic %s", deleted, clinic_id)
    return deleted
