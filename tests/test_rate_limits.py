# tests/test_rate_limits.py
"""
Unit tests for HTTP and Claude rate limiting (Plan 012).

Covers:
- make_rate_limit_dep: raises 429 when Redis count exceeds limit; passes under limit.
- make_rate_limit_dep: fails open (allows request) when Redis is unreachable.
- claude_rate_limit.check_and_increment: returns False when over limit, True when under.
- claude_rate_limit: per-clinic tenant isolation (clinic B not blocked by clinic A).
- env var override: RATE_LIMIT_AUTH and RATE_LIMIT_CLAUDE_PER_CLINIC read at request time.
"""
import os
import time
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure required env vars are set before any app import.
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("PHI_ENCRYPTION_KEY", "dGVzdGtleXRlc3RrZXl0ZXN0a2V5dGVzdGtleQ==")
os.environ.setdefault("PHI_HASH_KEY", "aGFzaGtleWhhc2hrZXloYXNoa2V5aGFzaGtleQ==")


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_request(ip: str = "1.2.3.4") -> MagicMock:
    """Build a minimal fake starlette Request with a given client IP."""
    req = MagicMock()
    req.client = MagicMock()
    req.client.host = ip
    req.headers = {}
    return req


def _make_redis(current_count: int) -> AsyncMock:
    """Return a fake async Redis whose INCR always returns current_count."""
    r = AsyncMock()
    r.incr = AsyncMock(return_value=current_count)
    r.expire = AsyncMock(return_value=True)
    return r


# ── make_rate_limit_dep ───────────────────────────────────────────────────────


@pytest.mark.unit
class TestMakeRateLimitDep:
    @pytest.mark.asyncio
    async def test_allows_request_under_limit(self):
        """First request (count=1) must pass for a limit of 20/minute."""
        from Clinic_app.common.rate_limit import make_rate_limit_dep

        dep = make_rate_limit_dep("20/minute")
        req = _make_request()

        with patch("Clinic_app.common.rate_limit.get_redis", return_value=_make_redis(1)):
            result = await dep(req)  # should not raise
        assert result is None

    @pytest.mark.asyncio
    async def test_raises_429_when_limit_exceeded(self):
        """Request that pushes count above N must raise HTTP 429."""
        from fastapi import HTTPException
        from Clinic_app.common.rate_limit import make_rate_limit_dep

        dep = make_rate_limit_dep("3/minute")
        req = _make_request()

        with patch("Clinic_app.common.rate_limit.get_redis", return_value=_make_redis(4)):
            with pytest.raises(HTTPException) as exc_info:
                await dep(req)

        assert exc_info.value.status_code == 429
        assert exc_info.value.detail["code"] == "RATE_LIMIT_EXCEEDED"

    @pytest.mark.asyncio
    async def test_allows_exactly_at_limit(self):
        """Request at exactly N (not N+1) must pass."""
        from Clinic_app.common.rate_limit import make_rate_limit_dep

        dep = make_rate_limit_dep("5/minute")
        req = _make_request()

        with patch("Clinic_app.common.rate_limit.get_redis", return_value=_make_redis(5)):
            result = await dep(req)
        assert result is None

    @pytest.mark.asyncio
    async def test_fails_open_on_redis_error(self):
        """If Redis raises, request must be allowed (fail-open) with no exception."""
        from Clinic_app.common.rate_limit import make_rate_limit_dep

        dep = make_rate_limit_dep("5/minute")
        req = _make_request()

        broken_redis = AsyncMock()
        broken_redis.incr = AsyncMock(side_effect=ConnectionError("Redis down"))

        with patch("Clinic_app.common.rate_limit.get_redis", return_value=broken_redis):
            result = await dep(req)  # must not raise
        assert result is None

    @pytest.mark.asyncio
    async def test_env_var_override_read_at_request_time(self):
        """Setting RATE_LIMIT_AUTH=1/minute at runtime must be respected."""
        from fastapi import HTTPException
        from Clinic_app.common.rate_limit import make_rate_limit_dep

        dep = make_rate_limit_dep("20/minute", env_var="RATE_LIMIT_AUTH")
        req = _make_request()

        os.environ["RATE_LIMIT_AUTH"] = "1/minute"
        try:
            with patch("Clinic_app.common.rate_limit.get_redis", return_value=_make_redis(2)):
                with pytest.raises(HTTPException) as exc_info:
                    await dep(req)
            assert exc_info.value.status_code == 429
        finally:
            os.environ.pop("RATE_LIMIT_AUTH", None)

    @pytest.mark.asyncio
    async def test_ip_isolation(self):
        """Different IPs must have independent counters (different Redis keys)."""
        from Clinic_app.common.rate_limit import make_rate_limit_dep

        dep = make_rate_limit_dep("1/minute")

        call_keys: list[str] = []
        redis_mock = AsyncMock()
        redis_mock.incr = AsyncMock(side_effect=lambda k: call_keys.append(k) or 1)
        redis_mock.expire = AsyncMock(return_value=True)

        req_a = _make_request("10.0.0.1")
        req_b = _make_request("10.0.0.2")

        with patch("Clinic_app.common.rate_limit.get_redis", return_value=redis_mock):
            await dep(req_a)
            await dep(req_b)

        # Keys must differ by IP segment
        assert len(call_keys) == 2
        assert call_keys[0] != call_keys[1]
        assert "10.0.0.1" in call_keys[0]
        assert "10.0.0.2" in call_keys[1]


# ── claude_rate_limit ─────────────────────────────────────────────────────────


@pytest.mark.unit
class TestClaudeRateLimit:
    @pytest.mark.asyncio
    async def test_allows_first_call(self):
        """First call for a clinic (count=1) must return True."""
        from Clinic_app.common.claude_rate_limit import check_and_increment

        clinic_id = uuid.uuid4()
        with patch(
            "Clinic_app.common.claude_rate_limit.get_redis",
            return_value=_make_redis(1),
        ):
            os.environ["RATE_LIMIT_CLAUDE_PER_CLINIC"] = "10"
            result = await check_and_increment(clinic_id)
        assert result is True

    @pytest.mark.asyncio
    async def test_blocks_when_over_limit(self):
        """Call number 11 with a limit of 10 must return False."""
        from Clinic_app.common.claude_rate_limit import check_and_increment

        clinic_id = uuid.uuid4()
        os.environ["RATE_LIMIT_CLAUDE_PER_CLINIC"] = "10"
        with patch(
            "Clinic_app.common.claude_rate_limit.get_redis",
            return_value=_make_redis(11),
        ):
            result = await check_and_increment(clinic_id)
        assert result is False

    @pytest.mark.asyncio
    async def test_tenant_isolation(self):
        """Clinic A over limit must not affect clinic B."""
        from Clinic_app.common.claude_rate_limit import check_and_increment

        clinic_a = uuid.uuid4()
        clinic_b = uuid.uuid4()
        os.environ["RATE_LIMIT_CLAUDE_PER_CLINIC"] = "10"

        incr_counts: dict[str, int] = {}

        async def fake_incr(key: str) -> int:
            # Simulate clinic A at count=11, clinic B at count=1
            if str(clinic_a) in key:
                incr_counts[key] = 11
            else:
                incr_counts[key] = 1
            return incr_counts[key]

        redis_mock = AsyncMock()
        redis_mock.incr = fake_incr
        redis_mock.expire = AsyncMock(return_value=True)

        with patch("Clinic_app.common.claude_rate_limit.get_redis", return_value=redis_mock):
            result_a = await check_and_increment(clinic_a)
            result_b = await check_and_increment(clinic_b)

        assert result_a is False, "Clinic A should be blocked (count=11 > limit=10)"
        assert result_b is True, "Clinic B should be allowed (count=1 <= limit=10)"

    @pytest.mark.asyncio
    async def test_fails_open_on_redis_error(self):
        """Redis error must return True (fail-open) so summarization is not blocked."""
        from Clinic_app.common.claude_rate_limit import check_and_increment

        clinic_id = uuid.uuid4()
        broken_redis = AsyncMock()
        broken_redis.incr = AsyncMock(side_effect=ConnectionError("Redis down"))

        with patch("Clinic_app.common.claude_rate_limit.get_redis", return_value=broken_redis):
            result = await check_and_increment(clinic_id)
        assert result is True

    @pytest.mark.asyncio
    async def test_env_limit_read_at_call_time(self):
        """RATE_LIMIT_CLAUDE_PER_CLINIC is read at call time (not import time)."""
        from Clinic_app.common.claude_rate_limit import check_and_increment

        clinic_id = uuid.uuid4()
        os.environ["RATE_LIMIT_CLAUDE_PER_CLINIC"] = "1"
        try:
            with patch(
                "Clinic_app.common.claude_rate_limit.get_redis",
                return_value=_make_redis(2),  # count=2 > limit=1
            ):
                result = await check_and_increment(clinic_id)
            assert result is False
        finally:
            os.environ.pop("RATE_LIMIT_CLAUDE_PER_CLINIC", None)
