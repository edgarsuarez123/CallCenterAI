"""
Pytest configuration and fixtures for CallCenterAI Gateway tests.
"""
import pytest
import os
import sys
from pathlib import Path

# Add gateway directory to path
gateway_dir = Path(__file__).parent.parent
sys.path.insert(0, str(gateway_dir))

# Set test environment variables (must be set before importing configuration)
os.environ.setdefault("APP_ENVIRONMENT", "development")
os.environ.setdefault("CLINIC_ID", "test-clinic-001")
os.environ.setdefault("CLINIC_NAME", "Test Clinic")
os.environ.setdefault("CLINIC_PHONE", "+1-555-000-0000")
os.environ.setdefault("CLINIC_SUBSCRIPTION_TIER", "basic")
os.environ.setdefault("SECURITY_ENCRYPTION_KEY", "K2Mo6tvmYdgQoIjazUq/h42MUWVK5UaLAPuIBhsF8T4=")  # Base64 encoded 32-byte key
os.environ.setdefault("SECURITY_JWT_SECRET", "test_jwt_secret_at_least_32_characters_long_123456")
os.environ.setdefault("CLINIC_TOKEN_HMAC_KEY_BASE64", "VGrksg2BpDK6eA2jZwWMpmxKoMvGVtp/PHYuha+WCSU=")
os.environ.setdefault("AES_GCM_KEY_BASE64", "pr/ug84YRLp78uR+4j+7vArWfxd3CkFceXfOERcBJKI=")
os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_PORT", "5432")
os.environ.setdefault("DB_NAME", "test_db")
os.environ.setdefault("DB_USER", "test_user")
os.environ.setdefault("DB_PASSWORD", "test_password")
os.environ.setdefault("ACS_CONNECTION_STRING", "endpoint=https://test.communication.azure.com/;accesskey=test_key")
os.environ.setdefault("ACS_PHONE_NUMBER", "+1234567890")
os.environ.setdefault("ACS_CALLBACK_URL", "https://test.com/api/v1/acs/webhooks/events")
os.environ.setdefault("ACS_WEBHOOK_SECRET", "test_webhook_secret_32_characters_long")
os.environ.setdefault("AZURE_SPEECH_KEY", "test_speech_key")
os.environ.setdefault("AZURE_SPEECH_REGION", "eastus")
os.environ.setdefault("AZURE_OPENAI_ENDPOINT", "https://test.openai.azure.com/")
os.environ.setdefault("AZURE_OPENAI_API_KEY", "test_api_key")
os.environ.setdefault("AZURE_OPENAI_API_VERSION", "2024-07-18")
os.environ.setdefault("AZURE_OPENAI_DEPLOYMENT_NAME", "test_deployment")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test_client_id.apps.googleusercontent.com")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test_client_secret")
os.environ.setdefault("GOOGLE_REDIRECT_URI", "http://localhost:8443/auth/callback")

import sys
import pytest_cov
import pytest_asyncio
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime, timezone, timedelta
from typing import Generator, AsyncGenerator

# Mock asyncpg before importing database module
class MockAsyncpg:
    """Mock asyncpg module to avoid import errors."""
    pass

sys.modules['asyncpg'] = MockAsyncpg()

# Now import database module (it will use mocked asyncpg)
from services.database import Base

# Import models (they use Base from database)
from models.models import Clinic, ClinicLicense, Patient, Provider, Appointment, AppointmentSlot, Call, Reminder
from models.enums import SubscriptionTier, YesNo, CallStatus

# Test database URL (use in-memory SQLite for tests)
TEST_DATABASE_URL = "sqlite:///:memory:"
TEST_ASYNC_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

@pytest.fixture(scope="session")
def test_engine():
    """Create test database engine using SQLite."""
    engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
    # Create all tables using Base from models
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)

def test_engine_session():
    """Create a test database session."""
    engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    return SessionLocal()

@pytest.fixture(scope="function")
def db_session(test_engine) -> Generator[Session, None, None]:
    """Create a test database session (sync - for backward compatibility)."""
    connection = test_engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection)()
    
    yield session
    
    session.close()
    transaction.rollback()
    connection.close()

@pytest.fixture(scope="session")
def async_test_engine():
    """Create async test database engine using SQLite."""
    try:
        import aiosqlite
    except ImportError:
        pytest.skip("aiosqlite not installed, skipping async tests")
    
    engine = create_async_engine(TEST_ASYNC_DATABASE_URL, echo=False)
    # Create all tables
    import asyncio
    async def create_tables():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    asyncio.run(create_tables())
    yield engine
    # Drop all tables and dispose
    async def cleanup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()
    asyncio.run(cleanup())

@pytest_asyncio.fixture(scope="function")
async def async_db_session(async_test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Create an async test database session."""
    async_session = async_sessionmaker(
        bind=async_test_engine,
        class_=AsyncSession,
        expire_on_commit=False
    )
    
    async with async_session() as session:
        yield session
        await session.rollback()

@pytest_asyncio.fixture
async def async_test_clinic(async_db_session: AsyncSession) -> Clinic:
    """Create a test clinic (async)."""
    from services.crypto import make_ulid_token
    from sqlalchemy import select
    
    # Check if clinic already exists (idempotent fixture)
    clinic_result = await async_db_session.execute(
        select(Clinic).where(Clinic.clinic_id == "test-clinic-001")
    )
    clinic = clinic_result.scalar_one_or_none()
    
    if not clinic:
        clinic = Clinic(
            clinic_id="test-clinic-001",
            clinic_name="Test Clinic",
            phone_number="+1-555-000-0000",
            timezone="America/New_York",
            default_language="en",
            supported_languages="en,es",
            ehr_system="google_calendar",
            subscription_tier="basic",
            is_active="yes"
        )
        async_db_session.add(clinic)
        
        license = ClinicLicense(
            license_id="LICENSE_test-clinic-001",
            clinic_id="test-clinic-001",
            tier="basic",
            max_calls_per_month=500,
            max_concurrent_calls=5,
            max_providers=5,
            monthly_fee_usd=199.0,
            license_status="active",
            current_month_calls=0,
            billing_cycle_start=datetime.now(timezone.utc).replace(day=1),
            billing_cycle_end=datetime.now(timezone.utc).replace(day=1) + timedelta(days=32),
            next_billing_date=datetime.now(timezone.utc).replace(day=1) + timedelta(days=32)
        )
        async_db_session.add(license)
        await async_db_session.commit()
    else:
        # Refresh to ensure we have latest data
        await async_db_session.refresh(clinic)
    
    return clinic

@pytest.fixture
def test_clinic(db_session: Session) -> Clinic:
    """Create a test clinic."""
    from services.crypto import make_ulid_token
    
    clinic = Clinic(
        clinic_id="test-clinic-001",
        clinic_name="Test Clinic",
        phone_number="+1-555-000-0000",
        timezone="America/New_York",
        default_language="en",
        supported_languages="en,es",
        ehr_system="google_calendar",
        subscription_tier="basic",
        is_active="yes"
    )
    db_session.add(clinic)
    
    license = ClinicLicense(
        license_id="LICENSE_test-clinic-001",
        clinic_id="test-clinic-001",
        tier="basic",
        max_calls_per_month=500,
        max_concurrent_calls=5,
        max_providers=5,
        monthly_fee_usd=199.0,
        license_status="active",
        current_month_calls=0,
        billing_cycle_start=datetime.now(timezone.utc).replace(day=1),
        billing_cycle_end=datetime.now(timezone.utc).replace(day=1) + timedelta(days=32),
        next_billing_date=datetime.now(timezone.utc).replace(day=1) + timedelta(days=32)
    )
    db_session.add(license)
    db_session.commit()
    
    return clinic

@pytest_asyncio.fixture
async def async_test_provider(async_db_session: AsyncSession, async_test_clinic: Clinic) -> Provider:
    """Create a test provider (async)."""
    from services.crypto import make_hmac_token
    from sqlalchemy import select
    
    # Check if provider already exists (idempotent fixture)
    provider_result = await async_db_session.execute(
        select(Provider).where(Provider.provider_id == "test-provider-001")
    )
    provider = provider_result.scalar_one_or_none()
    
    if not provider:
        provider = Provider(
            provider_id="test-provider-001",
            clinic_id="test-clinic-001",
            name_token=make_hmac_token("PROVIDER_NAME", "Dr. Test"),
            title="Dr.",
            specialty="General Practice",
            email="dr.test@testclinic.com",
            is_available="yes"
        )
        async_db_session.add(provider)
        await async_db_session.commit()
    else:
        await async_db_session.refresh(provider)
    
    return provider

@pytest.fixture
def test_provider(db_session: Session, test_clinic: Clinic) -> Provider:
    """Create a test provider."""
    from services.crypto import make_hmac_token
    
    provider = Provider(
        provider_id="test-provider-001",
        clinic_id="test-clinic-001",
        name_token=make_hmac_token("PROVIDER_NAME", "Dr. Test"),
        title="Dr.",
        specialty="General Practice",
        email="dr.test@testclinic.com",
        is_available="yes"
    )
    db_session.add(provider)
    db_session.commit()
    
    return provider

@pytest_asyncio.fixture
async def async_test_patient(async_db_session: AsyncSession, async_test_clinic: Clinic) -> Patient:
    """Create a test patient (async)."""
    from services.crypto import make_hmac_token, encrypt_str
    from sqlalchemy import select
    
    # Check if patient already exists (idempotent fixture)
    patient_result = await async_db_session.execute(
        select(Patient).where(Patient.patient_id == "test-patient-001")
    )
    patient = patient_result.scalar_one_or_none()
    
    if not patient:
        name_token = make_hmac_token("PATIENT_NAME", "John Doe")
        phone_token = make_hmac_token("PHONE", "+1-555-111-2222")
        dob_token = make_hmac_token("DOB", "1990-01-01")
        
        name_nonce, name_ct = encrypt_str("John Doe")
        phone_nonce, phone_ct = encrypt_str("+1-555-111-2222")
        dob_nonce, dob_ct = encrypt_str("1990-01-01")
        
        patient = Patient(
            patient_id="test-patient-001",
            clinic_id="test-clinic-001",
            name_token=name_token,
            phone_token=phone_token,
            dob_token=dob_token
        )
        async_db_session.add(patient)
        await async_db_session.commit()
    else:
        await async_db_session.refresh(patient)
    
    return patient

@pytest.fixture
def test_patient(db_session: Session, test_clinic: Clinic) -> Patient:
    """Create a test patient."""
    from services.crypto import make_hmac_token, encrypt_str
    
    name_token = make_hmac_token("PATIENT_NAME", "John Doe")
    phone_token = make_hmac_token("PHONE", "+1-555-111-2222")
    dob_token = make_hmac_token("DOB", "1990-01-01")
    
    name_nonce, name_ct = encrypt_str("John Doe")
    phone_nonce, phone_ct = encrypt_str("+1-555-111-2222")
    dob_nonce, dob_ct = encrypt_str("1990-01-01")
    
    patient = Patient(
        patient_id="test-patient-001",
        clinic_id="test-clinic-001",
        name_token=name_token,
        phone_token=phone_token,
        dob_token=dob_token
    )
    db_session.add(patient)
    db_session.commit()
    
    return patient

@pytest.fixture
def mock_azure_services(monkeypatch):
    """Mock Azure services for testing."""
    class MockACSService:
        async def register_incoming_call(self, *args, **kwargs):
            return {"status": "registered"}
        
        async def get_call_status(self, *args, **kwargs):
            return {"status": "active"}
    
    class MockSTTService:
        async def start_recognition(self, *args, **kwargs):
            return True
        
        async def stop_recognition(self, *args, **kwargs):
            return True
    
    class MockTTSService:
        async def synthesize_speech(self, *args, **kwargs):
            return {"audio": b"mock_audio"}
    
    monkeypatch.setattr("services.azure_communication_service.get_azure_communication_service", lambda: MockACSService())
    monkeypatch.setattr("services.azure_speech_stt.get_stt_service", lambda: MockSTTService())
    monkeypatch.setattr("services.azure_speech_tts.get_text_to_speech_service", lambda: MockTTSService())

@pytest.fixture
def mock_google_calendar(monkeypatch):
    """Mock Google Calendar service for testing."""
    class MockGoogleCalendar:
        async def create_event(self, *args, **kwargs):
            return {"id": "test_event_id", "htmlLink": "https://calendar.google.com/event"}
        
        async def get_events(self, *args, **kwargs):
            return []
    
    monkeypatch.setattr("services.google_calendar_service.get_google_calendar_service", lambda db: MockGoogleCalendar())

@pytest.fixture
def mock_openai(monkeypatch):
    """Mock OpenAI service for testing."""
    class MockOpenAI:
        async def classify_intent(self, *args, **kwargs):
            from services.nlp_service import IntentResult, IntentType, ExtractedEntities
            return IntentResult(
                intent=IntentType.APPOINTMENT_BOOKING,
                confidence=0.95,
                entities=ExtractedEntities(name="John Doe", date_of_birth="1990-01-01")
            )
        
        async def generate_response(self, *args, **kwargs):
            from services.nlp_service import ResponseResult, IntentType
            from models.enums import LanguageCode
            from datetime import datetime, timezone
            return ResponseResult(
                response_text="I can help you schedule an appointment.",
                intent=IntentType.APPOINTMENT_BOOKING,
                entities=[],
                processing_time_ms=150,
                timestamp=datetime.now(timezone.utc),
                language=LanguageCode.ENGLISH
            )
    
    monkeypatch.setattr("services.nlp_service.get_nlp_service", lambda: MockOpenAI())

