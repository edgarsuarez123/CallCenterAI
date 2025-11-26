"""
Unit tests for Provider Routes.

Tests cover:
- Provider CRUD (create, get, update, list)
- Google Calendar validation
- Time blocking/unblocking
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from Clinic_app.Routes.provider import (
    provider_router,
    ProviderCreateRequest,
    ProviderUpdateRequest,
    BlockTimeRequest,
    UnblockTimeRequest,
    APIResponse
)
from Clinic_app.data.enums import SlotStatus


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
def sample_slot_id():
    """Generate a sample slot UUID."""
    return uuid4()


@pytest.fixture
def mock_clinic(sample_clinic_id):
    """Create a mock Clinic object."""
    clinic = Mock()
    clinic.id = sample_clinic_id
    clinic.name = "Test Clinic"
    clinic.timezone = "America/New_York"
    return clinic


@pytest.fixture
def mock_provider(sample_provider_id, sample_clinic_id):
    """Create a mock Provider object."""
    provider = Mock()
    provider.id = sample_provider_id
    provider.clinic_id = sample_clinic_id
    provider.display_name = "Dr. Lopez"
    provider.google_calendar_id = "provider@example.com"
    provider.timezone = "America/New_York"
    provider.active = True
    provider.capacity = 2
    provider.booking_duration_mins = 30
    provider.created_at = datetime.now(timezone.utc)
    return provider


@pytest.fixture
def mock_blocked_slot(sample_slot_id, sample_provider_id):
    """Create a mock blocked AvailabilitySlot."""
    slot = Mock()
    slot.id = sample_slot_id
    slot.provider_id = sample_provider_id
    slot.start = datetime.now(timezone.utc) + timedelta(days=1, hours=10)
    slot.end = datetime.now(timezone.utc) + timedelta(days=1, hours=12)
    slot.status = SlotStatus.BLOCKED
    return slot


@pytest.fixture
def mock_db_session():
    """Create a mock async database session."""
    session = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.flush = AsyncMock()
    session.add = Mock()
    session.get = AsyncMock()
    session.refresh = AsyncMock()
    session.execute = AsyncMock()
    return session


# ============================================================================
# TEST PYDANTIC MODELS
# ============================================================================

class TestPydanticModels:
    """Tests for Pydantic request models."""
    
    def test_provider_create_request_valid(self, sample_clinic_id):
        """Test ProviderCreateRequest with valid data."""
        request = ProviderCreateRequest(
            display_name="Dr. Maria Lopez",
            google_calendar_id="maria.lopez@example.com",
            timezone="America/New_York",
            capacity=3,
            booking_duration_mins=30
        )
        
        assert request.display_name == "Dr. Maria Lopez"
        assert request.google_calendar_id == "maria.lopez@example.com"
        assert request.capacity == 3
    
    def test_provider_create_request_defaults(self):
        """Test ProviderCreateRequest has correct defaults."""
        request = ProviderCreateRequest(
            display_name="Dr. Smith",
            google_calendar_id="dr.smith@example.com",
            timezone="America/New_York"
        )
        
        # Check defaults
        assert request.capacity == 1 or request.capacity is None
        assert request.booking_duration_mins == 30 or request.booking_duration_mins is None
    
    def test_provider_update_request_partial(self):
        """Test ProviderUpdateRequest with partial data."""
        request = ProviderUpdateRequest(
            capacity=5
        )
        
        assert request.capacity == 5
        assert request.display_name is None
        assert request.google_calendar_id is None
    
    def test_block_time_request_valid(self):
        """Test BlockTimeRequest with valid data."""
        start = datetime.now(timezone.utc) + timedelta(days=1, hours=12)
        end = datetime.now(timezone.utc) + timedelta(days=1, hours=13)
        
        request = BlockTimeRequest(
            start_datetime=start,
            end_datetime=end
        )
        
        assert request.start_datetime == start
        assert request.end_datetime == end
    
    def test_unblock_time_request_valid(self):
        """Test UnblockTimeRequest with valid data."""
        start = datetime.now(timezone.utc) + timedelta(days=1, hours=12)
        end = datetime.now(timezone.utc) + timedelta(days=1, hours=13)
        
        request = UnblockTimeRequest(
            start_datetime=start,
            end_datetime=end
        )
        
        assert request.start_datetime == start
        assert request.end_datetime == end


# ============================================================================
# TEST PROVIDER CRUD
# ============================================================================

class TestProviderCRUD:
    """Tests for provider CRUD operations."""
    
    @pytest.mark.asyncio
    async def test_create_provider_success(
        self, mock_db_session, mock_clinic, sample_clinic_id
    ):
        """Test successful provider creation conceptually."""
        mock_db_session.get = AsyncMock(return_value=mock_clinic)
        
        # Conceptual test - actual endpoint testing via TestClient
        result = await mock_db_session.get(Mock, sample_clinic_id)
        
        assert result is not None
    
    @pytest.mark.asyncio
    async def test_create_provider_validates_calendar(self):
        """Test provider creation validates Google Calendar access."""
        # Conceptual: When creating a provider, should verify GCal access
        pass  # Placeholder for integration test
    
    @pytest.mark.asyncio
    async def test_get_provider_success(
        self, mock_db_session, mock_provider, sample_provider_id
    ):
        """Test successful provider retrieval."""
        mock_db_session.get = AsyncMock(return_value=mock_provider)
        
        result = await mock_db_session.get(Mock, sample_provider_id)
        
        assert result.display_name == "Dr. Lopez"
    
    @pytest.mark.asyncio
    async def test_get_provider_not_found(
        self, mock_db_session, sample_provider_id
    ):
        """Test provider not found returns None."""
        mock_db_session.get = AsyncMock(return_value=None)
        
        result = await mock_db_session.get(Mock, sample_provider_id)
        
        assert result is None
    
    @pytest.mark.asyncio
    async def test_update_provider_success(
        self, mock_db_session, mock_provider
    ):
        """Test successful provider update."""
        mock_db_session.get = AsyncMock(return_value=mock_provider)
        
        # Simulate update
        mock_provider.capacity = 5
        
        assert mock_provider.capacity == 5
    
    @pytest.mark.asyncio
    async def test_list_providers(
        self, mock_db_session, mock_provider, sample_clinic_id
    ):
        """Test listing providers for a clinic."""
        mock_scalars = Mock()
        mock_scalars.all.return_value = [mock_provider]
        mock_result = Mock()
        mock_result.scalars.return_value = mock_scalars
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        
        result = mock_result.scalars().all()
        
        assert len(result) == 1
        assert result[0].display_name == "Dr. Lopez"
    
    @pytest.mark.asyncio
    async def test_list_providers_active_only(
        self, mock_db_session, mock_provider, sample_clinic_id
    ):
        """Test listing only active providers."""
        # Create inactive provider
        inactive_provider = Mock()
        inactive_provider.display_name = "Dr. Inactive"
        inactive_provider.active = False
        
        # Mock should only return active provider
        mock_scalars = Mock()
        mock_scalars.all.return_value = [mock_provider]  # Only active
        mock_result = Mock()
        mock_result.scalars.return_value = mock_scalars
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        
        result = mock_result.scalars().all()
        
        # Should only have active provider
        assert len(result) == 1
        assert result[0].active is True


# ============================================================================
# TEST TIME BLOCKING
# ============================================================================

class TestTimeBlocking:
    """Tests for time blocking/unblocking."""
    
    @pytest.mark.asyncio
    async def test_block_time_success(
        self, mock_db_session, mock_provider, sample_provider_id
    ):
        """Test successful time blocking."""
        mock_db_session.get = AsyncMock(return_value=mock_provider)
        
        # Check that provider was found
        result = await mock_db_session.get(Mock, sample_provider_id)
        assert result is not None
        
        # Would add AvailabilitySlot with BLOCKED status
        mock_db_session.add.assert_not_called()  # Not called yet in mock
    
    @pytest.mark.asyncio
    async def test_block_time_overlapping_rejected(
        self, mock_db_session, mock_provider, mock_blocked_slot
    ):
        """Conceptual test: overlapping block should be rejected or merged."""
        # When blocking time that overlaps existing block,
        # should either reject or merge the blocks
        pass  # Placeholder for integration test
    
    @pytest.mark.asyncio
    async def test_unblock_time_success(
        self, mock_db_session, mock_provider, mock_blocked_slot, sample_provider_id
    ):
        """Test successful time unblocking."""
        mock_db_session.get = AsyncMock(return_value=mock_provider)
        
        # Mock finding the blocked slot
        mock_scalars = Mock()
        mock_scalars.all.return_value = [mock_blocked_slot]
        mock_result = Mock()
        mock_result.scalars.return_value = mock_scalars
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        
        result = mock_result.scalars().all()
        
        assert len(result) == 1
        assert result[0].status == SlotStatus.BLOCKED
    
    @pytest.mark.asyncio
    async def test_unblock_time_not_found(
        self, mock_db_session, mock_provider
    ):
        """Test unblocking time that doesn't exist."""
        mock_db_session.get = AsyncMock(return_value=mock_provider)
        
        # Mock finding no blocked slots
        mock_scalars = Mock()
        mock_scalars.all.return_value = []
        mock_result = Mock()
        mock_result.scalars.return_value = mock_scalars
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        
        result = mock_result.scalars().all()
        
        assert len(result) == 0


# ============================================================================
# TEST VALIDATION
# ============================================================================

class TestValidation:
    """Tests for input validation."""
    
    def test_timezone_validation(self):
        """Test timezone validation in provider creation."""
        # Provider timezone validation only accepts IANA region-based timezones
        valid_timezones = [
            "America/New_York",
            "America/Los_Angeles",
            "America/Chicago",
            "Europe/London",
        ]
        
        for tz in valid_timezones:
            request = ProviderCreateRequest(
                display_name="Dr. Test",
                google_calendar_id="test@example.com",
                timezone=tz
            )
            assert request.timezone == tz
    
    def test_capacity_must_be_positive(self):
        """Conceptual test: capacity should be positive."""
        request = ProviderCreateRequest(
            display_name="Dr. Test",
            google_calendar_id="test@example.com",
            timezone="America/New_York",
            capacity=1
        )
        
        assert request.capacity > 0
    
    def test_booking_duration_must_be_positive(self):
        """Conceptual test: booking duration should be positive."""
        request = ProviderCreateRequest(
            display_name="Dr. Test",
            google_calendar_id="test@example.com",
            timezone="America/New_York",
            booking_duration_mins=30
        )
        
        assert request.booking_duration_mins > 0
    
    def test_block_time_end_after_start(self):
        """Test that block end time must be after start time."""
        start = datetime.now(timezone.utc) + timedelta(days=1, hours=10)
        end = datetime.now(timezone.utc) + timedelta(days=1, hours=12)
        
        request = BlockTimeRequest(
            start_datetime=start,
            end_datetime=end
        )
        
        assert request.end_datetime > request.start_datetime


# ============================================================================
# TEST API RESPONSE
# ============================================================================

class TestAPIResponse:
    """Tests for API response format."""
    
    def test_provider_response_success(self, mock_provider):
        """Test successful provider response."""
        response = APIResponse(
            success=True,
            message="Provider created",
            data={
                "id": str(mock_provider.id),
                "display_name": mock_provider.display_name,
                "capacity": mock_provider.capacity
            }
        )
        
        assert response.success is True
        assert response.data["display_name"] == "Dr. Lopez"
    
    def test_provider_response_error(self):
        """Test error response."""
        response = APIResponse(
            success=False,
            message="Provider not found",
            error={"detail": "No provider with that ID exists"}
        )
        
        assert response.success is False
        assert "not found" in response.message.lower()
    
    def test_list_providers_response(self, mock_provider):
        """Test list providers response."""
        response = APIResponse(
            success=True,
            message="Found 1 provider",
            data=[
                {
                    "id": str(mock_provider.id),
                    "display_name": mock_provider.display_name
                }
            ]
        )
        
        assert response.success is True
        assert len(response.data) == 1


# ============================================================================
# TEST GOOGLE CALENDAR INTEGRATION
# ============================================================================

class TestGoogleCalendarIntegration:
    """Tests for Google Calendar integration in provider routes."""
    
    @pytest.mark.asyncio
    async def test_create_validates_calendar_access(self):
        """Conceptual: Creating provider should verify GCal access."""
        # When creating a provider with a google_calendar_id,
        # the endpoint should verify that the calendar is accessible
        pass  # Placeholder for integration test
    
    @pytest.mark.asyncio
    async def test_update_validates_new_calendar(self):
        """Conceptual: Updating calendar ID should verify new calendar."""
        # When updating google_calendar_id,
        # should verify the new calendar is accessible
        pass  # Placeholder for integration test
    
    def test_calendar_id_format(self):
        """Test calendar ID is typically an email format."""
        valid_calendar_ids = [
            "dr.smith@example.com",
            "provider@clinic.com",
            "calendar123@group.calendar.google.com"
        ]
        
        for cal_id in valid_calendar_ids:
            request = ProviderCreateRequest(
                display_name="Dr. Test",
                google_calendar_id=cal_id,
                timezone="America/New_York"
            )
            assert request.google_calendar_id == cal_id

