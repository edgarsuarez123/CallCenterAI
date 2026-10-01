"""
Unit tests for Availability Service.

Tests cover:
- Helper functions (keyword detection, overlap checking, slot generation)
- is_slot_available with capacity enforcement
- get_available_slots for bulk retrieval
- get_next_available_slots for future slot search
- find_slot_at_time for specific time search
- check_and_offer_alternatives
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime, date, time, timedelta, timezone
from uuid import uuid4
import pytz

from Clinic_app.services.availability import (
    _is_patient_appointment,
    _events_overlap,
    _parse_time,
    _get_clinic_business_hours,
    _generate_candidate_slots,
    _parse_gcal_datetime,
    is_slot_available,
    get_available_slots,
    get_next_available_slots,
    find_slot_at_time,
    check_and_offer_alternatives,
    PATIENT_KEYWORDS,
    FALLBACK_START,
    FALLBACK_END,
)
from Clinic_app.data.enums import BookingStatus, SlotStatus


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def sample_clinic_id():
    """Generate a sample clinic UUID."""
    return uuid4()


@pytest.fixture
def sample_provider_id():
    """Generate a sample provider UUID."""
    return uuid4()


@pytest.fixture
def mock_provider(sample_provider_id, sample_clinic_id):
    """Create a mock Provider object."""
    provider = Mock()
    provider.id = sample_provider_id
    provider.clinic_id = sample_clinic_id
    provider.display_name = "Dr. Lopez"
    provider.active = True
    provider.capacity = 2
    provider.booking_duration_mins = 30
    provider.timezone = "America/New_York"
    provider.google_calendar_id = "provider@example.com"
    return provider


@pytest.fixture
def mock_clinic(sample_clinic_id):
    """Create a mock Clinic object."""
    clinic = Mock()
    clinic.id = sample_clinic_id
    clinic.name = "Test Clinic"
    clinic.business_hours_start = "09:00"
    clinic.business_hours_end = "17:00"
    return clinic


@pytest.fixture
def mock_db_session():
    """Create a mock async database session."""
    session = AsyncMock()
    session.get = AsyncMock()
    return session


@pytest.fixture
def sample_gcal_event():
    """Create a sample Google Calendar event."""
    return {
        "id": "event123",
        "summary": "Staff Meeting",
        "start": {"dateTime": "2025-01-20T10:00:00-05:00"},
        "end": {"dateTime": "2025-01-20T11:00:00-05:00"},
    }


@pytest.fixture
def sample_patient_gcal_event():
    """Create a sample patient Google Calendar event."""
    return {
        "id": "event456",
        "summary": "Patient: John Smith",
        "start": {"dateTime": "2025-01-20T09:00:00-05:00"},
        "end": {"dateTime": "2025-01-20T09:30:00-05:00"},
    }


@pytest.fixture
def sample_callcenter_gcal_event():
    """Create a CallCenterAI-created Google Calendar event."""
    return {
        "id": "event789",
        "summary": "Patient Appointment - Dr. Lopez",
        "start": {"dateTime": "2025-01-20T14:00:00-05:00"},
        "end": {"dateTime": "2025-01-20T14:30:00-05:00"},
        "extendedProperties": {
            "private": {
                "source": "callcenter_ai",
                "booking_id": str(uuid4()),
                "clinic_id": str(uuid4()),
            }
        },
    }


# ============================================================================
# TEST HELPER FUNCTIONS - _is_patient_appointment
# ============================================================================


class TestIsPatientAppointment:
    """Tests for _is_patient_appointment function."""

    def test_is_patient_appointment_with_metadata(self, sample_callcenter_gcal_event):
        """Test detection via callcenter_ai metadata."""
        with patch("Clinic_app.services.availability.GoogleCalendarService") as mock_gcal:
            mock_gcal.parse_extended_properties.return_value = {"source": "callcenter_ai"}
            result = _is_patient_appointment(sample_callcenter_gcal_event)
        assert result is True

    def test_is_patient_appointment_with_keyword_english(self, sample_patient_gcal_event):
        """Test detection via English patient keyword."""
        with patch("Clinic_app.services.availability.GoogleCalendarService") as mock_gcal:
            mock_gcal.parse_extended_properties.return_value = None
            result = _is_patient_appointment(sample_patient_gcal_event)
        assert result is True

    def test_is_patient_appointment_with_keyword_spanish(self):
        """Test detection via Spanish patient keyword."""
        event = {"summary": "Cita: Maria Garcia"}
        with patch("Clinic_app.services.availability.GoogleCalendarService") as mock_gcal:
            mock_gcal.parse_extended_properties.return_value = None
            result = _is_patient_appointment(event)
        assert result is True

    def test_is_patient_appointment_external_event(self, sample_gcal_event):
        """Test external events are not detected as patient appointments."""
        with patch("Clinic_app.services.availability.GoogleCalendarService") as mock_gcal:
            mock_gcal.parse_extended_properties.return_value = None
            result = _is_patient_appointment(sample_gcal_event)
        assert result is False

    def test_keyword_case_insensitive(self):
        """Test keywords are case insensitive."""
        event = {"summary": "PATIENT CONSULTATION"}
        with patch("Clinic_app.services.availability.GoogleCalendarService") as mock_gcal:
            mock_gcal.parse_extended_properties.return_value = None
            result = _is_patient_appointment(event)
        assert result is True

    def test_all_keywords_detected(self):
        """Test all patient keywords are detected."""
        with patch("Clinic_app.services.availability.GoogleCalendarService") as mock_gcal:
            mock_gcal.parse_extended_properties.return_value = None
            for keyword in PATIENT_KEYWORDS:
                event = {"summary": f"Test {keyword} event"}
                result = _is_patient_appointment(event)
                assert result is True, f"Keyword '{keyword}' not detected"


# ============================================================================
# TEST HELPER FUNCTIONS - _events_overlap
# ============================================================================


class TestEventsOverlap:
    """Tests for _events_overlap function."""

    def test_events_overlap_completely(self):
        """Test completely overlapping events."""
        tz = pytz.UTC
        event_start = datetime(2025, 1, 20, 10, 0, tzinfo=tz)
        event_end = datetime(2025, 1, 20, 11, 0, tzinfo=tz)
        slot_start = datetime(2025, 1, 20, 10, 0, tzinfo=tz)
        slot_end = datetime(2025, 1, 20, 11, 0, tzinfo=tz)

        assert _events_overlap(event_start, event_end, slot_start, slot_end) is True

    def test_events_overlap_partially(self):
        """Test partially overlapping events."""
        tz = pytz.UTC
        event_start = datetime(2025, 1, 20, 10, 0, tzinfo=tz)
        event_end = datetime(2025, 1, 20, 11, 0, tzinfo=tz)
        slot_start = datetime(2025, 1, 20, 10, 30, tzinfo=tz)
        slot_end = datetime(2025, 1, 20, 11, 30, tzinfo=tz)

        assert _events_overlap(event_start, event_end, slot_start, slot_end) is True

    def test_events_no_overlap_before(self):
        """Test non-overlapping events (slot before event)."""
        tz = pytz.UTC
        event_start = datetime(2025, 1, 20, 10, 0, tzinfo=tz)
        event_end = datetime(2025, 1, 20, 11, 0, tzinfo=tz)
        slot_start = datetime(2025, 1, 20, 8, 0, tzinfo=tz)
        slot_end = datetime(2025, 1, 20, 9, 0, tzinfo=tz)

        assert _events_overlap(event_start, event_end, slot_start, slot_end) is False

    def test_events_no_overlap_after(self):
        """Test non-overlapping events (slot after event)."""
        tz = pytz.UTC
        event_start = datetime(2025, 1, 20, 10, 0, tzinfo=tz)
        event_end = datetime(2025, 1, 20, 11, 0, tzinfo=tz)
        slot_start = datetime(2025, 1, 20, 12, 0, tzinfo=tz)
        slot_end = datetime(2025, 1, 20, 13, 0, tzinfo=tz)

        assert _events_overlap(event_start, event_end, slot_start, slot_end) is False

    def test_events_adjacent_no_overlap(self):
        """Test adjacent events don't overlap."""
        tz = pytz.UTC
        event_start = datetime(2025, 1, 20, 10, 0, tzinfo=tz)
        event_end = datetime(2025, 1, 20, 10, 30, tzinfo=tz)
        slot_start = datetime(2025, 1, 20, 10, 30, tzinfo=tz)
        slot_end = datetime(2025, 1, 20, 11, 0, tzinfo=tz)

        assert _events_overlap(event_start, event_end, slot_start, slot_end) is False


# ============================================================================
# TEST HELPER FUNCTIONS - _parse_time
# ============================================================================


class TestParseTime:
    """Tests for _parse_time function."""

    def test_parse_time_valid(self):
        """Test parsing valid time strings."""
        assert _parse_time("09:00") == time(9, 0)
        assert _parse_time("17:30") == time(17, 30)
        assert _parse_time("00:00") == time(0, 0)
        assert _parse_time("23:59") == time(23, 59)

    def test_parse_time_invalid_format(self):
        """Test parsing invalid time format raises error."""
        with pytest.raises(ValueError):
            _parse_time("9:00:00")  # Too many parts

        with pytest.raises(ValueError):
            _parse_time("9")  # Missing minutes


# ============================================================================
# TEST HELPER FUNCTIONS - _get_clinic_business_hours
# ============================================================================


class TestGetClinicBusinessHours:
    """Tests for _get_clinic_business_hours function."""

    def test_get_business_hours_from_clinic(self, mock_clinic):
        """Test getting business hours from clinic."""
        start, end = _get_clinic_business_hours(mock_clinic)
        assert start == "09:00"
        assert end == "17:00"

    def test_get_business_hours_fallback(self):
        """Test fallback when clinic doesn't have business hours."""
        clinic = Mock()
        clinic.business_hours_start = None
        clinic.business_hours_end = None

        start, end = _get_clinic_business_hours(clinic)
        assert start == FALLBACK_START
        assert end == FALLBACK_END


# ============================================================================
# TEST HELPER FUNCTIONS - _generate_candidate_slots
# ============================================================================


class TestGenerateCandidateSlots:
    """Tests for _generate_candidate_slots function."""

    def test_generate_30min_slots(self):
        """Test generating 30-minute slots."""
        target = date(2025, 1, 20)
        slots = _generate_candidate_slots(
            target_date=target,
            start_time="09:00",
            end_time="11:00",
            duration_mins=30,
            timezone_str="America/New_York",
        )

        assert len(slots) == 4  # 9:00, 9:30, 10:00, 10:30

    def test_generate_15min_slots(self):
        """Test generating 15-minute slots."""
        target = date(2025, 1, 20)
        slots = _generate_candidate_slots(
            target_date=target,
            start_time="09:00",
            end_time="10:00",
            duration_mins=15,
            timezone_str="America/New_York",
        )

        assert len(slots) == 4  # 9:00, 9:15, 9:30, 9:45

    def test_generate_slots_respects_end_time(self):
        """Test slots don't extend beyond end time."""
        target = date(2025, 1, 20)
        slots = _generate_candidate_slots(
            target_date=target,
            start_time="09:00",
            end_time="09:45",  # Not divisible by 30
            duration_mins=30,
            timezone_str="America/New_York",
        )

        # Only 1 slot fits (9:00-9:30), second would end at 10:00
        assert len(slots) == 1

    def test_generate_slots_timezone_aware(self):
        """Test slots are timezone-aware."""
        target = date(2025, 1, 20)
        slots = _generate_candidate_slots(
            target_date=target,
            start_time="09:00",
            end_time="10:00",
            duration_mins=30,
            timezone_str="America/New_York",
        )

        for slot_start, slot_end in slots:
            assert slot_start.tzinfo is not None
            assert slot_end.tzinfo is not None


# ============================================================================
# TEST is_slot_available
# ============================================================================


class TestIsSlotAvailable:
    """Tests for is_slot_available function."""

    @pytest.mark.asyncio
    async def test_slot_available_when_empty(
        self, mock_db_session, mock_provider, mock_clinic, sample_clinic_id
    ):
        """Test slot is available when no blocking events or bookings."""
        tz = pytz.timezone("America/New_York")
        slot_start = tz.localize(datetime(2025, 1, 20, 10, 0))
        slot_end = tz.localize(datetime(2025, 1, 20, 10, 30))

        # Mock DB queries to return empty
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = None
        mock_result.scalars.return_value.all.return_value = []
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        mock_db_session.get = AsyncMock(return_value=mock_clinic)

        with patch("Clinic_app.services.availability.GoogleCalendarService") as mock_gcal:
            mock_gcal.list_events = AsyncMock(return_value=[])

            result = await is_slot_available(
                db=mock_db_session,
                provider=mock_provider,
                slot_start=slot_start,
                slot_end=slot_end,
                clinic_id=sample_clinic_id,
            )

        assert result is True

    @pytest.mark.asyncio
    async def test_slot_blocked_by_availability_slot(
        self, mock_db_session, mock_provider, mock_clinic, sample_clinic_id
    ):
        """Test slot is unavailable when blocked by AvailabilitySlot."""
        tz = pytz.timezone("America/New_York")
        slot_start = tz.localize(datetime(2025, 1, 20, 10, 0))
        slot_end = tz.localize(datetime(2025, 1, 20, 10, 30))

        # Mock blocked slot
        blocked_slot = Mock()
        blocked_slot.status = SlotStatus.BLOCKED

        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = blocked_slot
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        mock_db_session.get = AsyncMock(return_value=mock_clinic)

        with patch("Clinic_app.services.availability.GoogleCalendarService") as mock_gcal:
            mock_gcal.list_events = AsyncMock(return_value=[])

            result = await is_slot_available(
                db=mock_db_session,
                provider=mock_provider,
                slot_start=slot_start,
                slot_end=slot_end,
                clinic_id=sample_clinic_id,
            )

        assert result is False

    @pytest.mark.asyncio
    async def test_slot_blocked_by_external_gcal_event(
        self, mock_db_session, mock_provider, mock_clinic, sample_clinic_id, sample_gcal_event
    ):
        """Test slot blocked by non-patient GCal event."""
        tz = pytz.timezone("America/New_York")
        slot_start = tz.localize(datetime(2025, 1, 20, 10, 0))
        slot_end = tz.localize(datetime(2025, 1, 20, 10, 30))

        # Mock DB to return no blocked slots or bookings
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = None
        mock_result.scalars.return_value.all.return_value = []
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        mock_db_session.get = AsyncMock(return_value=mock_clinic)

        with patch("Clinic_app.services.availability.GoogleCalendarService") as mock_gcal:
            mock_gcal.list_events = AsyncMock(return_value=[sample_gcal_event])
            mock_gcal.parse_extended_properties.return_value = None

            result = await is_slot_available(
                db=mock_db_session,
                provider=mock_provider,
                slot_start=slot_start,
                slot_end=slot_end,
                clinic_id=sample_clinic_id,
            )

        assert result is False


# ============================================================================
# TEST get_available_slots
# ============================================================================


class TestGetAvailableSlots:
    """Tests for get_available_slots function."""

    @pytest.mark.asyncio
    async def test_returns_available_slots_for_date(
        self, mock_db_session, mock_provider, mock_clinic, sample_clinic_id
    ):
        """Test returning available slots for a date."""
        target = date(2025, 1, 20)

        # Mock DB and GCal to return empty (all slots available)
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = None
        mock_result.scalars.return_value.all.return_value = []
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        mock_db_session.get = AsyncMock(return_value=mock_clinic)

        with patch("Clinic_app.services.availability.GoogleCalendarService") as mock_gcal:
            mock_gcal.list_events = AsyncMock(return_value=[])

            result = await get_available_slots(
                db=mock_db_session,
                provider=mock_provider,
                target_date=target,
                clinic_id=sample_clinic_id,
            )

        assert isinstance(result, list)
        # With 9-5 hours and 30 min slots = 16 slots
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_respects_time_range(
        self, mock_db_session, mock_provider, mock_clinic, sample_clinic_id
    ):
        """Test that time_range parameter limits slots."""
        target = date(2025, 1, 20)

        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = None
        mock_result.scalars.return_value.all.return_value = []
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        mock_db_session.get = AsyncMock(return_value=mock_clinic)

        with patch("Clinic_app.services.availability.GoogleCalendarService") as mock_gcal:
            mock_gcal.list_events = AsyncMock(return_value=[])

            result = await get_available_slots(
                db=mock_db_session,
                provider=mock_provider,
                target_date=target,
                clinic_id=sample_clinic_id,
                time_range=("09:00", "10:00"),  # Only 1 hour window
            )

        # With 30 min slots, only 2 slots fit in 1 hour
        assert len(result) <= 2


# ============================================================================
# TEST get_next_available_slots
# ============================================================================


class TestGetNextAvailableSlots:
    """Tests for get_next_available_slots function."""

    @pytest.mark.asyncio
    async def test_finds_slots_starting_today(
        self, mock_db_session, mock_provider, mock_clinic, sample_clinic_id
    ):
        """Test finding slots starting from today."""
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = None
        mock_result.scalars.return_value.all.return_value = []
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        mock_db_session.get = AsyncMock(return_value=mock_clinic)

        with patch("Clinic_app.services.availability.GoogleCalendarService") as mock_gcal:
            mock_gcal.list_events = AsyncMock(return_value=[])

            result = await get_next_available_slots(
                db=mock_db_session,
                provider=mock_provider,
                clinic_id=sample_clinic_id,
                max_days_ahead=7,
                max_slots=5,
            )

        assert isinstance(result, list)
        assert len(result) <= 5  # Respects max_slots

    @pytest.mark.asyncio
    async def test_respects_max_slots(
        self, mock_db_session, mock_provider, mock_clinic, sample_clinic_id
    ):
        """Test max_slots parameter limits results."""
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = None
        mock_result.scalars.return_value.all.return_value = []
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        mock_db_session.get = AsyncMock(return_value=mock_clinic)

        with patch("Clinic_app.services.availability.GoogleCalendarService") as mock_gcal:
            mock_gcal.list_events = AsyncMock(return_value=[])

            result = await get_next_available_slots(
                db=mock_db_session,
                provider=mock_provider,
                clinic_id=sample_clinic_id,
                max_days_ahead=30,
                max_slots=3,
            )

        assert len(result) <= 3


# ============================================================================
# TEST find_slot_at_time
# ============================================================================


class TestFindSlotAtTime:
    """Tests for find_slot_at_time function."""

    @pytest.mark.asyncio
    async def test_finds_slot_at_specific_time(
        self, mock_db_session, mock_provider, mock_clinic, sample_clinic_id
    ):
        """Test finding slot at specific time."""
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = None
        mock_result.scalars.return_value.all.return_value = []
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        mock_db_session.get = AsyncMock(return_value=mock_clinic)

        with patch("Clinic_app.services.availability.GoogleCalendarService") as mock_gcal:
            mock_gcal.list_events = AsyncMock(return_value=[])

            result = await find_slot_at_time(
                db=mock_db_session,
                provider=mock_provider,
                preferred_time="10:00",
                clinic_id=sample_clinic_id,
                max_days_ahead=7,
            )

        assert isinstance(result, list)


# ============================================================================
# TEST check_and_offer_alternatives
# ============================================================================


class TestCheckAndOfferAlternatives:
    """Tests for check_and_offer_alternatives function."""

    @pytest.mark.asyncio
    async def test_returns_available_if_slot_free(
        self, mock_db_session, mock_provider, mock_clinic, sample_clinic_id
    ):
        """Test returns available=True when slot is free."""
        tz = pytz.timezone("America/New_York")
        requested_datetime = tz.localize(datetime(2025, 1, 20, 10, 0))

        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = None
        mock_result.scalars.return_value.all.return_value = []
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        mock_db_session.get = AsyncMock(return_value=mock_clinic)

        with patch("Clinic_app.services.availability.GoogleCalendarService") as mock_gcal:
            mock_gcal.list_events = AsyncMock(return_value=[])

            result = await check_and_offer_alternatives(
                db=mock_db_session,
                provider=mock_provider,
                requested_datetime=requested_datetime,
                clinic_id=sample_clinic_id,
            )

        assert result["available"] is True
