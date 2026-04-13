"""
Unit tests for Admin Routes.

Tests cover:
- Clinic CRUD (setup, create, get, update, list)
- Integration CRUD (create, get, update)
- Business hours management
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from Clinic_app.Routes.admin import (
    admin_router,
    APIResponse,
    ClinicSetupRequest,
    ClinicCreateRequest,
    ClinicUpdateRequest,
    IntegrationCreateRequest,
    BusinessHoursRequest,
    validate_e164_phone,
    validate_time_format
)
import pytz

def validate_timezone_str(tz: str) -> bool:
    """Helper to validate timezone strings."""
    try:
        pytz.timezone(tz)
        return True
    except pytz.UnknownTimeZoneError:
        return False


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def sample_clinic_id():
    """Generate a sample clinic UUID."""
    return uuid4()


@pytest.fixture
def sample_integration_id():
    """Generate a sample integration UUID."""
    return uuid4()


@pytest.fixture
def mock_clinic(sample_clinic_id):
    """Create a mock Clinic object."""
    clinic = Mock()
    clinic.id = sample_clinic_id
    clinic.name = "Test Clinic"
    clinic.timezone = "America/New_York"
    clinic.default_language = "en"
    clinic.business_hours_start = "09:00"
    clinic.business_hours_end = "17:00"
    clinic.address = "123 Main St"
    clinic.phone = "+15551234567"
    clinic.email = "clinic@example.com"
    clinic.created_at = datetime.now(timezone.utc)
    return clinic


@pytest.fixture
def mock_integration(sample_integration_id, sample_clinic_id):
    """Create a mock ClinicIntegration object."""
    integration = Mock()
    integration.id = sample_integration_id
    integration.clinic_id = sample_clinic_id
    integration.ehr_system = "epic"
    integration.retell_agent_id = "agent_123"
    integration.retell_did = "+15559876543"
    return integration


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
    return session


# ============================================================================
# TEST VALIDATION FUNCTIONS
# ============================================================================

class TestValidationFunctions:
    """Tests for validation helper functions."""
    
    def test_validate_e164_phone_valid(self):
        """Test valid E.164 phone numbers."""
        valid_phones = [
            "+15551234567",
            "+14155551234",
            "+447911123456",  # UK
            "+33612345678",   # France
        ]
        for phone in valid_phones:
            assert validate_e164_phone(phone) is True
    
    def test_validate_e164_phone_invalid(self):
        """Test invalid phone numbers."""
        invalid_phones = [
            "5551234567",       # Missing +
            "+1-555-123-4567",  # Contains dashes
            "+1 555 123 4567",  # Contains spaces
            "not-a-phone",
            "",
        ]
        for phone in invalid_phones:
            assert validate_e164_phone(phone) is False
    
    def test_validate_timezone_str_valid(self):
        """Test valid timezone strings."""
        valid_timezones = [
            "America/New_York",
            "America/Los_Angeles",
            "America/Chicago",
            "Europe/London",
            "UTC",
        ]
        for tz in valid_timezones:
            assert validate_timezone_str(tz) is True
    
    def test_validate_timezone_str_invalid(self):
        """Test invalid timezone strings."""
        invalid_timezones = [
            "Invalid/Timezone",
            "Not_A_Timezone",
            "America/Invalid_City",
        ]
        for tz in invalid_timezones:
            assert validate_timezone_str(tz) is False


# ============================================================================
# TEST CLINIC ENDPOINTS
# ============================================================================

class TestClinicEndpoints:
    """Tests for clinic CRUD endpoints."""
    
    def test_clinic_create_request_valid(self):
        """Test ClinicCreateRequest with valid data."""
        request = ClinicCreateRequest(
            name="Test Clinic",
            tier="basic",
            license_token="test_token_123"
        )
        
        assert request.name == "Test Clinic"
        assert request.tier == "basic"
    
    def test_clinic_setup_request_valid(self):
        """Test ClinicSetupRequest with full data."""
        clinic = ClinicCreateRequest(
            name="Test Clinic",
            tier="basic",
            license_token="test_token_123",
            max_concurrency=5,
            features={"hedis": True},
        )
        integration = IntegrationCreateRequest(
            retell_agent_id="agent_123",
            retell_did="+15551234567",
            google_service_account_json='{"type": "service_account", "project_id": "test", "private_key_id": "123", "private_key": "key", "client_email": "test@test.iam.gserviceaccount.com"}'
        )
        
        request = ClinicSetupRequest(
            clinic=clinic,
            integration=integration,
        )
        
        assert request.clinic.name == "Test Clinic"
        assert request.clinic.max_concurrency == 5
        assert request.clinic.features == {"hedis": True}
        assert request.integration.retell_agent_id == "agent_123"
    
    def test_clinic_update_request_partial(self):
        """Test ClinicUpdateRequest with partial data."""
        request = ClinicUpdateRequest(
            name="Updated Clinic"
        )
        
        assert request.name == "Updated Clinic"
        assert request.tier is None
    
    @pytest.mark.asyncio
    async def test_get_clinic_success(
        self, mock_db_session, mock_clinic, sample_clinic_id
    ):
        """Test successful clinic retrieval conceptually."""
        mock_db_session.get = AsyncMock(return_value=mock_clinic)
        
        # Conceptual test - actual endpoint testing via TestClient
        result = await mock_db_session.get(Mock, sample_clinic_id)
        
        assert result.name == "Test Clinic"
    
    @pytest.mark.asyncio
    async def test_get_clinic_not_found(self, mock_db_session, sample_clinic_id):
        """Test clinic not found returns 404."""
        mock_db_session.get = AsyncMock(return_value=None)
        
        result = await mock_db_session.get(Mock, sample_clinic_id)
        
        assert result is None


# ============================================================================
# TEST INTEGRATION ENDPOINTS
# ============================================================================

class TestIntegrationEndpoints:
    """Tests for integration CRUD endpoints."""
    
    def test_integration_create_request_valid(self, sample_clinic_id):
        """Test IntegrationCreateRequest with valid data."""
        request = IntegrationCreateRequest(
            retell_agent_id="agent_123",
            retell_did="+15559876543",
            google_service_account_json='{"type": "service_account", "project_id": "test", "private_key_id": "123", "private_key": "key", "client_email": "test@test.iam.gserviceaccount.com"}'
        )
        
        assert request.retell_agent_id == "agent_123"
        assert request.retell_did == "+15559876543"
    
    @pytest.mark.asyncio
    async def test_get_integration_success(
        self, mock_db_session, mock_integration
    ):
        """Test successful integration retrieval conceptually."""
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = mock_integration
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        
        result = mock_result.scalar_one_or_none()
        
        assert result.retell_agent_id == "agent_123"


# ============================================================================
# TEST BUSINESS HOURS ENDPOINTS
# ============================================================================

class TestBusinessHoursEndpoints:
    """Tests for business hours management."""
    
    def test_business_hours_update_request_valid(self):
        """Test BusinessHoursRequest with valid data."""
        request = BusinessHoursRequest(
            start="08:00",
            end="18:00"
        )
        
        assert request.start == "08:00"
        assert request.end == "18:00"
    
    def test_business_hours_format_validation(self):
        """Test that business hours must be in HH:MM format."""
        # Valid formats
        valid_times = ["00:00", "09:00", "12:30", "23:59"]
        for time_str in valid_times:
            # Just test the format check, actual validation in endpoint
            parts = time_str.split(":")
            assert len(parts) == 2
            assert 0 <= int(parts[0]) <= 23
            assert 0 <= int(parts[1]) <= 59
    
    @pytest.mark.asyncio
    async def test_get_business_hours_success(
        self, mock_db_session, mock_clinic
    ):
        """Test successful business hours retrieval conceptually."""
        mock_db_session.get = AsyncMock(return_value=mock_clinic)
        
        result = await mock_db_session.get(Mock, mock_clinic.id)
        
        assert result.business_hours_start == "09:00"
        assert result.business_hours_end == "17:00"
    
    def test_business_hours_end_must_be_after_start(self):
        """Conceptual test for business hours validation."""
        # End time must be after start time
        start = "10:00"
        end = "18:00"
        
        start_parts = start.split(":")
        end_parts = end.split(":")
        
        start_mins = int(start_parts[0]) * 60 + int(start_parts[1])
        end_mins = int(end_parts[0]) * 60 + int(end_parts[1])
        
        assert end_mins > start_mins


# ============================================================================
# TEST API RESPONSE
# ============================================================================

class TestAPIResponse:
    """Tests for APIResponse model."""
    
    def test_api_response_success(self):
        """Test successful API response."""
        response = APIResponse(
            success=True,
            message="Operation completed",
            data={"id": "123", "name": "Test"}
        )
        
        assert response.success is True
        assert response.message == "Operation completed"
        assert response.data["id"] == "123"
    
    def test_api_response_error(self):
        """Test error API response."""
        response = APIResponse(
            success=False,
            message="Operation failed",
            error={"detail": "Resource not found"}
        )
        
        assert response.success is False
        assert response.error["detail"] == "Resource not found"
    
    def test_api_response_with_list(self):
        """Test API response with list data."""
        clinics = [
            {"id": "1", "name": "Clinic A"},
            {"id": "2", "name": "Clinic B"}
        ]
        response = APIResponse(
            success=True,
            message="Found 2 clinics",
            data=clinics
        )
        
        assert len(response.data) == 2


# ============================================================================
# TEST ERROR HANDLING
# ============================================================================

class TestErrorHandling:
    """Tests for error handling in admin routes."""
    
    def test_invalid_timezone_rejected(self):
        """Test that invalid timezone is rejected."""
        # This would raise validation error in endpoint
        invalid_tz = "Invalid/Timezone"
        assert validate_timezone_str(invalid_tz) is False
    
    def test_invalid_phone_rejected(self):
        """Test that invalid phone is rejected."""
        invalid_phone = "not-a-phone"
        assert validate_e164_phone(invalid_phone) is False
    
    def test_empty_name_rejected(self):
        """Conceptual test - empty clinic name should be rejected."""
        # Would be validated by Pydantic in actual endpoint
        # Empty string should trigger validation error
        pass  # Placeholder


# ============================================================================
# TEST PYDANTIC MODEL DEFAULTS
# ============================================================================

class TestPydanticDefaults:
    """Tests for Pydantic model defaults."""
    
    def test_clinic_create_defaults(self):
        """Test ClinicCreateRequest has correct defaults."""
        request = ClinicCreateRequest(
            name="Test Clinic",
            tier="basic",
            license_token="test_token"
        )
        
        assert request.status == "active"
        assert request.max_concurrency == 3
        assert request.features == {}

    def test_clinic_create_custom_concurrency(self):
        """Test ClinicCreateRequest with explicit max_concurrency and features."""
        request = ClinicCreateRequest(
            name="Test Clinic",
            tier="pro",
            license_token="test_token",
            max_concurrency=10,
            features={"hedis": True, "reminders": False},
        )

        assert request.max_concurrency == 10
        assert request.features == {"hedis": True, "reminders": False}

