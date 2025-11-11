"""
Transaction Management Service

This service provides transaction management for the CallCenterAI application,
ensuring atomic operations, race condition prevention, and data consistency.

Key Features:
- Atomic operations (all-or-nothing)
- Row-level locking for critical operations
- Automatic rollback on errors
- Usage counter management with proper locking
- Timeout protection and retry logic
"""

import asyncio
from contextlib import asynccontextmanager
from typing import Any, Callable, Dict, List, Optional, Type
from datetime import datetime, timezone

from sqlalchemy import text, select
from sqlalchemy.exc import (
    OperationalError,
    DisconnectionError
)

from services.exceptions import ValidationError
from services.structured_logging import get_logger, LogCategory
from sqlalchemy.ext.asyncio import AsyncSession

from models.models import (
    Appointment, AppointmentSlot, Patient, Provider, 
    ClinicLicense, Call
)

logger = get_logger("transaction_manager")


class TransactionError(Exception):
    """Base exception for transaction-related errors."""
    pass


class LockTimeoutError(TransactionError):
    """Raised when a lock timeout occurs."""
    pass


class ConcurrencyError(TransactionError):
    """Raised when a concurrency conflict occurs."""
    pass


class TransactionManager:
    """
    Transaction management service for atomic operations and concurrency control.
    
    This service ensures:
    1. Atomic operations (all-or-nothing)
    2. Race condition prevention with row-level locking
    3. Automatic rollback on errors
    4. Usage counter accuracy with proper locking
    5. Timeout protection and retry logic
    """
    
    def __init__(self, db_session: AsyncSession, max_retries: int = 3, 
                 lock_timeout_seconds: int = 30, retry_delay: float = 1.0):
        self.db = db_session
        self.max_retries = max_retries
        self.lock_timeout_seconds = lock_timeout_seconds
        self.retry_delay = retry_delay
        self._lock_timeout_set = False  # Track if timeout has been set
    
    async def _set_lock_timeout(self):
        """Set the lock timeout for this database session (only once per session)."""
        if self._lock_timeout_set:
            return
        
        try:
            await self.db.execute(text(f"SET lock_timeout = '{self.lock_timeout_seconds}s'"))
            self._lock_timeout_set = True
        except Exception as e:
            # Some databases may not support lock_timeout (e.g., SQLite)
            logger.warning(
                f"Failed to set lock timeout (may not be supported): {e}",
                LogCategory.DATABASE
            )
    
    @asynccontextmanager
    async def atomic_transaction(self):
        """
        Async context manager for atomic transactions with automatic rollback on errors.
        
        Yields:
            AsyncSession: Database session for the transaction
            
        Raises:
            TransactionError: If transaction fails and cannot be retried
        """
        # Set lock timeout on first use
        await self._set_lock_timeout()
        
        try:
            yield self.db
            try:
                await self.db.commit()
                logger.debug("Transaction committed successfully", LogCategory.DATABASE)
            except Exception as commit_error:
                await self.db.rollback()
                logger.error(
                    f"Transaction commit failed, rolled back: {commit_error}",
                    LogCategory.DATABASE,
                    exception=commit_error
                )
                raise TransactionError(f"Transaction commit failed: {commit_error}") from commit_error
        except TransactionError:
            raise
        except Exception as e:
            try:
                await self.db.rollback()
            except Exception as rollback_error:
                logger.error(
                    f"Failed to rollback transaction: {rollback_error}",
                    LogCategory.DATABASE,
                    exception=rollback_error
                )
            logger.error(
                f"Transaction rolled back due to error: {e}",
                LogCategory.DATABASE,
                exception=e
            )
            raise TransactionError(f"Transaction failed: {e}") from e
    
    async def with_retry(self, operation: Callable, *args, **kwargs) -> Any:
        """
        Execute an async operation with automatic retry on lock timeout or connection errors.
        
        Args:
            operation: Async function to execute
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
                return await operation(*args, **kwargs)
            except (LockTimeoutError, ConcurrencyError) as e:
                last_exception = e
                if attempt < self.max_retries:
                    logger.warning(
                        f"Retry {attempt + 1}/{self.max_retries} after {e.__class__.__name__}: {e}",
                        LogCategory.DATABASE
                    )
                    await asyncio.sleep(self.retry_delay)
                else:
                    logger.error(
                        f"Operation failed after {self.max_retries} retries: {e}",
                        LogCategory.DATABASE,
                        exception=e
                    )
                    raise TransactionError(f"Operation failed after {self.max_retries} retries: {e}") from e
            except Exception as e:
                # Check if error is retryable
                error_type = type(e).__name__
                # Import ConnectionError for proper checking
                from builtins import ConnectionError as BuiltinConnectionError
                if isinstance(e, (OperationalError, DisconnectionError)) or isinstance(e, BuiltinConnectionError):
                    last_exception = e
                    if attempt < self.max_retries:
                        logger.warning(
                            f"Retry {attempt + 1}/{self.max_retries} after {error_type}: {e}",
                            LogCategory.DATABASE
                        )
                        await asyncio.sleep(self.retry_delay)
                        continue
                # Non-retryable error or out of retries
                logger.error(
                    f"Non-retryable error in operation: {e}",
                    LogCategory.DATABASE,
                    exception=e
                )
                raise TransactionError(f"Operation failed: {e}") from e
        
        raise TransactionError(f"Operation failed after {self.max_retries} retries") from last_exception
    
    async def lock_row(self, model_class: Type, record_id: str) -> Any:
        """
        Lock a specific row for update to prevent race conditions.
        
        Args:
            model_class: SQLAlchemy model class
            record_id: Primary key value of the record to lock
            
        Returns:
            Any: The locked record
            
        Raises:
            LockTimeoutError: If lock cannot be acquired within timeout
            ConcurrencyError: If record is not found
        """
        try:
            # Get the primary key column name
            primary_key_columns = list(model_class.__table__.primary_key.columns.keys())
            if not primary_key_columns:
                raise TransactionError(f"Model {model_class.__tablename__} has no primary key")
            
            primary_key_column = primary_key_columns[0]
            
            # Lock the row
            result = await self.db.execute(
                select(model_class).where(
                    getattr(model_class, primary_key_column) == record_id
                ).with_for_update()
            )
            
            record = result.scalar_one_or_none()
            
            if not record:
                raise ConcurrencyError(f"Record {record_id} not found in {model_class.__tablename__}")
            
            logger.debug(
                f"Locked {model_class.__tablename__} record {record_id}",
                LogCategory.DATABASE
            )
            return record
            
        except OperationalError as e:
            if "lock timeout" in str(e).lower():
                raise LockTimeoutError(f"Lock timeout for {model_class.__tablename__} record {record_id}") from e
            else:
                raise TransactionError(f"Database error locking {model_class.__tablename__} record {record_id}: {e}") from e
    
    async def atomic_appointment_booking(
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
        # Validate input parameters before starting transaction
        if not appointment_data or not slot_id or not patient_id or not provider_id or not clinic_id:
            raise ValidationError("atomic_appointment_booking", {
                "appointment_data": appointment_data,
                "slot_id": slot_id,
                "patient_id": patient_id,
                "provider_id": provider_id,
                "clinic_id": clinic_id
            }, "All parameters are required")
        
        # Validate patient exists before starting transaction
        try:
            patient_result = await self.db.execute(select(Patient).where(Patient.patient_id == patient_id))
            patient = patient_result.scalar_one_or_none()
            if not patient:
                raise ValidationError("patient_id", patient_id, f"Patient {patient_id} does not exist")
        except ValidationError:
            raise
        except Exception as patient_error:
            logger.warning(f"Failed to validate patient {patient_id}: {patient_error}")
        
        # Validate clinic exists before starting transaction
        try:
            from models.models import Clinic
            clinic_result = await self.db.execute(select(Clinic).where(Clinic.clinic_id == clinic_id))
            clinic = clinic_result.scalar_one_or_none()
            if not clinic:
                raise ValidationError("clinic_id", clinic_id, f"Clinic {clinic_id} does not exist")
        except ValidationError:
            raise
        except Exception as clinic_error:
            logger.warning(f"Failed to validate clinic {clinic_id}: {clinic_error}")
        
        async def _book_appointment():
            try:
                async with self.atomic_transaction():
                    # Step 1: Lock the appointment slot
                    slot = await self.lock_row(AppointmentSlot, slot_id)
                    
                    if not slot:
                        raise ConcurrencyError(f"Appointment slot {slot_id} not found after locking")
                    
                    # Step 2: Verify slot is still available
                    from models.enums import YesNo
                    if slot.is_booked == YesNo.YES.value:
                        raise ConcurrencyError(f"Appointment slot {slot_id} is already booked")
                    elif slot.is_booked == "held":
                        # Check if hold has expired
                        current_time = datetime.now(timezone.utc)
                        if slot.held_until and slot.held_until > current_time:
                            raise ConcurrencyError(f"Appointment slot {slot_id} is held until {slot.held_until}")
                    elif slot.is_booked != YesNo.NO.value:
                        raise ConcurrencyError(f"Appointment slot {slot_id} is no longer available (state: {slot.is_booked})")
                    
                    # Step 3: Normalize timezones before creating appointment
                    appointment_date = appointment_data['appointment_date']
                    start_time = appointment_data['start_time']
                    end_time = appointment_data['end_time']
                    
                    # Normalize timezones to UTC
                    if start_time.tzinfo is None:
                        start_time = start_time.replace(tzinfo=timezone.utc)
                    elif start_time.tzinfo != timezone.utc:
                        start_time = start_time.astimezone(timezone.utc)
                    
                    if end_time.tzinfo is None:
                        end_time = end_time.replace(tzinfo=timezone.utc)
                    elif end_time.tzinfo != timezone.utc:
                        end_time = end_time.astimezone(timezone.utc)
                    
                    # Step 4: Create the appointment
                    appointment = Appointment(
                        appointment_id=appointment_data['appointment_id'],
                        patient_id=patient_id,
                        provider_id=provider_id,
                        appointment_date=appointment_date,
                        start_time=start_time,
                        end_time=end_time,
                        appointment_type=appointment_data['appointment_type'],
                        duration_minutes=appointment_data['duration_minutes'],
                        status='scheduled'
                    )
                    self.db.add(appointment)
                    await self.db.flush()
                    
                    # Step 5: Mark slot as booked
                    slot.is_booked = YesNo.YES.value
                    slot.booked_by_appointment_id = appointment.appointment_id
                    slot.held_until = None
                    slot.held_by_call_sid = None
                    
                    # Step 6: Update usage counters
                    # Note: Appointments are not calls, so we don't increment call counters
                    # Appointments are tracked separately in Clinic model
                    
                    # Step 7: Log the booking
                    await self._log_audit('appointments', appointment.appointment_id, 'create', 
                                  None, appointment_data)
                    
                    return {
                        'appointment': appointment,
                        'slot': slot,
                        'success': True
                    }
            except (OperationalError, DisconnectionError) as conn_error:
                logger.error(
                    f"Database connection failure during appointment booking: {conn_error}",
                    LogCategory.DATABASE,
                    exception=conn_error
                )
                raise TransactionError(f"Database connection failed: {conn_error}") from conn_error
            except Exception as e:
                logger.error(
                    f"Database error during appointment booking: {e}",
                    LogCategory.DATABASE,
                    exception=e
                )
                raise
        
        try:
            return await self.with_retry(_book_appointment)
        except ConcurrencyError as e:
            logger.warning(
                f"Concurrency error during appointment booking: {e}",
                LogCategory.DATABASE
            )
            raise
        except ValidationError as e:
            raise
        except Exception as e:
            logger.error(
                f"Unexpected error during appointment booking: {e}",
                LogCategory.DATABASE,
                exception=e
            )
            raise TransactionError(f"Failed to book appointment: {e}") from e
    
    async def atomic_slot_release(self, slot_id: str, appointment_id: str) -> bool:
        """
        Atomically release an appointment slot when an appointment is cancelled.
        
        This operation:
        1. Locks the appointment slot
        2. Verifies slot is booked by the specified appointment
        3. Releases the slot (marks as available)
        4. Clears booking references
        5. All or nothing - if any step fails, everything rolls back
        
        Args:
            slot_id: ID of the slot to release
            appointment_id: ID of the appointment being cancelled (for verification)
            
        Returns:
            bool: True if successful, False if slot not found or not booked by this appointment
            
        Raises:
            TransactionError: If release fails due to database error
            ConcurrencyError: If slot is not booked by the specified appointment
        """
        # Validate input parameters
        if not slot_id or not appointment_id:
            raise ValidationError("atomic_slot_release", {
                "slot_id": slot_id,
                "appointment_id": appointment_id
            }, "Both slot_id and appointment_id are required")
        
        async def _release_slot():
            try:
                async with self.atomic_transaction():
                    # Step 1: Lock the slot
                    slot = await self.lock_row(AppointmentSlot, slot_id)
                    
                    if not slot:
                        logger.warning(
                            f"Appointment slot {slot_id} not found",
                            LogCategory.DATABASE
                        )
                        return False
                    
                    # Step 2: Verify slot is booked by this appointment
                    from models.enums import YesNo
                    if not slot.booked_by_appointment_id:
                        logger.warning(
                            f"Slot {slot_id} is not booked (no appointment_id)",
                            LogCategory.DATABASE
                        )
                        return False
                    
                    if slot.booked_by_appointment_id != appointment_id:
                        raise ConcurrencyError(
                            f"Slot {slot_id} is booked by appointment {slot.booked_by_appointment_id}, "
                            f"not {appointment_id}"
                        )
                    
                    # Step 3: Verify slot is actually marked as booked
                    if slot.is_booked != YesNo.YES.value:
                        logger.warning(
                            f"Slot {slot_id} is not marked as booked (state: {slot.is_booked})",
                            LogCategory.DATABASE
                        )
                        # Still release it to clean up inconsistent state
                    
                    # Step 4: Release the slot
                    slot.is_booked = YesNo.NO.value
                    slot.booked_by_appointment_id = None
                    slot.held_until = None
                    slot.held_by_call_sid = None
                    
                    # Step 5: Log the release
                    await self._log_audit(
                        'appointment_slots',
                        slot_id,
                        'release',
                        {
                            'is_booked': YesNo.YES.value,
                            'booked_by_appointment_id': appointment_id
                        },
                        {
                            'is_booked': YesNo.NO.value,
                            'booked_by_appointment_id': None
                        }
                    )
                    
                    logger.info(
                        f"Released slot {slot_id} for appointment {appointment_id}",
                        LogCategory.DATABASE
                    )
                    
                    return True
                    
            except (OperationalError, DisconnectionError) as conn_error:
                logger.error(
                    f"Database connection failure during slot release: {conn_error}",
                    LogCategory.DATABASE,
                    exception=conn_error
                )
                raise TransactionError(f"Database connection failed: {conn_error}") from conn_error
            except Exception as e:
                logger.error(
                    f"Database error during slot release: {e}",
                    LogCategory.DATABASE,
                    exception=e
                )
                raise
        
        try:
            return await self.with_retry(_release_slot)
        except ConcurrencyError as e:
            logger.warning(
                f"Concurrency error during slot release: {e}",
                LogCategory.DATABASE
            )
            raise
        except ValidationError as e:
            raise
        except Exception as e:
            logger.error(
                f"Unexpected error during slot release: {e}",
                LogCategory.DATABASE,
                exception=e
            )
            raise TransactionError(f"Failed to release slot: {e}") from e
    
    async def atomic_call_processing(self, call_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Atomically process a call record when a call ends.
        
        This operation:
        1. Creates or updates the Call record
        2. Calculates call duration
        3. Updates clinic usage counters (calls_completed, minutes_used)
        4. All or nothing - if any step fails, everything rolls back
        
        Args:
            call_data: Dictionary containing call information:
                - call_sid: Azure Communication Services call ID (required)
                - call_id: Internal call ID (required)
                - status: Call status (default: "completed")
                - clinic_id: Clinic ID for usage tracking (optional)
                - patient_id: Patient ID if call was associated (optional)
                - caller_phone_token: Tokenized caller phone number (optional)
                - started_at: Call start time (optional, defaults to now)
                - ended_at: Call end time (optional, defaults to now)
                - duration_minutes: Call duration in minutes (optional, calculated if not provided)
                
        Returns:
            Dict containing:
                - call: The created/updated Call record
                - duration_minutes: Calculated call duration
                - success: True if successful
                
        Raises:
            ValidationError: If required fields are missing
            TransactionError: If processing fails
        """
        # Validate required fields
        if not call_data.get('call_sid') or not call_data.get('call_id'):
            raise ValidationError("atomic_call_processing", call_data, 
                                "call_sid and call_id are required")
        
        # Set defaults
        status = call_data.get('status', 'completed')
        started_at = call_data.get('started_at') or datetime.now(timezone.utc)
        ended_at = call_data.get('ended_at') or datetime.now(timezone.utc)
        
        # Calculate duration if not provided
        duration_minutes = call_data.get('duration_minutes')
        if duration_minutes is None:
            duration_seconds = (ended_at - started_at).total_seconds()
            duration_minutes = max(0, int(duration_seconds / 60))  # Round down to minutes
        
        async def _process_call():
            try:
                async with self.atomic_transaction():
                    # Step 1: Check if call already exists
                    call_result = await self.db.execute(
                        select(Call).where(Call.call_sid == call_data['call_sid'])
                    )
                    existing_call = call_result.scalar_one_or_none()
                    
                    if existing_call:
                        # Update existing call
                        existing_call.status = status
                        existing_call.ended_at = ended_at
                        if call_data.get('clinic_id'):
                            existing_call.clinic_id = call_data['clinic_id']
                        if call_data.get('patient_id'):
                            existing_call.patient_id = call_data['patient_id']
                        call = existing_call
                        logger.debug(
                            f"Updated existing call {call_data['call_sid']}",
                            LogCategory.DATABASE
                        )
                    else:
                        # Create new call record
                        call = Call(
                            call_sid=call_data['call_sid'],
                            call_id=call_data['call_id'],
                            status=status,
                            started_at=started_at,
                            ended_at=ended_at,
                            clinic_id=call_data.get('clinic_id'),
                            patient_id=call_data.get('patient_id'),
                            caller_phone_token=call_data.get('caller_phone_token')
                        )
                        self.db.add(call)
                        logger.debug(
                            f"Created new call record {call_data['call_sid']}",
                            LogCategory.DATABASE
                        )
                    
                    await self.db.flush()
                    
                    # Step 2: Update usage counters if call is completed and clinic_id is provided
                    if status == 'completed' and call_data.get('clinic_id'):
                        clinic_id = call_data['clinic_id']
                        # Increment calls_completed counter
                        await self._increment_usage_counters(clinic_id, 'calls_completed', 1)
                        # Increment minutes_used counter
                        if duration_minutes > 0:
                            await self._increment_usage_counters(clinic_id, 'minutes_used', duration_minutes)
                    
                    # Step 3: Log the call processing
                    await self._log_audit(
                        'calls',
                        call.call_sid,
                        'process',
                        None,
                        {
                            'status': status,
                            'duration_minutes': duration_minutes,
                            'clinic_id': call_data.get('clinic_id')
                        }
                    )
                    
                    logger.info(
                        f"Processed call {call_data['call_sid']}: {status}, {duration_minutes} minutes",
                        LogCategory.DATABASE
                    )
                    
                    return {
                        'call': call,
                        'duration_minutes': duration_minutes,
                        'success': True
                    }
                    
            except (OperationalError, DisconnectionError) as conn_error:
                logger.error(
                    f"Database connection failure during call processing: {conn_error}",
                    LogCategory.DATABASE,
                    exception=conn_error
                )
                raise TransactionError(f"Database connection failed: {conn_error}") from conn_error
            except Exception as e:
                logger.error(
                    f"Database error during call processing: {e}",
                    LogCategory.DATABASE,
                    exception=e
                )
                raise
        
        try:
            return await self.with_retry(_process_call)
        except ValidationError as e:
            raise
        except Exception as e:
            logger.error(
                f"Unexpected error during call processing: {e}",
                LogCategory.DATABASE,
                exception=e
            )
            raise TransactionError(f"Failed to process call: {e}") from e
    
    async def bulk_operation_with_locking(self, operations: List[Callable]) -> List[Any]:
        """
        Execute multiple async operations atomically with proper locking order.
        
        This operation:
        1. Executes all operations in a single transaction
        2. Ensures proper locking order to prevent deadlocks
        3. All operations succeed or all roll back
        4. Returns results in the same order as operations
        
        Args:
            operations: List of async functions (callables) to execute.
                       Each function should accept no arguments or use closures
                       to capture required data.
                       
        Returns:
            List of results from each operation, in the same order as provided
            
        Raises:
            ValidationError: If operations list is empty
            TransactionError: If any operation fails (all operations roll back)
            
        Example:
            async def cancel_appointment(appointment_id):
                # Cancel appointment logic
                return appointment
            
            async def release_slot(slot_id):
                # Release slot logic
                return True
            
            results = await transaction_manager.bulk_operation_with_locking([
                lambda: cancel_appointment("APT123"),
                lambda: release_slot("SLOT456")
            ])
        """
        # Validate input
        if not operations or len(operations) == 0:
            raise ValidationError("bulk_operation_with_locking", {
                "operations": operations
            }, "Operations list cannot be empty")
        
        async def _execute_operations():
            try:
                async with self.atomic_transaction():
                    results = []
                    for i, operation in enumerate(operations):
                        try:
                            # Execute operation (supports both async and sync callables)
                            if asyncio.iscoroutinefunction(operation):
                                result = await operation()
                            else:
                                result = operation()
                            results.append(result)
                            
                            logger.debug(
                                f"Bulk operation {i+1}/{len(operations)} completed",
                                LogCategory.DATABASE
                            )
                        except Exception as op_error:
                            logger.error(
                                f"Bulk operation {i+1}/{len(operations)} failed: {op_error}",
                                LogCategory.DATABASE,
                                exception=op_error
                            )
                            # Re-raise to trigger rollback
                            raise TransactionError(
                                f"Bulk operation {i+1} failed: {op_error}"
                            ) from op_error
                    
                    logger.info(
                        f"All {len(operations)} bulk operations completed successfully",
                        LogCategory.DATABASE
                    )
                    return results
                    
            except (OperationalError, DisconnectionError) as conn_error:
                logger.error(
                    f"Database connection failure during bulk operations: {conn_error}",
                    LogCategory.DATABASE,
                    exception=conn_error
                )
                raise TransactionError(f"Database connection failed: {conn_error}") from conn_error
            except Exception as e:
                logger.error(
                    f"Database error during bulk operations: {e}",
                    LogCategory.DATABASE,
                    exception=e
                )
                raise
        
        try:
            return await self.with_retry(_execute_operations)
        except ValidationError as e:
            raise
        except Exception as e:
            logger.error(
                f"Unexpected error during bulk operations: {e}",
                LogCategory.DATABASE,
                exception=e
            )
            raise TransactionError(f"Failed to execute bulk operations: {e}") from e
    
    async def _increment_usage_counters(self, clinic_id: str, counter_type: str, amount: int = 1):
        """
        Safely increment usage counters with proper locking.
        
        Args:
            clinic_id: ID of the clinic
            counter_type: Type of counter to increment
            amount: Amount to increment by
        """
        # Validate inputs
        if not clinic_id:
            logger.warning(
                "clinic_id is empty in _increment_usage_counters",
                LogCategory.DATABASE
            )
            return
        
        if not counter_type:
            logger.warning(
                "counter_type is empty in _increment_usage_counters",
                LogCategory.DATABASE
            )
            return
        
        # Allow negative amounts for decrements (e.g., when cancelling appointments)
        if amount == 0:
            logger.warning(
                f"Zero amount in _increment_usage_counters (no-op)",
                LogCategory.DATABASE
            )
            return
        
        try:
            # Lock the clinic license to prevent concurrent counter updates
            license_result = await self.db.execute(
                select(ClinicLicense).where(ClinicLicense.clinic_id == clinic_id).with_for_update()
            )
            license_record = license_result.scalar_one_or_none()
            
            if not license_record:
                logger.warning(
                    f"No license found for clinic {clinic_id}",
                    LogCategory.DATABASE
                )
                return
            
            # Update the appropriate counter
            # Note: Appointments are tracked separately in Clinic model, not in ClinicLicense
            if counter_type == 'calls_completed':
                license_record.current_month_calls += amount
            elif counter_type == 'minutes_used':
                license_record.current_month_minutes += amount
            else:
                logger.warning(
                    f"Unknown counter type: {counter_type} for clinic {clinic_id}",
                    LogCategory.DATABASE
                )
                return
            
            # Recalculate usage percentage
            if license_record.max_calls_per_month and license_record.max_calls_per_month > 0:
                license_record.usage_percentage = (
                    license_record.current_month_calls / license_record.max_calls_per_month * 100
                )
            else:
                license_record.usage_percentage = 0.0
            
            logger.debug(
                f"Incremented {counter_type} for clinic {clinic_id} by {amount}",
                LogCategory.DATABASE
            )
            
        except Exception as e:
            logger.error(
                f"Failed to increment usage counters for clinic {clinic_id}: {e}",
                LogCategory.DATABASE,
                exception=e
            )
            raise TransactionError(f"Failed to update usage counters: {e}") from e
    
    async def _log_audit(self, table_name: str, record_id: str, action_type: str, 
                   old_values: Optional[Dict], new_values: Optional[Dict]):
        """Log audit information for the transaction."""
        from services.audit_utils import log_audit_trail
        await log_audit_trail(
            self.db,
            table_name=table_name,
            record_id=record_id,
            action_type=action_type,
            old_values=old_values,
            new_values=new_values,
            user_id="system",
            service_name="TransactionManager"
        )


def get_transaction_manager(db_session: AsyncSession) -> TransactionManager:
    """Factory function to get a TransactionManager instance."""
    return TransactionManager(db_session)


