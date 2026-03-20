# tests/test_campaign_service.py
"""
Unit tests for services/campaign_service.py.
DB is mocked — no real database required.
"""

import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call

from fastapi import HTTPException

from Clinic_app.data.enums import CampaignStatus, ContactStatus, GapType
from Clinic_app.services.csv_parser import ParsedRow


def _make_integration():
    ci = MagicMock()
    ci.calling_hours_start = "09:00"
    ci.calling_hours_end = "18:00"
    ci.campaign_concurrency_limit = 3
    ci.voicemail_retry_hours = 4
    ci.no_answer_retry_hours = 2
    ci.error_retry_hours = 24
    ci.max_attempts = 3
    return ci


def _make_row(phone: str = "+17875551234", gap: GapType = GapType.COLORECTAL_CANCER_SCREENING):
    return ParsedRow(
        phone_e164=phone,
        gap_type=gap,
        language="en",
        raw_row_number=2,
    )


def _make_campaign(status: str = CampaignStatus.ACTIVE.value):
    c = MagicMock()
    c.id = uuid.uuid4()
    c.clinic_id = uuid.uuid4()
    c.status = status
    c.name = "Test Campaign"
    c.measurement_year = 2026
    c.total_contacts = 10
    c.called_count = 3
    c.booked_count = 1
    c.failed_count = 0
    return c


# ── phone hashing + encryption ────────────────────────────────────────────────

@pytest.mark.unit
class TestPhoneHandling:
    def test_phone_is_hashed_not_plaintext(self):
        """Phone must be stored as SHA-256 hash, never plaintext."""
        from Clinic_app.services.campaign_service import hash_phone
        result = hash_phone("+17875551234")
        assert "+17875551234" not in result
        assert len(result) == 64  # SHA-256 hex

    def test_hash_is_deterministic(self):
        from Clinic_app.services.campaign_service import hash_phone
        assert hash_phone("+17875551234") == hash_phone("+17875551234")


# ── get_campaign ───────────────────────────────────────────────────────────────

@pytest.mark.unit
@pytest.mark.asyncio
class TestGetCampaign:
    async def test_returns_campaign_for_correct_clinic(self):
        from Clinic_app.services.campaign_service import get_campaign
        campaign = _make_campaign()
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = campaign
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await get_campaign(mock_db, campaign.clinic_id, campaign.id)
        assert result is campaign

    async def test_raises_404_for_wrong_clinic(self):
        from Clinic_app.services.campaign_service import get_campaign
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(HTTPException) as exc_info:
            await get_campaign(mock_db, uuid.uuid4(), uuid.uuid4())
        assert exc_info.value.status_code == 404

    async def test_raises_404_not_found(self):
        from Clinic_app.services.campaign_service import get_campaign
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(HTTPException) as exc_info:
            await get_campaign(mock_db, uuid.uuid4(), uuid.uuid4())
        assert exc_info.value.status_code == 404
        assert exc_info.value.detail["code"] == "CAMPAIGN_NOT_FOUND"


# ── list_campaigns ─────────────────────────────────────────────────────────────

@pytest.mark.unit
@pytest.mark.asyncio
class TestListCampaigns:
    async def test_returns_list(self):
        from Clinic_app.services.campaign_service import list_campaigns
        campaigns = [_make_campaign(), _make_campaign()]
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = campaigns
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await list_campaigns(mock_db, uuid.uuid4())
        assert result == campaigns

    async def test_empty_list_for_new_clinic(self):
        from Clinic_app.services.campaign_service import list_campaigns
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await list_campaigns(mock_db, uuid.uuid4())
        assert result == []


# ── pause_campaign ─────────────────────────────────────────────────────────────

@pytest.mark.unit
@pytest.mark.asyncio
class TestPauseCampaign:
    async def test_pause_active_campaign(self):
        from Clinic_app.services.campaign_service import pause_campaign
        campaign = _make_campaign(CampaignStatus.ACTIVE.value)
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = campaign
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        result = await pause_campaign(mock_db, campaign.clinic_id, campaign.id)
        assert result.status == CampaignStatus.PAUSED.value

    async def test_pause_already_paused_raises_409(self):
        from Clinic_app.services.campaign_service import pause_campaign
        campaign = _make_campaign(CampaignStatus.PAUSED.value)
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = campaign
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(HTTPException) as exc_info:
            await pause_campaign(mock_db, campaign.clinic_id, campaign.id)
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail["code"] == "INVALID_TRANSITION"

    async def test_pause_pending_raises_409(self):
        from Clinic_app.services.campaign_service import pause_campaign
        campaign = _make_campaign(CampaignStatus.PENDING.value)
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = campaign
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(HTTPException) as exc_info:
            await pause_campaign(mock_db, campaign.clinic_id, campaign.id)
        assert exc_info.value.status_code == 409


# ── resume_campaign ────────────────────────────────────────────────────────────

@pytest.mark.unit
@pytest.mark.asyncio
class TestResumeCampaign:
    async def test_resume_paused_campaign(self):
        from Clinic_app.services.campaign_service import resume_campaign
        campaign = _make_campaign(CampaignStatus.PAUSED.value)
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = campaign
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        result = await resume_campaign(mock_db, campaign.clinic_id, campaign.id)
        assert result.status == CampaignStatus.ACTIVE.value

    async def test_resume_active_raises_409(self):
        from Clinic_app.services.campaign_service import resume_campaign
        campaign = _make_campaign(CampaignStatus.ACTIVE.value)
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = campaign
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(HTTPException) as exc_info:
            await resume_campaign(mock_db, campaign.clinic_id, campaign.id)
        assert exc_info.value.status_code == 409


# ── cancel_campaign ────────────────────────────────────────────────────────────

@pytest.mark.unit
@pytest.mark.asyncio
class TestCancelCampaign:
    async def test_cancel_active_campaign(self):
        from Clinic_app.services.campaign_service import cancel_campaign
        campaign = _make_campaign(CampaignStatus.ACTIVE.value)
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = campaign
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        result = await cancel_campaign(mock_db, campaign.clinic_id, campaign.id)
        assert result.status == CampaignStatus.CANCELED.value

    async def test_cancel_already_canceled_raises_409(self):
        from Clinic_app.services.campaign_service import cancel_campaign
        campaign = _make_campaign(CampaignStatus.CANCELED.value)
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = campaign
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(HTTPException) as exc_info:
            await cancel_campaign(mock_db, campaign.clinic_id, campaign.id)
        assert exc_info.value.status_code == 409

    async def test_cancel_completed_raises_409(self):
        from Clinic_app.services.campaign_service import cancel_campaign
        campaign = _make_campaign(CampaignStatus.COMPLETED.value)
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = campaign
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(HTTPException) as exc_info:
            await cancel_campaign(mock_db, campaign.clinic_id, campaign.id)
        assert exc_info.value.status_code == 409
