"""
Unit tests for EHR slot cache (playbook_cache.py).
Replaces test_selector_cache.py — AgentQL selector cache removed (HIPAA T-01).
"""

import json
import pytest
from unittest.mock import AsyncMock
from uuid import UUID

import Clinic_app.services.playbook_cache as pc


@pytest.fixture
def clinic_a() -> UUID:
    return UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


@pytest.fixture
def clinic_b() -> UUID:
    return UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


SAMPLE_SLOTS = [
    {"date": "2026-06-15", "time": "9:00 AM", "provider_name": "Dr. Smith"},
    {"date": "2026-06-15", "time": "10:00 AM", "provider_name": "Dr. Smith"},
]


@pytest.mark.unit
@pytest.mark.asyncio
class TestSlotCache:
    async def test_cache_miss_returns_none(self, clinic_a, monkeypatch):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        monkeypatch.setattr(pc, "get_redis", AsyncMock(return_value=mock_redis))

        result = await pc.get_cached_slots(clinic_a, "Dr. Smith")
        assert result is None
        mock_redis.get.assert_awaited_once_with(
            "ehr:slots:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa:dr._smith"
        )

    async def test_cache_hit_returns_slot_list(self, clinic_a, monkeypatch):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=json.dumps(SAMPLE_SLOTS).encode())
        monkeypatch.setattr(pc, "get_redis", AsyncMock(return_value=mock_redis))

        result = await pc.get_cached_slots(clinic_a, "Dr. Smith")
        assert result == SAMPLE_SLOTS

    async def test_set_cached_slots_uses_ttl(self, clinic_a, monkeypatch):
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock()
        monkeypatch.setattr(pc, "get_redis", AsyncMock(return_value=mock_redis))

        await pc.set_cached_slots(clinic_a, "Dr. Smith", SAMPLE_SLOTS)
        mock_redis.set.assert_awaited_once_with(
            "ehr:slots:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa:dr._smith",
            json.dumps(SAMPLE_SLOTS),
            ex=90,
        )

    async def test_tenant_isolation_different_keys(self, clinic_a, clinic_b, monkeypatch):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(
            side_effect=[
                json.dumps(SAMPLE_SLOTS).encode(),
                json.dumps([]).encode(),
            ]
        )
        monkeypatch.setattr(pc, "get_redis", AsyncMock(return_value=mock_redis))

        slots_a = await pc.get_cached_slots(clinic_a, "Dr. Jones")
        slots_b = await pc.get_cached_slots(clinic_b, "Dr. Jones")
        assert slots_a == SAMPLE_SLOTS
        assert slots_b == []

        calls = [c.args[0] for c in mock_redis.get.await_args_list]
        assert calls[0] != calls[1], "Different clinics must produce different cache keys"

    async def test_invalidate_clinic_ehr_cache_deletes_matching_keys(self, clinic_a, monkeypatch):
        keys = [
            b"ehr:slots:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa:dr._smith",
            b"ehr:slots:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa:dr._jones",
        ]
        mock_redis = AsyncMock()

        async def scan_iter(match=None):
            for k in keys:
                yield k

        mock_redis.scan_iter = scan_iter
        mock_redis.delete = AsyncMock(return_value=1)
        monkeypatch.setattr(pc, "get_redis", AsyncMock(return_value=mock_redis))

        n = await pc.invalidate_clinic_ehr_cache(clinic_a)
        assert n == 2
        assert mock_redis.delete.await_count == 2

    def test_ttl_constant_is_90_seconds(self):
        assert pc.SLOT_CACHE_TTL_SECONDS == 90
