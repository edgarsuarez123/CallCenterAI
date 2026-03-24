# tests/test_measurement_year_dedup.py
"""
Unit tests for the cross-campaign dedup logic in campaign_service.
Tests the _find_duplicate_contact function and the create_campaign dedup behavior.
All DB calls are mocked.
"""

import hashlib
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from Clinic_app.data.enums import ContactStatus, GapType
from Clinic_app.services.campaign_service import (
    hash_phone,
    _DEDUP_BLOCK_STATUSES,
    _TERMINAL_STATUSES,
    _ACTIVE_STATUSES,
)


# ── hash_phone ─────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestHashPhone:
    def test_sha256_of_e164(self):
        phone = "+17875551234"
        expected = hashlib.sha256(phone.encode("utf-8")).hexdigest()
        assert hash_phone(phone) == expected

    def test_different_phones_different_hashes(self):
        assert hash_phone("+17875551234") != hash_phone("+17875559999")

    def test_same_phone_same_hash(self):
        assert hash_phone("+17875551234") == hash_phone("+17875551234")

    def test_hash_is_64_hex_chars(self):
        result = hash_phone("+17875551234")
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)


# ── Dedup status sets ──────────────────────────────────────────────────────────

@pytest.mark.unit
class TestDedupStatusSets:
    def test_booked_is_in_dedup_block(self):
        assert ContactStatus.BOOKED.value in _DEDUP_BLOCK_STATUSES

    def test_exhausted_is_in_dedup_block(self):
        assert ContactStatus.EXHAUSTED.value in _DEDUP_BLOCK_STATUSES

    def test_declined_is_in_dedup_block(self):
        assert ContactStatus.DECLINED.value in _DEDUP_BLOCK_STATUSES

    def test_pending_is_in_dedup_block(self):
        assert ContactStatus.PENDING.value in _DEDUP_BLOCK_STATUSES

    def test_calling_is_in_dedup_block(self):
        assert ContactStatus.CALLING.value in _DEDUP_BLOCK_STATUSES

    def test_dedup_block_covers_all_relevant_statuses(self):
        # Dedup blocks re-upload when any prior contact is terminal or still active
        expected = _TERMINAL_STATUSES | _ACTIVE_STATUSES
        assert _DEDUP_BLOCK_STATUSES == expected


# ── create_campaign dedup behavior ────────────────────────────────────────────

@pytest.mark.unit
@pytest.mark.asyncio
class TestCreateCampaignDedup:
    """
    Tests for the dedup logic inside create_campaign.
    Uses a mock DB that simulates existing contacts.
    """

    def _make_parsed_row(self, phone: str, gap_type: GapType = GapType.COLORECTAL):
        from Clinic_app.services.csv_parser import ParsedRow
        return ParsedRow(
            phone_e164=phone,
            gap_type=gap_type,
            language="en",
            raw_row_number=2,
        )

    def _make_clinic_integration(self):
        ci = MagicMock()
        ci.calling_hours_start = "09:00"
        ci.calling_hours_end = "18:00"
        ci.campaign_concurrency_limit = 3
        ci.voicemail_retry_hours = 4
        ci.no_answer_retry_hours = 2
        ci.error_retry_hours = 24
        ci.max_attempts = 3
        return ci

    async def test_same_phone_gap_year_is_skipped(self):
        """A contact with the same phone+gap+year should be skipped."""
        existing_contact = MagicMock()
        existing_contact.status = ContactStatus.PENDING.value

        mock_db = AsyncMock()
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.add = MagicMock()

        # Simulate dedup check returning an existing contact
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_contact
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("Clinic_app.services.campaign_service._find_duplicate_contact",
                   new=AsyncMock(return_value=existing_contact)):
            from Clinic_app.services.campaign_service import create_campaign
            result = await create_campaign(
                db=mock_db,
                clinic_id=uuid.uuid4(),
                staff_id=None,
                name="Test Campaign",
                measurement_year=2026,
                parsed_rows=[self._make_parsed_row("+17875551234")],
                clinic_integration=self._make_clinic_integration(),
            )

        assert result.total_contacts == 0
        assert len(result.skipped_contacts) == 1
        assert result.skipped_contacts[0].reason == "already_active"

    async def test_booked_contact_gives_already_booked_reason(self):
        existing_contact = MagicMock()
        existing_contact.status = ContactStatus.BOOKED.value

        mock_db = AsyncMock()
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.add = MagicMock()

        with patch("Clinic_app.services.campaign_service._find_duplicate_contact",
                   new=AsyncMock(return_value=existing_contact)):
            from Clinic_app.services.campaign_service import create_campaign
            result = await create_campaign(
                db=mock_db,
                clinic_id=uuid.uuid4(),
                staff_id=None,
                name="Test",
                measurement_year=2026,
                parsed_rows=[self._make_parsed_row("+17875551234")],
                clinic_integration=self._make_clinic_integration(),
            )

        assert result.skipped_contacts[0].reason == "already_booked"

    async def test_no_duplicate_creates_contact(self):
        """When no duplicate exists, the contact should be created."""
        mock_db = AsyncMock()
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.add = MagicMock()

        with patch("Clinic_app.services.campaign_service._find_duplicate_contact",
                   new=AsyncMock(return_value=None)), \
             patch("Clinic_app.services.campaign_service.encrypt_phi",
                   return_value=b"encrypted"):
            from Clinic_app.services.campaign_service import create_campaign
            result = await create_campaign(
                db=mock_db,
                clinic_id=uuid.uuid4(),
                staff_id=None,
                name="Test",
                measurement_year=2026,
                parsed_rows=[self._make_parsed_row("+17875551234")],
                clinic_integration=self._make_clinic_integration(),
            )

        assert result.total_contacts == 1
        assert len(result.skipped_contacts) == 0

    async def test_different_gap_type_not_skipped(self):
        """Same phone + different gap_type = different obligation → not skipped."""
        call_count = 0

        async def no_dup_for_second(db, clinic_id, phone_hash, gap_type, year):
            # Only the first gap_type has an existing contact
            if gap_type == GapType.COLORECTAL.value:
                m = MagicMock()
                m.status = ContactStatus.BOOKED.value
                return m
            return None

        mock_db = AsyncMock()
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.add = MagicMock()

        with patch("Clinic_app.services.campaign_service._find_duplicate_contact",
                   new=no_dup_for_second), \
             patch("Clinic_app.services.campaign_service.encrypt_phi",
                   return_value=b"encrypted"):
            from Clinic_app.services.campaign_service import create_campaign
            result = await create_campaign(
                db=mock_db,
                clinic_id=uuid.uuid4(),
                staff_id=None,
                name="Test",
                measurement_year=2026,
                parsed_rows=[
                    self._make_parsed_row("+17875551234", GapType.COLORECTAL),
                    self._make_parsed_row("+17875551234", GapType.EYE_EXAM),
                ],
                clinic_integration=self._make_clinic_integration(),
            )

        assert result.total_contacts == 1   # eye_exam created
        assert len(result.skipped_contacts) == 1  # colorectal skipped
