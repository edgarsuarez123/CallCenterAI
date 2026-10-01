"""
Per-clinic Claude API rate limiting via Redis fixed-window counters.

Each clinic gets its own counter bucket per minute. When the limit is exceeded,
callers receive False and must use a safe fallback (e.g. "Call summary unavailable.")
instead of calling Claude.

Webhooks (e.g. call_analyzed) must still return 200 even when rate-limited so
Retell does not retry indefinitely. The audit row is still written with the
fallback summary text.

Key format: claude:clinic:{clinic_id}:{epoch_minute}
"""

import logging
import os
import time
from uuid import UUID

from Clinic_app.common.redis import get_redis

logger = logging.getLogger(__name__)

_DEFAULT_LIMIT = 10  # calls per minute per clinic


async def check_and_increment(clinic_id: UUID) -> bool:
    """
    Check and increment the per-clinic Claude usage counter.

    Returns:
        True  — under the per-minute limit; proceed with the Claude call.
        False — limit exceeded; use fallback, skip Claude.

    Fails open (returns True) if Redis is unreachable so calls are never blocked
    by infrastructure issues.
    """
    limit = _get_limit()
    bucket = int(time.time()) // 60
    key = f"claude:clinic:{clinic_id}:{bucket}"

    try:
        r = await get_redis()
        count = await r.incr(key)
        if count == 1:
            await r.expire(key, 90)  # 60s window + 30s safety margin

        if count > limit:
            logger.warning(
                "Claude rate limit exceeded: clinic_id=%s count=%d limit=%d/minute",
                clinic_id,
                count,
                limit,
            )
            return False

        return True

    except Exception as exc:
        # Redis unavailable — fail open so summarization still works.
        logger.warning("Claude rate limiter Redis error (failing open): %s", exc)
        return True


def _get_limit() -> int:
    """Read per-clinic limit from env at call time so tests can override."""
    raw = os.environ.get("RATE_LIMIT_CLAUDE_PER_CLINIC", str(_DEFAULT_LIMIT))
    try:
        return int(raw.strip())
    except ValueError:
        logger.warning(
            "Invalid RATE_LIMIT_CLAUDE_PER_CLINIC=%r — using default %d",
            raw,
            _DEFAULT_LIMIT,
        )
        return _DEFAULT_LIMIT
