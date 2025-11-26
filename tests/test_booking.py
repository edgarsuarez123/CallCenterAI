"""
Unit tests for Booking Service.

Tests cover:
- Helper functions (audit entry, capacity check, provider lookup)
- Tentative booking creation with capacity enforcement
- Booking confirmation with GCal integration
- Booking cancellation
- Rescheduling
- Query functions
- Expiration logic
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime, timedelta, timezone
from uuid import uuid4, UUID

from Clinic_app.services.booking import (
    _create_audit_entry,
    _count_slot_bookings,
    _get_provider,
    create_tentative_booking,
    confirm_booking,
    cancel_booking,
    reschedule_booking,
    get_booking_by_hold_token,
    get_patient_bookings,
    get_booking_by_id,
    expire_booking,
    get_expired_tentative_bookings,
    HOLD_DURATION_MINUTES
)
from Clinic_app.data.enums import BookingStatus, BookingAction


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
def sample_patient_id():
    """Generate a sample patient UUID."""
    return uuid4()


@pytest.fixture
def sample_booking_id():
    """Generate a sample booking UUID."""
    return uuid4()


@pytest.fixture
def sample_hold_token():
    """Generate a sample hold token UUID."""
    return uuid4()


@pytest.fixture
def future_slot_start():
    """Generate a future slot start datetime."""
    return datetime.now(timezone.utc) + timedelta(days=1, hours=10)


@pytest.fixture
def future_slot_end(future_slot_start):
    """Generate a future slot end datetime (30 mins after start)."""
    return future_slot_start + timedelta(minutes=30)


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
def mock_patient(sample_patient_id, sample_clinic_id):
    """Create a mock Patient object."""
    patient = Mock()
    patient.id = sample_patient_id
    patient.clinic_id = sample_clinic_id
    return patient


@pytest.fixture
def mock_booking(sample_booking_id, sample_provider_id, sample_patient_id, sample_clinic_id, sample_hold_token, future_slot_start, future_slot_end):
    """Create a mock Booking object."""
    booking = Mock()
    booking.id = sample_booking_id
    booking.clinic_id = sample_clinic_id
    booking.provider_id = sample_provider_id
    booking.patient_id = sample_patient_id
    booking.slot_start = future_slot_start
    booking.slot_end = future_slot_end
    booking.status = BookingStatus.TENTATIVE
    booking.hold_token = sample_hold_token
    booking.hold_expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    booking.google_event_id = None
    booking.source = "call"
    return booking


@pytest.fixture
def mock_confirmed_booking(mock_booking):
    """Create a mock confirmed Booking object."""
    mock_booking.status = BookingStatus.CONFIRMED
    mock_booking.hold_token = None
    mock_booking.hold_expires_at = None
    mock_booking.google_event_id = "gcal_event_123"
    return mock_booking


@pytest.fixture
def mock_db_session():
    """Create a mock async database session."""
    session = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.flush = AsyncMock()
    session.add = Mock()
    session.get = AsyncMock()
    return session


# ============================================================================
# TEST HELPER FUNCTIONS
# ============================================================================

class TestCreateAuditEntry:
    """Tests for _create_audit_entry function."""
    
    @pytest.mark.asyncio
    async def test_create_audit_entry_success(self, mock_db_session, sample_clinic_id, sample_booking_id):
        """Test successful audit entry creation."""
        result = await _create_audit_entry(
            db=mock_db_session,
            clinic_id=sample_clinic_id,
            booking_id=sample_booking_id,
            action=BookingAction.HOLD,
            actor="patient"
        )
        
        mock_db_session.add.assert_called_once()
        mock_db_session.flush.assert_called_once()
        assert result is not None
    
    @pytest.mark.asyncio
    async def test_create_audit_entry_all_actions(self, mock_db_session, sample_clinic_id, sample_booking_id):
        """Test audit entry creation for all action types."""
        actions = [BookingAction.HOLD, BookingAction.CONFIRM, BookingAction.CANCEL, BookingAction.EXPIRE]
        
        for action in actions:
            mock_db_session.reset_mock()
            result = await _create_audit_entry(
                db=mock_db_session,
                clinic_id=sample_clinic_id,
                booking_id=sample_booking_id,
                action=action,
                actor="test"
            )
            mock_db_session.add.assert_called_once()


class TestCountSlotBookings:
    """Tests for _count_slot_bookings function."""
    
    @pytest.mark.asyncio
    async def test_count_returns_zero_for_empty_slot(self, mock_db_session, sample_provider_id, future_slot_start, future_slot_end):
        """Test count returns 0 when no bookings exist."""
        mock_result = Mock()
        mock_result.scalar.return_value = 0
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        
        count = await _count_slot_bookings(
            db=mock_db_session,
            provider_id=sample_provider_id,
            slot_start=future_slot_start,
            slot_end=future_slot_end
        )
        
        assert count == 0
    
    @pytest.mark.asyncio
    async def test_count_returns_booking_count(self, mock_db_session, sample_provider_id, future_slot_start, future_slot_end):
        """Test count returns correct number of bookings."""
        mock_result = Mock()
        mock_result.scalar.return_value = 2
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        
        count = await _count_slot_bookings(
            db=mock_db_session,
            provider_id=sample_provider_id,
            slot_start=future_slot_start,
            slot_end=future_slot_end
        )
        
        assert count == 2


class TestGetProvider:
    """Tests for _get_provider function."""
    
    @pytest.mark.asyncio
    async def test_get_provider_success(self, mock_db_session, mock_provider, sample_provider_id, sample_clinic_id):
        """Test successful provider retrieval."""
        mock_db_session.get = AsyncMock(return_value=mock_provider)
        
        result = await _get_provider(
            db=mock_db_session,
            provider_id=sample_provider_id,
            clinic_id=sample_clinic_id
        )
        
        assert result == mock_provider
    
    @pytest.mark.asyncio
    async def test_get_provider_not_found(self, mock_db_session, sample_provider_id, sample_clinic_id):
        """Test provider not found raises ValueError."""
        mock_db_session.get = AsyncMock(return_value=None)
        
        with pytest.raises(ValueError) as exc_info:
            await _get_provider(
                db=mock_db_session,
                provider_id=sample_provider_id,
                clinic_id=sample_clinic_id
            )
        assert "not found" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_get_provider_wrong_clinic(self, mock_db_session, mock_provider, sample_provider_id):
        """Test provider from different clinic raises ValueError."""
        different_clinic_id = uuid4()
        mock_db_session.get = AsyncMock(return_value=mock_provider)
        
        with pytest.raises(ValueError) as exc_info:
            await _get_provider(
                db=mock_db_session,
                provider_id=sample_provider_id,
                clinic_id=different_clinic_id
            )
        assert "does not belong to clinic" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_get_provider_inactive(self, mock_db_session, mock_provider, sample_provider_id, sample_clinic_id):
        """Test inactive provider raises ValueError."""
        mock_provider.active = False
        mock_db_session.get = AsyncMock(return_value=mock_provider)
        
        with pytest.raises(ValueError) as exc_info:
            await _get_provider(
                db=mock_db_session,
                provider_id=sample_provider_id,
                clinic_id=sample_clinic_id
            )
        assert "not active" in str(exc_info.value)


# ============================================================================
# TEST CREATE_TENTATIVE_BOOKING
# ============================================================================

class TestCreateTentativeBooking:
    """Tests for create_tentative_booking function."""
    
    @pytest.mark.asyncio
    async def test_create_booking_success(
        self, mock_db_session, mock_provider, sample_clinic_id, 
        sample_provider_id, sample_patient_id, future_slot_start, future_slot_end
    ):
        """Test successful tentative booking creation."""
        # Setup mocks
        mock_db_session.get = AsyncMock(return_value=mock_provider)
        
        count_result = Mock()
        count_result.scalar.return_value = 0
        mock_db_session.execute = AsyncMock(return_value=count_result)
        
        booking, hold_token = await create_tentative_booking(
            db=mock_db_session,
            clinic_id=sample_clinic_id,
            provider_id=sample_provider_id,
            patient_id=sample_patient_id,
            slot_start=future_slot_start,
            slot_end=future_slot_end,
            source="call"
        )
        
        assert booking is not None
        assert hold_token is not None
        mock_db_session.add.assert_called()  # Booking and audit added
    
    @pytest.mark.asyncio
    async def test_creates_hold_token(
        self, mock_db_session, mock_provider, sample_clinic_id,
        sample_provider_id, sample_patient_id, future_slot_start, future_slot_end
    ):
        """Test that hold token is generated."""
        mock_db_session.get = AsyncMock(return_value=mock_provider)
        count_result = Mock()
        count_result.scalar.return_value = 0
        mock_db_session.execute = AsyncMock(return_value=count_result)
        
        booking, hold_token = await create_tentative_booking(
            db=mock_db_session,
            clinic_id=sample_clinic_id,
            provider_id=sample_provider_id,
            patient_id=sample_patient_id,
            slot_start=future_slot_start,
            slot_end=future_slot_end
        )
        
        assert isinstance(hold_token, UUID)
        assert booking.hold_token == hold_token
    
    @pytest.mark.asyncio
    async def test_sets_5_minute_expiration(
        self, mock_db_session, mock_provider, sample_clinic_id,
        sample_provider_id, sample_patient_id, future_slot_start, future_slot_end
    ):
        """Test that hold expires in 5 minutes."""
        mock_db_session.get = AsyncMock(return_value=mock_provider)
        count_result = Mock()
        count_result.scalar.return_value = 0
        mock_db_session.execute = AsyncMock(return_value=count_result)
        
        before = datetime.now(timezone.utc)
        
        booking, _ = await create_tentative_booking(
            db=mock_db_session,
            clinic_id=sample_clinic_id,
            provider_id=sample_provider_id,
            patient_id=sample_patient_id,
            slot_start=future_slot_start,
            slot_end=future_slot_end
        )
        
        after = datetime.now(timezone.utc)
        
        expected_min = before + timedelta(minutes=HOLD_DURATION_MINUTES)
        expected_max = after + timedelta(minutes=HOLD_DURATION_MINUTES)
        
        assert expected_min <= booking.hold_expires_at <= expected_max
    
    @pytest.mark.asyncio
    async def test_fails_at_capacity(
        self, mock_db_session, mock_provider, sample_clinic_id,
        sample_provider_id, sample_patient_id, future_slot_start, future_slot_end
    ):
        """Test that booking fails when slot is at capacity."""
        mock_provider.capacity = 2
        mock_db_session.get = AsyncMock(return_value=mock_provider)
        
        count_result = Mock()
        count_result.scalar.return_value = 2  # At capacity
        mock_db_session.execute = AsyncMock(return_value=count_result)
        
        with pytest.raises(ValueError) as exc_info:
            await create_tentative_booking(
                db=mock_db_session,
                clinic_id=sample_clinic_id,
                provider_id=sample_provider_id,
                patient_id=sample_patient_id,
                slot_start=future_slot_start,
                slot_end=future_slot_end
            )
        assert "capacity" in str(exc_info.value).lower()


# ============================================================================
# TEST CONFIRM_BOOKING
# ============================================================================

class TestConfirmBooking:
    """Tests for confirm_booking function."""
    
    @pytest.mark.asyncio
    async def test_confirm_success(
        self, mock_db_session, mock_booking, mock_provider, mock_patient,
        sample_clinic_id, sample_hold_token
    ):
        """Test successful booking confirmation."""
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = mock_booking
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        mock_db_session.get = AsyncMock(side_effect=[mock_provider, mock_patient])
        
        with patch('Clinic_app.services.booking.GoogleCalendarService') as mock_gcal:
            mock_gcal.create_event = AsyncMock(return_value={"id": "gcal_event_123"})
            
            result = await confirm_booking(
                db=mock_db_session,
                hold_token=sample_hold_token,
                clinic_id=sample_clinic_id
            )
        
        assert result.status == BookingStatus.CONFIRMED
        assert result.hold_token is None
        assert result.hold_expires_at is None
    
    @pytest.mark.asyncio
    async def test_confirm_creates_gcal_event(
        self, mock_db_session, mock_booking, mock_provider, mock_patient,
        sample_clinic_id, sample_hold_token
    ):
        """Test that confirming creates Google Calendar event."""
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = mock_booking
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        mock_db_session.get = AsyncMock(side_effect=[mock_provider, mock_patient])
        
        with patch('Clinic_app.services.booking.GoogleCalendarService') as mock_gcal:
            mock_gcal.create_event = AsyncMock(return_value={"id": "gcal_event_123"})
            
            result = await confirm_booking(
                db=mock_db_session,
                hold_token=sample_hold_token,
                clinic_id=sample_clinic_id
            )
            
            mock_gcal.create_event.assert_called_once()
        
        assert result.google_event_id == "gcal_event_123"
    
    @pytest.mark.asyncio
    async def test_confirm_expired_token_fails(
        self, mock_db_session, mock_booking, sample_clinic_id, sample_hold_token
    ):
        """Test that expired hold token raises error."""
        mock_booking.hold_expires_at = datetime.now(timezone.utc) - timedelta(minutes=10)
        
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = mock_booking
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        
        with pytest.raises(ValueError) as exc_info:
            await confirm_booking(
                db=mock_db_session,
                hold_token=sample_hold_token,
                clinic_id=sample_clinic_id
            )
        assert "expired" in str(exc_info.value).lower()
    
    @pytest.mark.asyncio
    async def test_confirm_invalid_token_fails(
        self, mock_db_session, sample_clinic_id
    ):
        """Test that invalid hold token raises error."""
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        
        with pytest.raises(ValueError) as exc_info:
            await confirm_booking(
                db=mock_db_session,
                hold_token=uuid4(),
                clinic_id=sample_clinic_id
            )
        assert "not found" in str(exc_info.value).lower()
    
    @pytest.mark.asyncio
    async def test_confirm_already_confirmed_fails(
        self, mock_db_session, mock_confirmed_booking, sample_clinic_id, sample_hold_token
    ):
        """Test confirming already confirmed booking raises error."""
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = mock_confirmed_booking
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        
        with pytest.raises(ValueError) as exc_info:
            await confirm_booking(
                db=mock_db_session,
                hold_token=sample_hold_token,
                clinic_id=sample_clinic_id
            )
        assert "not tentative" in str(exc_info.value).lower()


# ============================================================================
# TEST CANCEL_BOOKING
# ============================================================================

class TestCancelBooking:
    """Tests for cancel_booking function."""
    
    @pytest.mark.asyncio
    async def test_cancel_success(
        self, mock_db_session, mock_booking, mock_provider,
        sample_clinic_id, sample_booking_id
    ):
        """Test successful booking cancellation."""
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = mock_booking
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        mock_db_session.get = AsyncMock(return_value=mock_provider)
        
        result = await cancel_booking(
            db=mock_db_session,
            booking_id=sample_booking_id,
            clinic_id=sample_clinic_id,
            actor="patient"
        )
        
        assert result.status == BookingStatus.CANCELED
    
    @pytest.mark.asyncio
    async def test_cancel_deletes_gcal_event(
        self, mock_db_session, mock_confirmed_booking, mock_provider,
        sample_clinic_id, sample_booking_id
    ):
        """Test that canceling deletes Google Calendar event."""
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = mock_confirmed_booking
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        mock_db_session.get = AsyncMock(return_value=mock_provider)
        
        with patch('Clinic_app.services.booking.GoogleCalendarService') as mock_gcal:
            mock_gcal.delete_event = AsyncMock()
            
            await cancel_booking(
                db=mock_db_session,
                booking_id=sample_booking_id,
                clinic_id=sample_clinic_id
            )
            
            mock_gcal.delete_event.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_cancel_not_found_fails(
        self, mock_db_session, sample_clinic_id, sample_booking_id
    ):
        """Test canceling non-existent booking raises error."""
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        
        with pytest.raises(ValueError) as exc_info:
            await cancel_booking(
                db=mock_db_session,
                booking_id=sample_booking_id,
                clinic_id=sample_clinic_id
            )
        assert "not found" in str(exc_info.value).lower()
    
    @pytest.mark.asyncio
    async def test_cancel_already_canceled_fails(
        self, mock_db_session, mock_booking, sample_clinic_id, sample_booking_id
    ):
        """Test canceling already canceled booking raises error."""
        mock_booking.status = BookingStatus.CANCELED
        
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = mock_booking
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        
        with pytest.raises(ValueError) as exc_info:
            await cancel_booking(
                db=mock_db_session,
                booking_id=sample_booking_id,
                clinic_id=sample_clinic_id
            )
        assert "already canceled" in str(exc_info.value).lower()


# ============================================================================
# TEST RESCHEDULE_BOOKING
# ============================================================================

class TestRescheduleBooking:
    """Tests for reschedule_booking function."""
    
    @pytest.mark.asyncio
    async def test_reschedule_success(
        self, mock_db_session, mock_booking, mock_provider,
        sample_clinic_id, sample_booking_id
    ):
        """Test successful booking rescheduling."""
        # Setup for finding original booking
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = mock_booking
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        mock_db_session.get = AsyncMock(return_value=mock_provider)
        
        # New slot
        new_start = datetime.now(timezone.utc) + timedelta(days=2)
        new_end = new_start + timedelta(minutes=30)
        
        # Mock the capacity check to return 0
        with patch('Clinic_app.services.booking._count_slot_bookings', new=AsyncMock(return_value=0)):
            with patch('Clinic_app.services.booking.GoogleCalendarService'):
                new_booking, hold_token = await reschedule_booking(
                    db=mock_db_session,
                    booking_id=sample_booking_id,
                    clinic_id=sample_clinic_id,
                    new_slot_start=new_start,
                    new_slot_end=new_end,
                    actor="patient"
                )
        
        assert new_booking is not None
        assert hold_token is not None
    
    @pytest.mark.asyncio
    async def test_reschedule_not_found_fails(
        self, mock_db_session, sample_clinic_id, sample_booking_id
    ):
        """Test rescheduling non-existent booking raises error."""
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        
        new_start = datetime.now(timezone.utc) + timedelta(days=2)
        new_end = new_start + timedelta(minutes=30)
        
        with pytest.raises(ValueError) as exc_info:
            await reschedule_booking(
                db=mock_db_session,
                booking_id=sample_booking_id,
                clinic_id=sample_clinic_id,
                new_slot_start=new_start,
                new_slot_end=new_end
            )
        assert "not found" in str(exc_info.value).lower()


# ============================================================================
# TEST QUERY FUNCTIONS
# ============================================================================

class TestQueryFunctions:
    """Tests for query functions."""
    
    @pytest.mark.asyncio
    async def test_get_by_hold_token_found(
        self, mock_db_session, mock_booking, sample_clinic_id, sample_hold_token
    ):
        """Test finding booking by hold token."""
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = mock_booking
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        
        result = await get_booking_by_hold_token(
            db=mock_db_session,
            hold_token=sample_hold_token,
            clinic_id=sample_clinic_id
        )
        
        assert result == mock_booking
    
    @pytest.mark.asyncio
    async def test_get_by_hold_token_not_found(
        self, mock_db_session, sample_clinic_id
    ):
        """Test that non-existent hold token returns None."""
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        
        result = await get_booking_by_hold_token(
            db=mock_db_session,
            hold_token=uuid4(),
            clinic_id=sample_clinic_id
        )
        
        assert result is None
    
    @pytest.mark.asyncio
    async def test_get_patient_bookings(
        self, mock_db_session, mock_booking, sample_clinic_id, sample_patient_id
    ):
        """Test getting patient bookings."""
        mock_scalars = Mock()
        mock_scalars.all.return_value = [mock_booking]
        mock_result = Mock()
        mock_result.scalars.return_value = mock_scalars
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        
        result = await get_patient_bookings(
            db=mock_db_session,
            patient_id=sample_patient_id,
            clinic_id=sample_clinic_id
        )
        
        assert len(result) == 1
        assert result[0] == mock_booking
    
    @pytest.mark.asyncio
    async def test_get_patient_bookings_with_status_filter(
        self, mock_db_session, mock_booking, sample_clinic_id, sample_patient_id
    ):
        """Test getting patient bookings with status filter."""
        mock_scalars = Mock()
        mock_scalars.all.return_value = [mock_booking]
        mock_result = Mock()
        mock_result.scalars.return_value = mock_scalars
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        
        result = await get_patient_bookings(
            db=mock_db_session,
            patient_id=sample_patient_id,
            clinic_id=sample_clinic_id,
            status_filter=[BookingStatus.CONFIRMED]
        )
        
        assert len(result) == 1
    
    @pytest.mark.asyncio
    async def test_get_booking_by_id(
        self, mock_db_session, mock_booking, sample_clinic_id, sample_booking_id
    ):
        """Test getting booking by ID."""
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = mock_booking
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        
        result = await get_booking_by_id(
            db=mock_db_session,
            booking_id=sample_booking_id,
            clinic_id=sample_clinic_id
        )
        
        assert result == mock_booking


# ============================================================================
# TEST EXPIRATION
# ============================================================================

class TestExpiration:
    """Tests for expiration functions."""
    
    @pytest.mark.asyncio
    async def test_expire_booking_updates_status(
        self, mock_db_session, mock_booking, sample_booking_id
    ):
        """Test expiring booking updates status to canceled."""
        mock_db_session.get = AsyncMock(return_value=mock_booking)
        
        result = await expire_booking(
            db=mock_db_session,
            booking_id=sample_booking_id
        )
        
        assert result.status == BookingStatus.CANCELED
        assert result.hold_token is None
        assert result.hold_expires_at is None
    
    @pytest.mark.asyncio
    async def test_expire_booking_not_found_fails(
        self, mock_db_session, sample_booking_id
    ):
        """Test expiring non-existent booking raises error."""
        mock_db_session.get = AsyncMock(return_value=None)
        
        with pytest.raises(ValueError) as exc_info:
            await expire_booking(
                db=mock_db_session,
                booking_id=sample_booking_id
            )
        assert "not found" in str(exc_info.value).lower()
    
    @pytest.mark.asyncio
    async def test_expire_confirmed_booking_fails(
        self, mock_db_session, mock_confirmed_booking, sample_booking_id
    ):
        """Test expiring confirmed booking raises error."""
        mock_db_session.get = AsyncMock(return_value=mock_confirmed_booking)
        
        with pytest.raises(ValueError) as exc_info:
            await expire_booking(
                db=mock_db_session,
                booking_id=sample_booking_id
            )
        assert "not tentative" in str(exc_info.value).lower()
    
    @pytest.mark.asyncio
    async def test_get_expired_finds_expired_holds(
        self, mock_db_session, mock_booking
    ):
        """Test getting expired tentative bookings."""
        mock_booking.hold_expires_at = datetime.now(timezone.utc) - timedelta(minutes=10)
        
        mock_scalars = Mock()
        mock_scalars.all.return_value = [mock_booking]
        mock_result = Mock()
        mock_result.scalars.return_value = mock_scalars
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        
        result = await get_expired_tentative_bookings(
            db=mock_db_session,
            limit=100
        )
        
        assert len(result) == 1
        assert result[0] == mock_booking
    
    @pytest.mark.asyncio
    async def test_get_expired_returns_empty_when_none(self, mock_db_session):
        """Test getting expired bookings returns empty list when none exist."""
        mock_scalars = Mock()
        mock_scalars.all.return_value = []
        mock_result = Mock()
        mock_result.scalars.return_value = mock_scalars
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        
        result = await get_expired_tentative_bookings(
            db=mock_db_session,
            limit=100
        )
        
        assert result == []

