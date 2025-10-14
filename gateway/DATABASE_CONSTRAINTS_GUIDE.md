# Database Constraints and Indexes Guide

This guide explains the comprehensive database constraints and indexes implemented in the CallCenterAI system to ensure data integrity, performance, and business rule enforcement.

## Why Constraints and Indexes Are Critical

### Problems Without Proper Constraints
- **Double Booking**: Two patients could book the same time slot
- **Invalid Data**: Negative durations, impossible dates, invalid statuses
- **Performance Issues**: Slow queries as data grows, timeouts under load
- **Data Corruption**: Orphaned records, inconsistent relationships
- **Business Rule Violations**: Invalid subscription tiers, impossible configurations

### Benefits of Proper Constraints
- **Data Integrity**: Database enforces rules even if application code has bugs
- **Performance**: Indexes make queries 10x-1000x faster
- **Business Protection**: Prevents double booking and invalid configurations
- **Self-Documenting**: Constraints document business rules in the database
- **Error Prevention**: Clear error messages when rules are violated

## Critical Business Constraints

### 1. Double Booking Prevention (MOST CRITICAL)

```sql
-- Prevents two appointments for the same provider at the same time
UNIQUE CONSTRAINT unique_provider_slot_datetime ON appointment_slots (provider_id, slot_datetime)
```

**Business Impact**: 
- Prevents customer service nightmares
- Ensures no "overbooking" situations
- Handles race conditions between simultaneous bookings
- Database-level protection even if application code has bugs

**Error Message**: `duplicate key value violates unique constraint "unique_provider_slot_datetime"`

### 2. Appointment Time Validation

```sql
-- Ensures appointments have logical timing
CHECK CONSTRAINT check_appointments_end_after_start ON appointments (end_time > start_time)
CHECK CONSTRAINT check_appointments_positive_duration ON appointments (duration_minutes > 0)
```

**Business Impact**:
- Prevents nonsensical appointments (end before start)
- Ensures all appointments have positive duration
- Protects against data entry errors

### 3. Appointment Slot Status Validation

```sql
-- Ensures slot status is valid
CHECK CONSTRAINT check_appointment_slots_valid_status ON appointment_slots 
(is_booked IN ('yes', 'no', 'held'))
```

**Business Impact**:
- Prevents invalid slot states
- Ensures booking system works correctly
- Protects against typos in status values

### 4. Call Status Validation

```sql
-- Ensures call status is valid
CHECK CONSTRAINT check_calls_valid_status ON calls 
(status IN ('initiated', 'active', 'completed', 'failed', 'abandoned'))
```

**Business Impact**:
- Prevents invalid call states
- Ensures call tracking works correctly
- Protects against data corruption

### 5. Clinic Configuration Validation

```sql
-- Ensures clinic settings are reasonable
CHECK CONSTRAINT check_clinics_positive_concurrent_calls ON clinics 
(max_concurrent_calls > 0 AND max_concurrent_calls <= 100)
CHECK CONSTRAINT check_clinics_valid_subscription_tier ON clinics 
(subscription_tier IN ('basic', 'professional', 'enterprise'))
```

**Business Impact**:
- Prevents impossible configurations
- Ensures subscription tiers are valid
- Protects against configuration errors

## Performance Indexes

### 1. Appointment Booking Performance (CRITICAL)

```sql
-- Makes "find available slots" queries instant
INDEX idx_appointment_slots_available_booking ON appointment_slots 
(clinic_id, slot_datetime, is_booked)

-- Makes "show provider availability" queries fast
INDEX idx_appointment_slots_provider_available ON appointment_slots 
(provider_id, slot_datetime, is_booked)
```

**Performance Impact**:
- **Without Index**: Database scans entire table (slow for large datasets)
- **With Index**: Direct lookup (milliseconds vs seconds)
- **Query Example**: "Show me all available slots for Dr. Smith on January 15th"

### 2. Call Processing Performance

```sql
-- Makes "show active calls" queries instant
INDEX idx_calls_clinic_status ON calls (clinic_id, status)

-- Makes patient call history queries fast
INDEX idx_calls_patient_recent ON calls (patient_id, started_at)
```

**Performance Impact**:
- **Without Index**: Scans all calls to find active ones
- **With Index**: Direct lookup of active calls
- **Query Example**: "Show me all active calls for this clinic"

### 3. Multi-Tenant Performance

```sql
-- Makes clinic lookups by phone instant
INDEX idx_clinics_phone_lookup ON clinics (phone_number)

-- Makes active clinic queries fast
INDEX idx_clinics_active_tier ON clinics (is_active, subscription_tier)
```

**Performance Impact**:
- **Without Index**: Scans all clinics to find by phone number
- **With Index**: Direct phone number lookup
- **Query Example**: "Find clinic by phone number +17875551234"

### 4. Billing and Usage Performance

```sql
-- Makes billing queries fast
INDEX idx_usage_billing_period ON clinic_usage (clinic_id, billing_period_start)

-- Makes license monitoring queries fast
INDEX idx_licenses_usage_monitoring ON clinic_licenses 
(current_month_calls, max_calls_per_month)
```

**Performance Impact**:
- **Without Index**: Scans all usage records for billing
- **With Index**: Direct lookup of current month usage
- **Query Example**: "Get current month usage for billing"

## Partial Indexes for Specific Queries

### 1. Active Appointments Only

```sql
-- Index only active appointments (smaller, faster)
INDEX idx_appointments_active_only ON appointments (clinic_id, appointment_date)
WHERE status IN ('scheduled', 'confirmed')
```

**Benefits**:
- Smaller index size (only active appointments)
- Faster queries for active appointments
- Reduced maintenance overhead

### 2. Available Slots Only

```sql
-- Index only available slots
INDEX idx_slots_available_only ON appointment_slots (clinic_id, slot_datetime)
WHERE is_booked = 'no'
```

**Benefits**:
- Faster "find available slots" queries
- Smaller index size
- Optimized for most common booking query

### 3. Emergency Calls Only

```sql
-- Index only emergency calls
INDEX idx_call_queue_emergency_only ON call_queue (priority_level, created_at)
WHERE is_emergency = 'yes'
```

**Benefits**:
- Fast emergency call processing
- Smaller index size
- Optimized for critical emergency handling

## Unique Constraints for Business Rules

### 1. One License Per Clinic

```sql
UNIQUE CONSTRAINT unique_clinic_license ON clinic_licenses (clinic_id)
```

**Business Impact**: Ensures each clinic has exactly one license

### 2. Unique Clinic Phone Numbers

```sql
UNIQUE CONSTRAINT unique_clinic_phone ON clinics (phone_number)
```

**Business Impact**: Prevents two clinics from having the same phone number

### 3. Unique Provider Emails

```sql
UNIQUE CONSTRAINT unique_provider_email ON providers (email)
```

**Business Impact**: Ensures each provider has a unique email for Google Calendar integration

## Foreign Key Relationships

### 1. Clinic Relationships

```sql
-- When clinic is deleted, related data is handled by application layer
-- This ensures data integrity while allowing for business logic
```

**Business Impact**: Prevents orphaned records while allowing proper cleanup

### 2. Provider Relationships

```sql
-- When provider is deleted, appointments and slots are handled by application layer
-- This ensures data integrity while allowing for business logic
```

**Business Impact**: Prevents orphaned appointments while allowing proper cleanup

## Error Handling and Debugging

### 1. Constraint Violation Messages

When constraints are violated, PostgreSQL provides specific error messages:

```sql
-- Double booking attempt
ERROR: duplicate key value violates unique constraint "unique_provider_slot_datetime"

-- Invalid appointment time
ERROR: new row for relation "appointments" violates check constraint "check_appointments_end_after_start"

-- Invalid status value
ERROR: new row for relation "calls" violates check constraint "check_calls_valid_status"
```

### 2. Application Error Handling

The application should catch these specific errors and provide user-friendly messages:

```python
try:
    # Attempt to book appointment
    book_appointment(slot_id, appointment_id)
except IntegrityError as e:
    if "unique_provider_slot_datetime" in str(e):
        return {"error": "Time slot is no longer available"}
    elif "check_appointments_end_after_start" in str(e):
        return {"error": "Invalid appointment time"}
    else:
        return {"error": "Database constraint violation"}
```

## Monitoring and Maintenance

### 1. Index Usage Monitoring

```sql
-- Check which indexes are being used
SELECT schemaname, tablename, indexname, idx_scan, idx_tup_read, idx_tup_fetch
FROM pg_stat_user_indexes
ORDER BY idx_scan DESC;
```

### 2. Constraint Violation Monitoring

```sql
-- Monitor constraint violations in logs
-- Look for ERROR messages containing constraint names
```

### 3. Performance Monitoring

```sql
-- Check slow queries
SELECT query, mean_time, calls, total_time
FROM pg_stat_statements
ORDER BY mean_time DESC
LIMIT 10;
```

## Best Practices

### 1. Constraint Design

- **Start with business rules**: What must never happen?
- **Add performance indexes**: What queries are slow?
- **Test with realistic data**: Ensure constraints work with real data
- **Monitor performance**: Watch for slow queries and unused indexes

### 2. Index Design

- **Composite indexes**: For multi-column queries
- **Partial indexes**: For filtered queries
- **Covering indexes**: Include all needed columns
- **Monitor usage**: Remove unused indexes

### 3. Maintenance

- **Regular monitoring**: Check index usage and performance
- **Constraint testing**: Ensure constraints work as expected
- **Performance testing**: Test with realistic data volumes
- **Documentation**: Keep this guide updated

## Troubleshooting

### 1. Slow Queries

**Problem**: Queries are slow despite indexes
**Solution**: 
- Check if indexes are being used: `EXPLAIN ANALYZE`
- Consider composite indexes for multi-column queries
- Add partial indexes for filtered queries

### 2. Constraint Violations

**Problem**: Unexpected constraint violations
**Solution**:
- Check application logic for edge cases
- Review constraint definitions
- Add proper error handling

### 3. Index Bloat

**Problem**: Indexes are large and slow
**Solution**:
- Rebuild indexes: `REINDEX`
- Consider partial indexes
- Monitor index usage and remove unused ones

## Conclusion

The comprehensive constraint and index system ensures:

1. **Data Integrity**: Business rules are enforced at the database level
2. **Performance**: Queries are fast even with large datasets
3. **Reliability**: System works correctly even with application bugs
4. **Maintainability**: Constraints document business rules
5. **Scalability**: Performance remains good as data grows

This system prevents critical business problems like double booking while ensuring excellent performance for all common queries.
