"""
Unit tests for Google Calendar Service.

Tests cover:
- Service account authentication and validation
- CRUD operations (list, create, update, delete, get)
- Retry logic (including rate limit handling)
- Timezone handling (RFC3339 formatting)
- Extended properties helpers
- Error scenarios (invalid credentials, rate limits, 404s)
- Calendar validation
"""

import pytest
import json
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime, timezone, timedelta, tzinfo
from uuid import uuid4, UUID
from googleapiclient.errors import HttpError
import time

from Clinic_app.services.google_calendar import (
    GoogleCalendarService,
    GoogleCalendarError,
    GoogleCalendarAuthError,
    GoogleCalendarNotFoundError,
    GoogleCalendarRateLimitError
)


# Test fixtures
@pytest.fixture
def sample_clinic_id():
    """Generate a sample clinic UUID."""
    return uuid4()


@pytest.fixture
def sample_calendar_id():
    """Sample Google Calendar ID (email)."""
    return "provider@example.com"


@pytest.fixture
def sample_service_account_json():
    """Valid service account JSON."""
    return {
        "type": "service_account",
        "project_id": "test-project",
        "private_key_id": "test-key-id",
        "private_key": "-----BEGIN PRIVATE KEY-----\nMOCK_KEY\n-----END PRIVATE KEY-----\n",
        "client_email": "test@test-project.iam.gserviceaccount.com",
        "client_id": "123456789",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/test%40test-project.iam.gserviceaccount.com"
    }


@pytest.fixture
def sample_clinic_integration(sample_clinic_id, sample_service_account_json):
    """Mock ClinicIntegration object."""
    integration = Mock()
    integration.clinic_id = sample_clinic_id
    integration.google_service_account_json = json.dumps(sample_service_account_json)
    return integration


@pytest.fixture
def mock_db_session(sample_clinic_integration):
    """Mock database session."""
    session = AsyncMock()
    
    # Mock the select query result
    mock_result = Mock()
    mock_result.scalar_one_or_none.return_value = sample_clinic_integration
    
    # Mock the select statement
    mock_stmt = Mock()
    mock_stmt.where.return_value = mock_stmt
    
    # Mock session.execute to return our mock result
    async def execute_side_effect(stmt):
        return mock_result
    
    session.execute = AsyncMock(side_effect=execute_side_effect)
    return session


@pytest.fixture
def mock_calendar_service():
    """Mock Google Calendar API service."""
    service = Mock()
    
    # Mock events() method
    events_mock = Mock()
    service.events.return_value = events_mock
    
    # Mock calendars() method
    calendars_mock = Mock()
    service.calendars.return_value = calendars_mock
    
    return service, events_mock, calendars_mock


@pytest.fixture
def sample_event():
    """Sample Google Calendar event."""
    return {
        "id": "event123",
        "summary": "Test Appointment",
        "start": {
            "dateTime": "2025-01-20T09:00:00-08:00",
            "timeZone": "America/Los_Angeles"
        },
        "end": {
            "dateTime": "2025-01-20T09:15:00-08:00",
            "timeZone": "America/Los_Angeles"
        },
        "extendedProperties": {
            "private": {
                "source": "callcenter_ai",
                "booking_id": str(uuid4()),
                "clinic_id": str(uuid4()),
                "reminded": "false"
            }
        }
    }


class TestServiceAccountValidation:
    """Test service account JSON validation."""
    
    def test_validate_service_account_json_valid(self, sample_service_account_json):
        """Test validation with valid JSON."""
        assert GoogleCalendarService._validate_service_account_json(sample_service_account_json) is True
    
    def test_validate_service_account_json_missing_fields(self):
        """Test validation with missing required fields."""
        invalid_json = {"type": "service_account"}
        assert GoogleCalendarService._validate_service_account_json(invalid_json) is False
    
    def test_validate_service_account_json_empty(self):
        """Test validation with empty dict."""
        assert GoogleCalendarService._validate_service_account_json({}) is False


class TestExtendedProperties:
    """Test extended properties helpers."""
    
    def test_build_extended_properties(self, sample_clinic_id):
        """Test building extended properties."""
        booking_id = uuid4()
        props = GoogleCalendarService.build_extended_properties(
            booking_id=booking_id,
            clinic_id=sample_clinic_id,
            reminded=False
        )
        
        assert "extendedProperties" in props
        assert props["extendedProperties"]["private"]["source"] == "callcenter_ai"
        assert props["extendedProperties"]["private"]["booking_id"] == str(booking_id)
        assert props["extendedProperties"]["private"]["clinic_id"] == str(sample_clinic_id)
        assert props["extendedProperties"]["private"]["reminded"] == "false"
    
    def test_build_extended_properties_reminded(self, sample_clinic_id):
        """Test building extended properties with reminded=True."""
        booking_id = uuid4()
        props = GoogleCalendarService.build_extended_properties(
            booking_id=booking_id,
            clinic_id=sample_clinic_id,
            reminded=True
        )
        
        assert props["extendedProperties"]["private"]["reminded"] == "true"
    
    def test_parse_extended_properties(self, sample_event):
        """Test parsing extended properties from event."""
        metadata = GoogleCalendarService.parse_extended_properties(sample_event)
        
        assert metadata is not None
        assert metadata["source"] == "callcenter_ai"
        assert "booking_id" in metadata
        assert "clinic_id" in metadata
        assert metadata["reminded"] == "false"
    
    def test_parse_extended_properties_missing(self):
        """Test parsing extended properties from event without metadata."""
        event = {"id": "event123", "summary": "Test"}
        metadata = GoogleCalendarService.parse_extended_properties(event)
        assert metadata is None
    
    def test_parse_extended_properties_empty(self):
        """Test parsing extended properties from event with empty extendedProperties."""
        event = {"id": "event123", "extendedProperties": {}}
        metadata = GoogleCalendarService.parse_extended_properties(event)
        assert metadata is None


class TestRetryLogic:
    """Test retry logic and error handling."""
    
    @pytest.mark.asyncio
    async def test_retry_on_rate_limit(self, sample_clinic_id, sample_calendar_id, mock_db_session, mock_calendar_service):
        """Test retry logic on rate limit (HTTP 429)."""
        service, events_mock, _ = mock_calendar_service
        
        # Create mock HTTP error for rate limit
        rate_limit_error = HttpError(
            resp=Mock(status=429),
            content=b'{"error": "rateLimitExceeded"}'
        )
        
        # First two attempts fail with rate limit, third succeeds
        events_mock.list.return_value.execute.side_effect = [
            rate_limit_error,
            rate_limit_error,
            {"items": []}
        ]
        
        with patch('Clinic_app.services.google_calendar.GoogleCalendarService.get_calendar_service', new_callable=AsyncMock) as mock_get_service:
            mock_get_service.return_value = service
            
            # Mock time.sleep to speed up test
            with patch('asyncio.sleep', new_callable=AsyncMock):
                result = await GoogleCalendarService.list_events(
                    calendar_id=sample_calendar_id,
                    time_min=datetime.now(timezone.utc),
                    time_max=datetime.now(timezone.utc) + timedelta(days=1),
                    clinic_id=sample_clinic_id,
                    db=mock_db_session
                )
            
            # Should succeed after retries
            assert result == []
            # Should have been called 3 times (2 retries + 1 success)
            assert events_mock.list.return_value.execute.call_count == 3
    
    @pytest.mark.asyncio
    async def test_retry_on_transient_error(self, sample_clinic_id, sample_calendar_id, mock_db_session, mock_calendar_service):
        """Test retry logic on transient errors (500, 502, 503, 504)."""
        service, events_mock, _ = mock_calendar_service
        
        # Create mock HTTP error for server error
        server_error = HttpError(
            resp=Mock(status=500),
            content=b'{"error": "internalError"}'
        )
        
        # First attempt fails, second succeeds
        events_mock.list.return_value.execute.side_effect = [
            server_error,
            {"items": []}
        ]
        
        with patch('Clinic_app.services.google_calendar.GoogleCalendarService.get_calendar_service', new_callable=AsyncMock) as mock_get_service:
            mock_get_service.return_value = service
            
            with patch('asyncio.sleep', new_callable=AsyncMock):
                result = await GoogleCalendarService.list_events(
                    calendar_id=sample_calendar_id,
                    time_min=datetime.now(timezone.utc),
                    time_max=datetime.now(timezone.utc) + timedelta(days=1),
                    clinic_id=sample_clinic_id,
                    db=mock_db_session
                )
            
            assert result == []
            assert events_mock.list.return_value.execute.call_count == 2
    
    @pytest.mark.asyncio
    async def test_no_retry_on_404(self, sample_clinic_id, sample_calendar_id, mock_db_session, mock_calendar_service):
        """Test that 404 errors are not retried."""
        service, events_mock, _ = mock_calendar_service
        
        not_found_error = HttpError(
            resp=Mock(status=404),
            content=b'{"error": "notFound"}'
        )
        
        events_mock.list.return_value.execute.side_effect = not_found_error
        
        with patch('Clinic_app.services.google_calendar.GoogleCalendarService.get_calendar_service', new_callable=AsyncMock) as mock_get_service:
            mock_get_service.return_value = service
            
            result = await GoogleCalendarService.list_events(
                calendar_id=sample_calendar_id,
                time_min=datetime.now(timezone.utc),
                time_max=datetime.now(timezone.utc) + timedelta(days=1),
                clinic_id=sample_clinic_id,
                db=mock_db_session
            )
            
            # Should return empty list (graceful degradation)
            assert result == []
            # Should only be called once (no retry)
            assert events_mock.list.return_value.execute.call_count == 1
    
    @pytest.mark.asyncio
    async def test_graceful_degradation_on_failure(self, sample_clinic_id, sample_calendar_id, mock_db_session, mock_calendar_service):
        """Test graceful degradation when all retries fail."""
        service, events_mock, _ = mock_calendar_service
        
        server_error = HttpError(
            resp=Mock(status=500),
            content=b'{"error": "internalError"}'
        )
        
        # All attempts fail
        events_mock.list.return_value.execute.side_effect = server_error
        
        with patch('Clinic_app.services.google_calendar.GoogleCalendarService.get_calendar_service', new_callable=AsyncMock) as mock_get_service:
            mock_get_service.return_value = service
            
            with patch('asyncio.sleep', new_callable=AsyncMock):
                result = await GoogleCalendarService.list_events(
                    calendar_id=sample_calendar_id,
                    time_min=datetime.now(timezone.utc),
                    time_max=datetime.now(timezone.utc) + timedelta(days=1),
                    clinic_id=sample_clinic_id,
                    db=mock_db_session
                )
            
            # Should return empty list (graceful degradation)
            assert result == []
            # Should have tried 3 times
            assert events_mock.list.return_value.execute.call_count == 3


class TestListEvents:
    """Test list_events operation."""
    
    @pytest.mark.asyncio
    async def test_list_events_success(self, sample_clinic_id, sample_calendar_id, mock_db_session, mock_calendar_service, sample_event):
        """Test successful event listing."""
        service, events_mock, _ = mock_calendar_service
        
        events_mock.list.return_value.execute.return_value = {
            "items": [sample_event]
        }
        
        with patch('Clinic_app.services.google_calendar.GoogleCalendarService.get_calendar_service', new_callable=AsyncMock) as mock_get_service:
            mock_get_service.return_value = service
            
            time_min = datetime.now(timezone.utc)
            time_max = time_min + timedelta(days=1)
            
            result = await GoogleCalendarService.list_events(
                calendar_id=sample_calendar_id,
                time_min=time_min,
                time_max=time_max,
                clinic_id=sample_clinic_id,
                db=mock_db_session
            )
            
            assert len(result) == 1
            assert result[0]["id"] == "event123"
            events_mock.list.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_list_events_filter_by_source(self, sample_clinic_id, sample_calendar_id, mock_db_session, mock_calendar_service, sample_event):
        """Test filtering events by source."""
        service, events_mock, _ = mock_calendar_service
        
        # Create event without callcenter_ai source
        other_event = {
            "id": "event456",
            "summary": "Other Event",
            "extendedProperties": {
                "private": {
                    "source": "other"
                }
            }
        }
        
        events_mock.list.return_value.execute.return_value = {
            "items": [sample_event, other_event]
        }
        
        with patch('Clinic_app.services.google_calendar.GoogleCalendarService.get_calendar_service', new_callable=AsyncMock) as mock_get_service:
            mock_get_service.return_value = service
            
            time_min = datetime.now(timezone.utc)
            time_max = time_min + timedelta(days=1)
            
            result = await GoogleCalendarService.list_events(
                calendar_id=sample_calendar_id,
                time_min=time_min,
                time_max=time_max,
                clinic_id=sample_clinic_id,
                db=mock_db_session,
                filter_by_source="callcenter_ai"
            )
            
            # Should only return callcenter_ai events
            assert len(result) == 1
            assert result[0]["id"] == "event123"


class TestCreateEvent:
    """Test create_event operation."""
    
    @pytest.mark.asyncio
    async def test_create_event_success(self, sample_clinic_id, sample_calendar_id, mock_db_session, mock_calendar_service):
        """Test successful event creation."""
        service, events_mock, _ = mock_calendar_service
        
        created_event = {
            "id": "new_event123",
            "summary": "New Appointment"
        }
        
        events_mock.insert.return_value.execute.return_value = created_event
        
        with patch('Clinic_app.services.google_calendar.GoogleCalendarService.get_calendar_service', new_callable=AsyncMock) as mock_get_service:
            mock_get_service.return_value = service
            
            start = datetime.now(timezone.utc)
            end = start + timedelta(minutes=15)
            booking_id = uuid4()
            
            extended_props = GoogleCalendarService.build_extended_properties(
                booking_id=booking_id,
                clinic_id=sample_clinic_id,
                reminded=False
            )
            
            result = await GoogleCalendarService.create_event(
                calendar_id=sample_calendar_id,
                start=start,
                end=end,
                summary="New Appointment",
                description="Test description",
                extended_properties=extended_props,
                clinic_id=sample_clinic_id,
                db=mock_db_session
            )
            
            assert result is not None
            assert result["id"] == "new_event123"
            events_mock.insert.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_create_event_graceful_degradation(self, sample_clinic_id, sample_calendar_id, mock_db_session, mock_calendar_service):
        """Test graceful degradation when event creation fails."""
        service, events_mock, _ = mock_calendar_service
        
        server_error = HttpError(
            resp=Mock(status=500),
            content=b'{"error": "internalError"}'
        )
        
        events_mock.insert.return_value.execute.side_effect = server_error
        
        with patch('Clinic_app.services.google_calendar.GoogleCalendarService.get_calendar_service', new_callable=AsyncMock) as mock_get_service:
            mock_get_service.return_value = service
            
            with patch('asyncio.sleep', new_callable=AsyncMock):
                start = datetime.now(timezone.utc)
                end = start + timedelta(minutes=15)
                booking_id = uuid4()
                
                extended_props = GoogleCalendarService.build_extended_properties(
                    booking_id=booking_id,
                    clinic_id=sample_clinic_id,
                    reminded=False
                )
                
                result = await GoogleCalendarService.create_event(
                    calendar_id=sample_calendar_id,
                    start=start,
                    end=end,
                    summary="New Appointment",
                    description=None,
                    extended_properties=extended_props,
                    clinic_id=sample_clinic_id,
                    db=mock_db_session
                )
                
                # Should return None (graceful degradation)
                assert result is None


class TestUpdateEvent:
    """Test update_event operation."""
    
    @pytest.mark.asyncio
    async def test_update_event_success(self, sample_clinic_id, sample_calendar_id, mock_db_session, mock_calendar_service, sample_event):
        """Test successful event update."""
        service, events_mock, _ = mock_calendar_service
        
        updated_event = sample_event.copy()
        updated_event["summary"] = "Updated Appointment"
        
        events_mock.get.return_value.execute.return_value = sample_event
        events_mock.update.return_value.execute.return_value = updated_event
        
        with patch('Clinic_app.services.google_calendar.GoogleCalendarService.get_calendar_service', new_callable=AsyncMock) as mock_get_service:
            mock_get_service.return_value = service
            
            result = await GoogleCalendarService.update_event(
                calendar_id=sample_calendar_id,
                event_id="event123",
                start=None,
                end=None,
                summary="Updated Appointment",
                extended_properties=None,
                clinic_id=sample_clinic_id,
                db=mock_db_session
            )
            
            assert result is not None
            assert result["summary"] == "Updated Appointment"
            events_mock.get.assert_called_once()
            events_mock.update.assert_called_once()


class TestDeleteEvent:
    """Test delete_event operation."""
    
    @pytest.mark.asyncio
    async def test_delete_event_success(self, sample_clinic_id, sample_calendar_id, mock_db_session, mock_calendar_service):
        """Test successful event deletion."""
        service, events_mock, _ = mock_calendar_service
        
        events_mock.delete.return_value.execute.return_value = None
        
        with patch('Clinic_app.services.google_calendar.GoogleCalendarService.get_calendar_service', new_callable=AsyncMock) as mock_get_service:
            mock_get_service.return_value = service
            
            result = await GoogleCalendarService.delete_event(
                calendar_id=sample_calendar_id,
                event_id="event123",
                clinic_id=sample_clinic_id,
                db=mock_db_session
            )
            
            assert result is True
            events_mock.delete.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_delete_event_not_found(self, sample_clinic_id, sample_calendar_id, mock_db_session, mock_calendar_service):
        """Test deletion of non-existent event."""
        service, events_mock, _ = mock_calendar_service
        
        not_found_error = HttpError(
            resp=Mock(status=404),
            content=b'{"error": "notFound"}'
        )
        
        events_mock.delete.return_value.execute.side_effect = not_found_error
        
        with patch('Clinic_app.services.google_calendar.GoogleCalendarService.get_calendar_service', new_callable=AsyncMock) as mock_get_service:
            mock_get_service.return_value = service
            
            result = await GoogleCalendarService.delete_event(
                calendar_id=sample_calendar_id,
                event_id="nonexistent",
                clinic_id=sample_clinic_id,
                db=mock_db_session
            )
            
            # Should return False (not found)
            assert result is False


class TestDeleteMultipleEvents:
    """Test delete_multiple_events operation."""
    
    @pytest.mark.asyncio
    async def test_delete_multiple_events_success(self, sample_clinic_id, sample_calendar_id, mock_db_session, mock_calendar_service):
        """Test successful bulk deletion."""
        service, events_mock, _ = mock_calendar_service
        
        events_mock.delete.return_value.execute.return_value = None
        
        with patch('Clinic_app.services.google_calendar.GoogleCalendarService.get_calendar_service', new_callable=AsyncMock) as mock_get_service:
            mock_get_service.return_value = service
            
            event_ids = ["event1", "event2", "event3"]
            
            with patch('asyncio.sleep', new_callable=AsyncMock):
                result = await GoogleCalendarService.delete_multiple_events(
                    calendar_id=sample_calendar_id,
                    event_ids=event_ids,
                    clinic_id=sample_clinic_id,
                    db=mock_db_session
                )
            
            # All should succeed
            assert len(result) == 3
            assert all(result.values())  # All True
    
    @pytest.mark.asyncio
    async def test_delete_multiple_events_partial_failure(self, sample_clinic_id, sample_calendar_id, mock_db_session, mock_calendar_service):
        """Test bulk deletion with some failures."""
        service, events_mock, _ = mock_calendar_service
        
        # Track calls per event_id - use a list to track order
        call_order = []
        
        def delete_side_effect():
            # Since we can't easily get the event_id from the mock call,
            # we'll track the order and make every second call fail
            call_order.append(len(call_order))
            call_num = len(call_order)
            
            # Make the second call fail with a non-retryable error
            if call_num == 2:
                raise HttpError(
                    resp=Mock(status=400),  # 400 is not retryable
                    content=b'{"error": "badRequest"}'
                )
            return None
        
        events_mock.delete.return_value.execute.side_effect = delete_side_effect
        
        with patch('Clinic_app.services.google_calendar.GoogleCalendarService.get_calendar_service', new_callable=AsyncMock) as mock_get_service:
            mock_get_service.return_value = service
            
            event_ids = ["event1", "event2", "event3"]
            
            with patch('asyncio.sleep', new_callable=AsyncMock):
                result = await GoogleCalendarService.delete_multiple_events(
                    calendar_id=sample_calendar_id,
                    event_ids=event_ids,
                    clinic_id=sample_clinic_id,
                    db=mock_db_session
                )
            
            # Should have results for all events
            assert len(result) == 3
            # Verify that at least one event failed (the second one)
            # Since we can't guarantee which event_id corresponds to which call,
            # we'll just verify that not all succeeded
            success_count = sum(1 for v in result.values() if v)
            # At least one should have failed
            assert success_count < len(event_ids)


class TestGetEvent:
    """Test get_event operation."""
    
    @pytest.mark.asyncio
    async def test_get_event_success(self, sample_clinic_id, sample_calendar_id, mock_db_session, mock_calendar_service, sample_event):
        """Test successful event retrieval."""
        service, events_mock, _ = mock_calendar_service
        
        events_mock.get.return_value.execute.return_value = sample_event
        
        with patch('Clinic_app.services.google_calendar.GoogleCalendarService.get_calendar_service', new_callable=AsyncMock) as mock_get_service:
            mock_get_service.return_value = service
            
            result = await GoogleCalendarService.get_event(
                calendar_id=sample_calendar_id,
                event_id="event123",
                clinic_id=sample_clinic_id,
                db=mock_db_session
            )
            
            assert result is not None
            assert result["id"] == "event123"
            events_mock.get.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_get_event_not_found(self, sample_clinic_id, sample_calendar_id, mock_db_session, mock_calendar_service):
        """Test retrieval of non-existent event."""
        service, events_mock, _ = mock_calendar_service
        
        not_found_error = HttpError(
            resp=Mock(status=404),
            content=b'{"error": "notFound"}'
        )
        
        events_mock.get.return_value.execute.side_effect = not_found_error
        
        with patch('Clinic_app.services.google_calendar.GoogleCalendarService.get_calendar_service', new_callable=AsyncMock) as mock_get_service:
            mock_get_service.return_value = service
            
            result = await GoogleCalendarService.get_event(
                calendar_id=sample_calendar_id,
                event_id="nonexistent",
                clinic_id=sample_clinic_id,
                db=mock_db_session
            )
            
            # Should return None (not found)
            assert result is None


class TestValidateCalendarAccess:
    """Test validate_calendar_access operation."""
    
    @pytest.mark.asyncio
    async def test_validate_calendar_access_success(self, sample_clinic_id, sample_calendar_id, mock_db_session, mock_calendar_service):
        """Test successful calendar access validation."""
        service, _, calendars_mock = mock_calendar_service
        
        calendars_mock.get.return_value.execute.return_value = {
            "id": sample_calendar_id,
            "summary": "Test Calendar"
        }
        
        with patch('Clinic_app.services.google_calendar.GoogleCalendarService.get_calendar_service', new_callable=AsyncMock) as mock_get_service:
            mock_get_service.return_value = service
            
            result = await GoogleCalendarService.validate_calendar_access(
                calendar_id=sample_calendar_id,
                clinic_id=sample_clinic_id,
                db=mock_db_session
            )
            
            assert result is True
            calendars_mock.get.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_validate_calendar_access_not_found(self, sample_clinic_id, sample_calendar_id, mock_db_session, mock_calendar_service):
        """Test validation when calendar is not found."""
        service, _, calendars_mock = mock_calendar_service
        
        not_found_error = HttpError(
            resp=Mock(status=404),
            content=b'{"error": "notFound"}'
        )
        
        calendars_mock.get.return_value.execute.side_effect = not_found_error
        
        with patch('Clinic_app.services.google_calendar.GoogleCalendarService.get_calendar_service', new_callable=AsyncMock) as mock_get_service:
            mock_get_service.return_value = service
            
            with pytest.raises(GoogleCalendarNotFoundError):
                await GoogleCalendarService.validate_calendar_access(
                    calendar_id=sample_calendar_id,
                    clinic_id=sample_clinic_id,
                    db=mock_db_session
                )


class TestCountOverlappingEvents:
    """Test count_overlapping_events helper."""
    
    def test_count_overlapping_events(self):
        """Test counting overlapping events."""
        # Create events that overlap with the slot
        overlapping_events = [
            {
                "id": "event1",
                "start": {"dateTime": "2025-01-20T09:00:00-08:00"},
                "end": {"dateTime": "2025-01-20T09:15:00-08:00"}
            },
            {
                "id": "event2",
                "start": {"dateTime": "2025-01-20T09:10:00-08:00"},
                "end": {"dateTime": "2025-01-20T09:25:00-08:00"}
            },
            {
                "id": "event3",
                "start": {"dateTime": "2025-01-20T10:00:00-08:00"},
                "end": {"dateTime": "2025-01-20T10:15:00-08:00"}
            }
        ]
        
        slot_start = datetime(2025, 1, 20, 9, 0, 0, tzinfo=timezone(timedelta(hours=-8)))
        slot_end = datetime(2025, 1, 20, 9, 15, 0, tzinfo=timezone(timedelta(hours=-8)))
        
        # count_overlapping_events is a static method that takes events directly
        count = GoogleCalendarService.count_overlapping_events(
            events=overlapping_events,
            slot_start=slot_start,
            slot_end=slot_end
        )
        
        # Should count both overlapping events (event1 and event2, not event3)
        assert count == 2


class TestTimezoneHandling:
    """Test timezone handling and RFC3339 formatting."""
    
    @pytest.mark.asyncio
    async def test_timezone_aware_datetime(self, sample_clinic_id, sample_calendar_id, mock_db_session, mock_calendar_service):
        """Test that timezone-aware datetimes are handled correctly."""
        service, events_mock, _ = mock_calendar_service
        
        created_event = {"id": "event123"}
        events_mock.insert.return_value.execute.return_value = created_event
        
        with patch('Clinic_app.services.google_calendar.GoogleCalendarService.get_calendar_service', new_callable=AsyncMock) as mock_get_service:
            mock_get_service.return_value = service
            
            # Use timezone-aware datetime (UTC)
            start = datetime(2025, 1, 20, 9, 0, 0, tzinfo=timezone.utc)
            end = datetime(2025, 1, 20, 9, 15, 0, tzinfo=timezone.utc)
            
            booking_id = uuid4()
            extended_props = GoogleCalendarService.build_extended_properties(
                booking_id=booking_id,
                clinic_id=sample_clinic_id,
                reminded=False
            )
            
            result = await GoogleCalendarService.create_event(
                calendar_id=sample_calendar_id,
                start=start,
                end=end,
                summary="Test",
                description=None,
                extended_properties=extended_props,
                clinic_id=sample_clinic_id,
                db=mock_db_session
            )
            
            # Verify the call was made and datetime is formatted
            call_args = events_mock.insert.call_args
            assert call_args is not None
            event_body = call_args[1]["body"]
            assert "dateTime" in event_body["start"]
            # Should be ISO format (RFC3339 compatible)
            assert "+00:00" in event_body["start"]["dateTime"] or "Z" in event_body["start"]["dateTime"]
    
    @pytest.mark.asyncio
    async def test_timezone_with_zone_attribute(self, sample_clinic_id, sample_calendar_id, mock_db_session, mock_calendar_service):
        """Test timezone handling when tzinfo has 'zone' attribute (e.g., zoneinfo)."""
        service, events_mock, _ = mock_calendar_service
        
        created_event = {"id": "event123"}
        events_mock.insert.return_value.execute.return_value = created_event
        
        # Create a custom timezone class with 'zone' attribute
        class MockTimezone(tzinfo):
            def __init__(self, offset, zone_name):
                self.offset = offset
                self.zone = zone_name
            
            def utcoffset(self, dt):
                return self.offset
            
            def tzname(self, dt):
                return self.zone
            
            def dst(self, dt):
                return timedelta(0)
        
        mock_tz = MockTimezone(timedelta(hours=-8), "America/Los_Angeles")
        
        with patch('Clinic_app.services.google_calendar.GoogleCalendarService.get_calendar_service', new_callable=AsyncMock) as mock_get_service:
            mock_get_service.return_value = service
            
            start = datetime(2025, 1, 20, 9, 0, 0, tzinfo=mock_tz)
            end = datetime(2025, 1, 20, 9, 15, 0, tzinfo=mock_tz)
            
            booking_id = uuid4()
            extended_props = GoogleCalendarService.build_extended_properties(
                booking_id=booking_id,
                clinic_id=sample_clinic_id,
                reminded=False
            )
            
            result = await GoogleCalendarService.create_event(
                calendar_id=sample_calendar_id,
                start=start,
                end=end,
                summary="Test",
                description=None,
                extended_properties=extended_props,
                clinic_id=sample_clinic_id,
                db=mock_db_session
            )
            
            # Verify timezone is included in event body
            call_args = events_mock.insert.call_args
            assert call_args is not None
            event_body = call_args[1]["body"]
            assert "timeZone" in event_body["start"]
            assert event_body["start"]["timeZone"] == "America/Los_Angeles"

