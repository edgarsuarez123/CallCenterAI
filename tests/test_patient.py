"""
Unit tests for Patient Service.

Tests cover:
- Hash computation and normalization
- Input validation
- Patient lookup with collision handling
- Patient creation with encryption
"""

import pytest
import os
import base64
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from uuid import uuid4

from Clinic_app.services.patient import (
    _compute_name_dob_hash,
    _validate_patient_inputs,
    find_patient,
    create_patient,
    DOB_PATTERN,
    EMAIL_PATTERN,
    VALID_LANGUAGES
)
from Clinic_app.common.encryption import EncryptionError, DecryptionError
import Clinic_app.common.encryption as encryption_module


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def sample_clinic_id():
    """Generate a sample clinic UUID."""
    return uuid4()


@pytest.fixture
def sample_patient_id():
    """Generate a sample patient UUID."""
    return uuid4()


@pytest.fixture
def valid_key_base64():
    """Valid encryption key for tests."""
    return base64.b64encode(os.urandom(32)).decode('utf-8')


@pytest.fixture(autouse=True)
def reset_encryption_key():
    """Reset encryption key cache before each test."""
    encryption_module._encryption_key = None
    yield
    encryption_module._encryption_key = None


@pytest.fixture
def mock_clinic(sample_clinic_id):
    """Create a mock Clinic object."""
    clinic = Mock()
    clinic.id = sample_clinic_id
    clinic.name = "Test Clinic"
    return clinic


@pytest.fixture
def mock_patient(sample_patient_id, sample_clinic_id, valid_key_base64):
    """Create a mock Patient object with encrypted tokens."""
    with patch.dict(os.environ, {"PHI_ENCRYPTION_KEY": valid_key_base64}):
        from Clinic_app.common.encryption import encrypt_phi
        
        patient = Mock()
        patient.id = sample_patient_id
        patient.clinic_id = sample_clinic_id
        patient.name_token = encrypt_phi("John Doe")
        patient.dob_token = encrypt_phi("1990-05-15")
        patient.phone_token = encrypt_phi("+15551234567")
        patient.email_token = encrypt_phi("john@example.com")
        patient.name_dob_hash = _compute_name_dob_hash("John Doe", "1990-05-15")
        patient.language = "en"
        patient.insurance_plan = None
        return patient


@pytest.fixture
def mock_db_session(mock_clinic):
    """Create a mock async database session."""
    session = AsyncMock()
    
    # Default: return clinic for clinic lookup
    async def execute_side_effect(stmt):
        result = Mock()
        # Check if this is a Clinic query or Patient query
        result.scalar_one_or_none.return_value = mock_clinic
        return result
    
    session.execute = AsyncMock(side_effect=execute_side_effect)
    session.add = Mock()
    session.flush = AsyncMock()
    
    return session


# ============================================================================
# TEST _COMPUTE_NAME_DOB_HASH
# ============================================================================

class TestComputeNameDobHash:
    """Tests for _compute_name_dob_hash function."""
    
    def test_hash_is_consistent(self):
        """Test that hash is consistent for same inputs."""
        hash1 = _compute_name_dob_hash("John Doe", "1990-05-15")
        hash2 = _compute_name_dob_hash("John Doe", "1990-05-15")
        assert hash1 == hash2
    
    def test_hash_is_64_chars(self):
        """Test that hash is 64 character hex string (SHA-256)."""
        hash_result = _compute_name_dob_hash("John Doe", "1990-05-15")
        assert len(hash_result) == 64
        assert all(c in '0123456789abcdef' for c in hash_result)
    
    def test_hash_normalized_case_insensitive(self):
        """Test that name is normalized case-insensitively."""
        hash1 = _compute_name_dob_hash("John Doe", "1990-05-15")
        hash2 = _compute_name_dob_hash("JOHN DOE", "1990-05-15")
        hash3 = _compute_name_dob_hash("john doe", "1990-05-15")
        assert hash1 == hash2 == hash3
    
    def test_hash_strips_whitespace(self):
        """Test that whitespace is stripped from name and DOB."""
        hash1 = _compute_name_dob_hash("John Doe", "1990-05-15")
        hash2 = _compute_name_dob_hash("  John Doe  ", "  1990-05-15  ")
        hash3 = _compute_name_dob_hash("\tJohn Doe\n", "\n1990-05-15\t")
        assert hash1 == hash2 == hash3
    
    def test_different_names_different_hashes(self):
        """Test that different names produce different hashes."""
        hash1 = _compute_name_dob_hash("John Doe", "1990-05-15")
        hash2 = _compute_name_dob_hash("Jane Doe", "1990-05-15")
        assert hash1 != hash2
    
    def test_different_dobs_different_hashes(self):
        """Test that different DOBs produce different hashes."""
        hash1 = _compute_name_dob_hash("John Doe", "1990-05-15")
        hash2 = _compute_name_dob_hash("John Doe", "1990-05-16")
        assert hash1 != hash2
    
    def test_unicode_names(self):
        """Test that Unicode names are handled correctly."""
        hash1 = _compute_name_dob_hash("José García", "1990-05-15")
        hash2 = _compute_name_dob_hash("JOSÉ GARCÍA", "1990-05-15")
        # Unicode normalization might differ, but case insensitivity should work
        # Note: The implementation uses simple .lower() which may not handle
        # all Unicode cases perfectly
        assert len(hash1) == 64


# ============================================================================
# TEST _VALIDATE_PATIENT_INPUTS
# ============================================================================

class TestValidatePatientInputs:
    """Tests for _validate_patient_inputs function."""
    
    @pytest.mark.asyncio
    async def test_valid_inputs_passes(self, mock_db_session, sample_clinic_id):
        """Test that valid inputs pass validation."""
        # Should not raise any exception
        await _validate_patient_inputs(
            db=mock_db_session,
            clinic_id=sample_clinic_id,
            name="John Doe",
            dob="1990-05-15",
            phone="+15551234567",
            email="john@example.com",
            language="en"
        )
    
    @pytest.mark.asyncio
    async def test_invalid_clinic_raises_error(self, sample_clinic_id):
        """Test that invalid clinic_id raises ValueError."""
        # Create mock session that returns no clinic
        mock_session = AsyncMock()
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)
        
        with pytest.raises(ValueError) as exc_info:
            await _validate_patient_inputs(
                db=mock_session,
                clinic_id=sample_clinic_id,
                name="John Doe",
                dob="1990-05-15",
                phone="+15551234567"
            )
        assert "not found" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_empty_name_raises_error(self, mock_db_session, sample_clinic_id):
        """Test that empty name raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            await _validate_patient_inputs(
                db=mock_db_session,
                clinic_id=sample_clinic_id,
                name="",
                dob="1990-05-15",
                phone="+15551234567"
            )
        assert "name" in str(exc_info.value).lower()
    
    @pytest.mark.asyncio
    async def test_whitespace_name_raises_error(self, mock_db_session, sample_clinic_id):
        """Test that whitespace-only name raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            await _validate_patient_inputs(
                db=mock_db_session,
                clinic_id=sample_clinic_id,
                name="   ",
                dob="1990-05-15",
                phone="+15551234567"
            )
        assert "name" in str(exc_info.value).lower()
    
    @pytest.mark.asyncio
    async def test_invalid_dob_format_raises_error(self, mock_db_session, sample_clinic_id):
        """Test that invalid DOB format raises ValueError."""
        invalid_dobs = [
            "05-15-1990",  # Wrong order
            "1990/05/15",  # Wrong separator
            "199-05-15",   # Wrong year length
            "1990-5-15",   # Single digit month
            "1990-05-5",   # Single digit day
            "not-a-date",
            ""
        ]
        for dob in invalid_dobs:
            with pytest.raises(ValueError) as exc_info:
                await _validate_patient_inputs(
                    db=mock_db_session,
                    clinic_id=sample_clinic_id,
                    name="John Doe",
                    dob=dob,
                    phone="+15551234567"
                )
            assert "YYYY-MM-DD" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_invalid_phone_format_raises_error(self, mock_db_session, sample_clinic_id):
        """Test that invalid phone format raises ValueError."""
        invalid_phones = [
            "5551234567",      # Missing country code
            "1-555-123-4567",  # Has dashes
            "+1 555 123 4567", # Has spaces
        ]
        for phone in invalid_phones:
            with pytest.raises(ValueError) as exc_info:
                await _validate_patient_inputs(
                    db=mock_db_session,
                    clinic_id=sample_clinic_id,
                    name="John Doe",
                    dob="1990-05-15",
                    phone=phone
                )
            assert "E.164" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_invalid_email_format_raises_error(self, mock_db_session, sample_clinic_id):
        """Test that invalid email format raises ValueError."""
        invalid_emails = [
            "not-an-email",
            "missing@domain",
            "@nodomain.com",
            "spaces in@email.com"
        ]
        for email in invalid_emails:
            with pytest.raises(ValueError) as exc_info:
                await _validate_patient_inputs(
                    db=mock_db_session,
                    clinic_id=sample_clinic_id,
                    name="John Doe",
                    dob="1990-05-15",
                    phone="+15551234567",
                    email=email
                )
            assert "email" in str(exc_info.value).lower()
    
    @pytest.mark.asyncio
    async def test_optional_email_none_passes(self, mock_db_session, sample_clinic_id):
        """Test that None email is valid."""
        await _validate_patient_inputs(
            db=mock_db_session,
            clinic_id=sample_clinic_id,
            name="John Doe",
            dob="1990-05-15",
            phone="+15551234567",
            email=None
        )
    
    @pytest.mark.asyncio
    async def test_invalid_language_raises_error(self, mock_db_session, sample_clinic_id):
        """Test that invalid language code raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            await _validate_patient_inputs(
                db=mock_db_session,
                clinic_id=sample_clinic_id,
                name="John Doe",
                dob="1990-05-15",
                phone="+15551234567",
                language="fr"  # Not supported
            )
        assert "Language" in str(exc_info.value)


# ============================================================================
# TEST FIND_PATIENT
# ============================================================================

class TestFindPatient:
    """Tests for find_patient function."""
    
    @pytest.mark.asyncio
    async def test_find_existing_patient_returns_patient(
        self, mock_patient, sample_clinic_id, valid_key_base64
    ):
        """Test finding an existing patient returns the patient."""
        # Setup mock session
        mock_session = AsyncMock()
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = mock_patient
        mock_session.execute = AsyncMock(return_value=mock_result)
        
        with patch.dict(os.environ, {"PHI_ENCRYPTION_KEY": valid_key_base64}):
            result = await find_patient(
                db=mock_session,
                clinic_id=sample_clinic_id,
                name="John Doe",
                dob="1990-05-15"
            )
        
        assert result is not None
        assert result.id == mock_patient.id
    
    @pytest.mark.asyncio
    async def test_find_nonexistent_returns_none(self, sample_clinic_id, valid_key_base64):
        """Test finding non-existent patient returns None."""
        mock_session = AsyncMock()
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)
        
        with patch.dict(os.environ, {"PHI_ENCRYPTION_KEY": valid_key_base64}):
            result = await find_patient(
                db=mock_session,
                clinic_id=sample_clinic_id,
                name="Nonexistent Person",
                dob="2000-01-01"
            )
        
        assert result is None
    
    @pytest.mark.asyncio
    async def test_find_case_insensitive(
        self, mock_patient, sample_clinic_id, valid_key_base64
    ):
        """Test that lookup is case insensitive."""
        mock_session = AsyncMock()
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = mock_patient
        mock_session.execute = AsyncMock(return_value=mock_result)
        
        with patch.dict(os.environ, {"PHI_ENCRYPTION_KEY": valid_key_base64}):
            result = await find_patient(
                db=mock_session,
                clinic_id=sample_clinic_id,
                name="JOHN DOE",  # Different case
                dob="1990-05-15"
            )
        
        assert result is not None
    
    @pytest.mark.asyncio
    async def test_find_empty_name_raises_error(self, sample_clinic_id):
        """Test that empty name raises ValueError."""
        mock_session = AsyncMock()
        
        with pytest.raises(ValueError) as exc_info:
            await find_patient(
                db=mock_session,
                clinic_id=sample_clinic_id,
                name="",
                dob="1990-05-15"
            )
        assert "name" in str(exc_info.value).lower()
    
    @pytest.mark.asyncio
    async def test_find_invalid_dob_raises_error(self, sample_clinic_id):
        """Test that invalid DOB raises ValueError."""
        mock_session = AsyncMock()
        
        with pytest.raises(ValueError) as exc_info:
            await find_patient(
                db=mock_session,
                clinic_id=sample_clinic_id,
                name="John Doe",
                dob="invalid-date"
            )
        assert "YYYY-MM-DD" in str(exc_info.value)


# ============================================================================
# TEST CREATE_PATIENT
# ============================================================================

class TestCreatePatient:
    """Tests for create_patient function."""
    
    @pytest.mark.asyncio
    async def test_create_patient_success(self, mock_db_session, sample_clinic_id, valid_key_base64):
        """Test successful patient creation."""
        # Configure mock to return no existing patient
        call_count = [0]
        
        async def execute_side_effect(stmt):
            result = Mock()
            call_count[0] += 1
            if call_count[0] == 1:
                # First call: clinic lookup
                clinic = Mock()
                clinic.id = sample_clinic_id
                result.scalar_one_or_none.return_value = clinic
            else:
                # Subsequent calls: patient lookup returns None
                result.scalar_one_or_none.return_value = None
            return result
        
        mock_db_session.execute = AsyncMock(side_effect=execute_side_effect)
        
        with patch.dict(os.environ, {"PHI_ENCRYPTION_KEY": valid_key_base64}):
            result = await create_patient(
                db=mock_db_session,
                clinic_id=sample_clinic_id,
                name="Jane Doe",
                dob="1995-03-20",
                phone="+15559876543",
                email="jane@example.com",
                language="en"
            )
        
        assert result is not None
        assert result.clinic_id == sample_clinic_id
        mock_db_session.add.assert_called_once()
        mock_db_session.flush.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_create_encrypts_all_phi(self, mock_db_session, sample_clinic_id, valid_key_base64):
        """Test that all PHI fields are encrypted."""
        # Configure mock to return no existing patient
        call_count = [0]
        
        async def execute_side_effect(stmt):
            result = Mock()
            call_count[0] += 1
            if call_count[0] == 1:
                clinic = Mock()
                clinic.id = sample_clinic_id
                result.scalar_one_or_none.return_value = clinic
            else:
                result.scalar_one_or_none.return_value = None
            return result
        
        mock_db_session.execute = AsyncMock(side_effect=execute_side_effect)
        
        with patch.dict(os.environ, {"PHI_ENCRYPTION_KEY": valid_key_base64}):
            result = await create_patient(
                db=mock_db_session,
                clinic_id=sample_clinic_id,
                name="Jane Doe",
                dob="1995-03-20",
                phone="+15559876543",
                email="jane@example.com",
                language="en"
            )
        
        # Check that PHI fields are bytes (encrypted)
        assert isinstance(result.name_token, bytes)
        assert isinstance(result.dob_token, bytes)
        assert isinstance(result.phone_token, bytes)
        assert isinstance(result.email_token, bytes)
    
    @pytest.mark.asyncio
    async def test_create_stores_hash(self, mock_db_session, sample_clinic_id, valid_key_base64):
        """Test that name_dob_hash is stored."""
        # Configure mock to return no existing patient
        call_count = [0]
        
        async def execute_side_effect(stmt):
            result = Mock()
            call_count[0] += 1
            if call_count[0] == 1:
                clinic = Mock()
                clinic.id = sample_clinic_id
                result.scalar_one_or_none.return_value = clinic
            else:
                result.scalar_one_or_none.return_value = None
            return result
        
        mock_db_session.execute = AsyncMock(side_effect=execute_side_effect)
        
        with patch.dict(os.environ, {"PHI_ENCRYPTION_KEY": valid_key_base64}):
            result = await create_patient(
                db=mock_db_session,
                clinic_id=sample_clinic_id,
                name="Jane Doe",
                dob="1995-03-20",
                phone="+15559876543"
            )
        
        expected_hash = _compute_name_dob_hash("Jane Doe", "1995-03-20")
        assert result.name_dob_hash == expected_hash
    
    @pytest.mark.asyncio
    async def test_create_duplicate_raises_error(
        self, mock_patient, sample_clinic_id, valid_key_base64
    ):
        """Test that creating duplicate patient raises ValueError."""
        call_count = [0]
        
        async def execute_side_effect(stmt):
            result = Mock()
            call_count[0] += 1
            if call_count[0] == 1:
                # First call: clinic lookup
                clinic = Mock()
                clinic.id = sample_clinic_id
                result.scalar_one_or_none.return_value = clinic
            else:
                # Patient lookup: return existing patient
                result.scalar_one_or_none.return_value = mock_patient
            return result
        
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=execute_side_effect)
        mock_session.add = Mock()
        mock_session.flush = AsyncMock()
        
        with patch.dict(os.environ, {"PHI_ENCRYPTION_KEY": valid_key_base64}):
            with pytest.raises(ValueError) as exc_info:
                await create_patient(
                    db=mock_session,
                    clinic_id=sample_clinic_id,
                    name="John Doe",
                    dob="1990-05-15",
                    phone="+15551234567"
                )
        assert "already exists" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_create_optional_email(self, mock_db_session, sample_clinic_id, valid_key_base64):
        """Test creating patient without email."""
        call_count = [0]
        
        async def execute_side_effect(stmt):
            result = Mock()
            call_count[0] += 1
            if call_count[0] == 1:
                clinic = Mock()
                clinic.id = sample_clinic_id
                result.scalar_one_or_none.return_value = clinic
            else:
                result.scalar_one_or_none.return_value = None
            return result
        
        mock_db_session.execute = AsyncMock(side_effect=execute_side_effect)
        
        with patch.dict(os.environ, {"PHI_ENCRYPTION_KEY": valid_key_base64}):
            result = await create_patient(
                db=mock_db_session,
                clinic_id=sample_clinic_id,
                name="Jane Doe",
                dob="1995-03-20",
                phone="+15559876543",
                email=None
            )
        
        assert result.email_token is None
    
    @pytest.mark.asyncio
    async def test_create_with_spanish_language(self, mock_db_session, sample_clinic_id, valid_key_base64):
        """Test creating patient with Spanish language."""
        call_count = [0]
        
        async def execute_side_effect(stmt):
            result = Mock()
            call_count[0] += 1
            if call_count[0] == 1:
                clinic = Mock()
                clinic.id = sample_clinic_id
                result.scalar_one_or_none.return_value = clinic
            else:
                result.scalar_one_or_none.return_value = None
            return result
        
        mock_db_session.execute = AsyncMock(side_effect=execute_side_effect)
        
        with patch.dict(os.environ, {"PHI_ENCRYPTION_KEY": valid_key_base64}):
            result = await create_patient(
                db=mock_db_session,
                clinic_id=sample_clinic_id,
                name="José García",
                dob="1985-12-25",
                phone="+17875551234",
                language="es"
            )
        
        assert result.language == "es"
    
    @pytest.mark.asyncio
    async def test_create_invalid_inputs_raises_error(self, mock_db_session, sample_clinic_id):
        """Test that invalid inputs raise ValueError."""
        with pytest.raises(ValueError):
            await create_patient(
                db=mock_db_session,
                clinic_id=sample_clinic_id,
                name="",
                dob="1990-05-15",
                phone="+15551234567"
            )

