"""
Tests for campaign service — create, upload CSV, start/pause, report generation,
and demo-mode call simulation.

All tests use mocked DB sessions (no real database required).
"""

import hashlib
import io
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from Clinic_app.data.enums import CampaignStatus, ContactOutcome


# ============================================================================
# HELPERS
# ============================================================================

def _make_campaign(status=CampaignStatus.DRAFT, total=0, completed=0):
    campaign = MagicMock()
    campaign.id = uuid.uuid4()
    campaign.clinic_id = uuid.uuid4()
    campaign.name = "Test Campaign"
    campaign.reason = "Annual visit overdue"
    campaign.status = status
    campaign.total_contacts = total
    campaign.completed_contacts = completed
    campaign.created_at = datetime.now(timezone.utc)
    campaign.updated_at = datetime.now(timezone.utc)
    return campaign


def _make_contact(outcome=ContactOutcome.PENDING, campaign_id=None, clinic_id=None):
    c = MagicMock()
    c.id = uuid.uuid4()
    c.campaign_id = campaign_id or uuid.uuid4()
    c.clinic_id = clinic_id or uuid.uuid4()
    c.outcome = outcome
    c.attempt_count = 0
    c.created_at = datetime.now(timezone.utc)
    c.updated_at = datetime.now(timezone.utc)
    return c


def _make_result(scalar_result=None, scalars_result=None):
    """Build a mock SQLAlchemy result with sync scalar_one_or_none / scalars().all()."""
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=scalar_result)
    scalars_mock = MagicMock()
    scalars_mock.all = MagicMock(return_value=scalars_result or [])
    result.scalars = MagicMock(return_value=scalars_mock)
    return result


def _make_db(scalar_result=None, scalars_result=None):
    db = AsyncMock()
    result_mock = _make_result(scalar_result, scalars_result)
    db.execute = AsyncMock(return_value=result_mock)
    return db


# ============================================================================
# PHONE NORMALIZATION HELPERS
# ============================================================================

@pytest.mark.unit
class TestPhoneHelpers:
    def test_normalize_us_phone(self):
        from Clinic_app.services.campaign import _normalize_phone
        assert _normalize_phone("+17875550101") == "+17875550101"
        assert _normalize_phone("787-555-0101") == "+17875550101"
        assert _normalize_phone("7875550101") == "+17875550101"

    def test_normalize_invalid_phone(self):
        from Clinic_app.services.campaign import _normalize_phone
        assert _normalize_phone("not-a-phone") is None
        assert _normalize_phone("123") is None
        assert _normalize_phone("") is None

    def test_hash_phone_deterministic(self):
        from Clinic_app.services.campaign import _hash_phone
        h1 = _hash_phone("+17875550101")
        h2 = _hash_phone("+17875550101")
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex

    def test_hash_phone_different_inputs(self):
        from Clinic_app.services.campaign import _hash_phone
        h1 = _hash_phone("+17875550101")
        h2 = _hash_phone("+17875550102")
        assert h1 != h2

    def test_mask_phone(self):
        from Clinic_app.services.campaign import _mask_phone
        assert _mask_phone("+17875550101") == "***-***-0101"
        assert _mask_phone("+11234567890") == "***-***-7890"


# ============================================================================
# CAMPAIGN CRUD
# ============================================================================

@pytest.mark.unit
class TestCreateCampaign:
    @pytest.mark.asyncio
    async def test_creates_campaign(self):
        from Clinic_app.services.campaign import create_campaign

        db = AsyncMock()
        campaign_mock = MagicMock()
        campaign_mock.id = uuid.uuid4()
        db.refresh = AsyncMock()
        db.flush = AsyncMock()
        db.add = MagicMock()

        # Capture what was added to db
        added_obj = None
        def capture_add(obj):
            nonlocal added_obj
            added_obj = obj
        db.add.side_effect = capture_add

        async def mock_refresh(obj):
            pass
        db.refresh.side_effect = mock_refresh

        clinic_id = uuid.uuid4()
        result = await create_campaign(db, clinic_id, "Test", "Test reason")

        db.add.assert_called_once()
        assert added_obj.name == "Test"
        assert added_obj.reason == "Test reason"
        assert added_obj.clinic_id == clinic_id
        assert added_obj.status == CampaignStatus.DRAFT

    @pytest.mark.asyncio
    async def test_get_campaign_returns_none_for_wrong_clinic(self):
        from Clinic_app.services.campaign import get_campaign

        db = _make_db(scalar_result=None)
        result = await get_campaign(db, uuid.uuid4(), uuid.uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_list_campaigns_returns_list(self):
        from Clinic_app.services.campaign import list_campaigns

        campaigns = [_make_campaign(), _make_campaign()]
        db = _make_db(scalars_result=campaigns)
        # list_campaigns uses scalars().all()
        result = await list_campaigns(db, uuid.uuid4())
        assert len(result) == 2


@pytest.mark.unit
class TestCampaignStateTransitions:
    @pytest.mark.asyncio
    async def test_start_campaign_from_draft(self):
        from Clinic_app.services.campaign import start_campaign

        campaign = _make_campaign(status=CampaignStatus.DRAFT, total=5)
        db = AsyncMock()
        # start_campaign calls get_campaign internally which calls db.execute once
        db.execute = AsyncMock(return_value=_make_result(scalar_result=campaign))
        db.flush = AsyncMock()

        result, error = await start_campaign(db, campaign.id, campaign.clinic_id)
        assert error is None
        assert campaign.status == CampaignStatus.QUEUED

    @pytest.mark.asyncio
    async def test_start_campaign_with_no_contacts_fails(self):
        from Clinic_app.services.campaign import start_campaign

        campaign = _make_campaign(status=CampaignStatus.DRAFT, total=0)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_result(scalar_result=campaign))
        db.flush = AsyncMock()

        result, error = await start_campaign(db, campaign.id, campaign.clinic_id)
        assert result is None
        assert "no contacts" in error.lower()

    @pytest.mark.asyncio
    async def test_start_campaign_not_found(self):
        from Clinic_app.services.campaign import start_campaign

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_result(scalar_result=None))

        result, error = await start_campaign(db, uuid.uuid4(), uuid.uuid4())
        assert result is None
        assert "not found" in error.lower()

    @pytest.mark.asyncio
    async def test_pause_running_campaign(self):
        from Clinic_app.services.campaign import pause_campaign

        campaign = _make_campaign(status=CampaignStatus.RUNNING)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_result(scalar_result=campaign))
        db.flush = AsyncMock()

        result, error = await pause_campaign(db, campaign.id, campaign.clinic_id)
        assert error is None
        assert campaign.status == CampaignStatus.PAUSED

    @pytest.mark.asyncio
    async def test_pause_completed_campaign_fails(self):
        from Clinic_app.services.campaign import pause_campaign

        campaign = _make_campaign(status=CampaignStatus.COMPLETED)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_result(scalar_result=campaign))
        db.flush = AsyncMock()

        result, error = await pause_campaign(db, campaign.id, campaign.clinic_id)
        assert result is None
        assert error is not None


# ============================================================================
# CSV UPLOAD
# ============================================================================

@pytest.mark.unit
class TestUploadContacts:
    def _make_csv(self, rows: list[dict]) -> bytes:
        lines = ["patient_name,phone,reason"]
        for r in rows:
            lines.append(f"{r['name']},{r['phone']},{r.get('reason', 'Test reason')}")
        return "\n".join(lines).encode("utf-8")

    def _make_multi_execute(self, campaign, hashes=None):
        """Return an async execute side_effect: call 1=campaign, call 2=phone hashes."""
        hashes = hashes or []
        call_count = 0

        async def multi_execute(query):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_result(scalar_result=campaign)
            else:
                return _make_result(scalars_result=hashes)
        return multi_execute

    @pytest.mark.asyncio
    async def test_upload_valid_csv(self):
        from Clinic_app.services.campaign import upload_contacts

        campaign = _make_campaign(status=CampaignStatus.DRAFT, total=0)

        db = AsyncMock()
        db.flush = AsyncMock()
        db.add_all = MagicMock()
        db.execute.side_effect = self._make_multi_execute(campaign)

        csv_content = self._make_csv([
            {"name": "Maria Garcia", "phone": "+17875550101"},
            {"name": "James Wilson", "phone": "+17875550102"},
        ])

        with patch("Clinic_app.services.campaign.encrypt_phi", return_value=b"encrypted"):
            result = await upload_contacts(db, campaign.id, campaign.clinic_id, csv_content, "Default reason")

        assert result["imported"] == 2
        assert result["duplicates_skipped"] == 0
        assert result["invalid_rows"] == 0

    @pytest.mark.asyncio
    async def test_upload_invalid_phone_skipped(self):
        from Clinic_app.services.campaign import upload_contacts

        campaign = _make_campaign(status=CampaignStatus.DRAFT, total=0)

        db = AsyncMock()
        db.flush = AsyncMock()
        db.add_all = MagicMock()
        db.execute.side_effect = self._make_multi_execute(campaign)

        csv_content = self._make_csv([
            {"name": "Valid Person", "phone": "+17875550101"},
            {"name": "Bad Phone",   "phone": "not-a-phone"},
        ])

        with patch("Clinic_app.services.campaign.encrypt_phi", return_value=b"encrypted"):
            result = await upload_contacts(db, campaign.id, campaign.clinic_id, csv_content, "reason")

        assert result["imported"] == 1
        assert result["invalid_rows"] == 1
        assert len(result["errors"]) == 1

    @pytest.mark.asyncio
    async def test_upload_deduplicates_phone(self):
        from Clinic_app.services.campaign import upload_contacts, _hash_phone

        campaign = _make_campaign(status=CampaignStatus.DRAFT, total=0)
        existing_hash = _hash_phone("+17875550101")

        db = AsyncMock()
        db.flush = AsyncMock()
        db.add_all = MagicMock()
        db.execute.side_effect = self._make_multi_execute(campaign, hashes=[existing_hash])

        csv_content = self._make_csv([
            {"name": "Duplicate Person", "phone": "+17875550101"},
            {"name": "New Person",       "phone": "+17875550102"},
        ])

        with patch("Clinic_app.services.campaign.encrypt_phi", return_value=b"encrypted"):
            result = await upload_contacts(db, campaign.id, campaign.clinic_id, csv_content, "reason")

        assert result["imported"] == 1
        assert result["duplicates_skipped"] == 1

    @pytest.mark.asyncio
    async def test_upload_to_running_campaign_fails(self):
        from Clinic_app.services.campaign import upload_contacts

        campaign = _make_campaign(status=CampaignStatus.RUNNING)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_result(scalar_result=campaign))

        result = await upload_contacts(db, campaign.id, campaign.clinic_id, b"csv", "reason")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_upload_missing_phone_column_fails(self):
        from Clinic_app.services.campaign import upload_contacts

        campaign = _make_campaign(status=CampaignStatus.DRAFT)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_result(scalar_result=campaign))

        # CSV missing phone column
        csv = b"patient_name,reason\nMaria,test\n"
        result = await upload_contacts(db, campaign.id, campaign.clinic_id, csv, "reason")
        assert "error" in result
        assert "phone" in result["error"].lower()


# ============================================================================
# REPORT GENERATION
# ============================================================================

@pytest.mark.unit
class TestGetCampaignReport:
    @pytest.mark.asyncio
    async def test_report_returns_none_for_missing_campaign(self):
        from Clinic_app.services.campaign import get_campaign_report

        db = AsyncMock()
        # First execute (get_campaign) returns None
        db.execute = AsyncMock(return_value=_make_result(scalar_result=None))
        campaign, rows = await get_campaign_report(db, uuid.uuid4(), uuid.uuid4())
        assert campaign is None
        assert rows == []

    @pytest.mark.asyncio
    async def test_report_decrypts_names(self):
        from Clinic_app.services.campaign import get_campaign_report

        campaign = _make_campaign()
        contact = MagicMock()
        contact.id = uuid.uuid4()
        contact.patient_name_encrypted = b"encrypted_name"
        contact.phone_encrypted = b"encrypted_phone"
        contact.reason = "Annual visit"
        contact.outcome = "accepted"
        contact.call_date = datetime.now(timezone.utc)
        contact.call_duration_seconds = 90
        contact.attempt_count = 1
        contact.notes = "Patient agreed"
        contact.retell_call_id = "call_123"
        contact.created_at = datetime.now(timezone.utc)

        call_count = 0
        db = AsyncMock()

        async def multi_execute(query):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_result(scalar_result=campaign)
            else:
                return _make_result(scalars_result=[contact])
        db.execute.side_effect = multi_execute

        with patch("Clinic_app.services.campaign.decrypt_phi") as mock_decrypt:
            mock_decrypt.side_effect = ["Maria Garcia", "+17875550101"]
            _, rows = await get_campaign_report(db, campaign.id, campaign.clinic_id)

        assert len(rows) == 1
        assert rows[0]["patient_name"] == "Maria Garcia"
        assert rows[0]["phone_last4"] == "***-***-0101"
        assert rows[0]["outcome"] == "accepted"


# ============================================================================
# DEMO MODE SIMULATION
# ============================================================================

@pytest.mark.unit
class TestSimulateNextCall:
    @pytest.mark.asyncio
    async def test_simulate_returns_no_pending_when_empty(self):
        from Clinic_app.services.campaign import simulate_next_call

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_result(scalar_result=None))
        db.flush = AsyncMock()
        result = await simulate_next_call(db, uuid.uuid4(), uuid.uuid4())
        assert result["status"] == "no_pending_contacts"

    @pytest.mark.asyncio
    async def test_simulate_records_outcome(self):
        from Clinic_app.services.campaign import simulate_next_call

        campaign_id = uuid.uuid4()
        clinic_id = uuid.uuid4()

        # Use a spec-less MagicMock so attribute setting works
        contact = MagicMock(spec=None)
        contact.id = uuid.uuid4()
        contact.campaign_id = campaign_id
        contact.clinic_id = clinic_id
        contact.outcome = ContactOutcome.PENDING
        contact.attempt_count = 0
        contact.patient_name_encrypted = b"encrypted"
        contact.created_at = datetime.now(timezone.utc)
        contact.updated_at = datetime.now(timezone.utc)

        campaign = MagicMock(spec=None)
        campaign.id = campaign_id
        campaign.status = CampaignStatus.RUNNING
        campaign.total_contacts = 5
        campaign.completed_contacts = 2
        campaign.updated_at = datetime.now(timezone.utc)

        db = AsyncMock()
        call_count = 0

        async def multi_execute(query):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # get_next_pending_contact
                return _make_result(scalar_result=contact)
            elif call_count == 2:
                # record_outcome contact lookup
                return _make_result(scalar_result=contact)
            else:
                # record_outcome campaign lookup
                return _make_result(scalar_result=campaign)
        db.execute.side_effect = multi_execute
        db.flush = AsyncMock()

        with patch("Clinic_app.services.campaign.decrypt_phi", return_value="Test Patient"):
            result = await simulate_next_call(db, campaign_id, clinic_id)

        assert result["status"] == "processed"
        assert result["demo_mode"] is True
        assert result["outcome"] in ["accepted", "declined", "voicemail", "no_answer", "failed"]
        assert result["patient_name"] == "Test Patient"
