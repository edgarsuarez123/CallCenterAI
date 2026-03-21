"""Unit tests for AgentQL selector Redis cache (Feature 5)."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

from Clinic_app.services import selector_cache as sc


@pytest.fixture
def clinic_a() -> UUID:
    return UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


@pytest.fixture
def clinic_b() -> UUID:
    return UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


@pytest.mark.unit
@pytest.mark.asyncio
class TestSelectorCache:
    async def test_cache_miss_returns_none(self, clinic_a):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        with patch("Clinic_app.services.selector_cache.get_redis", AsyncMock(return_value=mock_redis)):
            assert await sc.get_cached_selector(clinic_a, "appointment_slot_grid") is None
        mock_redis.get.assert_awaited_once_with(
            "agentql:selector:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa:appointment_slot_grid"
        )

    async def test_cache_hit_returns_value(self, clinic_a):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value="#slot-grid > div.row")

        with patch("Clinic_app.services.selector_cache.get_redis", AsyncMock(return_value=mock_redis)):
            out = await sc.get_cached_selector(clinic_a, "login_form")
        assert out == "#slot-grid > div.row"

    async def test_set_cached_selector_uses_ttl(self, clinic_a):
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock()

        with patch("Clinic_app.services.selector_cache.get_redis", AsyncMock(return_value=mock_redis)):
            await sc.set_cached_selector(clinic_a, "login_form", "css >> .login")

        mock_redis.set.assert_awaited_once_with(
            "agentql:selector:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa:login_form",
            "css >> .login",
            ex=86_400,
        )

    async def test_tenant_isolation_different_keys(self, clinic_a, clinic_b):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(side_effect=["sel-a", "sel-b"])

        with patch("Clinic_app.services.selector_cache.get_redis", AsyncMock(return_value=mock_redis)):
            a = await sc.get_cached_selector(clinic_a, "grid")
            b = await sc.get_cached_selector(clinic_b, "grid")
        assert a == "sel-a"
        assert b == "sel-b"
        assert mock_redis.get.await_count == 2
        calls = [c.args[0] for c in mock_redis.get.await_args_list]
        assert calls[0] != calls[1]

    async def test_invalidate_clinic_selectors_deletes_matching_keys(self, clinic_a):
        keys = [
            b"agentql:selector:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa:grid",
            b"agentql:selector:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa:form",
        ]
        mock_redis = AsyncMock()

        async def scan_iter(match=None):
            for k in keys:
                yield k

        mock_redis.scan_iter = scan_iter
        mock_redis.delete = AsyncMock(return_value=1)

        with patch("Clinic_app.services.selector_cache.get_redis", AsyncMock(return_value=mock_redis)):
            n = await sc.invalidate_clinic_selectors(clinic_a)

        assert n == 2
        assert mock_redis.delete.await_count == 2

    def test_ttl_constant_matches_prd(self):
        assert sc.SELECTOR_CACHE_TTL_SECONDS == 24 * 60 * 60
