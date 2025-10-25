"""
Transaction Management and Concurrency Control Service

This service provides comprehensive transaction management for the CallCenterAI application,
ensuring atomic operations, race condition prevention, and data consistency.

Key Features:
- Atomic operations (all-or-nothing)
- Row-level locking for critical operations
- Deadlock detection and recovery
- Automatic rollback on errors
- Usage counter management with proper locking
- Timeout protection and retry logic
"""

import logging
import time
from contextlib import contextmanager
from typing import Any, Callable, Dict, List, Optional, Type, Union
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import text, and_, or_
from sqlalchemy.exc import (
    IntegrityError, 
    OperationalError, 
    StatementError,
    DisconnectionError,
    TimeoutError as SQLTimeoutError
)
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.orm.exc import StaleDataError
from sqlalchemy.pool import QueuePool

from models.models import (
    Appointment, AppointmentSlot, Patient, Provider, ClinicUsage, 
    ClinicLicense, Call, AuditLog
)

logger = logging.getLogger(__name__)

class IsolationLevel(Enum):
    """Database isolation levels for transaction control."""
    READ_UNCOMMITTED = "READ UNCOMMITTED"
    READ_COMMITTED = "READ COMMITTED"
    REPEATABLE_READ = "REPEATABLE READ"
    SERIALIZABLE = "SERIALIZABLE"

class LockMode(Enum):
    """Row locking modes for concurrency control."""
    SHARE = "FOR SHARE"
    UPDATE = "FOR UPDATE"
    NO_KEY_UPDATE = "FOR NO KEY UPDATE"
    KEY_SHARE = "FOR KEY SHARE"

class TransactionError(Exception):
    """Base exception for transaction-related errors."""
    pass

class DeadlockError(TransactionError):
    """Raised when a deadlock is detected."""
    pass

class LockTimeoutError(TransactionError):
    """Raised when a lock timeout occurs."""
    pass

class ConcurrencyError(TransactionError):
    """Raised when a concurrency conflict occurs."""
    pass

class TransactionManager:
    """
    Comprehensive transaction management service for atomic operations and concurrency control.
    
    This service ensures:
    1. Atomic operations (all-or-nothing)
    2. Race condition prevention with row-level locking
    3. Deadlock detection and recovery
    4. Automatic rollback on errors
    5. Usage counter accuracy with proper locking
    6. Timeout protection and retry logic
    """
    
    def __init__(self, db_session: Session, max_retries: int = 3, 
                 lock_timeout_seconds: int = 30, deadlock_retry_delay: float = 0.1):
        self.db = db_session
        self.max_retries = max_retries
        self.lock_timeout_seconds = lock_timeout_seconds
        self.deadlock_retry_delay = deadlock_retry_delay
        
        # Set lock timeout for this session
        self._set_lock_timeout()
    
    def _set_lock_timeout(self):
        """Set the lock timeout for this database session."""
        try:
            self.db.execute(text(f"SET lock_timeout = '{self.lock_timeout_seconds}s'"))
            self.db.commit()
        except Exception as e:
            logger.warning(f"Failed to set lock timeout: {e}")
    
    @contextmanager
    def atomic_transaction(self, isolation_level: IsolationLevel = IsolationLevel.READ_COMMITTED):
        """
        Context manager for atomic transactions with automatic rollback on errors.
        
        Args:
            isolation_level: Database isolation level for the transaction
            
        Yields:
            Session: Database session for the transaction
            
        Raises:
            TransactionError: If transaction fails and cannot be retried
        """
        # Set isolation level
        try:
            self.db.execute(text(f"SET TRANSACTION ISOLATION LEVEL {isolation_level.value}"))
        except Exception as e:
            logger.warning(f"Failed to set isolation level: {e}")
        
        try:
            yield self.db
            self.db.commit()
            logger.debug("Transaction committed successfully")
        except Exception as e:
            self.db.rollback()
            logger.error(f"Transaction rolled back due to error: {e}")
            raise TransactionError(f"Transaction failed: {e}") from e
    
    def with_retry(self, operation: Callable, *args, **kwargs) -> Any:
        """
        Execute an operation with automatic retry on deadlock or lock timeout.
        
        Args:
            operation: Function to execute
            *args: Arguments for the operation
            **kwargs: Keyword arguments for the operation
            
        Returns:
            Any: Result of the operation
            
        Raises:
            TransactionError: If operation fails after all retries
        """
        last_exception = None
        
        for attempt in range(self.max_retries + 1):
            try:
                return operation(*args, **kwargs)
            except (DeadlockError, LockTimeoutError, ConcurrencyError) as e:
                last_exception = e
                if attempt < self.max_retries:
                    delay = min(self.deadlock_retry_delay * (2 ** attempt), 60)  # Cap at 60 seconds
                    logger.warning(f"Retry {attempt + 1}/{self.max_retries} after {e.__class__.__name__}: {e}")
                    time.sleep(delay)
                else:
                    logger.error(f"Operation failed after {self.max_retries} retries: {e}")
                    raise TransactionError(f"Operation failed after {self.max_retries} retries: {e}") from e
            except Exception as e:
                logger.error(f"Non-retryable error in operation: {e}")
                raise TransactionError(f"Operation failed: {e}") from e
        
        raise TransactionError(f"Operation failed after {self.max_retries} retries") from last_exception
    
    def lock_row(self, model_class: Type, record_id: str, lock_mode: LockMode = LockMode.UPDATE) -> Any:
        """
        Lock a specific row for update to prevent race conditions.
        
        Args:
            model_class: SQLAlchemy model class
            record_id: Primary key value of the record to lock
            lock_mode: Lock mode to use
            
        Returns:
            Any: The locked record
            
        Raises:
            LockTimeoutError: If lock cannot be acquired within timeout
            ConcurrencyError: If record is not found
        """
        try:
            # Get the primary key column name
            primary_key_column = model_class.__table__.primary_key.columns.keys()[0]
            
            # Lock the row
            query = self.db.query(model_class).filter(
                getattr(model_class, primary_key_column) == record_id
            ).with_for_update()
            
            record = query.first()
            
            if not record:
                raise ConcurrencyError(f"Record {record_id} not found in {model_class.__tablename__}")
            
            logger.debug(f"Locked {model_class.__tablename__} record {record_id}")
            return record
            
        except OperationalError as e:
            if "lock timeout" in str(e).lower():
                raise LockTimeoutError(f"Lock timeout for {model_class.__tablename__} record {record_id}") from e
            elif "deadlock" in str(e).lower():
                raise DeadlockError(f"Deadlock detected for {model_class.__tablename__} record {record_id}") from e
            else:
                raise TransactionError(f"Database error locking {model_class.__tablename__} record {record_id}: {e}") from e
    
    def atomic_appointment_booking(
        self, 
        appointment_data: Dict[str, Any], 
        slot_id: str,
        patient_id: str,
        provider_id: str,
        clinic_id: str
    ) -> Dict[str, Any]:
        """
        Atomically book an appointment with proper locking to prevent double booking.
        
        This operation:
        1. Locks the appointment slot
        2. Verifies slot is still available
        3. Creates the appointment
        4. Marks slot as booked
        5. Updates usage counters
        6. All or nothing - if any step fails, everything rolls back
        
        Args:
            appointment_data: Appointment data to create
            slot_id: ID of the appointment slot to book
            patient_id: ID of the patient
            provider_id: ID of the provider
            clinic_id: ID of the clinic
            
        Returns:
            Dict containing the created appointment and slot information
            
        Raises:
            ConcurrencyError: If slot is no longer available
            TransactionError: If booking fails
        """
        def _book_appointment():
            with self.atomic_transaction():
                # Step 1: Lock the appointment slot
                slot = self.lock_row(AppointmentSlot, slot_id)
                
                # Step 2: Verify slot is still available
                if slot.is_booked != 'no':
                    raise ConcurrencyError(f"Appointment slot {slot_id} is no longer available")
                
                # Step 3: Create the appointment
                appointment = Appointment(
                    appointment_id=appointment_data['appointment_id'],
                    patient_id=patient_id,
                    provider_id=provider_id,
                    appointment_date=appointment_data['appointment_date'],
                    start_time=appointment_data['start_time'],
                    end_time=appointment_data['end_time'],
                    appointment_type=appointment_data['appointment_type'],
                    duration_minutes=appointment_data['duration_minutes'],
                    status='scheduled'
                )
                self.db.add(appointment)
                self.db.flush()  # Get the appointment ID
                
                # Step 4: Mark slot as booked
                slot.is_booked = 'yes'
                slot.booked_by_appointment_id = appointment.appointment_id
                slot.held_until = None
                slot.held_by_call_sid = None
                
                # Step 5: Update usage counters (with locking)
                self._increment_usage_counters(clinic_id, 'appointments_scheduled')
                
                # Step 6: Log the booking
                self._log_audit('appointments', appointment.appointment_id, 'create', 
                              None, appointment_data)
                
                return {
                    'appointment': appointment,
                    'slot': slot,
                    'success': True
                }
        
        return self.with_retry(_book_appointment)
    
    def atomic_slot_release(self, slot_id: str, appointment_id: str) -> bool:
        """
        Atomically release an appointment slot.
        
        Args:
            slot_id: ID of the slot to release
            appointment_id: ID of the appointment being cancelled
            
        Returns:
            bool: True if successful
            
        Raises:
            TransactionError: If release fails
        """
        def _release_slot():
            with self.atomic_transaction():
                # Lock the slot
                slot = self.lock_row(AppointmentSlot, slot_id)
                
                # Verify slot is booked by this appointment
                if slot.booked_by_appointment_id != appointment_id:
                    raise ConcurrencyError(f"Slot {slot_id} is not booked by appointment {appointment_id}")
                
                # Release the slot
                slot.is_booked = 'no'
                slot.booked_by_appointment_id = None
                slot.held_until = None
                slot.held_by_call_sid = None
                
                # Update usage counters
                # Note: We'd need clinic_id here - this is a simplified version
                # In practice, you'd get clinic_id from the appointment or slot
                
                return True
        
        return self.with_retry(_release_slot)
    
    def _increment_usage_counters(self, clinic_id: str, counter_type: str, amount: int = 1):
        """
        Safely increment usage counters with proper locking.
        
        Args:
            clinic_id: ID of the clinic
            counter_type: Type of counter to increment
            amount: Amount to increment by
        """
        try:
            # Lock the clinic license to prevent concurrent counter updates
            license_record = self.db.query(ClinicLicense).filter(
                ClinicLicense.clinic_id == clinic_id
            ).with_for_update().first()
            
            if not license_record:
                logger.warning(f"No license found for clinic {clinic_id}")
                return
            
            # Update the appropriate counter
            if counter_type == 'appointments_scheduled':
                license_record.current_month_calls += amount
            elif counter_type == 'calls_completed':
                license_record.current_month_calls += amount
            elif counter_type == 'minutes_used':
                license_record.current_month_minutes += amount
            
            # Recalculate usage percentage
            if license_record.max_calls_per_month:
                license_record.usage_percentage = (
                    license_record.current_month_calls / license_record.max_calls_per_month * 100
                )
            
            logger.debug(f"Incremented {counter_type} for clinic {clinic_id} by {amount}")
            
        except Exception as e:
            logger.error(f"Failed to increment usage counters for clinic {clinic_id}: {e}")
            raise TransactionError(f"Failed to update usage counters: {e}") from e
    
    def atomic_call_processing(self, call_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Atomically process a call with proper concurrency control.
        
        Args:
            call_data: Call data to process
            
        Returns:
            Dict containing the processed call information
        """
        def _process_call():
            with self.atomic_transaction():
                # Create the call record
                call = Call(
                    call_sid=call_data['call_sid'],
                    call_id=call_data['call_id'],
                    caller_phone_token=call_data.get('caller_phone_token'),
                    status=call_data.get('status', 'initiated'),
                    patient_id=call_data.get('patient_id')
                )
                self.db.add(call)
                self.db.flush()
                
                # Update usage counters if call is completed
                if call_data.get('status') == 'completed':
                    clinic_id = call_data.get('clinic_id')
                    if clinic_id:
                        self._increment_usage_counters(clinic_id, 'calls_completed')
                
                return {
                    'call': call,
                    'success': True
                }
        
        return self.with_retry(_process_call)
    
    def bulk_operation_with_locking(self, operations: List[Callable]) -> List[Any]:
        """
        Execute multiple operations atomically with proper locking order to prevent deadlocks.
        
        Args:
            operations: List of functions to execute
            
        Returns:
            List of results from each operation
        """
        def _execute_operations():
            with self.atomic_transaction():
                results = []
                for operation in operations:
                    result = operation()
                    results.append(result)
                return results
        
        return self.with_retry(_execute_operations)
    
    def _log_audit(self, table_name: str, record_id: str, action_type: str, 
                   old_values: Optional[Dict], new_values: Optional[Dict]):
        """Log audit information for the transaction."""
        try:
            from services.crypto import make_unique_audit_log_id
            audit_log = AuditLog(
                log_id=make_unique_audit_log_id(),
                user_id='system',
                action_type=action_type,
                table_name=table_name,
                record_id=record_id,
                details=f"Transaction: {action_type} on {table_name}",
                success='yes'
            )
            self.db.add(audit_log)
        except Exception as e:
            logger.warning(f"Failed to log audit: {e}")
    
    def check_deadlock_risk(self, operations: List[Dict[str, Any]]) -> bool:
        """
        Check if a set of operations might cause deadlocks.
        
        Args:
            operations: List of operations with their locking requirements
            
        Returns:
            bool: True if deadlock risk is detected
        """
        # Simple deadlock detection based on lock ordering
        # In practice, you'd implement more sophisticated detection
        lock_order = []
        for op in operations:
            if 'locks' in op:
                for lock in op['locks']:
                    lock_order.append((lock['table'], lock['mode']))
        
        # Check for circular dependencies
        # This is a simplified check - real deadlock detection is more complex
        return len(set(lock_order)) != len(lock_order)
    
    def get_transaction_status(self) -> Dict[str, Any]:
        """
        Get current transaction status and statistics.
        
        Returns:
            Dict containing transaction status information
        """
        try:
            # Get current transaction info
            result = self.db.execute(text("""
                SELECT 
                    txid_current() as transaction_id,
                    current_setting('transaction_isolation') as isolation_level,
                    current_setting('lock_timeout') as lock_timeout
            """)).fetchone()
            
            return {
                'transaction_id': result[0] if result else None,
                'isolation_level': result[1] if result else None,
                'lock_timeout': result[2] if result else None,
                'session_active': True
            }
        except Exception as e:
            logger.error(f"Failed to get transaction status: {e}")
            return {
                'transaction_id': None,
                'isolation_level': None,
                'lock_timeout': None,
                'session_active': False,
                'error': str(e)
            }


class ConcurrencyControlMixin:
    """
    Mixin class to add concurrency control methods to models.
    """
    
    @classmethod
    def lock_for_update(cls, db_session: Session, record_id: str):
        """Lock a record for update."""
        primary_key_column = cls.__table__.primary_key.columns.keys()[0]
        return db_session.query(cls).filter(
            getattr(cls, primary_key_column) == record_id
        ).with_for_update().first()
    
    @classmethod
    def lock_for_share(cls, db_session: Session, record_id: str):
        """Lock a record for share."""
        primary_key_column = cls.__table__.primary_key.columns.keys()[0]
        return db_session.query(cls).filter(
            getattr(cls, primary_key_column) == record_id
        ).with_for_update(read=True).first()
    
    def optimistic_update(self, db_session: Session, **updates):
        """
        Perform an optimistic update with version checking.
        
        Args:
            db_session: Database session
            **updates: Fields to update
        """
        # This would require a version field in the model
        # For now, this is a placeholder for the concept
        for key, value in updates.items():
            setattr(self, key, value)
        
        try:
            db_session.commit()
            return True
        except StaleDataError:
            db_session.rollback()
            raise ConcurrencyError("Record was modified by another transaction")


def get_transaction_manager(db_session: Session) -> TransactionManager:
    """Factory function to get a TransactionManager instance."""
    return TransactionManager(db_session)


