"""Unit tests for campaign_worker helpers and manager."""

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from Clinic_app.workers import campaign_worker


@pytest.mark.unit
def test_mask_phone_e164() -> None:
    assert campaign_worker._mask_phone_e164("+17875551234").endswith("1234")
    assert "+1787" not in campaign_worker._mask_phone_e164("+17875551234")


@pytest.mark.unit
def test_is_within_calling_hours_typical_day() -> None:
    integ = MagicMock()
    integ.timezone = "UTC"
    with patch.object(campaign_worker, "_local_now", return_value=MagicMock()):
        # Mock now.time() via replacing _local_now return
        pass

    # Direct time check: patch _local_now to return datetime with fixed time
    from datetime import datetime, timezone as tz

    class FakeInteg:
        timezone = "UTC"

    noon = datetime(2026, 6, 1, 12, 0, 0, tzinfo=tz.utc)
    with patch.object(campaign_worker, "_local_now", return_value=noon):
        assert campaign_worker._is_within_calling_hours(FakeInteg(), "09:00", "18:00") is True

    night = datetime(2026, 6, 1, 20, 0, 0, tzinfo=tz.utc)
    with patch.object(campaign_worker, "_local_now", return_value=night):
        assert campaign_worker._is_within_calling_hours(FakeInteg(), "09:00", "18:00") is False


@pytest.mark.asyncio
@pytest.mark.unit
async def test_manager_start_idempotent() -> None:
    m = campaign_worker.CampaignWorkerManager()
    cid = uuid.uuid4()

    async def noop_loop(_: uuid.UUID) -> None:
        return None

    with patch.object(campaign_worker, "_clinic_worker_loop", side_effect=noop_loop):
        await m.start_clinic_worker(cid)
        await m.start_clinic_worker(cid)
        assert len(m._tasks) == 1
        await m.shutdown_all()
