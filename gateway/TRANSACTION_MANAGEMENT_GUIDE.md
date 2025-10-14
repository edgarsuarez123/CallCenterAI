# Transaction Management and Concurrency Control Guide

This document provides a comprehensive guide to the transaction management and concurrency control system implemented in the CallCenterAI application. This system ensures data integrity, prevents race conditions, and maintains consistency under high concurrency scenarios.

## Table of Contents

1. [Why Transaction Management is Critical](#why-transaction-management-is-critical)
2. [System Architecture](#system-architecture)
3. [Core Components](#core-components)
4. [Usage Examples](#usage-examples)
5. [Concurrency Control Patterns](#concurrency-control-patterns)
6. [Error Handling and Recovery](#error-handling-and-recovery)
7. [Performance Considerations](#performance-considerations)
8. [Best Practices](#best-practices)
9. [Troubleshooting](#troubleshooting)
10. [Testing](#testing)

## Why Transaction Management is Critical

### 1. Atomic Operations (All or Nothing)
- **Appointment Booking**: Creating an appointment requires multiple steps:
  - Create appointment record
  - Mark appointment slot as booked
  - Update usage counters
  - Log audit trail
- **Problem Without Transactions**: If any step fails, the database is left in an inconsistent state
- **Solution**: All steps succeed or all rollback - database always remains consistent

### 2. Race Condition Prevention
- **Double Booking Scenario**: Two users click "Book" on the same appointment slot simultaneously
- **Problem Without Locking**: Both users see the slot as available and both get it
- **Solution**: Row-level locking with `FOR UPDATE` ensures only one user can book the slot

### 3. Deadlock Recovery
- **Deadlock Scenario**: 
  - Transaction A locks slot X, wants slot Y
  - Transaction B locks slot Y, wants slot X
- **Problem**: Both transactions wait forever for each other
- **Solution**: Database detects deadlock, kills one transaction, automatic retry succeeds

### 4. Isolation Levels for Correctness
- **READ COMMITTED**: See only committed changes (default)
- **REPEATABLE READ**: Same query returns same results during transaction
- **SERIALIZABLE**: Transactions appear to run one-at-a-time
- **Trade-off**: Higher isolation = fewer concurrency bugs, slower performance

### 5. Automatic Rollback on Errors
- **Exception Handling**: Any exception triggers automatic rollback
- **No Cleanup Code**: No need to manually undo changes
- **Consistent State**: Database never left in partial state

### 6. Prevents Lost Updates
- **Scenario**: Two users read slot (available), both update it (booked)
- **Problem**: Second update overwrites first update
- **Solution**: Locking ensures second user sees conflict and fails appropriately

### 7. Timeout Protection
- **Lock Timeout**: Prevents indefinite waiting for locks
- **User Experience**: "Slot busy, try again" instead of hanging
- **System Responsiveness**: Prevents cascading lockups

### 8. Usage Counter Accuracy
- **Billing Critical**: Accurate call/appointment counts for billing
- **Concurrency Issue**: Multiple concurrent increments can cause lost counts
- **Solution**: Locking ensures accurate counting

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Application Layer                        │
├─────────────────────────────────────────────────────────────┤
│  AppointmentService  │  CallFlowService  │  Other Services  │
├─────────────────────────────────────────────────────────────┤
│              TransactionManager (Core)                      │
│  ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐│
│  │ Atomic Ops      │ │ Row Locking     │ │ Retry Logic     ││
│  │ Context Manager │ │ FOR UPDATE      │ │ Deadlock Recovery││
│  └─────────────────┘ └─────────────────┘ └─────────────────┘│
├─────────────────────────────────────────────────────────────┤
│                    Database Layer                           │
│  ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐│
│  │ PostgreSQL      │ │ Row Locks       │ │ Deadlock Detect ││
│  │ ACID Properties │ │ Isolation Levels│ │ Timeout Control ││
│  └─────────────────┘ └─────────────────┘ └─────────────────┘│
└─────────────────────────────────────────────────────────────┘
```

## Core Components

### 1. TransactionManager Class

The central component that provides:

```python
from services.transaction_manager import TransactionManager, get_transaction_manager

# Get transaction manager instance
transaction_manager = get_transaction_manager(db_session)

# Atomic transaction context manager
with transaction_manager.atomic_transaction():
    # All operations here are atomic
    # Automatic rollback on any exception
    pass

# Row-level locking
locked_record = transaction_manager.lock_row(ModelClass, record_id)

# Retry mechanism for deadlocks
result = transaction_manager.with_retry(operation_function)
```

### 2. Isolation Levels

```python
from services.transaction_manager import IsolationLevel

# Different isolation levels for different use cases
with transaction_manager.atomic_transaction(IsolationLevel.READ_COMMITTED):
    # Default - see only committed changes
    pass

with transaction_manager.atomic_transaction(IsolationLevel.REPEATABLE_READ):
    # Same query returns same results during transaction
    pass

with transaction_manager.atomic_transaction(IsolationLevel.SERIALIZABLE):
    # Highest isolation - transactions appear sequential
    pass
```

### 3. Lock Modes

```python
from services.transaction_manager import LockMode

# Different lock modes for different scenarios
locked_record = transaction_manager.lock_row(ModelClass, record_id, LockMode.UPDATE)
locked_record = transaction_manager.lock_row(ModelClass, record_id, LockMode.SHARE)
```

### 4. Error Types

```python
from services.transaction_manager import (
    TransactionError,      # Base transaction error
    DeadlockError,        # Deadlock detected
    LockTimeoutError,     # Lock timeout occurred
    ConcurrencyError      # Concurrency conflict
)
```

## Usage Examples

### 1. Atomic Appointment Booking

```python
def book_appointment(appointment_data, slot_id, patient_id, provider_id, clinic_id):
    """Book an appointment with full transaction management."""
    transaction_manager = get_transaction_manager(db_session)
    
    try:
        result = transaction_manager.atomic_appointment_booking(
            appointment_data=appointment_data,
            slot_id=slot_id,
            patient_id=patient_id,
            provider_id=provider_id,
            clinic_id=clinic_id
        )
        return result['appointment']
    except ConcurrencyError:
        raise ValueError("Appointment slot is no longer available")
    except TransactionError as e:
        raise ValueError(f"Booking failed: {e}")
```

### 2. Usage Counter Management

```python
def increment_usage_counters(clinic_id, counter_type, amount=1):
    """Safely increment usage counters with proper locking."""
    transaction_manager = get_transaction_manager(db_session)
    
    with transaction_manager.atomic_transaction():
        transaction_manager._increment_usage_counters(
            clinic_id, counter_type, amount
        )
```

### 3. Custom Atomic Operations

```python
def custom_atomic_operation():
    """Custom atomic operation with transaction management."""
    transaction_manager = get_transaction_manager(db_session)
    
    def _perform_operation():
        with transaction_manager.atomic_transaction():
            # Step 1: Lock required records
            record1 = transaction_manager.lock_row(Model1, id1)
            record2 = transaction_manager.lock_row(Model2, id2)
            
            # Step 2: Perform operations
            record1.field = "new_value"
            record2.field = "another_value"
            
            # Step 3: All changes committed automatically
            return {"success": True}
    
    return transaction_manager.with_retry(_perform_operation)
```

### 4. Decorator Usage

```python
from services.transaction_manager import atomic_operation

@atomic_operation(IsolationLevel.REPEATABLE_READ)
def create_patient_with_appointment(patient_data, appointment_data):
    """Automatically wrapped in atomic transaction."""
    # All operations here are atomic
    patient = create_patient(patient_data)
    appointment = create_appointment(appointment_data)
    return patient, appointment
```

## Concurrency Control Patterns

### 1. Optimistic Locking

```python
class OptimisticModel:
    version = Column(Integer, default=1)
    
    def optimistic_update(self, db_session, **updates):
        """Update with version checking."""
        try:
            for key, value in updates.items():
                setattr(self, key, value)
            db_session.commit()
            return True
        except StaleDataError:
            db_session.rollback()
            raise ConcurrencyError("Record was modified by another transaction")
```

### 2. Pessimistic Locking (Row-Level)

```python
def update_with_pessimistic_lock(record_id, updates):
    """Update with pessimistic locking."""
    transaction_manager = get_transaction_manager(db_session)
    
    with transaction_manager.atomic_transaction():
        # Lock the record for update
        record = transaction_manager.lock_row(ModelClass, record_id)
        
        # Apply updates
        for key, value in updates.items():
            setattr(record, key, value)
        
        # Commit automatically
```

### 3. Lock Ordering (Deadlock Prevention)

```python
def prevent_deadlocks():
    """Always acquire locks in the same order."""
    transaction_manager = get_transaction_manager(db_session)
    
    with transaction_manager.atomic_transaction():
        # Always lock in alphabetical order of table names
        clinic = transaction_manager.lock_row(Clinic, clinic_id)
        provider = transaction_manager.lock_row(Provider, provider_id)
        slot = transaction_manager.lock_row(AppointmentSlot, slot_id)
        
        # Perform operations
        # ...
```

## Error Handling and Recovery

### 1. Automatic Retry for Deadlocks

```python
def robust_operation():
    """Operation with automatic deadlock recovery."""
    transaction_manager = get_transaction_manager(db_session)
    
    def _operation():
        with transaction_manager.atomic_transaction():
            # Operations that might cause deadlock
            pass
    
    # Automatic retry with exponential backoff
    return transaction_manager.with_retry(_operation)
```

### 2. Custom Error Handling

```python
def handle_transaction_errors():
    """Custom error handling for different transaction errors."""
    try:
        result = transaction_manager.atomic_appointment_booking(...)
    except ConcurrencyError as e:
        # Handle concurrency conflicts
        logger.warning(f"Concurrency conflict: {e}")
        return {"error": "Slot no longer available", "retry": True}
    except LockTimeoutError as e:
        # Handle lock timeouts
        logger.warning(f"Lock timeout: {e}")
        return {"error": "System busy, please try again", "retry": True}
    except DeadlockError as e:
        # Handle deadlocks (should be rare with retry)
        logger.error(f"Deadlock detected: {e}")
        return {"error": "System error, please try again", "retry": True}
    except TransactionError as e:
        # Handle other transaction errors
        logger.error(f"Transaction error: {e}")
        return {"error": "Operation failed", "retry": False}
```

### 3. Graceful Degradation

```python
def graceful_degradation():
    """Graceful degradation when transactions fail."""
    try:
        # Try with full transaction management
        return transaction_manager.atomic_appointment_booking(...)
    except TransactionError:
        # Fallback to simpler operation
        logger.warning("Falling back to simpler booking process")
        return simple_appointment_booking(...)
```

## Performance Considerations

### 1. Lock Duration

```python
# Minimize lock duration
def efficient_operation():
    with transaction_manager.atomic_transaction():
        # 1. Lock only what you need
        record = transaction_manager.lock_row(Model, id)
        
        # 2. Do minimal work while holding lock
        record.field = "new_value"
        
        # 3. Release lock quickly (automatic on commit)
        # Don't do heavy processing here
```

### 2. Lock Granularity

```python
# Use appropriate lock granularity
def granular_locking():
    # Row-level locking (preferred for most cases)
    record = transaction_manager.lock_row(Model, id)
    
    # Avoid table-level locking unless necessary
    # transaction_manager.lock_table(Model)  # Usually not needed
```

### 3. Batch Operations

```python
def batch_operations():
    """Batch multiple operations in single transaction."""
    transaction_manager = get_transaction_manager(db_session)
    
    with transaction_manager.atomic_transaction():
        # Batch multiple operations
        for item in items:
            process_item(item)
        # Single commit for all operations
```

### 4. Connection Pooling

```python
# Ensure proper connection pooling for high concurrency
# Configured in services/database.py
POOL_SIZE = 20
MAX_OVERFLOW = 30
POOL_TIMEOUT = 30
```

## Best Practices

### 1. Transaction Scope

```python
# Keep transactions short
def good_transaction_scope():
    with transaction_manager.atomic_transaction():
        # Only database operations
        record = transaction_manager.lock_row(Model, id)
        record.field = "value"
        # Commit quickly

# Avoid long-running operations in transactions
def bad_transaction_scope():
    with transaction_manager.atomic_transaction():
        record = transaction_manager.lock_row(Model, id)
        time.sleep(10)  # BAD: Long operation while holding lock
        record.field = "value"
```

### 2. Error Handling

```python
# Always handle transaction errors appropriately
def proper_error_handling():
    try:
        result = transaction_manager.atomic_appointment_booking(...)
        return result
    except ConcurrencyError:
        # User-friendly message for concurrency conflicts
        raise ValueError("Appointment slot is no longer available")
    except TransactionError as e:
        # Log technical details, return user-friendly message
        logger.error(f"Transaction failed: {e}")
        raise ValueError("Booking failed, please try again")
```

### 3. Lock Ordering

```python
# Always acquire locks in consistent order to prevent deadlocks
def consistent_lock_ordering():
    # Sort IDs to ensure consistent ordering
    ids = sorted([clinic_id, provider_id, slot_id])
    
    with transaction_manager.atomic_transaction():
        # Lock in sorted order
        for id in ids:
            if id == clinic_id:
                clinic = transaction_manager.lock_row(Clinic, id)
            elif id == provider_id:
                provider = transaction_manager.lock_row(Provider, id)
            elif id == slot_id:
                slot = transaction_manager.lock_row(AppointmentSlot, id)
```

### 4. Monitoring and Logging

```python
# Monitor transaction performance
def monitored_operation():
    start_time = time.time()
    
    try:
        result = transaction_manager.atomic_appointment_booking(...)
        
        duration = time.time() - start_time
        logger.info(f"Appointment booking completed in {duration:.2f}s")
        
        return result
    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"Appointment booking failed after {duration:.2f}s: {e}")
        raise
```

## Troubleshooting

### 1. Common Issues

#### Lock Timeout Errors
```python
# Symptoms: LockTimeoutError exceptions
# Causes: High concurrency, long-running transactions
# Solutions:
# 1. Increase lock timeout
transaction_manager = TransactionManager(db_session, lock_timeout_seconds=60)

# 2. Optimize transaction duration
# 3. Reduce lock granularity
# 4. Implement retry logic
```

#### Deadlock Errors
```python
# Symptoms: DeadlockError exceptions
# Causes: Inconsistent lock ordering
# Solutions:
# 1. Implement consistent lock ordering
# 2. Use retry mechanism (automatic)
# 3. Reduce transaction scope
```

#### Concurrency Errors
```python
# Symptoms: ConcurrencyError exceptions
# Causes: Race conditions, optimistic locking conflicts
# Solutions:
# 1. Use pessimistic locking
# 2. Implement retry logic
# 3. Provide user feedback
```

### 2. Performance Issues

#### Slow Transactions
```python
# Monitor transaction duration
def monitor_transaction_performance():
    start_time = time.time()
    
    with transaction_manager.atomic_transaction():
        # Operations
        pass
    
    duration = time.time() - start_time
    if duration > 5.0:  # 5 second threshold
        logger.warning(f"Slow transaction: {duration:.2f}s")
```

#### High Lock Contention
```python
# Monitor lock contention
def monitor_lock_contention():
    # Check database lock statistics
    result = db_session.execute(text("""
        SELECT * FROM pg_locks 
        WHERE NOT granted 
        ORDER BY waitstart
    """)).fetchall()
    
    if len(result) > 10:  # High contention threshold
        logger.warning(f"High lock contention: {len(result)} waiting locks")
```

### 3. Debugging Tools

```python
# Get transaction status
def debug_transaction_status():
    status = transaction_manager.get_transaction_status()
    logger.info(f"Transaction status: {status}")

# Check deadlock risk
def check_deadlock_risk():
    operations = [
        {'locks': [{'table': 'appointments', 'mode': 'update'}]},
        {'locks': [{'table': 'slots', 'mode': 'update'}]}
    ]
    
    risk = transaction_manager.check_deadlock_risk(operations)
    if risk:
        logger.warning("Potential deadlock risk detected")
```

## Testing

### 1. Unit Tests

```python
def test_atomic_transaction():
    """Test atomic transaction behavior."""
    transaction_manager = get_transaction_manager(db_session)
    
    # Test successful transaction
    with transaction_manager.atomic_transaction():
        call = Call(call_sid="TEST_001", call_id="CALL_001", status="initiated")
        db_session.add(call)
    
    # Verify record was committed
    result = db_session.query(Call).filter_by(call_sid="TEST_001").first()
    assert result is not None

def test_rollback_on_error():
    """Test automatic rollback on error."""
    transaction_manager = get_transaction_manager(db_session)
    
    with pytest.raises(TransactionError):
        with transaction_manager.atomic_transaction():
            call = Call(call_sid="TEST_002", call_id="CALL_002", status="initiated")
            db_session.add(call)
            raise ValueError("Test error")
    
    # Verify record was not committed
    result = db_session.query(Call).filter_by(call_sid="TEST_002").first()
    assert result is None
```

### 2. Concurrency Tests

```python
def test_concurrent_booking():
    """Test concurrent appointment booking."""
    results = []
    errors = []
    
    def book_appointment():
        try:
            result = transaction_manager.atomic_appointment_booking(...)
            results.append(result)
        except Exception as e:
            errors.append(e)
    
    # Start multiple concurrent booking attempts
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(book_appointment) for _ in range(5)]
        for future in as_completed(futures):
            future.result()
    
    # Only one booking should succeed
    successful_bookings = [r for r in results if r.get('success')]
    assert len(successful_bookings) == 1
```

### 3. Stress Tests

```python
def test_high_concurrency():
    """Test system under high concurrency."""
    # Create multiple appointment slots
    slots = create_multiple_slots(100)
    
    # Start high concurrency booking
    with ThreadPoolExecutor(max_workers=50) as executor:
        futures = [executor.submit(book_random_slot) for _ in range(200)]
        for future in as_completed(futures):
            future.result()
    
    # Verify all slots were booked exactly once
    booked_slots = db_session.query(AppointmentSlot).filter_by(is_booked="yes").count()
    assert booked_slots == 100
```

## Conclusion

The transaction management and concurrency control system provides:

1. **Data Integrity**: Atomic operations ensure database consistency
2. **Race Condition Prevention**: Row-level locking prevents double booking
3. **Deadlock Recovery**: Automatic detection and retry mechanisms
4. **Error Handling**: Comprehensive error types and recovery strategies
5. **Performance**: Optimized for high concurrency scenarios
6. **Reliability**: Robust error handling and monitoring

This system is critical for maintaining data integrity in a healthcare application where appointment booking accuracy and billing precision are essential for patient care and business operations.

For more information, see:
- [Database Constraints Guide](DATABASE_CONSTRAINTS_GUIDE.md)
- [Soft Delete Guide](SOFT_DELETE_GUIDE.md)
- [Connection Pooling Guide](CONNECTION_POOLING_GUIDE.md)
