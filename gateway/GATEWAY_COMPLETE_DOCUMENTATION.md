# CallCenterAI Gateway - Complete Documentation

## Table of Contents

1. [System Overview](#system-overview)
2. [Configuration Management](#configuration-management)
3. [Database Management](#database-management)
4. [Security & HIPAA Compliance](#security--hipaa-compliance)
5. [Logging & Monitoring](#logging--monitoring)
6. [Background Jobs](#background-jobs)
7. [Exception Handling](#exception-handling)
8. [Clinic Customization](#clinic-customization)
9. [Google Calendar Integration](#google-calendar-integration)
10. [Migration & Deployment](#migration--deployment)
11. [Troubleshooting](#troubleshooting)

---

## System Overview

The CallCenterAI Gateway is a HIPAA-compliant, multi-tenant call center automation system for medical clinics. It provides advanced natural language processing, real-time voice communication, and intelligent appointment management with Azure Cloud Services integration, Google Calendar synchronization, and secure PHI tokenization.

### Key Features

- **HIPAA-Compliant PHI Tokenization** - All sensitive patient data is encrypted and tokenized
- **Multi-Tenant Architecture** - Support for multiple clinics with complete data isolation
- **Natural Language Processing** - Advanced conversational AI for appointment booking
- **Google Calendar Integration** - OAuth authentication and automatic event creation
- **Web-Based Call Simulator** - Interactive testing interface for demos
- **Comprehensive API** - RESTful endpoints for all operations
- **Docker Containerization** - Easy deployment and scaling
- **Azure Services Integration** - Communication Services, Speech Services, OpenAI
- **Real-time Communication** - WebSocket for audio streaming
- **Background Processing** - Async job management with retry logic

---

## Configuration Management

### Why Configuration Management with Pydantic is Critical

#### 1. Type Safety at Startup
- **Prevents Runtime Errors**: `pool_size: int` ensures it's a number, not "ten"
- **Early Failure Detection**: Catches config errors before code runs
- **No Runtime Type Errors**: Prevents crashes from bad configuration
- **Better Error Messages**: Clear validation errors instead of cryptic runtime failures

#### 2. Validation Before Runtime
- **Range Validation**: `Field(ge=1, le=50)` ensures pool_size between 1-50
- **Format Validation**: Validates email formats, URL formats, etc.
- **Business Rule Enforcement**: Ensures configuration values make sense
- **Clear Error Messages**: "pool_size must be between 1 and 50"

#### 3. Environment-Specific Configs
- **Development**: `DEBUG=true`, `LOG_LEVEL=DEBUG`
- **Staging**: `DEBUG=false`, `LOG_LEVEL=INFO`
- **Production**: `DEBUG=false`, `LOG_LEVEL=WARNING`
- **Same Code, Different Config**: Easy to manage multiple environments

### Configuration Structure

#### Main Configuration Classes

##### 1. DatabaseConfig
```python
class DatabaseConfig(BaseSettings):
    # Connection settings
    host: str = Field(default="localhost", description="Database host")
    port: int = Field(default=5432, ge=1, le=65535, description="Database port")
    name: str = Field(default="callcenter", description="Database name")
    user: str = Field(default="postgres", description="Database user")
    password: SecretStr = Field(default="", description="Database password")
    
    # Connection pooling
    pool_size: int = Field(default=10, ge=1, le=50, description="Database pool size")
    max_overflow: int = Field(default=20, ge=0, le=100, description="Maximum overflow connections")
    pool_timeout: int = Field(default=30, ge=1, le=300, description="Pool timeout in seconds")
    pool_recycle: int = Field(default=3600, ge=300, le=86400, description="Pool recycle time in seconds")
    pool_pre_ping: bool = Field(default=True, description="Enable pool pre-ping")
```

##### 2. SecurityConfig
```python
class SecurityConfig(BaseSettings):
    # Encryption
    encryption_key: SecretStr = Field(..., description="32-byte encryption key for PHI")
    jwt_secret: SecretStr = Field(..., description="JWT signing secret")
    jwt_algorithm: str = Field(default="HS256", description="JWT algorithm")
    jwt_expiration_hours: int = Field(default=24, ge=1, le=168, description="JWT expiration in hours")
    
    # CORS
    cors_origins: List[str] = Field(default=["*"], description="Allowed CORS origins")
    cors_methods: List[str] = Field(default=["GET", "POST", "PUT", "DELETE"], description="Allowed CORS methods")
    cors_headers: List[str] = Field(default=["*"], description="Allowed CORS headers")
    
    # Rate limiting
    rate_limit_per_minute: int = Field(default=100, ge=1, le=1000, description="Rate limit per minute")
    rate_limit_burst: int = Field(default=200, ge=1, le=2000, description="Rate limit burst size")
```

##### 3. LoggingConfig
```python
class LoggingConfig(BaseSettings):
    # Log levels
    level: str = Field(default="INFO", pattern="^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$", description="Logging level")
    format: str = Field(default="json", pattern="^(json|text)$", description="Log format (json or text)")
    
    # File logging
    file_enabled: bool = Field(default=True, description="Enable file logging")
    file_path: str = Field(default="logs/app.log", description="Log file path")
    file_max_size_mb: int = Field(default=100, ge=1, le=1000, description="Max log file size in MB")
    file_backup_count: int = Field(default=5, ge=1, le=20, description="Number of backup files")
    
    # Structured logging
    structured_enabled: bool = Field(default=True, description="Enable structured logging")
    phi_masking_enabled: bool = Field(default=True, description="Enable PHI masking")
    performance_logging_enabled: bool = Field(default=True, description="Enable performance logging")
    security_logging_enabled: bool = Field(default=True, description="Enable security logging")
```

### Environment Variables

#### Database Configuration
```bash
# Database connection
DB_HOST=localhost
DB_PORT=5432
DB_NAME=callcenter
DB_USER=postgres
DB_PASSWORD=your_password

# Connection pooling
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=20
DB_POOL_TIMEOUT=30
DB_POOL_RECYCLE=3600
DB_POOL_PRE_PING=true

# Connection arguments
DB_CONNECT_TIMEOUT=10
DB_APPLICATION_NAME=CallCenterAI
DB_DEFAULT_TRANSACTION_ISOLATION=read_committed
```

#### Security Configuration
```bash
# Encryption
SECURITY_ENCRYPTION_KEY=your_32_byte_encryption_key_here
SECURITY_JWT_SECRET=your_jwt_secret_at_least_32_characters_long

# CORS
SECURITY_CORS_ORIGINS=["http://localhost:3000", "https://yourdomain.com"]
SECURITY_CORS_METHODS=["GET", "POST", "PUT", "DELETE"]
SECURITY_CORS_HEADERS=["*"]

# Rate limiting
SECURITY_RATE_LIMIT_PER_MINUTE=100
SECURITY_RATE_LIMIT_BURST=200

# Session security
SECURITY_SESSION_TIMEOUT_MINUTES=30
SECURITY_MAX_LOGIN_ATTEMPTS=5
SECURITY_LOCKOUT_DURATION_MINUTES=15
```

#### Google Calendar Configuration
```bash
# OAuth settings
GOOGLE_CLIENT_ID=your_client_id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your_client_secret
GOOGLE_REDIRECT_URI=http://localhost:8000/auth/callback

# API settings
GOOGLE_API_KEY=your_api_key
GOOGLE_SCOPES=["https://www.googleapis.com/auth/calendar"]

# Rate limiting
GOOGLE_REQUESTS_PER_MINUTE=100
GOOGLE_REQUESTS_PER_DAY=10000

# Sync settings
GOOGLE_SYNC_INTERVAL_MINUTES=5
GOOGLE_MAX_SYNC_RETRIES=3
GOOGLE_SYNC_TIMEOUT_SECONDS=30
```

#### Azure Configuration
```bash
# Communication Services
AZURE_ACS_CONNECTION_STRING=endpoint=https://your.communication.azure.com/;accesskey=your_key
AZURE_ACS_PHONE_NUMBER=+1234567890

# OpenAI
AZURE_OPENAI_ENDPOINT=https://your.openai.azure.com/
AZURE_OPENAI_API_KEY=your_api_key
AZURE_OPENAI_API_VERSION=2024-02-15-preview
AZURE_OPENAI_DEPLOYMENT_NAME=your_deployment

# Storage
AZURE_STORAGE_ACCOUNT_NAME=your_storage_account
AZURE_STORAGE_ACCOUNT_KEY=your_storage_key
AZURE_STORAGE_CONTAINER_NAME=callcenter

# Rate limiting
AZURE_ACS_REQUESTS_PER_MINUTE=100
AZURE_OPENAI_REQUESTS_PER_MINUTE=60
```

### Usage Examples

#### Basic Usage
```python
from services.configuration import get_settings

# Get configuration (cached)
settings = get_settings()

# Access configuration values
print(f"Environment: {settings.environment}")
print(f"Database host: {settings.database.host}")
print(f"Pool size: {settings.database.pool_size}")

# Access secrets
encryption_key = settings.security.encryption_key.get_secret_value()
jwt_secret = settings.security.jwt_secret.get_secret_value()
```

#### Testing with Overrides
```python
from services.configuration import get_test_settings

# Get test configuration with overrides
test_settings = get_test_settings(
    environment="testing",
    debug=True,
    port=9000
)

# Use in tests
assert test_settings.environment == "testing"
assert test_settings.debug is True
assert test_settings.port == 9000
```

#### Configuration Validation
```python
from services.configuration import validate_configuration

# Validate configuration
validation_results = validate_configuration()

if validation_results["valid"]:
    print("Configuration is valid")
else:
    print("Configuration errors:")
    for error in validation_results["errors"]:
        print(f"  - {error}")
    
    print("Configuration warnings:")
    for warning in validation_results["warnings"]:
        print(f"  - {warning}")
```

### Configuration Management Commands

```bash
# Generate configuration file
python config_manager.py generate --environment development --output .env

# Show current configuration
python config_manager.py show

# Test configuration
python config_manager.py test

# Validate configuration
python validate_config.py
```

---

## Database Management

### Connection Pooling

#### Why Connection Pooling Is Critical

**Problems Without Connection Pooling:**
- **Connection Exhaustion**: Each request creates a new connection, quickly exhausting PostgreSQL's max_connections limit
- **Performance Degradation**: Creating new connections takes 100-200ms each, causing slow response times
- **Memory Leaks**: Connections not properly closed consume server memory indefinitely
- **Cascading Failures**: When connections are exhausted, all new requests fail with "too many connections"
- **No Traffic Spike Handling**: System crashes when traffic doubles instead of gracefully degrading

**Benefits of Proper Connection Pooling:**
- **Connection Reuse**: Reusing existing connections (< 1ms) vs creating new ones (100-200ms)
- **Controlled Resource Usage**: Predictable memory consumption and connection limits
- **Traffic Spike Handling**: Overflow connections handle temporary load increases
- **Health Monitoring**: Automatic detection and replacement of stale connections
- **Graceful Degradation**: System continues working under load with performance warnings

#### Configuration Guidelines

##### Pool Size (`DB_POOL_SIZE`)
- **Small Clinic (1-5 providers)**: 5-10 connections
- **Medium Clinic (5-20 providers)**: 10-20 connections
- **Large Clinic (20+ providers)**: 20-50 connections
- **Multi-tenant System**: 50-100 connections

##### Max Overflow (`DB_MAX_OVERFLOW`)
- **Low Traffic**: 50-100% of pool size
- **High Traffic**: 100-200% of pool size
- **Peak Traffic**: 200-300% of pool size

##### Pool Timeout (`DB_POOL_TIMEOUT`)
- **Development**: 30 seconds
- **Production**: 10-30 seconds
- **High Load**: 5-10 seconds

### Database Constraints and Indexes

#### Critical Business Constraints

##### 1. Double Booking Prevention (MOST CRITICAL)
```sql
-- Prevents two appointments for the same provider at the same time
UNIQUE CONSTRAINT unique_provider_slot_datetime ON appointment_slots (provider_id, slot_datetime)
```

**Business Impact**: 
- Prevents customer service nightmares
- Ensures no "overbooking" situations
- Handles race conditions between simultaneous bookings
- Database-level protection even if application code has bugs

##### 2. Appointment Time Validation
```sql
-- Ensures appointments have logical timing
CHECK CONSTRAINT check_appointments_end_after_start ON appointments (end_time > start_time)
CHECK CONSTRAINT check_appointments_positive_duration ON appointments (duration_minutes > 0)
```

**Business Impact:**
- Prevents nonsensical appointments (end before start)
- Ensures all appointments have positive duration
- Protects against data entry errors

##### 3. Provider License Validation
```sql
-- Ensures providers have valid license numbers
CHECK CONSTRAINT check_providers_license_format ON providers (license_number ~ '^[A-Z]{2}[0-9]{6}$')
```

**Business Impact:**
- Ensures all providers have properly formatted license numbers
- Prevents invalid license data entry
- Supports regulatory compliance

#### Performance Indexes

##### 1. Appointment Queries
```sql
-- Fast appointment lookups by clinic and date
CREATE INDEX idx_appointments_clinic_date ON appointments (clinic_id, start_time);

-- Fast provider availability queries
CREATE INDEX idx_appointment_slots_provider_datetime ON appointment_slots (provider_id, slot_datetime);
```

##### 2. Call Management
```sql
-- Fast call status queries
CREATE INDEX idx_calls_status_clinic ON calls (status, clinic_id, created_at);

-- Fast call history queries
CREATE INDEX idx_calls_patient_clinic ON calls (patient_id, clinic_id, created_at);
```

##### 3. Audit and Compliance
```sql
-- Fast audit log queries
CREATE INDEX idx_audit_logs_clinic_timestamp ON audit_logs (clinic_id, timestamp);

-- Fast PHI access tracking
CREATE INDEX idx_audit_logs_phi_access ON audit_logs (action, entity_type, timestamp);
```

### Transaction Management

#### Why Transaction Management is Critical

##### 1. Atomic Operations (All or Nothing)
**Appointment Booking**: Creating an appointment requires multiple steps:
- Create appointment record
- Mark appointment slot as booked
- Update usage counters
- Log audit trail

**Problem Without Transactions**: If any step fails, the database is left in an inconsistent state
**Solution**: All steps succeed or all rollback - database always remains consistent

##### 2. Race Condition Prevention
**Double Booking Scenario**: Two users click "Book" on the same appointment slot simultaneously
**Problem Without Locking**: Both users see the slot as available and both get it
**Solution**: Row-level locking with `FOR UPDATE` ensures only one user can book the slot

##### 3. Deadlock Recovery
**Deadlock Scenario**: 
- Transaction A locks slot X, wants slot Y
- Transaction B locks slot Y, wants slot X
**Problem**: Both transactions wait forever for each other
**Solution**: Database detects deadlock, kills one transaction, automatic retry succeeds

#### Usage Examples

##### Basic Transaction
```python
from services.transaction_manager import get_transaction_manager

async def book_appointment(appointment_data):
    async with get_transaction_manager() as tx:
        # All operations in this block are atomic
        appointment = await create_appointment(appointment_data)
        await mark_slot_booked(appointment.slot_id)
        await update_usage_counters(appointment.clinic_id)
        await log_audit_trail("appointment_created", appointment.id)
        
        # If any operation fails, all are rolled back
        return appointment
```

##### Row-Level Locking
```python
async def book_appointment_with_locking(slot_id, patient_id):
    async with get_transaction_manager() as tx:
        # Lock the slot to prevent double booking
        slot = await tx.execute(
            "SELECT * FROM appointment_slots WHERE id = :slot_id FOR UPDATE",
            {"slot_id": slot_id}
        )
        
        if slot.is_booked:
            raise SlotUnavailableError("Slot is already booked")
        
        # Book the slot
        await tx.execute(
            "UPDATE appointment_slots SET is_booked = true WHERE id = :slot_id",
            {"slot_id": slot_id}
        )
        
        # Create appointment
        appointment = await create_appointment(slot_id, patient_id)
        return appointment
```

##### Deadlock Recovery
```python
from services.transaction_manager import retry_on_deadlock

@retry_on_deadlock(max_retries=3)
async def transfer_appointment(from_slot_id, to_slot_id):
    async with get_transaction_manager() as tx:
        # This operation might deadlock with other transfers
        await release_slot(from_slot_id)
        await book_slot(to_slot_id)
```

### Soft Delete Implementation

#### Why Soft Delete is Critical

##### 1. HIPAA 7-Year Retention Requirement
- **Regulatory Compliance**: HIPAA mandates keeping patient records for 7 years
- **Legal Protection**: Hard delete violates regulatory requirements and can result in fines up to $50,000 per violation
- **Audit Trail**: Maintains complete history of all patient interactions and data access

##### 2. Accidental Deletion Recovery
- **Human Error Protection**: Prevents permanent data loss from user mistakes
- **Recovery Mechanism**: Allows restoration of accidentally deleted patient records
- **Customer Service**: Enables quick resolution of "oops, I didn't mean to delete that" situations

##### 3. Legal Discovery Protection
- **Litigation Support**: Ensures historical records are available for legal requests
- **Compliance Evidence**: Proves adherence to retention policies
- **Data Integrity**: Maintains referential integrity across related records

#### Models with Soft Delete Support

##### PHI-Containing Models
- **`patients`**: Patient records with tokenized PHI
- **`calls`**: Call records containing caller information
- **`appointments`**: Appointment records with patient details
- **`call_notes`**: AI-generated summaries and notes
- **`mappings`**: Encrypted PHI tokens

##### Compliance-Critical Models
- **`audit_logs`**: Audit trail for all PHI access
- **`clinic_usage`**: Usage metrics (may contain PHI patterns)

#### Usage Examples

##### Soft Delete a Record
```python
from services.soft_delete import get_soft_delete_service

async def delete_patient(patient_id):
    soft_delete_service = get_soft_delete_service()
    
    # Soft delete the patient
    await soft_delete_service.soft_delete("patients", patient_id)
    
    # Record is marked as deleted but data is preserved
    # All related records maintain referential integrity
```

##### Query with Soft Delete Awareness
```python
# Query only active (non-deleted) records
active_patients = await db.query(Patient).filter(Patient.deleted_at.is_(None)).all()

# Query all records including deleted
all_patients = await db.query(Patient).all()

# Query only deleted records
deleted_patients = await db.query(Patient).filter(Patient.deleted_at.isnot(None)).all()
```

##### Restore a Deleted Record
```python
async def restore_patient(patient_id):
    soft_delete_service = get_soft_delete_service()
    
    # Restore the patient
    await soft_delete_service.restore("patients", patient_id)
    
    # Record is now active again
```

##### Permanent Delete (After Retention Period)
```python
async def permanent_delete_old_records():
    soft_delete_service = get_soft_delete_service()
    
    # Permanently delete records older than 7 years
    await soft_delete_service.permanent_delete_old_records(
        table_name="patients",
        retention_years=7
    )
```

### Database Migration

#### Why Migrations Are Critical

**Problems with `create_all()`:**
1. **Data Loss**: Drops and recreates all tables, destroying existing data
2. **No Version Control**: No tracking of schema changes over time
3. **Deployment Issues**: Schema mismatches between environments
4. **No Rollback**: Cannot undo problematic changes
5. **Compliance Violations**: No audit trail for HIPAA compliance

**Benefits of Alembic Migrations:**
1. **Schema Version Control**: Every change is tracked with timestamps and descriptions
2. **Zero-Downtime Deployments**: Migrate schema before deploying code
3. **Data Safety**: Preserve existing data while changing structure
4. **Rollback Capability**: Can undo problematic migrations
5. **Audit Trail**: Complete history for compliance requirements
6. **Team Coordination**: Everyone gets identical schemas

#### Migration Commands

##### Using the Migration Script
```bash
# Apply all pending migrations
python migrate.py upgrade

# Create a new migration (auto-generate from model changes)
python migrate.py revision "Add new column to patients table"

# Show migration history
python migrate.py history

# Show current migration version
python migrate.py current

# Rollback last migration
python migrate.py downgrade

# Reset database (DEVELOPMENT ONLY - DESTROYS ALL DATA)
python migrate.py reset
```

##### Direct Alembic Commands
```bash
# Initialize Alembic (first time only)
alembic init migrations

# Create a new migration
alembic revision --autogenerate -m "Add new table"

# Apply migrations
alembic upgrade head

# Rollback one migration
alembic downgrade -1

# Rollback to specific version
alembic downgrade abc123

# Show current version
alembic current

# Show migration history
alembic history
```

#### Creating New Migrations

##### 1. Modify Models
```python
# In models/models.py
class Patient(Base):
    __tablename__ = "patients"
    
    id = Column(String(64), primary_key=True)
    name_token = Column(String(64), nullable=False)
    phone_token = Column(String(64), nullable=False)
    
    # Add new column
    email_token = Column(String(64), nullable=True)  # New field
    date_of_birth = Column(Date, nullable=True)      # New field
```

##### 2. Generate Migration
```bash
# Auto-generate migration from model changes
python migrate.py revision "Add email and date_of_birth to patients"
```

##### 3. Review Generated Migration
```python
# In migrations/versions/xxx_add_email_and_date_of_birth.py
def upgrade():
    # Add new columns
    op.add_column('patients', sa.Column('email_token', sa.String(64), nullable=True))
    op.add_column('patients', sa.Column('date_of_birth', sa.Date(), nullable=True))

def downgrade():
    # Remove columns
    op.drop_column('patients', 'date_of_birth')
    op.drop_column('patients', 'email_token')
```

##### 4. Apply Migration
```bash
# Apply the migration
python migrate.py upgrade
```

#### Best Practices

##### 1. Always Review Auto-Generated Migrations
- Check the generated SQL before applying
- Ensure data types and constraints are correct
- Add data migrations if needed

##### 2. Test Migrations
```bash
# Test on development database first
python migrate.py upgrade

# Verify schema changes
python -c "from services.database import engine; print(engine.table_names())"
```

##### 3. Backup Before Major Changes
```bash
# Backup database before major migrations
pg_dump callcenterai > backup_before_migration.sql
```

##### 4. Use Data Migrations for Complex Changes
```python
def upgrade():
    # Add new column
    op.add_column('patients', sa.Column('full_name', sa.String(200), nullable=True))
    
    # Migrate existing data
    connection = op.get_bind()
    connection.execute(
        "UPDATE patients SET full_name = CONCAT(first_name, ' ', last_name)"
    )
    
    # Make column non-nullable
    op.alter_column('patients', 'full_name', nullable=False)
```

---

## Security & HIPAA Compliance

### PHI Tokenization System

#### Why Tokenization is Critical

##### 1. HIPAA Compliance
- **Data Minimization**: Only tokens stored in database, not actual PHI
- **Access Control**: PHI only accessible with proper encryption keys
- **Audit Trail**: All PHI access is logged and monitored
- **Breach Protection**: Stolen database contains only tokens, not PHI

##### 2. Security Benefits
- **Defense in Depth**: Multiple layers of protection
- **Key Management**: Encryption keys stored separately from data
- **Token Reversibility**: PHI can be retrieved when needed
- **Performance**: Fast token-based lookups

#### Token Types

##### 1. Deterministic Tokens (HMAC)
```python
# Same input always produces same token
phone_token = make_hmac_token("+1234567890", clinic_key)
# Result: "PHONE_HMAC_abc123def456..."

# Used for: Phone numbers, email addresses, SSNs
# Benefits: Consistent referencing, fast lookups
```

##### 2. Non-Deterministic Tokens (ULID)
```python
# Each call produces unique token
patient_token = make_ulid_token()
# Result: "PATIENT_ULID_01ARZ3NDEKTSV4RRFFQ69G5FAV"

# Used for: Patient names, addresses, medical records
# Benefits: No correlation, maximum security
```

#### Usage Examples

##### Tokenize PHI
```python
from services.crypto import make_hmac_token, make_ulid_token

# Tokenize phone number (deterministic)
phone_token = make_hmac_token("+1234567890", clinic_key)

# Tokenize patient name (non-deterministic)
name_token = make_ulid_token()

# Store tokens in database
patient = Patient(
    phone_token=phone_token,
    name_token=name_token,
    # ... other fields
)
```

##### Retrieve PHI
```python
from services.crypto import get_phi_value

# Retrieve original phone number
phone_number = get_phi_value(phone_token, clinic_key)

# Retrieve original patient name
patient_name = get_phi_value(name_token, clinic_key)
```

##### Search by Token
```python
# Find patient by phone token
phone_token = make_hmac_token("+1234567890", clinic_key)
patient = await db.query(Patient).filter(Patient.phone_token == phone_token).first()
```

### Encryption System

#### AES-GCM Encryption
```python
from services.crypto import encrypt_phi, decrypt_phi

# Encrypt PHI
encrypted_data = encrypt_phi("John Doe", encryption_key)

# Decrypt PHI
decrypted_data = decrypt_phi(encrypted_data, encryption_key)
```

#### Key Management
```python
from services.crypto import generate_encryption_key, validate_encryption_key

# Generate new encryption key
key = generate_encryption_key()  # Returns 32-byte key

# Validate encryption key
is_valid = validate_encryption_key(key)  # Returns True/False
```

### Security Configuration

#### Environment Variables
```bash
# Encryption key (32 bytes, base64 encoded)
SECURITY_ENCRYPTION_KEY=your_32_byte_encryption_key_here

# JWT secret (minimum 32 characters)
SECURITY_JWT_SECRET=your_jwt_secret_at_least_32_characters_long

# CORS configuration
SECURITY_CORS_ORIGINS=["https://yourdomain.com"]
SECURITY_CORS_METHODS=["GET", "POST", "PUT", "DELETE"]
SECURITY_CORS_HEADERS=["*"]

# Rate limiting
SECURITY_RATE_LIMIT_PER_MINUTE=100
SECURITY_RATE_LIMIT_BURST=200

# Session security
SECURITY_SESSION_TIMEOUT_MINUTES=30
SECURITY_MAX_LOGIN_ATTEMPTS=5
SECURITY_LOCKOUT_DURATION_MINUTES=15
```

#### Security Best Practices

##### 1. Key Rotation
```python
# Rotate encryption keys regularly
old_key = get_current_encryption_key()
new_key = generate_encryption_key()

# Re-encrypt all PHI with new key
await reencrypt_all_phi(old_key, new_key)

# Update configuration
update_encryption_key(new_key)
```

##### 2. Access Logging
```python
# Log all PHI access
await log_phi_access(
    user_id=user_id,
    action="view_patient",
    entity_type="patient",
    entity_id=patient_id,
    timestamp=datetime.utcnow()
)
```

##### 3. Audit Trail
```python
# Create audit log entry
audit_log = AuditLog(
    clinic_id=clinic_id,
    user_id=user_id,
    action="patient_created",
    entity_type="patient",
    entity_id=patient_id,
    timestamp=datetime.utcnow(),
    ip_address=request.client.host,
    user_agent=request.headers.get("user-agent")
)
```

---

## Logging & Monitoring

### Structured Logging System

#### Why Structured Logging is Critical

##### 1. HIPAA Compliance for Logs
- **Automatic PHI Detection**: Prevents accidental logging of patient names, phone numbers, SSNs
- **Automatic Masking**: PHI is automatically masked as `[PHONE_MASKED]`, `[EMAIL_MASKED]`, etc.
- **Safe Log Sharing**: Logs can be safely shared with developers without HIPAA violations
- **Compliance Auditing**: Complete audit trail of all PHI access and modifications

##### 2. Debugging Production Issues
- **Correlation IDs**: Track requests across multiple services
- **Structured Data**: JSON logs can be parsed by machines for analysis
- **Request Tracing**: Follow a single request through the entire system
- **Error Context**: Rich context for every error, including stack traces

##### 3. Performance Monitoring
- **Slow Query Detection**: Automatic detection of database queries > 1 second
- **Request Timing**: Track API response times and identify bottlenecks
- **Resource Usage**: Monitor memory usage and connection pool health
- **Performance Trends**: Analyze performance patterns over time

#### Log Categories

##### 1. API Logs
```python
from services.structured_logging import get_logger, LogCategory

logger = get_logger("api")

# Log API request
logger.info(
    "API request received",
    LogCategory.API,
    extra_data={
        "method": "POST",
        "endpoint": "/api/v1/appointments",
        "user_id": user_id,
        "clinic_id": clinic_id,
        "request_id": request_id
    }
)
```

##### 2. Database Logs
```python
# Log database operations
logger.info(
    "Database query executed",
    LogCategory.DATABASE,
    extra_data={
        "query": "SELECT * FROM patients WHERE clinic_id = :clinic_id",
        "execution_time": 0.045,
        "rows_returned": 25,
        "clinic_id": clinic_id
    }
)
```

##### 3. Security Logs
```python
# Log security events
logger.warning(
    "Failed authentication attempt",
    LogCategory.SECURITY,
    extra_data={
        "user_id": user_id,
        "ip_address": request.client.host,
        "user_agent": request.headers.get("user-agent"),
        "attempt_count": 3
    }
)
```

##### 4. Performance Logs
```python
# Log performance metrics
logger.info(
    "Slow query detected",
    LogCategory.PERFORMANCE,
    extra_data={
        "query": "SELECT * FROM appointments WHERE start_time > :start_time",
        "execution_time": 2.5,
        "threshold": 1.0,
        "clinic_id": clinic_id
    }
)
```

#### PHI Masking

##### Automatic PHI Detection
```python
# PHI is automatically detected and masked
logger.info(
    "Patient data accessed",
    LogCategory.API,
    extra_data={
        "patient_name": "John Doe",  # Automatically masked as [NAME_MASKED]
        "phone_number": "+1234567890",  # Automatically masked as [PHONE_MASKED]
        "email": "john@example.com",  # Automatically masked as [EMAIL_MASKED]
        "ssn": "123-45-6789"  # Automatically masked as [SSN_MASKED]
    }
)
```

##### Manual PHI Masking
```python
from services.structured_logging import mask_phi

# Manually mask PHI
masked_data = mask_phi({
    "patient_name": "John Doe",
    "phone_number": "+1234567890",
    "medical_record": "Patient has diabetes"
})

# Result: {
#     "patient_name": "[NAME_MASKED]",
#     "phone_number": "[PHONE_MASKED]",
#     "medical_record": "[MEDICAL_RECORD_MASKED]"
# }
```

#### Performance Monitoring

##### Request Timing
```python
from services.structured_logging import log_performance

@log_performance("appointment_booking")
async def book_appointment(appointment_data):
    # Function execution time is automatically logged
    appointment = await create_appointment(appointment_data)
    return appointment
```

##### Database Performance
```python
# Log slow queries
if query_time > 1.0:
    logger.warning(
        "Slow query detected",
        LogCategory.PERFORMANCE,
        extra_data={
            "query": query,
            "execution_time": query_time,
            "threshold": 1.0
        }
    )
```

##### Memory Usage
```python
import psutil

# Log memory usage
memory_usage = psutil.virtual_memory()
logger.info(
    "Memory usage",
    LogCategory.PERFORMANCE,
    extra_data={
        "total_memory": memory_usage.total,
        "available_memory": memory_usage.available,
        "percent_used": memory_usage.percent
    }
)
```

#### Log Configuration

##### Environment Variables
```bash
# Log levels
LOG_LEVEL=INFO
LOG_FORMAT=json

# File logging
LOG_FILE_ENABLED=true
LOG_FILE_PATH=logs/app.log
LOG_FILE_MAX_SIZE_MB=100
LOG_FILE_BACKUP_COUNT=5

# Structured logging
LOG_STRUCTURED_ENABLED=true
LOG_PHI_MASKING_ENABLED=true
LOG_PERFORMANCE_LOGGING_ENABLED=true
LOG_SECURITY_LOGGING_ENABLED=true

# Audit logging
LOG_AUDIT_ENABLED=true
LOG_AUDIT_FILE_PATH=logs/audit.log
LOG_AUDIT_RETENTION_DAYS=2555
```

##### Log Levels by Environment
```bash
# Development
LOG_LEVEL=DEBUG
LOG_FORMAT=text

# Staging
LOG_LEVEL=INFO
LOG_FORMAT=json

# Production
LOG_LEVEL=WARNING
LOG_FORMAT=json
```

#### Log Analysis

##### JSON Log Format
```json
{
    "timestamp": "2024-01-15T10:30:45.123Z",
    "level": "INFO",
    "logger": "api",
    "category": "API",
    "message": "API request received",
    "extra_data": {
        "method": "POST",
        "endpoint": "/api/v1/appointments",
        "user_id": "user_123",
        "clinic_id": "clinic_456",
        "request_id": "req_789"
    }
}
```

##### Log Parsing
```bash
# Parse JSON logs
jq '.extra_data.clinic_id' logs/app.log

# Filter by category
jq 'select(.category == "SECURITY")' logs/app.log

# Filter by time range
jq 'select(.timestamp > "2024-01-15T10:00:00Z")' logs/app.log
```

---

## Background Jobs

### Background Job Management System

#### Why This Is Critical

##### 1. Automatic Cleanup Without Manual Intervention
- **Expired slot holds released every minute** - No manual database queries needed
- **System self-heals automatically** - Reduces operational burden
- **Prevents resource leaks** - Slots held for 5 minutes, user abandons call, system releases automatically

##### 2. Monthly Billing Cycle Automation
- **Usage counters reset first of month** - No manual SQL scripts needed
- **Consistent timing across all clinics** - Prevents billing errors
- **Real-time usage tracking** - Updates every 5 minutes

##### 3. HIPAA Retention Compliance
- **After 7 years, data automatically purged** - Reduces legal liability from old data
- **Demonstrates data minimization** - No manual intervention required
- **Audit trail maintenance** - Old logs deleted automatically

##### 4. Proactive Monitoring
- **Database health checked every 5 minutes** - Alert before connection pool exhausted
- **Fix issues before users affected** - Prevents outages
- **System metrics collection** - Performance monitoring

#### Job Types

##### Cleanup Jobs
- **cleanup_expired_slots** - Release appointment slots held too long (every minute)
- **cleanup_abandoned_calls** - Mark calls as abandoned if active too long (every 5 minutes)
- **cleanup_old_audit_logs** - Delete audit logs older than retention period (daily)

##### Billing Jobs
- **reset_monthly_usage** - Reset usage counters on first of month (monthly)
- **update_usage_metrics** - Update real-time usage statistics (every 5 minutes)
- **check_license_expiration** - Check for expiring licenses (daily)

##### Compliance Jobs
- **purge_old_phi_data** - Permanently delete PHI after 7 years (daily)
- **generate_compliance_report** - Generate monthly compliance reports (monthly)
- **audit_data_access** - Audit PHI access patterns (daily)

##### Health Monitoring Jobs
- **check_database_health** - Monitor database connection pool (every 5 minutes)
- **check_service_health** - Monitor external service availability (every 10 minutes)
- **collect_system_metrics** - Collect performance metrics (every minute)

#### Job Configuration

##### Environment Variables
```bash
# Background job settings
BACKGROUND_JOBS_ENABLED=true
BACKGROUND_JOBS_MAX_WORKERS=4
BACKGROUND_JOBS_RETRY_ATTEMPTS=3
BACKGROUND_JOBS_RETRY_DELAY=60

# Job-specific settings
CLEANUP_EXPIRED_SLOTS_INTERVAL=60
CLEANUP_ABANDONED_CALLS_INTERVAL=300
CLEANUP_OLD_AUDIT_LOGS_INTERVAL=86400
RESET_MONTHLY_USAGE_INTERVAL=2592000
UPDATE_USAGE_METRICS_INTERVAL=300
CHECK_LICENSE_EXPIRATION_INTERVAL=86400
PURGE_OLD_PHI_DATA_INTERVAL=86400
CHECK_DATABASE_HEALTH_INTERVAL=300
CHECK_SERVICE_HEALTH_INTERVAL=600
COLLECT_SYSTEM_METRICS_INTERVAL=60
```

#### Usage Examples

##### Start Background Jobs
```python
from services.background_jobs import get_background_job_manager

# Start background job manager
job_manager = get_background_job_manager()
await job_manager.start()

# Jobs will run automatically according to their schedules
```

##### Monitor Job Status
```python
# Get job status
job_status = await job_manager.get_job_status("cleanup_expired_slots")
print(f"Last run: {job_status.last_run}")
print(f"Next run: {job_status.next_run}")
print(f"Status: {job_status.status}")
print(f"Error count: {job_status.error_count}")
```

##### Manual Job Execution
```python
# Run job manually
result = await job_manager.run_job("cleanup_expired_slots")
print(f"Job result: {result.status}")
print(f"Records processed: {result.records_processed}")
print(f"Execution time: {result.execution_time}")
```

##### Job API Endpoints
```bash
# Get all job statuses
curl http://localhost:8000/api/v1/background-jobs/status

# Get specific job status
curl http://localhost:8000/api/v1/background-jobs/status/cleanup_expired_slots

# Run job manually
curl -X POST http://localhost:8000/api/v1/background-jobs/run/cleanup_expired_slots

# Get job history
curl http://localhost:8000/api/v1/background-jobs/history/cleanup_expired_slots
```

#### Job Monitoring

##### Health Check Endpoint
```bash
# Check background job health
curl http://localhost:8000/health/background-jobs
```

##### Job Metrics
```python
# Get job metrics
metrics = await job_manager.get_metrics()
print(f"Total jobs: {metrics.total_jobs}")
print(f"Active jobs: {metrics.active_jobs}")
print(f"Failed jobs: {metrics.failed_jobs}")
print(f"Average execution time: {metrics.average_execution_time}")
```

##### Error Handling
```python
# Jobs automatically retry on failure
# After max retries, jobs are marked as failed
# Failed jobs can be manually restarted

# Restart failed job
await job_manager.restart_job("cleanup_expired_slots")
```

---

## Exception Handling

### Custom Exception Hierarchy

#### Why This Is Critical

##### 1. User-Friendly Error Messages
- **Generic exception**: "IntegrityError: duplicate key value violates unique constraint"
- **Custom exception**: "This time slot is already booked"
- Users understand what went wrong
- Reduces support tickets and user frustration

##### 2. Machine-Readable Error Codes
- API consumers can handle specific errors programmatically
- `error_code: "slot_unavailable"` → show different slots
- `error_code: "license_suspended"` → show payment page
- Enables smart error handling in UI components

##### 3. Centralized Error Handling
- All `SlotUnavailableError` handled consistently across the API
- Consistent error response format
- Change error format in one place
- Reduces code duplication

#### Exception Hierarchy

##### Base Exceptions
```python
class CallCenterAIException(Exception):
    """Base exception for all CallCenterAI errors."""
    def __init__(self, message: str, error_code: str = None, details: dict = None):
        self.message = message
        self.error_code = error_code
        self.details = details or {}
        super().__init__(self.message)

class ValidationError(CallCenterAIException):
    """Raised when input validation fails."""
    pass

class DatabaseError(CallCenterAIException):
    """Raised when database operations fail."""
    pass

class ExternalServiceError(CallCenterAIException):
    """Raised when external service calls fail."""
    pass
```

##### Business Logic Exceptions
```python
class SlotUnavailableError(CallCenterAIException):
    """Raised when appointment slot is not available."""
    def __init__(self, slot_id: str, reason: str = "Slot is already booked"):
        super().__init__(
            message=reason,
            error_code="slot_unavailable",
            details={"slot_id": slot_id, "reason": reason}
        )

class LicenseSuspendedError(CallCenterAIException):
    """Raised when clinic license is suspended."""
    def __init__(self, clinic_id: str, reason: str = "License suspended"):
        super().__init__(
            message=reason,
            error_code="license_suspended",
            details={"clinic_id": clinic_id, "reason": reason}
        )

class RecordNotFoundError(CallCenterAIException):
    """Raised when requested record is not found."""
    def __init__(self, entity_type: str, entity_id: str):
        super().__init__(
            message=f"{entity_type} not found",
            error_code="record_not_found",
            details={"entity_type": entity_type, "entity_id": entity_id}
        )
```

##### Service-Specific Exceptions
```python
class AzureCommunicationError(ExternalServiceError):
    """Raised when Azure Communication Services fails."""
    pass

class GoogleCalendarError(ExternalServiceError):
    """Raised when Google Calendar API fails."""
    pass

class OpenAIError(ExternalServiceError):
    """Raised when Azure OpenAI fails."""
    pass
```

#### Usage Examples

##### Raising Exceptions
```python
# Raise business logic exception
if slot.is_booked:
    raise SlotUnavailableError(
        slot_id=slot.id,
        reason="This time slot is already booked"
    )

# Raise validation exception
if not phone_number.startswith('+'):
    raise ValidationError(
        message="Phone number must include country code",
        error_code="invalid_phone_format",
        details={"phone_number": phone_number}
    )
```

##### Handling Exceptions
```python
from services.exceptions import SlotUnavailableError, ValidationError

try:
    appointment = await book_appointment(slot_id, patient_id)
except SlotUnavailableError as e:
    # Handle slot unavailable
    return {"error": e.message, "error_code": e.error_code, "details": e.details}
except ValidationError as e:
    # Handle validation error
    return {"error": e.message, "error_code": e.error_code, "details": e.details}
```

##### Exception Handler
```python
from services.exception_handler import get_exception_handler

@app.exception_handler(SlotUnavailableError)
async def slot_unavailable_handler(request: Request, exc: SlotUnavailableError):
    return JSONResponse(
        status_code=409,  # Conflict
        content={
            "error": exc.message,
            "error_code": exc.error_code,
            "details": exc.details
        }
    )

@app.exception_handler(ValidationError)
async def validation_error_handler(request: Request, exc: ValidationError):
    return JSONResponse(
        status_code=400,  # Bad Request
        content={
            "error": exc.message,
            "error_code": exc.error_code,
            "details": exc.details
        }
    )
```

#### Error Response Format

##### Standard Error Response
```json
{
    "error": "This time slot is already booked",
    "error_code": "slot_unavailable",
    "details": {
        "slot_id": "slot_123",
        "reason": "Slot is already booked"
    },
    "timestamp": "2024-01-15T10:30:45.123Z",
    "request_id": "req_789"
}
```

##### Validation Error Response
```json
{
    "error": "Phone number must include country code",
    "error_code": "invalid_phone_format",
    "details": {
        "phone_number": "1234567890",
        "field": "phone_number"
    },
    "timestamp": "2024-01-15T10:30:45.123Z",
    "request_id": "req_789"
}
```

#### Exception Logging

##### Automatic Logging
```python
# Exceptions are automatically logged with context
logger.error(
    "Slot unavailable error",
    LogCategory.API,
    extra_data={
        "error_code": "slot_unavailable",
        "slot_id": slot_id,
        "clinic_id": clinic_id,
        "user_id": user_id
    },
    exception=exc
)
```

##### Custom Logging
```python
# Log custom exception details
logger.warning(
    "License suspended",
    LogCategory.SECURITY,
    extra_data={
        "clinic_id": clinic_id,
        "reason": "Payment overdue",
        "suspension_date": suspension_date
    }
)
```

---

## Clinic Customization

### Multi-Tenant Architecture

#### Why Multi-Tenancy is Critical

##### 1. Data Isolation
- **Complete Separation**: Each clinic's data is completely isolated
- **Security**: No cross-clinic data access possible
- **Compliance**: HIPAA requires data isolation between entities
- **Scalability**: Easy to add new clinics without affecting existing ones

##### 2. Customization
- **Clinic-Specific Settings**: Each clinic can have different configurations
- **Branding**: Custom clinic names, phone numbers, timezones
- **Business Rules**: Different appointment durations, business hours
- **Integration**: Clinic-specific Google Calendar accounts

#### Clinic Configuration

##### Clinic Model
```python
class Clinic(Base):
    __tablename__ = "clinics"
    
    clinic_id = Column(String(64), primary_key=True)
    clinic_name = Column(String(200), nullable=False)
    phone_number = Column(String(20), nullable=False, unique=True)
    email_token = Column(String(64), nullable=True)
    address_token = Column(String(64), nullable=True)
    timezone = Column(String(50), default="America/Puerto_Rico", nullable=False)
    default_language = Column(String(5), default="en", nullable=False)
    supported_languages = Column(String(20), default="en,es", nullable=False)
    ehr_system = Column(String(20), nullable=False)
    ehr_api_endpoint = Column(String(500), nullable=True)
    ehr_credentials_vault_key = Column(String(100), nullable=True)
    ehr_enabled = Column(String(10), default="yes", nullable=False)
    fallback_system = Column(String(20), default="google_calendar", nullable=False)
    fallback_credentials_vault_key = Column(String(100), nullable=True)
    max_concurrent_calls = Column(Integer, default=10, nullable=False)
    queue_timeout_seconds = Column(Integer, default=60, nullable=False)
    subscription_tier = Column(String(20), default="professional", nullable=False)
    license_expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
```

##### Creating a New Clinic
```python
from services.clinic_management import ClinicManagementService

# Create clinic service
clinic_service = ClinicManagementService(db)

# Create new clinic
clinic_data = {
    "clinic_name": "St. Peters Medical Center",
    "phone_number": "+1234567890",
    "timezone": "America/New_York",
    "default_language": "en",
    "supported_languages": "en,es",
    "ehr_system": "google_calendar",
    "max_concurrent_calls": 15,
    "queue_timeout_seconds": 45,
    "subscription_tier": "professional"
}

clinic = await clinic_service.create_clinic(clinic_data)
```

##### Clinic-Specific Data Access
```python
# All queries automatically filter by clinic_id
patients = await db.query(Patient).filter(Patient.clinic_id == clinic_id).all()
appointments = await db.query(Appointment).filter(Appointment.clinic_id == clinic_id).all()
providers = await db.query(Provider).filter(Provider.clinic_id == clinic_id).all()
```

#### Provider Management

##### Provider Model
```python
class Provider(Base):
    __tablename__ = "providers"
    
    provider_id = Column(String(64), primary_key=True)
    clinic_id = Column(String(64), ForeignKey("clinics.clinic_id"), nullable=False, index=True)
    name_token = Column(String(64), nullable=False)
    title = Column(String(20), nullable=False)
    specialty = Column(String(100), nullable=False)
    license_number = Column(String(20), nullable=False)
    npi_number = Column(String(20), nullable=True)
    email = Column(String(200), nullable=False)
    phone_token = Column(String(64), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
```

##### Creating Providers
```python
from services.provider_management import ProviderManagementService

# Create provider service
provider_service = ProviderManagementService(db)

# Create new provider
provider_data = {
    "name_token": "PROVIDER_DR_SMITH_001",
    "title": "Dr.",
    "specialty": "Internal Medicine",
    "license_number": "NY123456",
    "npi_number": "1234567890",
    "email": "dr.smith@stpeters.com"
}

provider = await provider_service.create_provider(clinic_id, provider_data)
```

#### Appointment Slot Management

##### Creating Appointment Slots
```python
from services.appointment_service import AppointmentService

# Create appointment service
appointment_service = AppointmentService(db)

# Create appointment slots for a provider
slots = await appointment_service.create_appointment_slots(
    provider_id=provider_id,
    start_date=datetime(2024, 1, 15),
    end_date=datetime(2024, 1, 19),
    start_time=time(9, 0),  # 9:00 AM
    end_time=time(17, 0),   # 5:00 PM
    duration_minutes=30,
    days_of_week=[0, 1, 2, 3, 4]  # Monday to Friday
)
```

##### Clinic-Specific Business Rules
```python
# Different clinics can have different business rules
if clinic.subscription_tier == "basic":
    max_appointments_per_day = 50
    max_duration_minutes = 30
elif clinic.subscription_tier == "professional":
    max_appointments_per_day = 100
    max_duration_minutes = 60
elif clinic.subscription_tier == "enterprise":
    max_appointments_per_day = 500
    max_duration_minutes = 120
```

#### Customization Examples

##### 1. Clinic Setup Script
```python
# Create clinic setup script
async def setup_new_clinic(clinic_data, providers_data, appointment_slots_data):
    # Create clinic
    clinic = await clinic_service.create_clinic(clinic_data)
    
    # Create providers
    providers = []
    for provider_data in providers_data:
        provider = await provider_service.create_provider(clinic.clinic_id, provider_data)
        providers.append(provider)
    
    # Create appointment slots
    for provider in providers:
        await appointment_service.create_appointment_slots(
            provider_id=provider.provider_id,
            **appointment_slots_data
        )
    
    return clinic
```

##### 2. Clinic Configuration API
```bash
# Get clinic configuration
curl http://localhost:8000/api/v1/clinics/{clinic_id}

# Update clinic configuration
curl -X PUT http://localhost:8000/api/v1/clinics/{clinic_id} \
  -H "Content-Type: application/json" \
  -d '{
    "max_concurrent_calls": 20,
    "queue_timeout_seconds": 30,
    "subscription_tier": "enterprise"
  }'

# Get clinic providers
curl http://localhost:8000/api/v1/clinics/{clinic_id}/providers

# Create new provider
curl -X POST http://localhost:8000/api/v1/clinics/{clinic_id}/providers \
  -H "Content-Type: application/json" \
  -d '{
    "name_token": "PROVIDER_DR_JOHNSON_001",
    "title": "Dr.",
    "specialty": "Cardiology",
    "license_number": "NY789012",
    "email": "dr.johnson@clinic.com"
  }'
```

##### 3. Multi-Tenant Data Isolation
```python
# All database operations automatically include clinic_id
class Patient(Base):
    __tablename__ = "patients"
    
    patient_id = Column(String(64), primary_key=True)
    clinic_id = Column(String(64), ForeignKey("clinics.clinic_id"), nullable=False, index=True)
    # ... other fields

# Queries automatically filter by clinic_id
patients = await db.query(Patient).filter(Patient.clinic_id == clinic_id).all()

# No cross-clinic data access possible
# Each clinic only sees their own data
```

---

## Google Calendar Integration

### OAuth Setup

#### 1. Google Cloud Console Setup

1. **Go to Google Cloud Console**
   - Visit: https://console.cloud.google.com/
   - Sign in with your Google account

2. **Create a New Project**
   - Click "Select a project" → "New Project"
   - Name: "CallCenterAI Calendar Integration"
   - Click "Create"

3. **Enable Google Calendar API**
   - Go to "APIs & Services" → "Library"
   - Search for "Google Calendar API"
   - Click on it and press "Enable"

#### 2. Create OAuth 2.0 Credentials

1. **Go to Credentials**
   - Navigate to "APIs & Services" → "Credentials"
   - Click "Create Credentials" → "OAuth 2.0 Client IDs"

2. **Configure OAuth Consent Screen**
   - If prompted, configure the OAuth consent screen:
     - User Type: External
     - App name: "CallCenterAI"
     - User support email: Your email
     - Developer contact: Your email
     - Add scopes: `https://www.googleapis.com/auth/calendar`

3. **Create OAuth Client**
   - Application type: "Web application"
   - Name: "CallCenterAI Gateway"
   - Authorized redirect URIs:
     - `http://localhost:8443/api/google-calendar/oauth/callback`
     - `https://yourdomain.com/api/google-calendar/oauth/callback` (for production)

4. **Download Credentials**
   - Download the JSON file
   - Extract `client_id` and `client_secret`

#### 3. Environment Configuration

```bash
# Google Calendar Configuration
GOOGLE_CLIENT_ID=your_client_id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your_client_secret
GOOGLE_REDIRECT_URI=http://localhost:8443/api/google-calendar/oauth/callback
GOOGLE_API_KEY=your_api_key
GOOGLE_SCOPES=["https://www.googleapis.com/auth/calendar"]

# Rate limiting
GOOGLE_REQUESTS_PER_MINUTE=100
GOOGLE_REQUESTS_PER_DAY=10000

# Sync settings
GOOGLE_SYNC_INTERVAL_MINUTES=5
GOOGLE_MAX_SYNC_RETRIES=3
GOOGLE_SYNC_TIMEOUT_SECONDS=30
```

### OAuth Flow

#### 1. Initiate OAuth
```python
from services.google_calendar_service import GoogleCalendarService

# Create Google Calendar service
google_service = GoogleCalendarService()

# Generate OAuth URL
oauth_url = google_service.get_authorization_url(
    clinic_id=clinic_id,
    redirect_uri=redirect_uri
)

# Redirect user to oauth_url
```

#### 2. Handle OAuth Callback
```python
# Handle OAuth callback
async def oauth_callback(code: str, state: str):
    # Exchange code for tokens
    tokens = await google_service.exchange_code_for_tokens(code)
    
    # Store tokens securely
    await google_service.store_credentials(clinic_id, tokens)
    
    return {"status": "success", "message": "Google Calendar connected"}
```

#### 3. Use Google Calendar
```python
# Create calendar event
event_data = {
    "summary": "Appointment with Dr. Smith",
    "description": "Patient appointment",
    "start": {
        "dateTime": "2024-01-15T10:00:00-05:00",
        "timeZone": "America/New_York"
    },
    "end": {
        "dateTime": "2024-01-15T10:30:00-05:00",
        "timeZone": "America/New_York"
    }
}

# Create event
event = await google_service.create_event(clinic_id, event_data)
```

### Calendar Integration

#### 1. Appointment Synchronization
```python
# Sync appointment to Google Calendar
async def sync_appointment_to_calendar(appointment):
    google_service = GoogleCalendarService()
    
    # Create calendar event
    event_data = {
        "summary": f"Appointment with {appointment.provider.title} {appointment.provider.name_token}",
        "description": f"Patient: {appointment.patient.name_token}",
        "start": {
            "dateTime": appointment.start_time.isoformat(),
            "timeZone": appointment.clinic.timezone
        },
        "end": {
            "dateTime": appointment.end_time.isoformat(),
            "timeZone": appointment.clinic.timezone
        }
    }
    
    # Create event
    event = await google_service.create_event(appointment.clinic_id, event_data)
    
    # Store event ID
    appointment.google_event_id = event["id"]
    await db.commit()
```

#### 2. Availability Checking
```python
# Check provider availability
async def check_provider_availability(provider_id, start_time, end_time):
    google_service = GoogleCalendarService()
    
    # Get provider's calendar
    provider = await db.query(Provider).filter(Provider.provider_id == provider_id).first()
    
    # Check for conflicts
    conflicts = await google_service.get_conflicting_events(
        provider.clinic_id,
        start_time,
        end_time
    )
    
    return len(conflicts) == 0
```

#### 3. Calendar Webhooks
```python
# Handle calendar webhooks
async def handle_calendar_webhook(webhook_data):
    google_service = GoogleCalendarService()
    
    # Process webhook
    await google_service.process_webhook(webhook_data)
    
    return {"status": "success"}
```

### API Endpoints

#### 1. OAuth Endpoints
```bash
# Get OAuth URL
curl http://localhost:8000/api/v1/google-calendar/oauth/url?clinic_id=clinic_123

# Handle OAuth callback
curl -X POST http://localhost:8000/api/v1/google-calendar/oauth/callback \
  -H "Content-Type: application/json" \
  -d '{
    "code": "oauth_code",
    "state": "clinic_123"
  }'
```

#### 2. Calendar Endpoints
```bash
# Get calendar events
curl http://localhost:8000/api/v1/google-calendar/events?clinic_id=clinic_123

# Create calendar event
curl -X POST http://localhost:8000/api/v1/google-calendar/events \
  -H "Content-Type: application/json" \
  -d '{
    "clinic_id": "clinic_123",
    "summary": "Appointment with Dr. Smith",
    "start": "2024-01-15T10:00:00-05:00",
    "end": "2024-01-15T10:30:00-05:00"
  }'

# Update calendar event
curl -X PUT http://localhost:8000/api/v1/google-calendar/events/event_123 \
  -H "Content-Type: application/json" \
  -d '{
    "summary": "Updated appointment"
  }'

# Delete calendar event
curl -X DELETE http://localhost:8000/api/v1/google-calendar/events/event_123
```

#### 3. Sync Endpoints
```bash
# Sync appointments to calendar
curl -X POST http://localhost:8000/api/v1/google-calendar/sync/appointments \
  -H "Content-Type: application/json" \
  -d '{
    "clinic_id": "clinic_123",
    "start_date": "2024-01-15",
    "end_date": "2024-01-19"
  }'

# Get sync status
curl http://localhost:8000/api/v1/google-calendar/sync/status?clinic_id=clinic_123
```

---

## Migration & Deployment

### Database Migration

#### Migration Commands

##### Using the Migration Script
```bash
# Apply all pending migrations
python migrate.py upgrade

# Create a new migration (auto-generate from model changes)
python migrate.py revision "Add new column to patients table"

# Show migration history
python migrate.py history

# Show current migration version
python migrate.py current

# Rollback last migration
python migrate.py downgrade

# Reset database (DEVELOPMENT ONLY - DESTROYS ALL DATA)
python migrate.py reset
```

##### Direct Alembic Commands
```bash
# Initialize Alembic (first time only)
alembic init migrations

# Create a new migration
alembic revision --autogenerate -m "Add new table"

# Apply migrations
alembic upgrade head

# Rollback one migration
alembic downgrade -1

# Rollback to specific version
alembic downgrade abc123

# Show current version
alembic current

# Show migration history
alembic history
```

#### Creating New Migrations

##### 1. Modify Models
```python
# In models/models.py
class Patient(Base):
    __tablename__ = "patients"
    
    id = Column(String(64), primary_key=True)
    name_token = Column(String(64), nullable=False)
    phone_token = Column(String(64), nullable=False)
    
    # Add new column
    email_token = Column(String(64), nullable=True)  # New field
    date_of_birth = Column(Date, nullable=True)      # New field
```

##### 2. Generate Migration
```bash
# Auto-generate migration from model changes
python migrate.py revision "Add email and date_of_birth to patients"
```

##### 3. Review Generated Migration
```python
# In migrations/versions/xxx_add_email_and_date_of_birth.py
def upgrade():
    # Add new columns
    op.add_column('patients', sa.Column('email_token', sa.String(64), nullable=True))
    op.add_column('patients', sa.Column('date_of_birth', sa.Date(), nullable=True))

def downgrade():
    # Remove columns
    op.drop_column('patients', 'date_of_birth')
    op.drop_column('patients', 'email_token')
```

##### 4. Apply Migration
```bash
# Apply the migration
python migrate.py upgrade
```

### Docker Deployment

#### Dockerfile
```dockerfile
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create logs directory
RUN mkdir -p logs

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/healthz || exit 1

# Start application
CMD ["python", "main.py"]
```

#### Docker Compose
```yaml
version: "3.9"

services:
  gateway:
    build:
      context: ./gateway
      dockerfile: Dockerfile
    ports:
      - "8000:8000"
    environment:
      # Application Configuration
      - APP_ENVIRONMENT=production
      - APP_DEBUG=false
      - APP_HOST=0.0.0.0
      - APP_PORT=8000
      
      # Database Configuration
      - DB_HOST=postgres
      - DB_PORT=5432
      - DB_NAME=callcenterai
      - DB_USER=callcenterai
      - DB_PASSWORD=ChangeThisNow_!
      - DB_POOL_SIZE=20
      - DB_MAX_OVERFLOW=40
      
      # Security Configuration
      - SECURITY_ENCRYPTION_KEY=your_32_byte_encryption_key_here
      - SECURITY_JWT_SECRET=your_jwt_secret_at_least_32_characters_long
      - SECURITY_CORS_ORIGINS=["https://yourdomain.com"]
      
      # Logging Configuration
      - LOG_LEVEL=INFO
      - LOG_FORMAT=json
      - LOG_STRUCTURED_ENABLED=true
      - LOG_PHI_MASKING_ENABLED=true
      
      # Google Calendar Configuration
      - GOOGLE_CLIENT_ID=your_client_id.apps.googleusercontent.com
      - GOOGLE_CLIENT_SECRET=your_client_secret
      - GOOGLE_REDIRECT_URI=https://yourdomain.com/api/google-calendar/oauth/callback
      
      # Azure Configuration
      - AZURE_ACS_CONNECTION_STRING=endpoint=https://your.communication.azure.com/;accesskey=your_key
      - AZURE_OPENAI_ENDPOINT=https://your.openai.azure.com/
      - AZURE_OPENAI_API_KEY=your_api_key
    depends_on:
      - postgres
    restart: always
    volumes:
      - ./logs:/app/logs

  postgres:
    image: postgres:16
    environment:
      - POSTGRES_DB=callcenterai
      - POSTGRES_USER=callcenterai
      - POSTGRES_PASSWORD=ChangeThisNow_!
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    restart: always

volumes:
  postgres_data:
```

#### Deployment Commands
```bash
# Build and start services
docker-compose up -d

# View logs
docker-compose logs -f gateway

# Stop services
docker-compose down

# Rebuild and restart
docker-compose up -d --build

# Run migrations
docker-compose exec gateway python migrate.py upgrade

# Create demo data
docker-compose exec gateway python demo_setup.py
```

### Environment-Specific Configuration

#### Development Environment
```bash
# Development settings
APP_ENVIRONMENT=development
APP_DEBUG=true
LOG_LEVEL=DEBUG
DB_POOL_SIZE=5
SECURITY_CORS_ORIGINS=["http://localhost:3000", "http://localhost:8000"]
SECURITY_RATE_LIMIT_PER_MINUTE=1000
```

#### Staging Environment
```bash
# Staging settings
APP_ENVIRONMENT=staging
APP_DEBUG=false
LOG_LEVEL=INFO
DB_POOL_SIZE=10
SECURITY_CORS_ORIGINS=["https://staging.yourdomain.com"]
SECURITY_RATE_LIMIT_PER_MINUTE=200
```

#### Production Environment
```bash
# Production settings
APP_ENVIRONMENT=production
APP_DEBUG=false
LOG_LEVEL=WARNING
DB_POOL_SIZE=20
SECURITY_CORS_ORIGINS=["https://yourdomain.com"]
SECURITY_RATE_LIMIT_PER_MINUTE=100
```

### Health Monitoring

#### Health Check Endpoints
```bash
# Application health
curl http://localhost:8000/healthz

# Database health
curl http://localhost:8000/health/database

# Background jobs health
curl http://localhost:8000/health/background-jobs

# Google Calendar health
curl http://localhost:8000/health/google-calendar

# Azure services health
curl http://localhost:8000/health/azure
```

#### Health Check Response
```json
{
    "status": "healthy",
    "timestamp": "2024-01-15T10:30:45.123Z",
    "services": {
        "database": {
            "status": "healthy",
            "response_time": 0.045,
            "connection_pool": {
                "size": 20,
                "checked_in": 15,
                "checked_out": 5,
                "overflow": 0
            }
        },
        "background_jobs": {
            "status": "healthy",
            "active_jobs": 8,
            "failed_jobs": 0,
            "last_run": "2024-01-15T10:30:00.000Z"
        },
        "google_calendar": {
            "status": "healthy",
            "connected_clinics": 5,
            "last_sync": "2024-01-15T10:25:00.000Z"
        }
    }
}
```

---

## Troubleshooting

### Common Issues

#### 1. Configuration Issues

##### Missing Environment Variables
```bash
Error: Encryption key is required
Solution: Set SECURITY_ENCRYPTION_KEY environment variable

Error: JWT secret must be at least 32 characters
Solution: Use a longer JWT secret

Error: Invalid Google client ID format
Solution: Ensure client ID ends with .apps.googleusercontent.com
```

##### Configuration Validation
```bash
# Validate configuration
python validate_config.py

# Show detailed validation results
python validate_config.py --verbose

# Validate specific environment
python validate_config.py --environment production
```

#### 2. Database Issues

##### Connection Pool Exhaustion
```bash
Error: too many connections
Solution: Increase DB_POOL_SIZE or DB_MAX_OVERFLOW

Error: connection timeout
Solution: Increase DB_POOL_TIMEOUT
```

##### Migration Issues
```bash
Error: migration failed
Solution: Check migration file for syntax errors

Error: database locked
Solution: Wait for other operations to complete
```

#### 3. Google Calendar Issues

##### OAuth Issues
```bash
Error: invalid_grant
Solution: Check client_id and client_secret

Error: redirect_uri_mismatch
Solution: Ensure redirect URI matches exactly
```

##### API Issues
```bash
Error: quota exceeded
Solution: Check API quotas and rate limits

Error: calendar not found
Solution: Ensure calendar exists and is accessible
```

#### 4. Azure Services Issues

##### Communication Services
```bash
Error: invalid connection string
Solution: Check ACS_CONNECTION_STRING format

Error: phone number not found
Solution: Ensure phone number is provisioned
```

##### OpenAI Issues
```bash
Error: invalid endpoint
Solution: Check AZURE_OPENAI_ENDPOINT format

Error: deployment not found
Solution: Ensure deployment exists and is active
```

### Debugging Commands

#### 1. Configuration Debugging
```bash
# Check environment variables
env | grep -E "(APP_|DB_|SECURITY_|LOG_|GOOGLE_|AZURE_)"

# Test configuration loading
python -c "from services.configuration import get_settings; print(get_settings().environment)"

# Validate configuration
python validate_config.py --verbose
```

#### 2. Database Debugging
```bash
# Test database connection
python -c "from services.database import test_database_connection; test_database_connection()"

# Check migration status
python migrate.py current

# Show migration history
python migrate.py history
```

#### 3. Service Debugging
```bash
# Check service health
curl http://localhost:8000/healthz

# Check specific service
curl http://localhost:8000/health/database

# View logs
tail -f logs/app.log
```

#### 4. Google Calendar Debugging
```bash
# Test OAuth flow
curl http://localhost:8000/api/v1/google-calendar/oauth/url?clinic_id=test

# Check calendar connection
curl http://localhost:8000/health/google-calendar
```

### Performance Issues

#### 1. Slow Queries
```bash
# Enable query logging
LOG_LEVEL=DEBUG

# Check slow queries in logs
grep "Slow query" logs/app.log

# Optimize database indexes
python migrate.py revision "Add performance indexes"
```

#### 2. Memory Issues
```bash
# Check memory usage
python -c "import psutil; print(psutil.virtual_memory())"

# Monitor connection pool
curl http://localhost:8000/health/database
```

#### 3. Rate Limiting
```bash
# Check rate limit settings
SECURITY_RATE_LIMIT_PER_MINUTE=100

# Monitor rate limit usage
grep "rate_limit" logs/app.log
```

### Security Issues

#### 1. PHI Exposure
```bash
# Check PHI masking
LOG_PHI_MASKING_ENABLED=true

# Audit PHI access
grep "PHI" logs/audit.log
```

#### 2. Authentication Issues
```bash
# Check JWT configuration
SECURITY_JWT_SECRET=your_jwt_secret_at_least_32_characters_long

# Monitor failed logins
grep "Failed authentication" logs/app.log
```

#### 3. CORS Issues
```bash
# Check CORS configuration
SECURITY_CORS_ORIGINS=["https://yourdomain.com"]

# Test CORS
curl -H "Origin: https://yourdomain.com" http://localhost:8000/api/v1/clinics
```

### Recovery Procedures

#### 1. Database Recovery
```bash
# Restore from backup
pg_restore -d callcenterai backup.sql

# Rollback migration
python migrate.py downgrade

# Reset database (DEVELOPMENT ONLY)
python migrate.py reset
```

#### 2. Service Recovery
```bash
# Restart services
docker-compose restart gateway

# Rebuild services
docker-compose up -d --build

# Check service status
docker-compose ps
```

#### 3. Configuration Recovery
```bash
# Restore configuration
cp .env.backup .env

# Regenerate configuration
python config_manager.py generate --environment production
```

---

## Conclusion

The CallCenterAI Gateway provides a comprehensive, HIPAA-compliant solution for medical clinic call center automation. This documentation covers all aspects of the system, from configuration management to deployment and troubleshooting.

### Key Features Implemented

- ✅ **Configuration Management** - Pydantic-based type-safe configuration
- ✅ **Database Management** - Connection pooling, constraints, transactions, soft delete
- ✅ **Security & HIPAA Compliance** - PHI tokenization, encryption, audit trails
- ✅ **Logging & Monitoring** - Structured logging with PHI masking
- ✅ **Background Jobs** - Automated cleanup and maintenance
- ✅ **Exception Handling** - User-friendly error messages
- ✅ **Clinic Customization** - Multi-tenant architecture
- ✅ **Google Calendar Integration** - OAuth and event synchronization
- ✅ **Migration & Deployment** - Alembic migrations and Docker deployment

### Next Steps

1. **Configure Environment Variables** - Set up all required environment variables
2. **Run Database Migrations** - Apply all pending migrations
3. **Set Up Google Calendar** - Configure OAuth and test integration
4. **Deploy to Production** - Use Docker Compose for deployment
5. **Monitor System Health** - Set up monitoring and alerting

The system is production-ready and provides a solid foundation for HIPAA-compliant call center automation.
