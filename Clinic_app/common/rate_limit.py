"""
Per-IP HTTP rate limiting via Redis fixed-window counters.

Usage (per-route):
    from Clinic_app.common.rate_limit import make_rate_limit_dep

    @router.post("/endpoint")
    async def handler(
        ...,
        _rl: None = Depends(make_rate_limit_dep("20/minute")),
    ):
        ...

Usage (router-level in main.py):
    app.include_router(
        admin_router,
        dependencies=[Depends(make_rate_limit_dep("20/minute", env_var="RATE_LIMIT_ADMIN"))],
    )

Key format: rl:{limit_str}:{ip}:{time_bucket}
Falls back to allowing the request when Redis is unavailable (fail-open).
"""

import logging
import os
import time

from fastapi import HTTPException, Request

from Clinic_app.common.redis import get_redis

logger = logging.getLogger(__name__)


def _parse_limit(limit_str: str) -> tuple[int, int]:
    """Parse "N/unit" → (count, window_seconds).  Supports second/minute/hour/day."""
    n_str, unit = limit_str.split("/", 1)
    n = int(n_str.strip())
    unit = unit.strip().lower()
    windows = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}
    if unit not in windows:
        raise ValueError(f"Unknown rate limit unit: {unit!r}. Use second/minute/hour/day.")
    return n, windows[unit]


def _get_client_ip(request: Request) -> str:
    """Extract client IP, respecting X-Forwarded-For for reverse-proxy deployments."""
    forwarded = request.headers.get("X-Forwarded-For", "").strip()
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def make_rate_limit_dep(
    default_limit: str = "20/minute",
    env_var: str | None = None,
) -> callable:
    """
    Return a FastAPI dependency that enforces per-IP rate limiting.

    Args:
        default_limit: Fallback rate limit in "N/unit" format.
        env_var: If set, read the actual limit from this environment variable at
                 request time (so tests can override without restarting the app).

    The dependency raises HTTP 429 when the limit is exceeded and is a no-op
    when Redis is unreachable (fail-open with a warning log).
    """

    async def _dep(request: Request) -> None:
        limit_str = os.environ.get(env_var, default_limit) if env_var else default_limit
        try:
            n, window_secs = _parse_limit(limit_str)
        except (ValueError, AttributeError):
            logger.warning("Invalid rate limit string %r — skipping rate check", limit_str)
            return

        ip = _get_client_ip(request)
        bucket = int(time.time()) // window_secs
        # Key is unique per limit tier, IP, and time bucket.
        safe_tier = limit_str.replace("/", ":")
        key = f"rl:{safe_tier}:{ip}:{bucket}"

        try:
            r = await get_redis()
            count = await r.incr(key)
            # Set TTL on first increment; time-bucketed key ensures window reset.
            if count == 1:
                await r.expire(key, window_secs + 30)  # +30s safety margin

            if count > n:
                logger.warning(
                    "Rate limit exceeded: ip=%s limit=%s count=%d",
                    ip,
                    limit_str,
                    count,
                )
                raise HTTPException(
                    status_code=429,
                    detail={
                        "code": "RATE_LIMIT_EXCEEDED",
                        "message": "Too many requests. Please try again later.",
                    },
                )
        except HTTPException:
            raise
        except Exception as exc:
            # Redis unavailable — fail open so the app stays functional.
            logger.warning("Rate limiter Redis error (failing open): %s", exc)

    return _dep


# ── Pre-built dependency factories for each tier ────────────────────────────
# Import these and wrap with Depends() at the call site.


def auth_rate_limit():
    """Rate limiter for auth endpoints and campaign mutations (default 20/minute)."""
    return make_rate_limit_dep("20/minute", env_var="RATE_LIMIT_AUTH")


def admin_rate_limit():
    """Rate limiter for admin + provider endpoints (default 20/minute)."""
    return make_rate_limit_dep("20/minute", env_var="RATE_LIMIT_ADMIN")


def upload_rate_limit():
    """Rate limiter for CSV/Excel campaign upload (default 5/minute)."""
    return make_rate_limit_dep("5/minute", env_var="RATE_LIMIT_UPLOAD")


def webhook_rate_limit():
    """Rate limiter for Retell webhook endpoints (default 120/minute)."""
    return make_rate_limit_dep("120/minute", env_var="RATE_LIMIT_RETELL_WEBHOOK")
