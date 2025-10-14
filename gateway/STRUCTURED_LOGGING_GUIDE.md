# Structured Logging Guide - PHI-Safe and HIPAA Compliant

This document provides a comprehensive guide to the structured logging system implemented in the CallCenterAI application. This system ensures HIPAA compliance, provides comprehensive monitoring capabilities, and enables effective debugging and analysis.

## Table of Contents

1. [Why Structured Logging is Critical](#why-structured-logging-is-critical)
2. [System Architecture](#system-architecture)
3. [PHI Safety and HIPAA Compliance](#phi-safety-and-hipaa-compliance)
4. [Core Components](#core-components)
5. [Usage Examples](#usage-examples)
6. [Request Correlation](#request-correlation)
7. [Performance Monitoring](#performance-monitoring)
8. [Security Monitoring](#security-monitoring)
9. [Error Aggregation and Alerting](#error-aggregation-and-alerting)
10. [Audit Trail and Compliance](#audit-trail-and-compliance)
11. [Integration with Monitoring Systems](#integration-with-monitoring-systems)
12. [Best Practices](#best-practices)
13. [Troubleshooting](#troubleshooting)
14. [Testing](#testing)

## Why Structured Logging is Critical

### 1. HIPAA Compliance for Logs
- **Automatic PHI Detection**: Prevents accidental logging of patient names, phone numbers, SSNs
- **Automatic Masking**: PHI is automatically masked as `[PHONE_MASKED]`, `[EMAIL_MASKED]`, etc.
- **Safe Log Sharing**: Logs can be safely shared with developers without HIPAA violations
- **Compliance Auditing**: Complete audit trail of all PHI access and modifications

### 2. Debugging Production Issues
- **Correlation IDs**: Track requests across multiple services
- **Structured Data**: JSON logs can be parsed by machines for analysis
- **Request Tracing**: Follow a single request through the entire system
- **Error Context**: Rich context for every error, including stack traces

### 3. Performance Monitoring
- **Slow Query Detection**: Automatic detection of database queries > 1 second
- **Request Timing**: Track API response times and identify bottlenecks
- **Resource Usage**: Monitor memory usage and connection pool health
- **Performance Trends**: Analyze performance patterns over time

### 4. Security Monitoring
- **Failed Authentication Tracking**: Detect brute force attacks
- **Suspicious Activity**: Alert on unusual access patterns
- **Security Events**: Log all security-relevant events
- **Audit Trail**: Complete trail of who accessed what and when

### 5. Error Aggregation and Alerting
- **Error Grouping**: Group similar errors together for analysis
- **Error Spikes**: Detect when errors spike above normal levels
- **Alerting**: Automatic alerts for critical issues
- **Error Analysis**: Understand error patterns and root causes

### 6. Compliance Auditing
- **PHI Access Logging**: Track all access to patient data
- **Data Modifications**: Log all changes to patient records
- **User Activity**: Track user actions for compliance reporting
- **Automated Reports**: Generate compliance reports from log data

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Application Layer                        │
├─────────────────────────────────────────────────────────────┤
│  FastAPI Routes  │  Business Services  │  Database Layer   │
├─────────────────────────────────────────────────────────────┤
│              Structured Logging Service                     │
│  ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐│
│  │ PHI Detection   │ │ Request Context │ │ Performance     ││
│  │ & Masking       │ │ & Correlation   │ │ Monitoring      ││
│  └─────────────────┘ └─────────────────┘ └─────────────────┘│
│  ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐│
│  │ Security        │ │ Error           │ │ Audit Trail     ││
│  │ Monitoring      │ │ Aggregation     │ │ Generation      ││
│  └─────────────────┘ └─────────────────┘ └─────────────────┘│
├─────────────────────────────────────────────────────────────┤
│                    Output Layer                             │
│  ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐│
│  │ JSON Logs       │ │ Monitoring      │ │ Compliance      ││
│  │ (Console/File)  │ │ Systems         │ │ Reports         ││
│  │                 │ │ (Splunk, etc.)  │ │                 ││
│  └─────────────────┘ └─────────────────┘ └─────────────────┘│
└─────────────────────────────────────────────────────────────┘
```

## PHI Safety and HIPAA Compliance

### Automatic PHI Detection

The system automatically detects and masks the following types of PHI:

#### Phone Numbers
```python
# Detected patterns:
"+1-555-123-4567" → "[PHONE_MASKED]"
"(555) 123-4567" → "[PHONE_MASKED]"
"555.123.4567" → "[PHONE_MASKED]"
"5551234567" → "[PHONE_MASKED]"
```

#### Email Addresses
```python
"john.doe@example.com" → "[EMAIL_MASKED]"
"patient@clinic.org" → "[EMAIL_MASKED]"
```

#### Social Security Numbers
```python
"123-45-6789" → "[SSN_MASKED]"
"123 45 6789" → "[SSN_MASKED]"
"123456789" → "[SSN_MASKED]"
```

#### Dates of Birth
```python
"01/15/1985" → "[DOB_MASKED]"
"1985-01-15" → "[DOB_MASKED]"
"01-15-1985" → "[DOB_MASKED]"
```

#### Names
```python
"John Smith" → "[NAME_MASKED]"
"Dr. Jane Doe" → "Dr. [NAME_MASKED]"
"Smith, John" → "[NAME_MASKED]"
```

#### Medical Record Numbers
```python
"MRN: 12345" → "MRN: [MRN_MASKED]"
"Medical Record: 67890" → "Medical Record: [MRN_MASKED]"
"Patient ID: 54321" → "Patient ID: [MRN_MASKED]"
```

### Complex PHI Masking

The system handles complex text with multiple PHI elements:

```python
original = """
Patient John Smith (DOB: 01/15/1985) called from +1-555-123-4567.
Email: john.smith@example.com
SSN: 123-45-6789
MRN: 12345
"""

masked = """
Patient [NAME_MASKED] (DOB: [DOB_MASKED]) called from [PHONE_MASKED].
Email: [EMAIL_MASKED]
SSN: [SSN_MASKED]
MRN: [MRN_MASKED]
"""
```

## Core Components

### 1. StructuredLogger Class

The main logging service that provides:

```python
from services.structured_logging import get_logger, LogCategory

# Get logger instance
logger = get_logger("appointment_service")

# Log with different levels and categories
logger.info("Appointment created", LogCategory.APPOINTMENT, extra_data={
    'appointment_id': 'apt-123',
    'patient_id': 'pat-456',
    'provider_id': 'prov-789'
})

logger.error("Database connection failed", LogCategory.DATABASE, exception=e)
```

### 2. Log Categories

Organized logging categories for different system components:

```python
from services.structured_logging import LogCategory

# System categories
LogCategory.SYSTEM          # General system events
LogCategory.DATABASE        # Database operations
LogCategory.API            # API requests/responses
LogCategory.AUTHENTICATION # Authentication events
LogCategory.AUTHORIZATION  # Authorization events

# Business categories
LogCategory.APPOINTMENT    # Appointment operations
LogCategory.PATIENT        # Patient operations
LogCategory.PROVIDER       # Provider operations
LogCategory.CLINIC         # Clinic operations
LogCategory.CALL           # Call operations

# Security categories
LogCategory.SECURITY       # Security events
LogCategory.AUDIT          # Audit events
LogCategory.COMPLIANCE     # Compliance events

# Performance categories
LogCategory.PERFORMANCE    # Performance metrics
LogCategory.SLOW_QUERY     # Slow database queries
LogCategory.TIMEOUT        # Timeout events

# Error categories
LogCategory.ERROR          # General errors
LogCategory.EXCEPTION      # Exceptions
LogCategory.VALIDATION     # Validation errors
```

### 3. Request Context Manager

Track requests across services with correlation IDs:

```python
from services.structured_logging import RequestContextManager

# Create request context
with RequestContextManager(correlation_id="req-123", user_id="user-456", clinic_id="clinic-789"):
    # All logs within this context will include correlation information
    logger.info("Processing request")
    # ... business logic ...
```

### 4. Performance Monitoring

Monitor and log performance metrics:

```python
from services.structured_logging import log_performance, PerformanceMonitor

# Decorator for function performance
@log_performance("appointment_creation")
def create_appointment(appointment_data):
    # Function implementation
    pass

# Context manager for operation timing
monitor = PerformanceMonitor()
with monitor.time_operation("database_query"):
    # Database operation
    pass
```

## Usage Examples

### 1. Basic Logging

```python
from services.structured_logging import get_logger, LogCategory

logger = get_logger("my_service")

# Simple logging
logger.info("Service started", LogCategory.SYSTEM)
logger.warning("High memory usage detected", LogCategory.PERFORMANCE)
logger.error("Failed to connect to database", LogCategory.DATABASE, exception=e)

# Logging with extra data
logger.info("User logged in", LogCategory.AUTHENTICATION, extra_data={
    'user_id': 'user-123',
    'login_method': 'password',
    'ip_address': '192.168.1.100'
})
```

### 2. API Request Logging

```python
# Automatic API request logging (handled by middleware)
# Logs include:
# - Request method and path
# - Response status code
# - Request duration
# - Client IP address
# - Correlation ID

# Manual API logging
logger.log_api_request(
    method="POST",
    path="/api/appointments",
    status_code=201,
    duration_ms=250.5,
    client_ip="192.168.1.100"
)
```

### 3. Database Query Logging

```python
# Automatic database query logging (handled by SQLAlchemy events)
# Logs include:
# - Query text (with PHI masked)
# - Execution time
# - Rows affected
# - Slow query detection (> 1 second)

# Manual database logging
logger.log_database_query(
    query="SELECT * FROM patients WHERE clinic_id = ?",
    duration_ms=150.5,
    rows_affected=10
)
```

### 4. Security Event Logging

```python
# Log security events
logger.log_security_event(
    "failed_authentication",
    {
        'user_id': 'user-123',
        'ip_address': '192.168.1.100',
        'attempt_count': 3,
        'reason': 'invalid_password'
    }
)

# Log audit events
logger.log_audit_event(
    "PHI_ACCESS_READ",
    "patient:12345",
    {
        'user_id': 'doctor-1',
        'action': 'read',
        'compliance_required': True
    }
)
```

### 5. Business Event Logging

```python
# Log business events
logger.log_business_event(
    "appointment_created",
    LogCategory.APPOINTMENT,
    {
        'appointment_id': 'apt-123',
        'patient_id': 'pat-456',
        'provider_id': 'prov-789',
        'appointment_date': '2025-01-15T14:00:00Z',
        'duration_minutes': 30
    }
)
```

## Request Correlation

### Correlation ID Flow

1. **Request Initiation**: Client sends request with `X-Correlation-ID` header
2. **Context Creation**: Middleware creates request context with correlation ID
3. **Service Calls**: All service calls inherit the correlation ID
4. **Log Correlation**: All logs include the correlation ID
5. **Response**: Response includes correlation ID in headers

### Example Correlation Flow

```python
# Client request
curl -H "X-Correlation-ID: req-123" -H "X-User-ID: user-456" \
     POST /api/appointments

# Middleware creates context
with RequestContextManager(correlation_id="req-123", user_id="user-456"):
    # All logs include correlation information
    logger.info("Processing appointment request")  # Includes correlation_id
    
    # Service calls inherit context
    appointment_service.create_appointment(data)  # Logs include correlation_id
    
    # Database queries include correlation
    db.query(Appointment).filter_by(...)  # Logs include correlation_id
```

### Log Entry with Correlation

```json
{
  "timestamp": "2025-01-15T14:00:00.123Z",
  "level": "INFO",
  "category": "appointment",
  "message": "Appointment created successfully",
  "service": "appointment_service",
  "request_context": {
    "correlation_id": "req-123",
    "user_id": "user-456",
    "clinic_id": "clinic-789",
    "request_id": "req-456",
    "request_duration_ms": 250
  },
  "data": {
    "appointment_id": "apt-123",
    "patient_id": "pat-456",
    "provider_id": "prov-789"
  }
}
```

## Performance Monitoring

### Automatic Performance Tracking

The system automatically tracks:

- **API Request Duration**: Time from request start to response
- **Database Query Duration**: Time for each database query
- **Function Execution Time**: Time for decorated functions
- **Memory Usage**: Current memory consumption
- **Connection Pool Status**: Database connection pool health

### Slow Query Detection

```python
# Queries > 1 second are automatically logged as warnings
{
  "timestamp": "2025-01-15T14:00:00.123Z",
  "level": "WARNING",
  "category": "slow_query",
  "message": "Slow database query detected: 1500.5ms",
  "data": {
    "query": "SELECT * FROM large_table WHERE...",
    "duration_ms": 1500.5,
    "rows_affected": 1000
  }
}
```

### Performance Metrics

```python
# Get performance summary
monitor = PerformanceMonitor()
metrics = monitor.get_metrics_summary()

# Example output:
{
  "appointment_creation": {
    "count": 150,
    "avg_ms": 250.5,
    "min_ms": 100.0,
    "max_ms": 500.0,
    "total_ms": 37575.0
  },
  "database_query": {
    "count": 500,
    "avg_ms": 50.0,
    "min_ms": 10.0,
    "max_ms": 200.0,
    "total_ms": 25000.0
  }
}
```

## Security Monitoring

### Failed Authentication Tracking

```python
# Automatic tracking of failed authentication attempts
{
  "timestamp": "2025-01-15T14:00:00.123Z",
  "level": "WARNING",
  "category": "security",
  "message": "Suspicious authentication activity detected for user user-123",
  "data": {
    "failed_attempts": 6,
    "user_id": "user-123",
    "ip_address": "192.168.1.100"
  }
}
```

### Security Event Logging

```python
# Log security events
logger.log_security_event(
    "unauthorized_access_attempt",
    {
        'user_id': 'user-123',
        'ip_address': '192.168.1.100',
        'resource': '/api/patients/12345',
        'action': 'read',
        'reason': 'insufficient_permissions'
    }
)
```

### Security Summary

```python
# Get security summary
security_summary = logger.get_security_summary()

# Example output:
{
  "failed_auth_attempts": {
    "user-123": 6,
    "user-456": 2
  },
  "recent_security_events": [
    {
      "event_type": "failed_authentication",
      "timestamp": "2025-01-15T14:00:00.123Z",
      "user_id": "user-123"
    }
  ],
  "total_security_events": 25
}
```

## Error Aggregation and Alerting

### Error Tracking

The system automatically tracks and aggregates errors:

```python
# Errors are automatically grouped by category and message
{
  "total_errors": 47,
  "error_types": {
    "database:Connection timeout": 15,
    "validation:Invalid appointment data": 12,
    "api:Authentication failed": 20
  },
  "error_samples": {
    "database:Connection timeout": [
      {
        "timestamp": "2025-01-15T14:00:00.123Z",
        "message": "Database connection timeout",
        "data": {"timeout_seconds": 30}
      }
    ]
  }
}
```

### Error Alerting

```python
# Automatic alerts for error spikes
{
  "timestamp": "2025-01-15T14:00:00.123Z",
  "level": "WARNING",
  "category": "error",
  "message": "Error spike detected: database:Connection timeout occurred 15 times",
  "data": {
    "error_key": "database:Connection timeout",
    "count": 15,
    "alert_type": "error_spike"
  }
}
```

## Audit Trail and Compliance

### PHI Access Logging

```python
# Log all PHI access
audit_logger = get_audit_logger()
audit_logger.log_phi_access(
    user_id="doctor-1",
    resource_type="patient",
    resource_id="pat-123",
    action="read"
)
```

### Data Modification Logging

```python
# Log data modifications
audit_logger.log_data_modification(
    user_id="doctor-1",
    table_name="patients",
    record_id="pat-123",
    action="update",
    changes={
        "old_values": {"phone_token": "PHONE_OLD123"},
        "new_values": {"phone_token": "PHONE_NEW456"}
    }
)
```

### Compliance Reporting

```python
# Generate compliance reports from audit logs
# Query logs for specific patient access
# Example Splunk query:
# source="callcenter_ai" category="audit" data.action="PHI_ACCESS_READ" data.resource_type="patient" data.resource_id="pat-123"
```

## Integration with Monitoring Systems

### Splunk Integration

```python
# Logs are structured JSON for easy Splunk parsing
# Example Splunk queries:

# Find all PHI access for a specific patient
source="callcenter_ai" category="audit" data.resource_id="pat-123"

# Find slow queries
source="callcenter_ai" category="slow_query" data.duration_ms>1000

# Find authentication failures
source="callcenter_ai" category="security" message="*authentication*failed*"

# Find error spikes
source="callcenter_ai" category="error" message="*spike*"
```

### Datadog Integration

```python
# Logs can be sent to Datadog for monitoring
# Example Datadog queries:

# Monitor API response times
source:callcenter_ai category:api @duration_ms:>1000

# Monitor database performance
source:callcenter_ai category:database @duration_ms:>500

# Monitor security events
source:callcenter_ai category:security
```

### CloudWatch Integration

```python
# Logs can be sent to CloudWatch for AWS monitoring
# Example CloudWatch queries:

# Find high error rates
fields @timestamp, @message
| filter @message like /ERROR/
| stats count() by bin(5m)

# Find slow API requests
fields @timestamp, @message
| filter @message like /duration_ms/
| filter @message like /[0-9]{4,}ms/
| sort @timestamp desc
```

## Best Practices

### 1. Log Level Guidelines

```python
# DEBUG: Detailed information for debugging
logger.debug("Processing appointment data", LogCategory.APPOINTMENT, extra_data={
    'appointment_data': appointment_data.dict()
})

# INFO: General information about system operation
logger.info("Appointment created successfully", LogCategory.APPOINTMENT, extra_data={
    'appointment_id': appointment.appointment_id
})

# WARNING: Something unexpected happened but system continues
logger.warning("High memory usage detected", LogCategory.PERFORMANCE, extra_data={
    'memory_usage_mb': 1024
})

# ERROR: Error occurred but system can continue
logger.error("Database connection failed", LogCategory.DATABASE, exception=e)

# CRITICAL: Serious error that may cause system failure
logger.critical("Database is unreachable", LogCategory.DATABASE, exception=e)
```

### 2. Category Selection

```python
# Use appropriate categories for different types of events
logger.info("User authenticated", LogCategory.AUTHENTICATION)
logger.info("Appointment booked", LogCategory.APPOINTMENT)
logger.info("Database query executed", LogCategory.DATABASE)
logger.info("API request processed", LogCategory.API)
logger.info("Security event detected", LogCategory.SECURITY)
```

### 3. Extra Data Guidelines

```python
# Include relevant context in extra_data
logger.info("Appointment created", LogCategory.APPOINTMENT, extra_data={
    'appointment_id': appointment.appointment_id,
    'patient_id': appointment.patient_id,
    'provider_id': appointment.provider_id,
    'appointment_date': appointment.appointment_date.isoformat(),
    'duration_minutes': appointment.duration_minutes
})

# Avoid logging sensitive data (PHI is automatically masked)
logger.info("Patient data accessed", LogCategory.AUDIT, extra_data={
    'patient_id': patient.patient_id,  # OK - this is a token
    'access_type': 'read',
    'user_id': user.user_id
})
```

### 4. Exception Logging

```python
# Always include exception information for errors
try:
    # Risky operation
    result = risky_operation()
except Exception as e:
    logger.error(
        "Risky operation failed",
        LogCategory.ERROR,
        exception=e,
        extra_data={
            'operation': 'risky_operation',
            'input_data': safe_input_data
        }
    )
    raise
```

### 5. Performance Logging

```python
# Use decorators for function performance
@log_performance("appointment_creation")
def create_appointment(appointment_data):
    # Function implementation
    pass

# Use context managers for operation timing
with monitor.time_operation("database_batch_update"):
    # Database operations
    pass
```

## Troubleshooting

### 1. Common Issues

#### PHI Not Being Masked
```python
# Check if PHI patterns are being detected
logger = StructuredLogger("test")
masked = logger._detect_and_mask_phi("Call patient at +1-555-123-4567")
print(masked)  # Should show [PHONE_MASKED]

# If not working, check pattern definitions in PHIPattern class
```

#### Missing Correlation IDs
```python
# Ensure request context is properly set
with RequestContextManager(correlation_id="test-123"):
    logger.info("Test message")
    # Check if correlation_id appears in logs
```

#### Slow Query Not Detected
```python
# Check if database query logging is enabled
from services.structured_logging import log_database_queries
from services.database import engine

# Enable database query logging
log_database_queries(engine)
```

### 2. Debugging Log Configuration

```python
# Check logger configuration
logger = get_logger("test")
print(f"Logger level: {logger.level}")
print(f"Logger handlers: {logger.logger.handlers}")

# Test logging
logger.debug("Debug message")
logger.info("Info message")
logger.warning("Warning message")
logger.error("Error message")
```

### 3. Performance Issues

```python
# Check if logging is causing performance issues
import time

start_time = time.time()
for i in range(1000):
    logger.info(f"Test message {i}")
end_time = time.time()

print(f"1000 log messages took {end_time - start_time:.2f} seconds")
```

### 4. Memory Usage

```python
# Check memory usage of logging system
import psutil
import os

process = psutil.Process(os.getpid())
memory_before = process.memory_info().rss

# Perform logging operations
for i in range(10000):
    logger.info(f"Test message {i}")

memory_after = process.memory_info().rss
print(f"Memory increase: {(memory_after - memory_before) / 1024 / 1024:.2f} MB")
```

## Testing

### 1. Unit Tests

```python
# Test PHI detection
def test_phone_masking():
    logger = StructuredLogger("test")
    masked = logger._detect_and_mask_phi("Call +1-555-123-4567")
    assert "[PHONE_MASKED]" in masked
    assert "555-123-4567" not in masked

# Test structured logging
def test_log_structure():
    logger = StructuredLogger("test")
    with patch.object(logger.logger, 'info') as mock_info:
        logger.info("Test message", LogCategory.SYSTEM)
        logged_data = json.loads(mock_info.call_args[0][0])
        assert "timestamp" in logged_data
        assert "level" in logged_data
        assert "category" in logged_data
```

### 2. Integration Tests

```python
# Test request correlation
def test_request_correlation():
    correlation_id = "test-123"
    with RequestContextManager(correlation_id):
        logger.info("Test message")
        # Verify correlation ID appears in logs

# Test performance monitoring
def test_performance_monitoring():
    @log_performance("test_operation")
    def test_function():
        time.sleep(0.01)
        return "success"
    
    result = test_function()
    assert result == "success"
    # Verify performance was logged
```

### 3. Load Testing

```python
# Test logging under load
def test_concurrent_logging():
    def log_from_thread(thread_id):
        with RequestContextManager(f"correlation-{thread_id}"):
            logger.info(f"Message from thread {thread_id}")
    
    threads = []
    for i in range(10):
        thread = threading.Thread(target=log_from_thread, args=(i,))
        threads.append(thread)
        thread.start()
    
    for thread in threads:
        thread.join()
    
    # Verify all threads logged successfully
```

## Conclusion

The structured logging system provides:

1. **HIPAA Compliance**: Automatic PHI detection and masking
2. **Comprehensive Monitoring**: Performance, security, and error tracking
3. **Request Correlation**: Track requests across distributed services
4. **Audit Trails**: Complete compliance audit trails
5. **Error Analysis**: Error aggregation and alerting
6. **Integration Ready**: JSON logs for monitoring systems
7. **Performance Insights**: Slow query detection and performance metrics
8. **Security Monitoring**: Failed authentication and security event tracking

This system ensures that the CallCenterAI application maintains the highest standards of logging, monitoring, and compliance while providing developers with the tools they need to debug issues and optimize performance.

For more information, see:
- [Transaction Management Guide](TRANSACTION_MANAGEMENT_GUIDE.md)
- [Soft Delete Guide](SOFT_DELETE_GUIDE.md)
- [Database Constraints Guide](DATABASE_CONSTRAINTS_GUIDE.md)
- [Connection Pooling Guide](CONNECTION_POOLING_GUIDE.md)
