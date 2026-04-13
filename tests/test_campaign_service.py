# tests/test_campaign_service.py
"""
Unit tests for services/campaign_service.py.
DB is mocked — no real database required.
"""

import base64
import os
import uuid
from datetime import datetime, timezone

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call

import Clinic_app.common.encryption as encryption_module

_TEST_HASH_KEY = base64.b64encode(os.urandom(32)).decode()


@pytest.fixture(autouse=True)
def reset_hash_key():
    """Inject PHI_HASH_KEY and reset cache for every test in this module."""
    encryption_module._hash_key = None
    with patch.dict(os.environ, {"PHI_HASH_KEY": _TEST_HASH_KEY}):
        yield
    encryption_module._hash_key = None

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


def _make_row(phone: str = "+17875551234", gap: GapType = GapType.COLORECTAL):
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
    c.calling_hours_start = "09:00"
    c.calling_hours_end = "18:00"
    c.campaign_concurrency_limit = 3
    c.voicemail_retry_hours = 4
    c.no_answer_retry_hours = 2
    c.error_retry_hours = 24
    c.max_attempts = 3
    return c


def _make_clinic_integration_mock(
    *,
    calling_hours_start: str = "10:00",
    calling_hours_end: str = "19:00",
):
    """Matches fields read by _apply_clinic_operational_defaults_to_campaign."""
    m = MagicMock()
    m.calling_hours_start = calling_hours_start
    m.calling_hours_end = calling_hours_end
    m.campaign_concurrency_limit = 5
    m.voicemail_retry_hours = 4
    m.no_answer_retry_hours = 2
    m.error_retry_hours = 24
    m.max_attempts = 3
    return m


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
        camp_res = MagicMock()
        camp_res.scalar_one_or_none.return_value = campaign
        integ = _make_clinic_integration_mock()
        integ_res = MagicMock()
        integ_res.scalar_one_or_none.return_value = integ
        mock_db.execute = AsyncMock(side_effect=[camp_res, integ_res])
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        result = await resume_campaign(mock_db, campaign.clinic_id, campaign.id)
        assert result.status == CampaignStatus.ACTIVE.value
        assert campaign.calling_hours_start == integ.calling_hours_start

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


# ── start_campaign ─────────────────────────────────────────────────────────────

@pytest.mark.unit
@pytest.mark.asyncio
class TestStartCampaign:
    async def test_start_pending_with_verified_ehr(self):
        from Clinic_app.services.campaign_service import start_campaign

        campaign = _make_campaign(CampaignStatus.PENDING.value)
        ehr = MagicMock()
        ehr.connection_verified_at = datetime.now(timezone.utc)

        mock_db = AsyncMock()
        camp_res = MagicMock()
        camp_res.scalar_one_or_none.return_value = campaign
        ehr_res = MagicMock()
        ehr_res.scalar_one_or_none.return_value = ehr
        integ = _make_clinic_integration_mock()
        integ_res = MagicMock()
        integ_res.scalar_one_or_none.return_value = integ
        mock_db.execute = AsyncMock(side_effect=[camp_res, ehr_res, integ_res])
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        with patch.dict(
            os.environ,
            {"ALLOW_CAMPAIGN_START_WITHOUT_EHR": "false"},
            clear=False,
        ):
            out = await start_campaign(mock_db, campaign.clinic_id, campaign.id)
        assert out.status == CampaignStatus.ACTIVE.value
        assert campaign.calling_hours_start == integ.calling_hours_start
        assert campaign.calling_hours_end == integ.calling_hours_end
        assert campaign.campaign_concurrency_limit == integ.campaign_concurrency_limit

    async def test_start_from_canceled_with_verified_ehr(self):
        from Clinic_app.services.campaign_service import start_campaign

        campaign = _make_campaign(CampaignStatus.CANCELED.value)
        ehr = MagicMock()
        ehr.connection_verified_at = datetime.now(timezone.utc)

        mock_db = AsyncMock()
        camp_res = MagicMock()
        camp_res.scalar_one_or_none.return_value = campaign
        ehr_res = MagicMock()
        ehr_res.scalar_one_or_none.return_value = ehr
        integ = _make_clinic_integration_mock()
        integ_res = MagicMock()
        integ_res.scalar_one_or_none.return_value = integ
        mock_db.execute = AsyncMock(side_effect=[camp_res, ehr_res, integ_res])
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        with patch.dict(
            os.environ,
            {"ALLOW_CAMPAIGN_START_WITHOUT_EHR": "false"},
            clear=False,
        ):
            out = await start_campaign(mock_db, campaign.clinic_id, campaign.id)
        assert out.status == CampaignStatus.ACTIVE.value

    async def test_start_without_ehr_raises_422(self):
        from Clinic_app.services.campaign_service import start_campaign

        campaign = _make_campaign(CampaignStatus.PENDING.value)
        mock_db = AsyncMock()
        camp_res = MagicMock()
        camp_res.scalar_one_or_none.return_value = campaign
        ehr_res = MagicMock()
        ehr_res.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(side_effect=[camp_res, ehr_res])

        with patch.dict(
            os.environ,
            {
                "APP_ENVIRONMENT": "development",
                "ALLOW_CAMPAIGN_START_WITHOUT_EHR": "false",
            },
            clear=False,
        ):
            with pytest.raises(HTTPException) as exc_info:
                await start_campaign(mock_db, campaign.clinic_id, campaign.id)
        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "EHR_NOT_VERIFIED"

    async def test_start_without_ehr_allowed_when_dev_flag_set(self):
        from Clinic_app.services.campaign_service import start_campaign

        campaign = _make_campaign(CampaignStatus.PENDING.value)
        mock_db = AsyncMock()
        camp_res = MagicMock()
        camp_res.scalar_one_or_none.return_value = campaign
        integ = _make_clinic_integration_mock()
        integ_res = MagicMock()
        integ_res.scalar_one_or_none.return_value = integ
        mock_db.execute = AsyncMock(side_effect=[camp_res, integ_res])
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        with patch.dict(
            os.environ,
            {
                "APP_ENVIRONMENT": "development",
                "ALLOW_CAMPAIGN_START_WITHOUT_EHR": "true",
            },
            clear=False,
        ):
            out = await start_campaign(mock_db, campaign.clinic_id, campaign.id)
        assert out.status == CampaignStatus.ACTIVE.value
        assert mock_db.execute.await_count == 2

    async def test_start_without_ehr_still_enforced_in_production_with_flag(self):
        from Clinic_app.services.campaign_service import start_campaign

        campaign = _make_campaign(CampaignStatus.PENDING.value)
        mock_db = AsyncMock()
        camp_res = MagicMock()
        camp_res.scalar_one_or_none.return_value = campaign
        ehr_res = MagicMock()
        ehr_res.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(side_effect=[camp_res, ehr_res])

        with patch.dict(
            os.environ,
            {
                "APP_ENVIRONMENT": "production",
                "ALLOW_CAMPAIGN_START_WITHOUT_EHR": "true",
            },
            clear=False,
        ):
            with pytest.raises(HTTPException) as exc_info:
                await start_campaign(mock_db, campaign.clinic_id, campaign.id)
        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "EHR_NOT_VERIFIED"

    async def test_start_active_raises_409(self):
        from Clinic_app.services.campaign_service import start_campaign

        campaign = _make_campaign(CampaignStatus.ACTIVE.value)
        mock_db = AsyncMock()
        camp_res = MagicMock()
        camp_res.scalar_one_or_none.return_value = campaign
        mock_db.execute = AsyncMock(return_value=camp_res)

        with pytest.raises(HTTPException) as exc_info:
            await start_campaign(mock_db, campaign.clinic_id, campaign.id)
        assert exc_info.value.status_code == 409

    async def test_start_paused_raises_409(self):
        from Clinic_app.services.campaign_service import start_campaign

        campaign = _make_campaign(CampaignStatus.PAUSED.value)
        mock_db = AsyncMock()
        camp_res = MagicMock()
        camp_res.scalar_one_or_none.return_value = campaign
        mock_db.execute = AsyncMock(return_value=camp_res)

        with pytest.raises(HTTPException) as exc_info:
            await start_campaign(mock_db, campaign.clinic_id, campaign.id)
        assert exc_info.value.status_code == 409
        assert "resume" in exc_info.value.detail["message"].lower()


# ── get_next_eligible_contact ─────────────────────────────────────────────────

@pytest.mark.unit
@pytest.mark.asyncio
class TestGetNextEligibleContact:
    async def test_returns_contact_when_found(self):
        from Clinic_app.services.campaign_service import get_next_eligible_contact

        contact = MagicMock()
        mock_db = AsyncMock()
        res = MagicMock()
        res.scalar_one_or_none.return_value = contact
        mock_db.execute = AsyncMock(return_value=res)

        out = await get_next_eligible_contact(mock_db, uuid.uuid4())
        assert out is contact

    async def test_returns_none_when_empty(self):
        from Clinic_app.services.campaign_service import get_next_eligible_contact

        mock_db = AsyncMock()
        res = MagicMock()
        res.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=res)

        out = await get_next_eligible_contact(mock_db, uuid.uuid4())
        assert out is None
