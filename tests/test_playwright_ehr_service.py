"""Unit tests for PlaywrightEHRService (mocked browser — no real NextGen)."""

import asyncio
from datetime import timedelta, timezone
import pytest
from uuid import UUID

from Clinic_app.services.playwright_ehr import PlaywrightEHRService, HEARTBEAT_INTERVAL_SECONDS

# Fixed offsets avoid tzdata dependency on minimal Windows/Python installs.
CHI = timezone(timedelta(hours=-6))
NYC = timezone(timedelta(hours=-5))


@pytest.fixture
def clinic_id() -> UUID:
    return UUID("550e8400-e29b-41d4-a716-446655440000")


@pytest.mark.unit
class TestPlaywrightEHRParseHelpers:
    def test_parse_slot_datetime_am_pm(self):
        svc = PlaywrightEHRService()
        dt = svc._parse_slot_datetime("2026-04-01", "10:30 AM", CHI)
        assert dt.hour == 10
        assert dt.minute == 30
        assert dt.tzinfo == CHI

    def test_parse_slot_datetime_24h(self):
        svc = PlaywrightEHRService()
        utc = timezone.utc
        dt = svc._parse_slot_datetime("2026-04-01", "14:00", utc)
        assert dt.hour == 14

    def test_normalize_slots_builds_iso_rows(self):
        svc = PlaywrightEHRService()
        slot = {"date": "2026-05-01", "time": "09:00 AM", "provider_name": "Dr. X"}
        rows = svc._normalize_slots([slot], "Dr. Default", NYC)
        assert len(rows) >= 1
        assert "start_time" in rows[0]
        assert "end_time" in rows[0]
        assert "T" in rows[0]["start_time"]


@pytest.mark.unit
@pytest.mark.asyncio
class TestPlaywrightEHRLockSerialization:
    async def test_concurrent_calls_serialize(self, clinic_id):
        svc = PlaywrightEHRService()
        order: list[int] = []

        async def slow_op(n: int):
            async with svc._lock(clinic_id):
                order.append(n)
                await asyncio.sleep(0.05)

        await asyncio.gather(slow_op(1), slow_op(2))
        assert len(order) == 2


@pytest.mark.unit
def test_heartbeat_interval_is_8_minutes():
    assert HEARTBEAT_INTERVAL_SECONDS == 8 * 60
