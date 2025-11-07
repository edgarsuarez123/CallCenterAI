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

# Atlantic Standard Time (UTC-4)
AST = timezone(timedelta(hours=-4))
from typing import Dict, List, Optional, Any, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func

from models.models import (
    Reminder, ReminderLog, Appointment, Patient, Clinic, 
    Mapping, ClinicUsage
)
from services.azure_communication_service import get_azure_communication_service, AzureCommunicationService
from services.azure_speech_tts import get_text_to_speech_service, TextToSpeechService
from services.bilingual_manager import get_bilingual_manager, BilingualManager
from services.crypto import make_ulid_token
from services.structured_logging import get_logger, LogCategory, log_performance
from services.configuration import get_settings
from services.exceptions import (
    AzureCommunicationError, ExternalServiceUnavailableError,
    ValidationError, CallCenterAIException, ErrorCode
)


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
        self.bilingual_manager: BilingualManager = get_bilingual_manager()
        
        # Concurrency control
        self._call_semaphore = asyncio.Semaphore(10)  # Max 10 concurrent reminder calls
        
        # Reminder call templates
        self.reminder_templates = {
            'appointment_reminder': {
                'en': "Hello, this is a reminder about your upcoming appointment. Your appointment is scheduled for {appointment_time}. Please call us if you need to reschedule. Thank you.",
                'es': "Hola, este es un recordatorio sobre su próxima cita. Su cita está programada para {appointment_time}. Por favor llámenos si necesita reprogramar. Gracias."
            },
            'follow_up': {
                'en': "Hello, this is a follow-up call regarding your recent appointment. How are you feeling? Please call us if you have any questions. Thank you.",
                'es': "Hola, esta es una llamada de seguimiento sobre su cita reciente. ¿Cómo se siente? Por favor llámenos si tiene alguna pregunta. Gracias."
            },
            'cancellation_reminder': {
                'en': "Hello, this is a reminder that your appointment has been cancelled. Please call us to reschedule if needed. Thank you.",
                'es': "Hola, este es un recordatorio de que su cita ha sido cancelada. Por favor llámenos para reprogramar si es necesario. Gracias."
            }
        }
        
        self.logger.info("ReminderService initialized.", LogCategory.REMINDER)
    
    @log_performance("reminder_scheduling")
    async def schedule_reminder(self, db: Session, appointment_id: str, 
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
            appointment = db.query(Appointment).filter(
                Appointment.appointment_id == appointment_id,
                Appointment.is_deleted == 'no'
            ).first()
            
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
            existing_reminder = db.query(Reminder).filter(
                Reminder.appointment_id == appointment_id,
                Reminder.is_deleted == 'no',
                Reminder.status.in_(['scheduled', 'pending'])
            ).first()
            if existing_reminder:
                self.logger.info(f"Reminder already exists for appointment {appointment_id}, skipping duplicate", LogCategory.REMINDER)
                raise CallCenterAIException(
                    "A reminder already exists for this appointment",
                    error_code=ErrorCode.VALIDATION_ERROR
                )
            
            # Get clinic settings
            clinic = db.query(Clinic).join(Patient).filter(
                Patient.patient_id == appointment.patient_id,
                Clinic.is_deleted == 'no'
            ).first()
            
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
            
            # Calculate scheduled time
            if custom_scheduled_time:
                scheduled_time = custom_scheduled_time
            else:
                # Use clinic settings to calculate reminder time
                if not appointment.start_time:
                    raise ValidationError("Appointment start_time is required for reminder scheduling")
                
                now = datetime.now(AST)
                scheduled_time = appointment.start_time - timedelta(hours=clinic.reminder_hours_before)
            
            # Check if reminder is too far in the past
            if scheduled_time < now:  # Use captured 'now'
                self.logger.warning(f"Reminder scheduled time {scheduled_time} is in the past for appointment {appointment_id}", LogCategory.REMINDER)
                raise ValidationError("Reminder scheduled time cannot be in the past")
            
            # Create reminder record
            reminder_id = make_ulid_token('REMINDER')
            reminder = Reminder(
                reminder_id=reminder_id,
                appointment_id=appointment_id,
                scheduled_time=scheduled_time,
                reminder_type=reminder_type,
                status='scheduled',
                max_retries=3  # Default retry count
            )
            
            db.add(reminder)
            try:
                db.commit()
                db.refresh(reminder)
            except Exception as commit_error:
                db.rollback()
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
            db.rollback()
            self.logger.error(f"Failed to schedule reminder for appointment {appointment_id}: {e}", LogCategory.REMINDER, exception=e)
            if isinstance(e, (CallCenterAIException, ValidationError, CallCenterAIException)):
                raise
            raise CallCenterAIException(
                f"Failed to schedule reminder: {e}",
                error_code=ErrorCode.DATABASE_ERROR
            )
    
    @log_performance("reminder_execution")
    async def execute_reminder(self, db: Session, reminder_id: str) -> Dict[str, Any]:
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
            reminder = db.query(Reminder).filter(
                Reminder.reminder_id == reminder_id,
                Reminder.is_deleted == 'no'
            ).first()
            
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
            appointment = db.query(Appointment).join(Patient).filter(
                Appointment.appointment_id == reminder.appointment_id,
                Appointment.is_deleted == 'no'
            ).first()
            
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
                    db.commit()
                except Exception as commit_error:
                    db.rollback()
                    self.logger.error(f"Failed to update reminder status: {commit_error}", LogCategory.REMINDER)
                raise CallCenterAIException(
                    "Cannot execute reminder for cancelled appointment",
                    error_code=ErrorCode.VALIDATION_ERROR
                )
            
            # Issue 73: Check and update reminder status atomically to prevent duplicate execution
            # Use SELECT FOR UPDATE to lock the reminder row
            from sqlalchemy import select
            locked_reminder = db.execute(
                select(Reminder).where(
                    Reminder.reminder_id == reminder_id,
                    Reminder.status.in_(['scheduled', 'failed'])
                ).with_for_update()
            ).scalar_one_or_none()
            
            if not locked_reminder or locked_reminder.status not in ['scheduled', 'failed']:
                raise CallCenterAIException(
                    f"Reminder {reminder_id} is not in a valid state for execution (current: {locked_reminder.status if locked_reminder else 'not found'})",
                    error_code=ErrorCode.VALIDATION_ERROR
                )
            
            # Issue 156: Update status to 'executing' to prevent duplicate execution
            # Keep lock held during execution to prevent concurrent execution attempts
            locked_reminder.status = 'executing'
            locked_reminder.started_at = datetime.now(AST)
            db.commit()
            db.refresh(locked_reminder)
            reminder = locked_reminder  # Use the locked reminder for the rest of the method
            
            # Issue 156: Note: Lock is released after commit, but status is 'executing' which prevents other workers
            # from picking up the same reminder. If execution takes a long time, periodic status checks
            # would be needed to prevent duplicate execution.
            
            # Get patient's phone number
            if not appointment.patient or not appointment.patient.caller_phone_token:
                raise CallCenterAIException(
                    f"Patient phone token not found for appointment {appointment.appointment_id}",
                    error_code=ErrorCode.RESOURCE_NOT_FOUND
                )
            
            # Issue 194: Re-query patient phone number when executing reminder to handle phone number changes
            phone_mapping = db.query(Mapping).filter(
                Mapping.token == appointment.patient.caller_phone_token,
                Mapping.is_deleted == 'no'
            ).first()
            
            if not phone_mapping:
                # Issue 194: Try to get phone number from patient record if mapping not found
                # This handles cases where phone number was updated but mapping wasn't refreshed
                self.logger.warning(f"Phone mapping not found for patient {appointment.patient_id}, attempting to re-query")
                # Re-query patient to get latest phone token
                db.refresh(appointment.patient)
                if appointment.patient.caller_phone_token:
                    phone_mapping = db.query(Mapping).filter(
                        Mapping.token == appointment.patient.caller_phone_token,
                        Mapping.is_deleted == 'no'
                    ).first()
                
                if not phone_mapping:
                    raise CallCenterAIException(
                        f"Phone number not found for patient {appointment.patient_id}",
                        error_code=ErrorCode.RESOURCE_NOT_FOUND
                    )
            
            if not phone_mapping.actual_value:
                raise CallCenterAIException(
                    f"Phone number value is empty for patient {appointment.patient_id}",
                    error_code=ErrorCode.RESOURCE_NOT_FOUND
                )
            
            # Issue 194: Use the most recent phone number from mapping
            patient_phone = phone_mapping.actual_value
            
            # Update reminder status
            reminder.status = 'calling'
            reminder.retry_count += 1
            try:
                db.commit()
            except Exception as commit_error:
                db.rollback()
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
                db.commit()
            except Exception as commit_error:
                db.rollback()
                self.logger.error(f"Failed to commit reminder log: {commit_error}", LogCategory.REMINDER, exception=commit_error)
                raise
            
            # Generate reminder message
            message = await self._generate_reminder_message(appointment, reminder.reminder_type)
            
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
            if call_result['status'] == 'completed':
                reminder.status = 'completed'
                reminder.completed_at = datetime.now(AST)
                reminder.call_duration_seconds = call_result.get('duration_seconds')
                reminder.call_outcome = call_result.get('outcome')
                reminder.reminder_call_id = call_result.get('call_id')
            else:
                # Determine if we should retry
                if reminder.retry_count < reminder.max_retries:
                    # Schedule retry
                    retry_delay = timedelta(minutes=30)  # Default retry delay
                    reminder.next_retry_time = datetime.now(AST) + retry_delay
                    reminder.status = 'failed'
                else:
                    # Max retries reached
                    reminder.status = 'failed'
                    reminder.completed_at = datetime.now(AST)
                    reminder.call_outcome = call_result.get('outcome', 'max_retries_exceeded')
            
            try:
                db.commit()
            except Exception as commit_error:
                db.rollback()
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
            db.rollback()
            self.logger.error(f"Failed to execute reminder {reminder_id}: {e}", LogCategory.REMINDER, exception=e)
            if isinstance(e, (CallCenterAIException, CallCenterAIException)):
                raise
            raise CallCenterAIException(
                f"Failed to execute reminder: {e}",
                error_code=ErrorCode.DATABASE_ERROR
            )
    
    async def _generate_reminder_message(self, appointment: Appointment, reminder_type: str) -> str:
        """
        Generate the reminder message text based on appointment and reminder type.
        """
        try:
            # Get template for reminder type
            template = self.reminder_templates.get(reminder_type, self.reminder_templates['appointment_reminder'])
            
            # Format appointment time
            if appointment.start_time:
                appointment_time = appointment.start_time.strftime("%A, %B %d at %I:%M %p")
            else:
                appointment_time = "your scheduled time"
            
            # For now, default to English. In a real system, you'd detect patient language
            message = template['en'].format(appointment_time=appointment_time)
            
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
            
            from services.rate_limiter import get_rate_limiter
            rate_limiter = get_rate_limiter()
            if not await rate_limiter.check_reminder_limit(clinic_id):
                self.logger.warning(f"Reminder rate limit exceeded for clinic {clinic_id}")
                # Reschedule for later
                await self._reschedule_reminder(clinic_id, reminder_id, delay_minutes=10)
                return {
                    'status': 'rescheduled',
                    'reason': 'rate_limit_exceeded',
                    'rescheduled_for': datetime.now(AST) + timedelta(minutes=10)
                }
            
            # Limit concurrency
            async with self._call_semaphore:
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
    
    async def _update_usage_metrics(self, db: Session, appointment: Appointment, call_result: Dict[str, Any]):
        """
        Update clinic usage metrics for reminder calls.
        """
        try:
            # Get clinic usage record for current period
            if not appointment.patient or not appointment.patient.clinic_id:
                self.logger.warning(f"Patient or clinic_id not found for appointment {appointment.appointment_id}", LogCategory.REMINDER)
                return
            
            clinic_usage = db.query(ClinicUsage).filter(
                ClinicUsage.clinic_id == appointment.patient.clinic_id,
                ClinicUsage.is_deleted == 'no'
            ).order_by(ClinicUsage.created_at.desc()).first()
            
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
                    db.commit()
                except Exception as commit_error:
                    db.rollback()
                    self.logger.error(f"Failed to commit usage metrics update: {commit_error}", LogCategory.REMINDER, exception=commit_error)
                    # Don't raise - this is not critical for reminder execution
                
        except Exception as e:
            self.logger.error(f"Failed to update usage metrics: {e}", LogCategory.REMINDER, exception=e)
            # Don't raise - this is not critical for reminder execution
    
    async def get_due_reminders(self, db: Session, limit: int = 100) -> List[Reminder]:
        """
        Get reminders that are due for execution.
        """
        try:
            now = datetime.now(AST)
            
            reminders = db.query(Reminder).filter(
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
            ).limit(limit).all()
            
            return reminders
            
        except Exception as e:
            self.logger.error(f"Failed to get due reminders: {e}", LogCategory.REMINDER, exception=e)
            raise CallCenterAIException(
                f"Failed to get due reminders: {e}",
                error_code=ErrorCode.DATABASE_ERROR
            )
    
    async def cancel_reminder(self, db: Session, reminder_id: str, reason: str = "cancelled_by_user") -> bool:
        """
        Cancel a scheduled reminder.
        """
        try:
            reminder = db.query(Reminder).filter(
                Reminder.reminder_id == reminder_id,
                Reminder.is_deleted == 'no'
            ).first()
            
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
            
            db.commit()
            
            self.logger.info(f"Reminder {reminder_id} cancelled: {reason}", LogCategory.REMINDER)
            return True
            
        except Exception as e:
            db.rollback()
            self.logger.error(f"Failed to cancel reminder {reminder_id}: {e}", LogCategory.REMINDER, exception=e)
            if isinstance(e, CallCenterAIException):
                raise
            raise CallCenterAIException(
                f"Failed to cancel reminder: {e}",
                error_code=ErrorCode.DATABASE_ERROR
            )
    
    async def _reschedule_reminder(self, clinic_id: str, reminder_id: str, delay_minutes: int = 10):
        """
        Reschedule a reminder call for later due to rate limiting.
        
        Args:
            clinic_id: Clinic ID
            reminder_id: Reminder ID to reschedule
            delay_minutes: Minutes to delay the reminder
        """
        try:
            # In a real implementation, you would:
            # 1. Update the reminder's scheduled_time in the database
            # 2. Add it back to the scheduler queue
            # 3. Log the rescheduling event
            
            self.logger.info(
                f"Rescheduling reminder {reminder_id} for clinic {clinic_id} due to rate limiting",
                LogCategory.REMINDER,
                extra_data={
                    "reminder_id": reminder_id,
                    "clinic_id": clinic_id,
                    "delay_minutes": delay_minutes
                }
            )
            
            # For now, just log the rescheduling
            # TODO: Implement actual rescheduling logic
            
        except Exception as e:
            self.logger.error(f"Failed to reschedule reminder {reminder_id}: {e}", LogCategory.REMINDER, exception=e)


# Global instance for dependency injection
_reminder_service: Optional[ReminderService] = None


def get_reminder_service() -> ReminderService:
    """Get the global reminder service instance."""
    global _reminder_service
    if _reminder_service is None:
        _reminder_service = ReminderService()
    return _reminder_service
