# Custom Exception Hierarchy Guide

## Overview

The CallCenterAI Custom Exception Hierarchy provides a comprehensive, user-friendly, and machine-readable error handling system that transforms generic database and system errors into meaningful, actionable messages for both users and API consumers.

## Why This Is Critical

### 1. User-Friendly Error Messages
- **Generic exception**: "IntegrityError: duplicate key value violates unique constraint"
- **Custom exception**: "This time slot is already booked"
- Users understand what went wrong
- Reduces support tickets and user frustration

### 2. Machine-Readable Error Codes
- API consumers can handle specific errors programmatically
- `error_code: "slot_unavailable"` → show different slots
- `error_code: "license_suspended"` → show payment page
- Enables smart error handling in UI components

### 3. Centralized Error Handling
- All `SlotUnavailableError` handled consistently across the API
- Consistent error response format
- Change error format in one place
- Reduces code duplication

### 4. Proper HTTP Status Codes
- `SlotUnavailableError` → 409 Conflict
- `RecordNotFoundError` → 404 Not Found
- `LicenseSuspendedError` → 403 Forbidden
- API follows REST conventions

### 5. Contextual Information
- Exception includes `slot_id`, `clinic_id`, `reason`
- Developers have context for debugging
- Users see relevant information
- Support staff can help faster

### 6. Distinguishable Error Types
- Catch `SlotUnavailableError` differently than `DatabaseError`
- Retry transient errors, don't retry permanent errors
- Log errors at appropriate severity
- Handle errors intelligently

### 7. Security Through Obscurity Avoidance
- Don't expose database internals to users
- "Database constraint violation" → "This record already exists"
- Prevents information leakage
- Professional error messages

### 8. Integration with Monitoring
- Count errors by `error_code`
- Alert on spike in specific error
- "50 slot_unavailable errors in 10 minutes" → double booking bug
- Proactive issue detection

## System Architecture

### Core Components

1. **Base Exception Class** (`CallCenterAIException`)
   - Provides common functionality for all exceptions
   - Includes error codes, HTTP status, user messages, context
   - Converts to API response format and log format

2. **Error Codes** (`ErrorCode` enum)
   - Machine-readable identifiers for all error types
   - Used by API consumers for programmatic handling
   - Enables monitoring and alerting

3. **Specific Exception Classes**
   - Appointment-related: `SlotUnavailableError`, `AppointmentNotFoundError`
   - Patient-related: `PatientNotFoundError`, `InvalidPatientDataError`
   - Clinic-related: `ClinicLicenseSuspendedError`, `ClinicLicenseExpiredError`
   - Authentication: `AuthenticationFailedError`, `AuthorizationDeniedError`
   - System: `DatabaseError`, `ValidationError`, `ConcurrencyError`

4. **Exception Mapper** (`ExceptionMapper`)
   - Maps generic exceptions to CallCenterAI exceptions
   - Handles database errors, validation errors, external service errors
   - Provides intelligent error classification

5. **Exception Handler** (`ExceptionHandler`)
   - FastAPI middleware for centralized exception handling
   - Logs exceptions with full context
   - Returns consistent error responses

## Exception Types

### Appointment-Related Exceptions

#### `SlotUnavailableError`
- **When**: Appointment slot is already booked
- **HTTP Status**: 409 Conflict
- **User Message**: "This time slot is already booked. Please select another time."
- **Context**: `slot_id`, `clinic_id`, `reason`

```python
raise SlotUnavailableError("slot123", "clinic456", "Already booked")
```

#### `AppointmentNotFoundError`
- **When**: Appointment cannot be found
- **HTTP Status**: 404 Not Found
- **User Message**: "The requested appointment could not be found."
- **Context**: `appointment_id`

```python
raise AppointmentNotFoundError("appointment123")
```

#### `InvalidAppointmentTimeError`
- **When**: Appointment time is invalid
- **HTTP Status**: 400 Bad Request
- **User Message**: "The appointment time is invalid. Please check the start and end times."
- **Context**: `start_time`, `end_time`, `reason`

```python
raise InvalidAppointmentTimeError("2024-01-01 10:00", "2024-01-01 09:00", "End time before start time")
```

### Patient-Related Exceptions

#### `PatientNotFoundError`
- **When**: Patient cannot be found
- **HTTP Status**: 404 Not Found
- **User Message**: "The requested patient could not be found."
- **Context**: `patient_id`

```python
raise PatientNotFoundError("patient123")
```

#### `PatientAlreadyExistsError`
- **When**: Patient with same email/phone already exists
- **HTTP Status**: 409 Conflict
- **User Message**: "A patient with this email or phone number already exists."
- **Context**: `email`, `phone`

```python
raise PatientAlreadyExistsError("test@example.com", "+1234567890")
```

#### `InvalidPatientDataError`
- **When**: Patient data validation fails
- **HTTP Status**: 400 Bad Request
- **User Message**: "The {field} field is invalid. {reason}"
- **Context**: `field`, `value`, `reason`

```python
raise InvalidPatientDataError("email", "invalid-email", "Invalid email format")
```

### Clinic-Related Exceptions

#### `ClinicNotFoundError`
- **When**: Clinic cannot be found
- **HTTP Status**: 404 Not Found
- **User Message**: "The requested clinic could not be found."
- **Context**: `clinic_id`

```python
raise ClinicNotFoundError("clinic123")
```

#### `ClinicLicenseSuspendedError`
- **When**: Clinic license is suspended
- **HTTP Status**: 403 Forbidden
- **User Message**: "This clinic's license has been suspended. Please contact support."
- **Context**: `clinic_id`, `reason`

```python
raise ClinicLicenseSuspendedError("clinic123", "Payment overdue")
```

#### `ClinicLicenseExpiredError`
- **When**: Clinic license has expired
- **HTTP Status**: 403 Forbidden
- **User Message**: "This clinic's license has expired. Please renew your license."
- **Context**: `clinic_id`, `expiry_date`

```python
raise ClinicLicenseExpiredError("clinic123", "2024-01-01")
```

### Authentication and Authorization Exceptions

#### `AuthenticationFailedError`
- **When**: Authentication fails
- **HTTP Status**: 401 Unauthorized
- **User Message**: "Authentication failed. Please check your credentials."
- **Context**: `reason`

```python
raise AuthenticationFailedError("Invalid password")
```

#### `AuthorizationDeniedError`
- **When**: User lacks permission for action
- **HTTP Status**: 403 Forbidden
- **User Message**: "You don't have permission to perform this action."
- **Context**: `resource`, `action`, `reason`

```python
raise AuthorizationDeniedError("appointments", "create", "Insufficient role")
```

#### `InvalidTokenError`
- **When**: Token is malformed or invalid
- **HTTP Status**: 401 Unauthorized
- **User Message**: "The provided token is invalid."
- **Context**: `reason`

```python
raise InvalidTokenError("Malformed JWT")
```

#### `TokenExpiredError`
- **When**: Token has expired
- **HTTP Status**: 401 Unauthorized
- **User Message**: "Your session has expired. Please log in again."
- **Context**: `expiry_time`

```python
raise TokenExpiredError("2024-01-01T12:00:00Z")
```

### System and Database Exceptions

#### `DatabaseError`
- **When**: Database operation fails
- **HTTP Status**: 500 Internal Server Error
- **User Message**: "A database error occurred. Please try again later."
- **Context**: `operation`, `reason`

```python
raise DatabaseError("create_appointment", "Connection timeout", original_exception)
```

#### `ConnectionError`
- **When**: Database connection fails
- **HTTP Status**: 503 Service Unavailable
- **User Message**: "Unable to connect to the service. Please try again later."
- **Context**: `service`, `reason`

```python
raise ConnectionError("database", "Connection refused")
```

#### `ValidationError`
- **When**: Data validation fails
- **HTTP Status**: 400 Bad Request
- **User Message**: "The {field} field is invalid. {reason}"
- **Context**: `field`, `value`, `reason`

```python
raise ValidationError("email", "invalid-email", "Invalid format")
```

#### `ConcurrencyError`
- **When**: Concurrency conflict occurs
- **HTTP Status**: 409 Conflict
- **User Message**: "The resource was modified by another user. Please refresh and try again."
- **Context**: `resource`, `reason`

```python
raise ConcurrencyError("appointment_slot", "Row was modified by another transaction")
```

#### `RateLimitExceededError`
- **When**: Rate limit is exceeded
- **HTTP Status**: 429 Too Many Requests
- **User Message**: "Too many requests. Please wait before trying again."
- **Context**: `limit`, `window`, `retry_after`

```python
raise RateLimitExceededError(100, "minute", 60)
```

### External Service Exceptions

#### `GoogleCalendarError`
- **When**: Google Calendar integration fails
- **HTTP Status**: 502 Bad Gateway
- **User Message**: "Calendar integration is temporarily unavailable. Please try again later."
- **Context**: `operation`, `reason`

```python
raise GoogleCalendarError("create_event", "API quota exceeded", original_exception)
```

#### `AzureCommunicationError`
- **When**: Azure Communication Services fails
- **HTTP Status**: 502 Bad Gateway
- **User Message**: "Communication service is temporarily unavailable. Please try again later."
- **Context**: `operation`, `reason`

```python
raise AzureCommunicationError("send_sms", "Service down", original_exception)
```

#### `ExternalServiceUnavailableError`
- **When**: External service is unavailable
- **HTTP Status**: 503 Service Unavailable
- **User Message**: "An external service is temporarily unavailable. Please try again later."
- **Context**: `service`, `reason`

```python
raise ExternalServiceUnavailableError("payment_gateway", "Maintenance window")
```

### Business Logic Exceptions

#### `BusinessRuleViolationError`
- **When**: Business rule is violated
- **HTTP Status**: 400 Bad Request
- **User Message**: "Business rule violation: {reason}"
- **Context**: `rule`, `reason`

```python
raise BusinessRuleViolationError("no_double_booking", "Slot already booked", {"slot_id": "123"})
```

#### `OperationNotAllowedError`
- **When**: Operation is not allowed
- **HTTP Status**: 403 Forbidden
- **User Message**: "This operation is not allowed: {reason}"
- **Context**: `operation`, `reason`

```python
raise OperationNotAllowedError("delete_appointment", "Appointment is in the past", {"appointment_id": "123"})
```

#### `ResourceLimitExceededError`
- **When**: Resource limit is exceeded
- **HTTP Status**: 429 Too Many Requests
- **User Message**: "The {resource} limit has been exceeded. Please contact support."
- **Context**: `resource`, `limit`, `current`

```python
raise ResourceLimitExceededError("appointments", 100, 105)
```

#### `MaintenanceModeError`
- **When**: System is in maintenance mode
- **HTTP Status**: 503 Service Unavailable
- **User Message**: "The system is currently under maintenance. Please try again later."
- **Context**: `maintenance_window`, `reason`

```python
raise MaintenanceModeError("2024-01-01 02:00-04:00", "Scheduled maintenance")
```

## Usage Examples

### In Service Layer

```python
from services.exceptions import SlotUnavailableError, AppointmentNotFoundError

class AppointmentService:
    def create_appointment(self, appointment_data):
        # Check if slot is available
        if not self.is_slot_available(appointment_data.slot_id):
            raise SlotUnavailableError(
                appointment_data.slot_id, 
                appointment_data.clinic_id, 
                "Slot is already booked"
            )
        
        # Create appointment
        appointment = self._create_appointment(appointment_data)
        return appointment
    
    def get_appointment(self, appointment_id):
        appointment = self._get_appointment_by_id(appointment_id)
        if not appointment:
            raise AppointmentNotFoundError(appointment_id)
        return appointment
```

### In Route Handlers

```python
from fastapi import APIRouter, Depends
from services.exceptions import handle_route_exceptions
from services.appointment_service import AppointmentService

router = APIRouter()

@router.post("/appointments")
@handle_route_exceptions
async def create_appointment(
    appointment_data: AppointmentCreateRequest,
    appointment_service: AppointmentService = Depends()
):
    """Create a new appointment."""
    appointment = appointment_service.create_appointment(appointment_data)
    return {"appointment": appointment}

@router.get("/appointments/{appointment_id}")
@handle_route_exceptions
async def get_appointment(
    appointment_id: str,
    appointment_service: AppointmentService = Depends()
):
    """Get an appointment by ID."""
    appointment = appointment_service.get_appointment(appointment_id)
    return {"appointment": appointment}
```

### Exception Mapping

```python
from services.exceptions import ExceptionMapper
from sqlalchemy.exc import IntegrityError

def create_appointment_with_mapping(appointment_data):
    try:
        # Database operation that might fail
        appointment = db.session.add(Appointment(**appointment_data))
        db.session.commit()
        return appointment
    except IntegrityError as e:
        # Map database error to CallCenterAI exception
        raise ExceptionMapper.map_database_exception(e, "create_appointment")
    except Exception as e:
        # Map other errors
        raise ExceptionMapper.map_validation_exception(e, "appointment_data")
```

### External Service Integration

```python
from services.exceptions import handle_external_service_exceptions

@handle_external_service_exceptions("google_calendar")
async def sync_with_google_calendar(appointment):
    """Sync appointment with Google Calendar."""
    try:
        # Google Calendar API call
        calendar_service.events().insert(
            calendarId='primary',
            body=event_body
        ).execute()
    except Exception as e:
        # Automatically mapped to GoogleCalendarError
        raise
```

## API Response Format

All exceptions return a consistent JSON response format:

```json
{
  "error_code": "slot_unavailable",
  "message": "This time slot is already booked. Please select another time.",
  "details": {
    "slot_id": "slot123",
    "clinic_id": "clinic456",
    "reason": "Already booked"
  },
  "timestamp": "2024-01-01T12:00:00Z",
  "context": {
    "slot_id": "slot123",
    "clinic_id": "clinic456"
  }
}
```

### Response Fields

- **`error_code`**: Machine-readable error identifier
- **`message`**: User-friendly error message
- **`details`**: Additional error information
- **`timestamp`**: When the error occurred
- **`context`**: Relevant context for debugging

## Error Code Reference

### Appointment Errors
- `slot_unavailable`: Appointment slot is not available
- `appointment_not_found`: Appointment cannot be found
- `appointment_already_exists`: Duplicate appointment
- `invalid_appointment_time`: Invalid appointment time
- `appointment_cancellation_failed`: Failed to cancel appointment

### Patient Errors
- `patient_not_found`: Patient cannot be found
- `patient_already_exists`: Duplicate patient
- `invalid_patient_data`: Invalid patient data
- `patient_deletion_failed`: Failed to delete patient

### Provider Errors
- `provider_not_found`: Provider cannot be found
- `provider_already_exists`: Duplicate provider
- `provider_unavailable`: Provider not available
- `invalid_provider_data`: Invalid provider data

### Clinic Errors
- `clinic_not_found`: Clinic cannot be found
- `clinic_already_exists`: Duplicate clinic
- `clinic_license_suspended`: Clinic license suspended
- `clinic_license_expired`: Clinic license expired
- `invalid_clinic_data`: Invalid clinic data

### Call Errors
- `call_not_found`: Call cannot be found
- `call_already_exists`: Duplicate call
- `invalid_call_status`: Invalid call status
- `call_routing_failed`: Failed to route call

### Authentication Errors
- `authentication_failed`: Authentication failed
- `authorization_denied`: Authorization denied
- `invalid_token`: Invalid token
- `token_expired`: Token expired
- `insufficient_permissions`: Insufficient permissions

### System Errors
- `database_error`: Database operation failed
- `connection_error`: Connection failed
- `validation_error`: Validation failed
- `concurrency_error`: Concurrency conflict
- `rate_limit_exceeded`: Rate limit exceeded

### External Service Errors
- `google_calendar_error`: Google Calendar integration failed
- `azure_communication_error`: Azure Communication failed
- `external_service_unavailable`: External service unavailable

### Business Logic Errors
- `business_rule_violation`: Business rule violated
- `operation_not_allowed`: Operation not allowed
- `resource_limit_exceeded`: Resource limit exceeded
- `maintenance_mode`: System in maintenance mode

## HTTP Status Code Mapping

| Exception Type | HTTP Status | Description |
|----------------|-------------|-------------|
| `SlotUnavailableError` | 409 | Conflict - resource not available |
| `AppointmentNotFoundError` | 404 | Not Found - resource doesn't exist |
| `PatientNotFoundError` | 404 | Not Found - resource doesn't exist |
| `ClinicLicenseSuspendedError` | 403 | Forbidden - access denied |
| `AuthenticationFailedError` | 401 | Unauthorized - authentication failed |
| `ValidationError` | 400 | Bad Request - invalid data |
| `DatabaseError` | 500 | Internal Server Error - system error |
| `RateLimitExceededError` | 429 | Too Many Requests - rate limited |
| `GoogleCalendarError` | 502 | Bad Gateway - external service error |
| `MaintenanceModeError` | 503 | Service Unavailable - maintenance |

## Integration with FastAPI

### Register Exception Handlers

```python
from fastapi import FastAPI
from services.exception_handler import register_exception_handlers

app = FastAPI()

# Register all exception handlers
register_exception_handlers(app)
```

### Use Decorators

```python
from services.exception_handler import handle_route_exceptions, handle_external_service_exceptions

@router.post("/appointments")
@handle_route_exceptions
async def create_appointment(appointment_data: AppointmentCreateRequest):
    # Route logic here
    pass

@router.post("/sync-calendar")
@handle_external_service_exceptions("google_calendar")
async def sync_calendar():
    # External service logic here
    pass
```

### Manual Exception Handling

```python
from services.exceptions import SlotUnavailableError, raise_slot_unavailable

# Using utility functions
def check_slot_availability(slot_id, clinic_id):
    if not is_slot_available(slot_id):
        raise_slot_unavailable(slot_id, clinic_id, "Already booked")

# Using exception classes directly
def check_slot_availability(slot_id, clinic_id):
    if not is_slot_available(slot_id):
        raise SlotUnavailableError(slot_id, clinic_id, "Already booked")
```

## Monitoring and Alerting

### Error Code Monitoring

```python
# Count errors by error code
error_counts = {
    "slot_unavailable": 45,
    "appointment_not_found": 12,
    "validation_error": 8,
    "database_error": 3
}

# Alert on spikes
if error_counts["slot_unavailable"] > 50:
    send_alert("High number of slot unavailable errors - possible double booking bug")
```

### Log Analysis

```python
# Search logs for specific error codes
grep "error_code.*slot_unavailable" /var/log/callcenterai/app.log

# Count errors by hour
grep "error_code.*validation_error" /var/log/callcenterai/app.log | cut -d' ' -f1 | sort | uniq -c
```

### Metrics Collection

```python
# Prometheus metrics
from prometheus_client import Counter

error_counter = Counter('callcenterai_errors_total', 'Total errors', ['error_code', 'endpoint'])

# Increment counter when exception occurs
error_counter.labels(error_code=exc.error_code.value, endpoint=request.url.path).inc()
```

## Best Practices

### 1. Use Specific Exceptions
- Prefer specific exceptions over generic ones
- `SlotUnavailableError` instead of `BusinessRuleViolationError`
- Provides better error handling and monitoring

### 2. Include Context
- Always include relevant context in exceptions
- `slot_id`, `clinic_id`, `user_id` for debugging
- Helps support staff and developers

### 3. User-Friendly Messages
- Write messages for end users, not developers
- Avoid technical jargon
- Provide actionable guidance

### 4. Consistent Error Codes
- Use consistent error code naming
- Follow the established patterns
- Document new error codes

### 5. Proper HTTP Status Codes
- Map exceptions to appropriate HTTP status codes
- Follow REST conventions
- Consider client behavior

### 6. Logging and Monitoring
- Log all exceptions with full context
- Monitor error rates by error code
- Set up alerts for critical errors

### 7. Error Recovery
- Handle transient errors (retry)
- Don't retry permanent errors
- Provide fallback behavior when possible

### 8. Security
- Don't expose sensitive information
- Sanitize error messages
- Log full details for debugging

## Troubleshooting

### Common Issues

#### 1. Generic Error Messages
**Problem**: Users see technical error messages
**Solution**: Use specific exceptions with user-friendly messages

```python
# Bad
raise Exception("Database constraint violation")

# Good
raise SlotUnavailableError("slot123", "clinic456", "Already booked")
```

#### 2. Missing Error Codes
**Problem**: API consumers can't handle errors programmatically
**Solution**: Always include error codes in exceptions

```python
# Bad
raise CallCenterAIException("Slot unavailable", ErrorCode.DATABASE_ERROR)

# Good
raise SlotUnavailableError("slot123", "clinic456")
```

#### 3. Inconsistent Error Format
**Problem**: Different endpoints return different error formats
**Solution**: Use centralized exception handling

```python
# Register exception handlers
register_exception_handlers(app)
```

#### 4. Missing Context
**Problem**: Difficult to debug errors
**Solution**: Include relevant context in exceptions

```python
# Bad
raise AppointmentNotFoundError("appointment123")

# Good
raise AppointmentNotFoundError("appointment123")  # Context is included automatically
```

#### 5. Wrong HTTP Status Codes
**Problem**: API doesn't follow REST conventions
**Solution**: Map exceptions to appropriate HTTP status codes

```python
# Bad
raise SlotUnavailableError("slot123", "clinic456")  # Defaults to 409 Conflict

# Good
raise SlotUnavailableError("slot123", "clinic456")  # Correctly returns 409 Conflict
```

### Debugging Tips

#### 1. Check Exception Logs
```bash
# Search for specific error codes
grep "error_code.*slot_unavailable" /var/log/callcenterai/app.log

# Check error rates
grep "error_code" /var/log/callcenterai/app.log | cut -d'"' -f4 | sort | uniq -c
```

#### 2. Monitor Error Patterns
```python
# Check for error spikes
error_counts = get_error_counts_by_hour()
if error_counts["slot_unavailable"] > threshold:
    investigate_double_booking_issue()
```

#### 3. Test Error Handling
```python
# Test exception handling
def test_slot_unavailable():
    with pytest.raises(SlotUnavailableError):
        appointment_service.create_appointment(invalid_data)
```

#### 4. Validate Error Responses
```python
# Test API error responses
response = client.post("/appointments", json=invalid_data)
assert response.status_code == 409
assert response.json()["error_code"] == "slot_unavailable"
```

## Security Considerations

### 1. Information Disclosure
- Don't expose internal system details
- Sanitize error messages
- Log full details for debugging

### 2. Error Message Sanitization
```python
# Bad - exposes internal details
raise DatabaseError("create_appointment", "Connection to postgresql://user:pass@host:5432/db failed")

# Good - sanitized message
raise DatabaseError("create_appointment", "Database connection failed")
```

### 3. Logging Security
```python
# Log full details for debugging (not sent to user)
logger.error("Database connection failed", extra={
    "technical_details": "postgresql://user:pass@host:5432/db",
    "user_message": "Database connection failed"
})
```

### 4. Rate Limiting
```python
# Prevent error message enumeration attacks
if error_count > rate_limit:
    raise RateLimitExceededError(100, "minute", 60)
```

## Performance Considerations

### 1. Exception Overhead
- Exceptions have performance overhead
- Use for error conditions, not control flow
- Consider alternative approaches for expected conditions

### 2. Logging Performance
- Structured logging is efficient
- Use appropriate log levels
- Consider async logging for high-volume applications

### 3. Error Response Size
- Keep error responses concise
- Include only necessary information
- Consider compression for large responses

## Testing

### 1. Unit Tests
```python
def test_slot_unavailable_error():
    exc = SlotUnavailableError("slot123", "clinic456", "Already booked")
    assert exc.error_code == ErrorCode.SLOT_UNAVAILABLE
    assert exc.http_status == 409
    assert "already booked" in exc.user_message.lower()
```

### 2. Integration Tests
```python
def test_appointment_creation_slot_unavailable():
    response = client.post("/appointments", json={
        "slot_id": "unavailable_slot",
        "clinic_id": "clinic123"
    })
    assert response.status_code == 409
    assert response.json()["error_code"] == "slot_unavailable"
```

### 3. Error Handling Tests
```python
def test_exception_handler():
    app = FastAPI()
    register_exception_handlers(app)
    
    @app.get("/test")
    def test_endpoint():
        raise SlotUnavailableError("slot123", "clinic456")
    
    client = TestClient(app)
    response = client.get("/test")
    assert response.status_code == 409
```

## Conclusion

The Custom Exception Hierarchy system provides a robust, user-friendly, and maintainable approach to error handling in the CallCenterAI application. By following the patterns and best practices outlined in this guide, you can ensure consistent error handling across the entire application, improve user experience, and enable effective monitoring and debugging.

The system transforms generic database and system errors into meaningful, actionable messages that help both users and developers understand and resolve issues quickly. This leads to better user experience, reduced support burden, and more reliable application behavior.
