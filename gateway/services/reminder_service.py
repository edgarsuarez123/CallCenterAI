"""
Reminder Service for CallCenterAI

This service manages automated reminder calls for appointments, including:
- Scheduling reminder calls based on clinic settings
- Making outbound calls using Azure Communication Services
- Retry logic for failed calls
- Comprehensive logging and audit trails
- Integration with appointment lifecycle

Critical for patient engagement and reducing no-shows.
"""

import asyncio
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass
from collections import deque

# Atlantic Standard Time (UTC-4)
AST = timezone(timedelta(hours=-4))
from typing import Dict, List, Optional, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import and_, or_, select

from models.models import (
    Reminder, ReminderLog, Appointment, Patient, Clinic, 
    Mapping, ClinicUsage
)
from services.azure_communication_service import get_azure_communication_service, AzureCommunicationService
from services.azure_speech_tts import get_text_to_speech_service, TextToSpeechService
from services.crypto import make_ulid_token
from services.structured_logging import get_logger, LogCategory, log_performance
from services.configuration import get_settings
from services.exceptions import (
    AzureCommunicationError, ExternalServiceUnavailableError,
    ValidationError, CallCenterAIException, ErrorCode
)


@dataclass
class QueuedReminder:
    """Represents a reminder waiting in the queue."""
    reminder_id: str
    appointment_id: str
    patient_phone: str
    message: str
    clinic_id: str
    retry_count: int = 0
    queued_at: datetime = None
    
    def __post_init__(self):
        if self.queued_at is None:
            self.queued_at = datetime.now(timezone.utc)


class ReminderService:
    """
    Service for managing automated reminder calls for appointments.
    
    Provides:
    - Reminder scheduling and management
    - Outbound call execution via Azure Communication Services
    - Retry logic for failed calls
    - Comprehensive logging and audit trails
    - Integration with appointment lifecycle
    """
    
    def __init__(self):
        self.logger = get_logger("reminder_service")
        self.settings = get_settings()
        self.acs_service: AzureCommunicationService = get_azure_communication_service()
        self.tts_service: TextToSpeechService = get_text_to_speech_service()
        
        # Reminder queue for processing calls
        self._reminder_queue: deque = deque()
        self._queue_lock = asyncio.Lock()
        self._processing = False
        self._max_retries = 5  # Max retries per reminder for the day
        self._retry_delay_minutes = 30  # Delay between retries
        
        # Reminder call templates
        self.reminder_templates = {
            'appointment_reminder': {
                'en': "Hello {patient_name}, this is a reminder about your upcoming appointment. Your appointment is scheduled for {appointment_time}. Please call us if you need to reschedule. Thank you.",
                'es': "Hola {patient_name}, este es un recordatorio sobre su próxima cita. Su cita está programada para {appointment_time}. Por favor llámenos si necesita reprogramar. Gracias."
            },
            'follow_up': {
                'en': "Hello {patient_name}, this is a follow-up call regarding your recent appointment. How are you feeling? Please call us if you have any questions. Thank you.",
                'es': "Hola {patient_name}, esta es una llamada de seguimiento sobre su cita reciente. ¿Cómo se siente? Por favor llámenos si tiene alguna pregunta. Gracias."
            },
            'cancellation_reminder': {
                'en': "Hello {patient_name}, this is a reminder that your appointment has been cancelled. Please call us to reschedule if needed. Thank you.",
                'es': "Hola {patient_name}, este es un recordatorio de que su cita ha sido cancelada. Por favor llámenos para reprogramar si es necesario. Gracias."
            }
        }
        
        self.logger.info("ReminderService initialized.", LogCategory.REMINDER)
    
    @log_performance("reminder_scheduling")
    async def schedule_reminder(self, db: AsyncSession, appointment_id: str, 
                              reminder_type: str = 'appointment_reminder',
                              custom_scheduled_time: Optional[datetime] = None) -> Reminder:
        """
        Schedule a reminder call for an appointment.
        
        Args:
            db: Database session
            appointment_id: ID of the appointment to remind about
            reminder_type: Type of reminder (appointment_reminder, follow_up, etc.)
            custom_scheduled_time: Custom time for reminder (if None, uses clinic settings)
            
        Returns:
            Created Reminder instance
        """
        # Validate inputs
        if not appointment_id:
            raise ValidationError("appointment_id cannot be empty")
        
        try:
            # Get appointment and related data
            appointment_result = await db.execute(select(Appointment).where(
                Appointment.appointment_id == appointment_id,
                Appointment.is_deleted == 'no'
            ))
            appointment = appointment_result.scalar_one_or_none()
            
            if not appointment:
                raise CallCenterAIException(
                    f"Appointment {appointment_id} not found",
                    error_code=ErrorCode.RESOURCE_NOT_FOUND
                )
            
            # Issue 26: Check if appointment is cancelled before scheduling reminder
            if appointment.status == 'cancelled':
                self.logger.info(f"Appointment {appointment_id} is cancelled, skipping reminder scheduling", LogCategory.REMINDER)
                raise CallCenterAIException(
                    "Cannot schedule reminder for cancelled appointment",
                    error_code=ErrorCode.VALIDATION_ERROR
                )
            
            # Issue 74: Check if reminder already exists for this appointment
            existing_reminder_result = await db.execute(select(Reminder).where(
                Reminder.appointment_id == appointment_id,
                Reminder.is_deleted == 'no',
                Reminder.status.in_(['scheduled', 'pending'])
            ))
            existing_reminder = existing_reminder_result.scalar_one_or_none()
            if existing_reminder:
                self.logger.info(f"Reminder already exists for appointment {appointment_id}, skipping duplicate", LogCategory.REMINDER)
                raise CallCenterAIException(
                    "A reminder already exists for this appointment",
                    error_code=ErrorCode.VALIDATION_ERROR
                )
            
            # Get clinic settings
            clinic_result = await db.execute(
                select(Clinic).join(Patient).where(
                    Patient.patient_id == appointment.patient_id,
                    Clinic.is_deleted == 'no'
                )
            )
            clinic = clinic_result.scalar_one_or_none()
            
            if not clinic:
                raise CallCenterAIException(
                    f"Clinic not found for appointment {appointment_id}",
                    error_code=ErrorCode.RESOURCE_NOT_FOUND
                )
            
            # Check if reminders are enabled for this clinic
            if clinic.reminders_enabled != 'yes':
                self.logger.info(f"Reminders disabled for clinic {clinic.clinic_id}, skipping reminder for appointment {appointment_id}", LogCategory.REMINDER)
                raise CallCenterAIException(
                    "Reminders are disabled for this clinic",
                    error_code=ErrorCode.CONFIGURATION_ERROR
                )
            
            # Calculate scheduled time - always 24 hours before appointment
            if custom_scheduled_time:
                scheduled_time = custom_scheduled_time
            else:
                if not appointment.start_time:
                    raise ValidationError("Appointment start_time is required for reminder scheduling")
                
                now = datetime.now(timezone.utc)
                # Ensure appointment.start_time is timezone-aware
                if appointment.start_time.tzinfo is None:
                    # If naive, assume UTC
                    appointment_start = appointment.start_time.replace(tzinfo=timezone.utc)
                else:
                    appointment_start = appointment.start_time
                # Always schedule 24 hours before appointment
                scheduled_time = appointment_start - timedelta(hours=24)
            
            # Check if reminder is too far in the past
            if scheduled_time < now:  # Use captured 'now'
                self.logger.warning(f"Reminder scheduled time {scheduled_time} is in the past for appointment {appointment_id}", LogCategory.REMINDER)
                raise ValidationError("scheduled_time", scheduled_time, "Reminder scheduled time cannot be in the past")
            
            # Create reminder record
            reminder_id = make_ulid_token('REMINDER')
            reminder = Reminder(
                reminder_id=reminder_id,
                appointment_id=appointment_id,
                scheduled_time=scheduled_time,
                reminder_type=reminder_type,
                status='scheduled',
                max_retries=self._max_retries  # Use service-level max retries
            )
            
            db.add(reminder)
            try:
                await db.commit()
                await db.refresh(reminder)
            except Exception as commit_error:
                await db.rollback()
                self.logger.error(f"Failed to commit reminder: {commit_error}", LogCategory.REMINDER, exception=commit_error)
                raise
            
            self.logger.info(f"Reminder {reminder_id} scheduled for appointment {appointment_id} at {scheduled_time}", LogCategory.REMINDER,
                            extra_data={
                                'reminder_id': reminder_id,
                                'appointment_id': appointment_id,
                                'scheduled_time': scheduled_time.isoformat(),
                                'reminder_type': reminder_type
                            })
            
            return reminder
            
        except Exception as e:
            await db.rollback()
            self.logger.error(f"Failed to schedule reminder for appointment {appointment_id}: {e}", LogCategory.REMINDER, exception=e)
            if isinstance(e, (CallCenterAIException, ValidationError)):
                raise
            raise CallCenterAIException(
                f"Failed to schedule reminder: {e}",
                error_code=ErrorCode.DATABASE_ERROR
            )
    
    @log_performance("reminder_execution")
    async def execute_reminder(self, db: AsyncSession, reminder_id: str) -> Dict[str, Any]:
        """
        Execute a reminder call.
        
        Args:
            db: Database session
            reminder_id: ID of the reminder to execute
            
        Returns:
            Dictionary with call outcome details
        """
        # Validate inputs
        if not reminder_id:
            raise ValidationError("reminder_id cannot be empty")
        
        try:
            # Get reminder and related data
            reminder_result = await db.execute(select(Reminder).where(
                Reminder.reminder_id == reminder_id,
                Reminder.is_deleted == 'no'
            ))
            reminder = reminder_result.scalar_one_or_none()
            
            if not reminder:
                raise CallCenterAIException(
                    f"Reminder {reminder_id} not found",
                    error_code=ErrorCode.RESOURCE_NOT_FOUND
                )
            
            if reminder.status not in ['scheduled', 'failed']:
                raise CallCenterAIException(
                    f"Reminder {reminder_id} is not in a valid state for execution (current: {reminder.status})",
                    error_code=ErrorCode.VALIDATION_ERROR
                )
            
            # Get appointment and patient data
            appointment_result = await db.execute(
                select(Appointment).join(Patient).where(
                    Appointment.appointment_id == reminder.appointment_id,
                    Appointment.is_deleted == 'no'
                )
            )
            appointment = appointment_result.scalar_one_or_none()
            
            if not appointment:
                raise CallCenterAIException(
                    f"Appointment {reminder.appointment_id} not found",
                    error_code=ErrorCode.RESOURCE_NOT_FOUND
                )
            
            # Issue 27: Check if appointment is cancelled before executing reminder
            if appointment.status == 'cancelled':
                self.logger.info(f"Appointment {reminder.appointment_id} is cancelled, skipping reminder execution", LogCategory.REMINDER)
                # Update reminder status to cancelled
                reminder.status = 'cancelled'
                reminder.completed_at = datetime.now(AST)
                reminder.deletion_reason = 'appointment_cancelled'
                try:
                    await db.commit()
                except Exception as commit_error:
                    await db.rollback()
                    self.logger.error(f"Failed to update reminder status: {commit_error}", LogCategory.REMINDER)
                raise CallCenterAIException(
                    "Cannot execute reminder for cancelled appointment",
                    error_code=ErrorCode.VALIDATION_ERROR
                )
            
            # Issue 73: Check and update reminder status atomically to prevent duplicate execution
            # Use SELECT FOR UPDATE to lock the reminder row
            locked_reminder_result = await db.execute(
                select(Reminder).where(
                    Reminder.reminder_id == reminder_id,
                    Reminder.status.in_(['scheduled', 'failed'])
                ).with_for_update()
            )
            locked_reminder = locked_reminder_result.scalar_one_or_none()
            
            if not locked_reminder or locked_reminder.status not in ['scheduled', 'failed']:
                raise CallCenterAIException(
                    f"Reminder {reminder_id} is not in a valid state for execution (current: {locked_reminder.status if locked_reminder else 'not found'})",
                    error_code=ErrorCode.VALIDATION_ERROR
                )
            
            # Issue 156: Update status to 'executing' to prevent duplicate execution
            # Keep lock held during execution to prevent concurrent execution attempts
            locked_reminder.status = 'executing'
            locked_reminder.started_at = datetime.now(AST)
            await db.commit()
            await db.refresh(locked_reminder)
            reminder = locked_reminder  # Use the locked reminder for the rest of the method
            
            # Issue 156: Note: Lock is released after commit, but status is 'executing' which prevents other workers
            # from picking up the same reminder. If execution takes a long time, periodic status checks
            # would be needed to prevent duplicate execution.
            
            # Get patient's phone number
            if not appointment.patient or not appointment.patient.phone_token:
                raise CallCenterAIException(
                    f"Patient phone token not found for appointment {appointment.appointment_id}",
                    error_code=ErrorCode.RESOURCE_NOT_FOUND
                )
            
            # Issue 194: Re-query patient phone number when executing reminder to handle phone number changes
            phone_mapping_result = await db.execute(select(Mapping).where(
                Mapping.token == appointment.patient.phone_token,
                Mapping.is_deleted == 'no'
            ))
            phone_mapping = phone_mapping_result.scalar_one_or_none()
            
            if not phone_mapping:
                # Issue 194: Try to get phone number from patient record if mapping not found
                # This handles cases where phone number was updated but mapping wasn't refreshed
                self.logger.warning(f"Phone mapping not found for patient {appointment.patient_id}, attempting to re-query")
                # Re-query patient to get latest phone token
                await db.refresh(appointment.patient)
                if appointment.patient.phone_token:
                    phone_mapping_result = await db.execute(select(Mapping).where(
                        Mapping.token == appointment.patient.phone_token,
                        Mapping.is_deleted == 'no'
                    ))
                    phone_mapping = phone_mapping_result.scalar_one_or_none()
                
                if not phone_mapping:
                    raise CallCenterAIException(
                        f"Phone number not found for patient {appointment.patient_id}",
                        error_code=ErrorCode.RESOURCE_NOT_FOUND
                    )
            
            # Decrypt phone number from mapping
            from services.crypto import decrypt_str
            try:
                patient_phone = decrypt_str(phone_mapping.value_nonce, phone_mapping.value_ciphertext)
            except Exception as decrypt_error:
                raise CallCenterAIException(
                    f"Failed to decrypt phone number for patient {appointment.patient_id}: {decrypt_error}",
                    error_code=ErrorCode.RESOURCE_NOT_FOUND
                )
            
            if not patient_phone:
                raise CallCenterAIException(
                    f"Phone number value is empty for patient {appointment.patient_id}",
                    error_code=ErrorCode.RESOURCE_NOT_FOUND
                )
            
            # Update reminder status
            reminder.status = 'calling'
            reminder.retry_count += 1
            try:
                await db.commit()
            except Exception as commit_error:
                await db.rollback()
                self.logger.error(f"Failed to commit reminder status update: {commit_error}", LogCategory.REMINDER, exception=commit_error)
                raise
            
            # Create reminder log entry
            log_id = make_ulid_token('REMINDER_LOG')
            reminder_log = ReminderLog(
                log_id=log_id,
                reminder_id=reminder_id,
                attempt_number=reminder.retry_count,
                call_started_at=datetime.now(AST),
                call_status='initiated'
            )
            db.add(reminder_log)
            try:
                await db.commit()
            except Exception as commit_error:
                await db.rollback()
                self.logger.error(f"Failed to commit reminder log: {commit_error}", LogCategory.REMINDER, exception=commit_error)
                raise
            
            # Generate reminder message
            message = await self._generate_reminder_message(appointment, reminder.reminder_type, db)
            
            # Make the outbound call
            call_result = await self._make_reminder_call(
                reminder_id, patient_phone, message, appointment
            )
            
            # Update reminder log with call outcome
            reminder_log.call_ended_at = datetime.now(AST)
            reminder_log.call_status = call_result['status']
            reminder_log.call_duration_seconds = call_result.get('duration_seconds')
            reminder_log.call_outcome = call_result.get('outcome')
            reminder_log.error_code = call_result.get('error_code')
            reminder_log.error_message = call_result.get('error_message')
            reminder_log.caller_id = call_result.get('caller_id')
            
            # Update reminder with final status
            if call_result['status'] == 'completed' and call_result.get('outcome') == 'answered':
                # Call was answered - mark as completed
                reminder.status = 'completed'
                reminder.completed_at = datetime.now(AST)
                reminder.call_duration_seconds = call_result.get('duration_seconds')
                reminder.call_outcome = call_result.get('outcome')
                reminder.reminder_call_id = call_result.get('call_id')
            else:
                # Call failed or not answered - put back in queue for retry
                if reminder.retry_count < reminder.max_retries:
                    # Put back in queue for retry
                    reminder.status = 'failed'
                    reminder.next_retry_time = datetime.now(AST) + timedelta(minutes=self._retry_delay_minutes)
                    # Re-queue the reminder
                    await self._enqueue_reminder_for_retry(
                        db, reminder_id, patient_phone, message, appointment, reminder.retry_count
                    )
                else:
                    # Max retries reached for the day
                    reminder.status = 'failed'
                    reminder.completed_at = datetime.now(AST)
                    reminder.call_outcome = call_result.get('outcome', 'max_retries_exceeded')
            
            try:
                await db.commit()
            except Exception as commit_error:
                await db.rollback()
                self.logger.error(f"Failed to commit reminder final status: {commit_error}", LogCategory.REMINDER, exception=commit_error)
                raise
            
            # Update clinic usage metrics
            await self._update_usage_metrics(db, appointment, call_result)
            
            self.logger.info(f"Reminder {reminder_id} executed with status {call_result['status']}", LogCategory.REMINDER,
                            extra_data={
                                'reminder_id': reminder_id,
                                'appointment_id': reminder.appointment_id,
                                'call_status': call_result['status'],
                                'call_outcome': call_result.get('outcome'),
                                'retry_count': reminder.retry_count
                            })
            
            return {
                'reminder_id': reminder_id,
                'status': call_result['status'],
                'outcome': call_result.get('outcome'),
                'duration_seconds': call_result.get('duration_seconds'),
                'retry_count': reminder.retry_count,
                'next_retry_time': reminder.next_retry_time.isoformat() if reminder.next_retry_time else None
            }
            
        except Exception as e:
            await db.rollback()
            self.logger.error(f"Failed to execute reminder {reminder_id}: {e}", LogCategory.REMINDER, exception=e)
            if isinstance(e, CallCenterAIException):
                raise
            raise CallCenterAIException(
                f"Failed to execute reminder: {e}",
                error_code=ErrorCode.DATABASE_ERROR
            )
    
    async def _generate_reminder_message(self, appointment: Appointment, reminder_type: str, db: Optional[AsyncSession] = None) -> str:
        """
        Generate the reminder message text based on appointment and reminder type.
        
        Args:
            appointment: Appointment object
            reminder_type: Type of reminder
            db: Database session (optional, needed to decrypt patient name)
            
        Returns:
            Formatted reminder message
        """
        try:
            # Get template for reminder type
            template = self.reminder_templates.get(reminder_type, self.reminder_templates['appointment_reminder'])
            
            # Format appointment time
            if appointment.start_time:
                appointment_time = appointment.start_time.strftime("%A, %B %d at %I:%M %p")
            else:
                appointment_time = "your scheduled time"
            
            # Get patient name from tokenized storage
            patient_name = "there"  # Default fallback
            if appointment.patient and appointment.patient.name_token and db:
                try:
                    from services.crypto import decrypt_str
                    name_mapping_result = await db.execute(select(Mapping).where(
                        Mapping.token == appointment.patient.name_token,
                        Mapping.is_deleted == 'no'
                    ))
                    name_mapping = name_mapping_result.scalar_one_or_none()
                    
                    if name_mapping:
                        try:
                            patient_name = decrypt_str(name_mapping.value_nonce, name_mapping.value_ciphertext)
                        except Exception as decrypt_error:
                            self.logger.warning(
                                f"Failed to decrypt patient name for appointment {appointment.appointment_id}: {decrypt_error}",
                                LogCategory.REMINDER
                            )
                except Exception as name_error:
                    self.logger.warning(
                        f"Failed to get patient name for appointment {appointment.appointment_id}: {name_error}",
                        LogCategory.REMINDER
                    )
            
            # For now, default to English. In a real system, you'd detect patient language
            message = template['en'].format(patient_name=patient_name, appointment_time=appointment_time)
            
            return message
            
        except Exception as e:
            self.logger.error(f"Failed to generate reminder message: {e}", LogCategory.REMINDER, exception=e)
            # Fallback message
            return "Hello, this is a reminder about your upcoming appointment. Please call us if you need to reschedule. Thank you."
    
    async def _make_reminder_call(self, reminder_id: str, patient_phone: str, 
                                message: str, appointment: Appointment) -> Dict[str, Any]:
        """
        Make the actual reminder call using Azure Communication Services.
        """
        try:
            # Check rate limit for reminder calls
            if not hasattr(appointment, 'clinic_id') or not appointment.clinic_id:
                # Try to get clinic_id from patient
                if not appointment.patient or not appointment.patient.clinic_id:
                    raise CallCenterAIException(
                        f"Clinic ID not found for appointment {appointment.appointment_id}",
                        error_code=ErrorCode.RESOURCE_NOT_FOUND
                    )
                clinic_id = appointment.patient.clinic_id
            else:
                clinic_id = appointment.clinic_id
            
            # Concurrent calls are handled by admission_controller.py
            # Generate TTS audio for the message
            # For now, default to English. In a real system, you'd detect patient language
            audio_bytes = await self.tts_service.synthesize_speech(message, "en-US")
            
            if not audio_bytes:
                raise ExternalServiceUnavailableError("Failed to generate TTS audio for reminder message")
            
            # Issue 44: Make the outbound call using ACS with proper error handling
            try:
                call_result = await self.acs_service.make_outbound_call(
                    to_phone=patient_phone,
                    from_phone=self.settings.azure.communication.phone_number,
                    audio_content=audio_bytes,
                    call_context={
                        'reminder_id': reminder_id,
                        'appointment_id': appointment.appointment_id,
                        'call_type': 'reminder'
                    }
                )
                
                # Issue 44: Validate call result and handle failures gracefully
                if not call_result:
                    raise ExternalServiceUnavailableError("Call result is None")
                
                call_success = call_result.get('success', False)
                if not call_success:
                    # Issue 44: Extract error information from call result
                    error_code = call_result.get('error_code', 'unknown_error')
                    error_message = call_result.get('error_message', 'Call failed')
                    self.logger.warning(f"Reminder call failed: {error_code} - {error_message}", LogCategory.REMINDER)
                    return {
                        'status': 'failed',
                        'call_id': call_result.get('call_id'),
                        'duration_seconds': call_result.get('duration_seconds', 0),
                        'outcome': 'failed',
                        'error_code': error_code,
                        'error_message': error_message,
                        'caller_id': self.settings.azure.communication.phone_number
                    }
                
                return {
                    'status': 'completed',
                    'call_id': call_result.get('call_id'),
                    'duration_seconds': call_result.get('duration_seconds'),
                    'outcome': 'answered',
                    'caller_id': self.settings.azure.communication.phone_number
                }
            # Issue 172: Handle call failure after status update - reminder status remains 'calling'
            # This is already handled by the outer try-except which updates status on failure
            except Exception as call_error:
                # Issue 44: Handle call failures gracefully with specific error codes
                error_type = type(call_error).__name__
                if 'phone' in str(call_error).lower() or 'invalid' in str(call_error).lower():
                    error_code = 'invalid_phone_number'
                elif 'network' in str(call_error).lower() or 'connection' in str(call_error).lower():
                    error_code = 'network_error'
                elif 'rate' in str(call_error).lower() or 'limit' in str(call_error).lower():
                    error_code = 'rate_limit_exceeded'
                else:
                    error_code = 'call_failed'
                
                self.logger.error(f"Reminder call error ({error_code}): {call_error}", LogCategory.REMINDER, exception=call_error)
                raise  # Re-raise to be caught by outer exception handler
            
        except AzureCommunicationError as e:
            self.logger.error(f"ACS error making reminder call: {e.message}", LogCategory.REMINDER, exception=e)
            return {
                'status': 'failed',
                'outcome': 'failed',
                'error_code': 'acs_error',
                'error_message': e.message
            }
        except ExternalServiceUnavailableError as e:
            self.logger.error(f"TTS error for reminder call: {e.message}", LogCategory.REMINDER, exception=e)
            return {
                'status': 'failed',
                'outcome': 'failed',
                'error_code': 'tts_error',
                'error_message': e.message
            }
        except Exception as e:
            self.logger.error(f"Unexpected error making reminder call: {e}", LogCategory.REMINDER, exception=e)
            return {
                'status': 'failed',
                'outcome': 'failed',
                'error_code': 'unexpected_error',
                'error_message': str(e)
            }
    
    async def _update_usage_metrics(self, db: AsyncSession, appointment: Appointment, call_result: Dict[str, Any]):
        """
        Update clinic usage metrics for reminder calls.
        """
        try:
            # Get clinic usage record for current period
            if not appointment.patient or not appointment.patient.clinic_id:
                self.logger.warning(f"Patient or clinic_id not found for appointment {appointment.appointment_id}", LogCategory.REMINDER)
                return
            
            clinic_usage_result = await db.execute(
                select(ClinicUsage).where(
                    ClinicUsage.clinic_id == appointment.patient.clinic_id,
                    ClinicUsage.is_deleted == 'no'
                ).order_by(ClinicUsage.created_at.desc())
            )
            clinic_usage = clinic_usage_result.scalar_one_or_none()
            
            if clinic_usage:
                # Update reminder call metrics
                clinic_usage.reminder_calls_sent += 1
                
                if call_result.get('outcome') == 'answered':
                    clinic_usage.reminder_calls_answered += 1
                
                # Estimate cost (this would be more sophisticated in production)
                estimated_cost = 0.05  # $0.05 per reminder call estimate
                clinic_usage.reminder_calls_cost_usd += estimated_cost
                clinic_usage.total_cost_usd += estimated_cost
                
                try:
                    await db.commit()
                except Exception as commit_error:
                    await db.rollback()
                    self.logger.error(f"Failed to commit usage metrics update: {commit_error}", LogCategory.REMINDER, exception=commit_error)
                    # Don't raise - this is not critical for reminder execution
                
        except Exception as e:
            self.logger.error(f"Failed to update usage metrics: {e}", LogCategory.REMINDER, exception=e)
            # Don't raise - this is not critical for reminder execution
    
    async def get_due_reminders(self, db: AsyncSession, limit: int = 100) -> List[Reminder]:
        """
        Get reminders that are due for execution.
        """
        try:
            now = datetime.now(AST)
            
            reminders_result = await db.execute(
                select(Reminder).where(
                    and_(
                        Reminder.is_deleted == 'no',
                        or_(
                            and_(
                                Reminder.status == 'scheduled',
                                Reminder.scheduled_time <= now
                            ),
                            and_(
                                Reminder.status == 'failed',
                                Reminder.next_retry_time <= now,
                                Reminder.retry_count < Reminder.max_retries
                            )
                        )
                    )
                ).limit(limit)
            )
            reminders = list(reminders_result.scalars().all())
            
            return reminders
            
        except Exception as e:
            self.logger.error(f"Failed to get due reminders: {e}", LogCategory.REMINDER, exception=e)
            raise CallCenterAIException(
                f"Failed to get due reminders: {e}",
                error_code=ErrorCode.DATABASE_ERROR
            )
    
    async def cancel_reminder(self, db: AsyncSession, reminder_id: str, reason: str = "cancelled_by_user") -> bool:
        """
        Cancel a scheduled reminder.
        """
        try:
            reminder_result = await db.execute(select(Reminder).where(
                Reminder.reminder_id == reminder_id,
                Reminder.is_deleted == 'no'
            ))
            reminder = reminder_result.scalar_one_or_none()
            
            if not reminder:
                raise CallCenterAIException(
                    f"Reminder {reminder_id} not found",
                    error_code=ErrorCode.RESOURCE_NOT_FOUND
                )
            
            if reminder.status in ['completed', 'cancelled']:
                self.logger.warning(f"Reminder {reminder_id} is already {reminder.status}", LogCategory.REMINDER)
                return False
            
            reminder.status = 'cancelled'
            reminder.completed_at = datetime.now(AST)
            reminder.call_outcome = reason
            
            await db.commit()
            
            self.logger.info(f"Reminder {reminder_id} cancelled: {reason}", LogCategory.REMINDER)
            return True
            
        except Exception as e:
            await db.rollback()
            self.logger.error(f"Failed to cancel reminder {reminder_id}: {e}", LogCategory.REMINDER, exception=e)
            if isinstance(e, CallCenterAIException):
                raise
            raise CallCenterAIException(
                f"Failed to cancel reminder: {e}",
                error_code=ErrorCode.DATABASE_ERROR
            )
    
    async def _enqueue_reminder_for_retry(
        self, db: AsyncSession, reminder_id: str, patient_phone: str, 
        message: str, appointment: Appointment, retry_count: int
    ):
        """
        Add a reminder back to the queue for retry.
        
        Args:
            db: Database session
            reminder_id: Reminder ID
            patient_phone: Patient phone number
            message: Reminder message
            appointment: Appointment object
            retry_count: Current retry count
        """
        try:
            # Get clinic_id
            if not hasattr(appointment, 'clinic_id') or not appointment.clinic_id:
                clinic_id = appointment.patient.clinic_id if appointment.patient else None
            else:
                clinic_id = appointment.clinic_id
            
            if not clinic_id:
                self.logger.warning(f"Cannot enqueue reminder {reminder_id} - no clinic_id", LogCategory.REMINDER)
                return
            
            # Create queued reminder
            queued_reminder = QueuedReminder(
                reminder_id=reminder_id,
                appointment_id=appointment.appointment_id,
                patient_phone=patient_phone,
                message=message,
                clinic_id=clinic_id,
                retry_count=retry_count
            )
            
            # Add to queue
            async with self._queue_lock:
                self._reminder_queue.append(queued_reminder)
            
            self.logger.info(
                f"Reminder {reminder_id} added to queue for retry (attempt {retry_count + 1})",
                LogCategory.REMINDER,
                extra_data={
                    "reminder_id": reminder_id,
                    "retry_count": retry_count + 1,
                    "queue_size": len(self._reminder_queue)
                }
            )
            
        except Exception as e:
            self.logger.error(f"Failed to enqueue reminder {reminder_id} for retry: {e}", LogCategory.REMINDER, exception=e)
    
    async def process_reminder_queue(self, db: AsyncSession) -> Dict[str, Any]:
        """
        Process all reminders in the queue until empty or max retries reached.
        This processes all reminders for the day.
        
        Args:
            db: Database session
            
        Returns:
            Dictionary with processing statistics
        """
        if self._processing:
            self.logger.warning("Reminder queue is already being processed", LogCategory.REMINDER)
            return {"status": "already_processing", "processed": 0, "succeeded": 0, "failed": 0}
        
        self._processing = True
        processed = 0
        succeeded = 0
        failed = 0
        
        try:
            self.logger.info("Starting reminder queue processing", LogCategory.REMINDER)
            
            while True:
                # Get next reminder from queue
                async with self._queue_lock:
                    if not self._reminder_queue:
                        break
                    queued_reminder = self._reminder_queue.popleft()
                
                try:
                    processed += 1
                    
                    # Execute the reminder
                    result = await self.execute_reminder(db, queued_reminder.reminder_id)
                    
                    if result.get('status') == 'completed' and result.get('outcome') == 'answered':
                        succeeded += 1
                    else:
                        failed += 1
                        # If not max retries, it's already back in queue
                    
                except Exception as e:
                    failed += 1
                    self.logger.error(
                        f"Failed to process queued reminder {queued_reminder.reminder_id}",
                        LogCategory.REMINDER,
                        exception=e
                    )
                    # If retries not exhausted, it will be re-queued by execute_reminder
                
                # Small delay between calls to avoid overwhelming the system
                await asyncio.sleep(1)
            
            self.logger.info(
                f"Reminder queue processing completed",
                LogCategory.REMINDER,
                extra_data={
                    "processed": processed,
                    "succeeded": succeeded,
                    "failed": failed,
                    "remaining_in_queue": len(self._reminder_queue)
                }
            )
            
            return {
                "status": "completed",
                "processed": processed,
                "succeeded": succeeded,
                "failed": failed,
                "remaining_in_queue": len(self._reminder_queue)
            }
            
        finally:
            self._processing = False
    
    async def load_due_reminders_into_queue(self, db: AsyncSession, limit: int = 100) -> int:
        """
        Load due reminders from database into the processing queue.
        
        Args:
            db: Database session
            limit: Maximum number of reminders to load
            
        Returns:
            Number of reminders loaded into queue
        """
        try:
            due_reminders = await self.get_due_reminders(db, limit=limit)
            loaded = 0
            
            for reminder in due_reminders:
                try:
                    # Get appointment and patient data
                    appointment_result = await db.execute(
                        select(Appointment).join(Patient).where(
                            Appointment.appointment_id == reminder.appointment_id,
                            Appointment.is_deleted == 'no'
                        )
                    )
                    appointment = appointment_result.scalar_one_or_none()
                    
                    if not appointment or not appointment.patient or not appointment.patient.phone_token:
                        continue
                    
                    # Get phone number
                    phone_mapping_result = await db.execute(select(Mapping).where(
                        Mapping.token == appointment.patient.phone_token,
                        Mapping.is_deleted == 'no'
                    ))
                    phone_mapping = phone_mapping_result.scalar_one_or_none()
                    
                    if not phone_mapping:
                        continue
                    
                    # Decrypt phone number
                    from services.crypto import decrypt_str
                    try:
                        patient_phone = decrypt_str(phone_mapping.value_nonce, phone_mapping.value_ciphertext)
                    except Exception as decrypt_error:
                        self.logger.warning(
                            f"Failed to decrypt phone number for reminder {reminder.reminder_id}: {decrypt_error}",
                            LogCategory.REMINDER
                        )
                        continue
                    
                    if not patient_phone:
                        continue
                    
                    # Generate message
                    message = await self._generate_reminder_message(appointment, reminder.reminder_type, db)
                    
                    # Get clinic_id
                    clinic_id = appointment.clinic_id if hasattr(appointment, 'clinic_id') and appointment.clinic_id else appointment.patient.clinic_id
                    
                    if not clinic_id:
                        continue
                    
                    # Create queued reminder
                    queued_reminder = QueuedReminder(
                        reminder_id=reminder.reminder_id,
                        appointment_id=reminder.appointment_id,
                        patient_phone=patient_phone,
                        message=message,
                        clinic_id=clinic_id,
                        retry_count=reminder.retry_count
                    )
                    
                    # Add to queue
                    async with self._queue_lock:
                        self._reminder_queue.append(queued_reminder)
                    
                    loaded += 1
                    
                except Exception as e:
                    self.logger.error(
                        f"Failed to load reminder {reminder.reminder_id} into queue: {e}",
                        LogCategory.REMINDER,
                        exception=e
                    )
            
            self.logger.info(
                f"Loaded {loaded} reminders into queue",
                LogCategory.REMINDER,
                extra_data={"loaded": loaded, "queue_size": len(self._reminder_queue)}
            )
            
            return loaded
            
        except Exception as e:
            self.logger.error(f"Failed to load due reminders into queue: {e}", LogCategory.REMINDER, exception=e)
            return 0


# Global instance for dependency injection
_reminder_service: Optional[ReminderService] = None


def get_reminder_service() -> ReminderService:
    """Get the global reminder service instance."""
    global _reminder_service
    if _reminder_service is None:
        _reminder_service = ReminderService()
    return _reminder_service
