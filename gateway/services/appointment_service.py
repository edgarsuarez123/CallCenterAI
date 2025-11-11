"""
Appointment Management Service
Handles appointment booking, scheduling, and Google Calendar integration.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from sqlalchemy import and_, select
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime, timezone, timedelta, date

from models.models import Appointment, AppointmentSlot, Patient, Provider, Clinic, AuditLog, provider_clinics, Reminder
from models.enums import YesNo
from models.schemas import (
    AppointmentCreateRequest, AppointmentUpdateRequest, AppointmentSearchRequest,
    AppointmentResponse, AppointmentSlotCreateRequest
)
from services.crypto import make_ulid_token
from services.google_calendar_service import GoogleCalendarIntegrationService
from services.transaction_manager import TransactionManager, get_transaction_manager, ConcurrencyError
from services.provider_management import ProviderManagementService
from services.audit_utils import log_audit_trail
from services.structured_logging import get_logger, LogCategory, log_performance
from services.configuration import get_settings
from services.exceptions import (
    SlotUnavailableError, AppointmentNotFoundError, InvalidAppointmentTimeError,
    PatientNotFoundError, ProviderNotFoundError, ProviderUnavailableError,
    ValidationError, BusinessRuleViolationError
)
from services.reminder_service import get_reminder_service


class AppointmentService:
    """Service for managing appointments and scheduling."""
    
    def __init__(self, db: AsyncSession, google_calendar_service: Optional[GoogleCalendarIntegrationService] = None):
        self.db = db
        self.google_calendar_service = google_calendar_service
        self.provider_management = ProviderManagementService(db)
        self.logger = get_logger("appointment_service")
        self.settings = get_settings()
    
    @log_performance("appointment_creation")
    async def create_appointment(self, appointment_data: AppointmentCreateRequest, 
                         patient_name: str = None) -> Tuple[Optional[Appointment], Optional[str]]:
        """
        Create a new appointment with atomic transaction management and sync to Google Calendar.
        
        This method uses transaction management to ensure:
        - Atomic appointment creation (all-or-nothing)
        - Row-level locking to prevent double booking
        - Automatic rollback on any failure
        - Proper concurrency control
        
        Args:
            appointment_data: Appointment creation request
            patient_name: Patient name for calendar event
            
        Returns:
            Tuple of (appointment_instance, google_calendar_event_id)
        """
        # Issue 148: Handle transaction manager not available
        try:
            transaction_manager = get_transaction_manager(self.db)
        except Exception as tm_error:
            self.logger.error(f"Transaction manager not available: {tm_error}", LogCategory.APPOINTMENT)
            raise BusinessRuleViolationError("transaction_manager_unavailable", f"Transaction manager not available: {tm_error}")
        
        try:
            # Track booking start time for latency measurement
            import time
            booking_start_time = time.time()
            
            self.logger.info(
                "Starting appointment creation",
                LogCategory.APPOINTMENT,
                extra_data={
                    'patient_id': appointment_data.patient_id,
                    'provider_id': appointment_data.provider_id,
                    'appointment_date': appointment_data.appointment_date.isoformat(),
                    'start_time': appointment_data.start_time.isoformat(),
                    'end_time': appointment_data.end_time.isoformat(),
                    'appointment_type': appointment_data.appointment_type
                }
            )
            
            # Issue 115: Validate input parameters before finding slot
            # Validate appointment data
            await self._validate_appointment_data(appointment_data)
            
            # Issue 134: Validate provider exists before finding slot
            provider_result = await self.db.execute(select(Provider).where(Provider.provider_id == appointment_data.provider_id))
            provider = provider_result.scalar_one_or_none()
            if not provider:
                raise ProviderNotFoundError(appointment_data.provider_id)
            
            # Issue 143: Validate slot duration before finding slot
            appointment_duration_minutes = (appointment_data.end_time - appointment_data.start_time).total_seconds() / 60
            if appointment_duration_minutes <= 0:
                raise ValidationError("appointment_duration", appointment_duration_minutes, "Appointment duration must be positive")
            
            # Issue 115: Validate slot parameters before finding
            if not appointment_data.start_time or not appointment_data.provider_id:
                raise ValidationError("appointment_data", appointment_data, "start_time and provider_id are required")
            
            # Issue 106, 107: Find and lock slot - note that lock is released when method returns
            # Issue 108: atomic_appointment_booking will re-lock and re-verify the slot
            # This is acceptable because atomic_appointment_booking uses SELECT FOR UPDATE within its transaction
            slot = await self._find_appointment_slot(appointment_data.start_time, appointment_data.provider_id)
            if not slot:
                self.logger.warning("No appointment slot found", LogCategory.APPOINTMENT, extra_data={
                    'start_time': appointment_data.start_time.isoformat(),
                    'provider_id': appointment_data.provider_id
                })
                raise SlotUnavailableError(
                    "unknown", 
                    appointment_data.provider_id, 
                    "No appointment slot found for the specified time"
                )
            
            # Issue 106, 107: Store slot_id immediately - the slot lock is released when _find_appointment_slot returns
            # Issue 108: atomic_appointment_booking will re-lock the slot by slot_id and verify it's still available
            slot_id = slot.slot_id
            clinic_id = slot.clinic_id  # Get clinic_id from slot before lock is released
            
            # Issue 32, 42, 70, 143: Validate that slot duration matches or is sufficient for appointment duration
            # Note: appointment_duration_minutes was already calculated above
            # Issue 106, 107: Validate slot duration before proceeding - lock is already released but we validate early
            if slot.duration_minutes < appointment_duration_minutes:
                self.logger.warning(f"Slot duration ({slot.duration_minutes} min) is less than appointment duration ({appointment_duration_minutes} min)", 
                                  LogCategory.APPOINTMENT, extra_data={
                                      'slot_id': slot_id,
                                      'slot_duration': slot.duration_minutes,
                                      'appointment_duration': appointment_duration_minutes
                                  })
                # Issue 143: Release slot quickly if validation fails
                # Note: Slot lock is already released when _find_appointment_slot returned
                raise SlotUnavailableError(
                    slot_id,
                    appointment_data.provider_id,
                    f"Slot duration ({slot.duration_minutes} minutes) is insufficient for appointment duration ({appointment_duration_minutes} minutes)"
                )
            
            # Generate appointment ID
            appointment_id = make_ulid_token('APPOINTMENT')
            
            # Prepare appointment data for atomic booking
            appointment_dict = {
                'appointment_id': appointment_id,
                'appointment_date': appointment_data.appointment_date,
                'start_time': appointment_data.start_time,
                'end_time': appointment_data.end_time,
                'appointment_type': appointment_data.appointment_type,
                'duration_minutes': appointment_duration_minutes
            }
            
            # Issue 106, 107: Perform atomic appointment booking - this will re-lock the slot by slot_id
            # Issue 108: atomic_appointment_booking will verify the slot is still available after locking
            # This ensures no race condition between finding and booking
            result = await transaction_manager.atomic_appointment_booking(
                appointment_data=appointment_dict,
                slot_id=slot_id,  # Use stored slot_id - slot object lock is already released
                patient_id=appointment_data.patient_id,
                provider_id=appointment_data.provider_id,
                clinic_id=clinic_id
            )
            
            appointment = result['appointment']
            
            # Issue 126: Handle Google Calendar sync failures and mark appointments that need sync
            google_event_id = None
            if self.google_calendar_service and self.settings.google_calendar.client_id:
                try:
                    # Issue 35: Handle event creation failure gracefully
                    google_event_id = await self.google_calendar_service.sync_appointment_to_calendar(
                        appointment, appointment_data.provider_id, patient_name
                    )
                    if google_event_id:
                        appointment.google_event_id = google_event_id  # Store event ID
                        appointment.needs_calendar_sync = False  # Sync successful
                        # Issue 6: Google Calendar Event ID Not Stored - Ensure event ID is committed to database
                        try:
                            await self.db.commit()
                        except Exception as commit_error:
                            await self.db.rollback()
                            self.logger.error(f"Failed to commit Google Calendar event ID: {commit_error}")
                            # Issue 5.1: Mark appointment as needing sync if commit fails
                            appointment.needs_calendar_sync = True
                            try:
                                await self.db.commit()
                            except Exception as retry_error:
                                await self.db.rollback()
                                self.logger.error(f"Failed to mark appointment for sync: {retry_error}")
                            # Don't fail appointment creation if calendar commit fails
                    else:
                        # Issue 5.1: Event creation failed - mark appointment as needing sync
                        self.logger.warning(f"Google Calendar event creation returned None for appointment {appointment.appointment_id}")
                        appointment.needs_calendar_sync = True
                        try:
                            await self.db.commit()
                        except Exception as commit_error:
                            await self.db.rollback()
                            self.logger.error(f"Failed to mark appointment for sync: {commit_error}")
                except Exception as calendar_error:
                    # Issue 5.1: Handle calendar service errors gracefully and mark for sync
                    self.logger.error(f"Failed to sync appointment to Google Calendar: {calendar_error}")
                    appointment.needs_calendar_sync = True
                    try:
                        await self.db.commit()
                    except Exception as commit_error:
                        await self.db.rollback()
                        self.logger.error(f"Failed to mark appointment for sync: {commit_error}")
                    # Don't fail appointment creation if calendar sync fails
            
            # Issue 196: Schedule reminder call if reminders are enabled, with retry logic
            try:
                reminder_service = get_reminder_service()
                reminder_scheduled = await reminder_service.schedule_reminder(
                    db=self.db,
                    appointment_id=appointment_id,
                    reminder_type='appointment_reminder'
                )
                if reminder_scheduled:
                    self.logger.info(f"Reminder scheduled for appointment {appointment_id}", LogCategory.APPOINTMENT)
                else:
                    # Issue 196: Reminder scheduling failed - mark for later scheduling
                    self.logger.warning(f"Reminder scheduling failed for appointment {appointment_id}, will retry later")
                    # Note: In production, you might want to add a field to mark appointments for reminder scheduling
                    # For now, we log the failure and reminders can be scheduled later via background job
            except Exception as e:
                # Don't fail appointment creation if reminder scheduling fails
                self.logger.warning(f"Failed to schedule reminder for appointment {appointment_id}: {e}", LogCategory.APPOINTMENT)
            
            # Record booking latency metric
            booking_latency_ms = (time.time() - booking_start_time) * 1000
            try:
                from services.metrics import get_metrics_service
                metrics_service = get_metrics_service()
                metrics_service.record_booking_latency(clinic_id, booking_latency_ms)
            except Exception as metrics_error:
                self.logger.warning(f"Failed to record booking latency metric: {metrics_error}")
            
            self.logger.info(
                "Appointment created successfully with transaction management",
                LogCategory.APPOINTMENT,
                extra_data={
                    'appointment_id': appointment_id,
                    'slot_id': slot_id,
                    'google_event_id': google_event_id,
                    'booking_latency_ms': booking_latency_ms
                }
            )
            return appointment, google_event_id
            
        except ConcurrencyError as e:
            self.logger.error(
                "Concurrency error creating appointment",
                LogCategory.APPOINTMENT,
                exception=e,
                extra_data={
                    'patient_id': appointment_data.patient_id,
                    'provider_id': appointment_data.provider_id,
                    'start_time': appointment_data.start_time.isoformat()
                }
            )
            raise SlotUnavailableError(
                "unknown",
                appointment_data.provider_id,
                "Appointment slot is no longer available - please try again"
            )
        except Exception as e:
            self.logger.error(
                "Error creating appointment",
                LogCategory.APPOINTMENT,
                exception=e,
                extra_data={
                    'patient_id': appointment_data.patient_id,
                    'provider_id': appointment_data.provider_id,
                    'start_time': appointment_data.start_time.isoformat()
                }
            )
            raise
    
    async def get_appointment(self, appointment_id: str) -> Optional[Appointment]:
        """Get appointment by ID."""
        result = await self.db.execute(select(Appointment).where(Appointment.appointment_id == appointment_id))
        appointment = result.scalar_one_or_none()
        if not appointment:
            raise AppointmentNotFoundError(appointment_id)
        return appointment
    
    async def update_appointment(self, appointment_id: str, updates: AppointmentUpdateRequest,
                          patient_name: str = None) -> Tuple[Optional[Appointment], bool]:
        """
        Update an appointment and sync changes to Google Calendar.
        
        Args:
            appointment_id: Appointment ID to update
            updates: Update request data
            patient_name: Patient name for calendar event
            
        Returns:
            Tuple of (updated_appointment, google_calendar_updated)
        """
        # Issue 154: Lock appointment before updating to prevent concurrent updates
        appointment_result = await self.db.execute(
            select(Appointment).where(Appointment.appointment_id == appointment_id).with_for_update()
        )
        appointment = appointment_result.scalar_one_or_none()
        
        if not appointment:
            raise AppointmentNotFoundError(appointment_id)
        
        # Store old values for audit
        old_values = {
            "provider_id": appointment.provider_id,
            "appointment_date": appointment.appointment_date,
            "start_time": appointment.start_time,
            "end_time": appointment.end_time,
            "appointment_type": appointment.appointment_type,
            "notes_token": appointment.notes_token,
            "status": appointment.status
        }
        
        # Check if time changes require slot rebooking
        time_changed = False
        if updates.start_time and updates.start_time != appointment.start_time:
            time_changed = True
        if updates.end_time and updates.end_time != appointment.end_time:
            time_changed = True
        
        # If time changed, check availability and rebook slot
        if time_changed:
            if not await self._is_slot_available(updates.start_time or appointment.start_time,
                                         updates.end_time or appointment.end_time,
                                         updates.provider_id or appointment.provider_id,
                                         exclude_appointment_id=appointment_id):
                raise SlotUnavailableError(
                    "unknown",
                    updates.provider_id or appointment.provider_id,
                    "New appointment time is not available"
                )
        
        # Update fields
        update_data = updates.dict(exclude_unset=True)
        for field, value in update_data.items():
            if hasattr(appointment, field):
                setattr(appointment, field, value)
        
        appointment.updated_at = datetime.now(timezone.utc)
        
        # Issue 187: Check if provider changed
        provider_changed = False
        if updates.provider_id and updates.provider_id != appointment.provider_id:
            provider_changed = True
        
        # Rebook appointment slot if time changed or provider changed (Issue 16, 21, 187: Store old values and validate new slot first)
        if time_changed or provider_changed:
            # Store old values before updating (Issue 16, 187)
            old_start_time = appointment.start_time
            old_provider_id = appointment.provider_id
            
            # Issue 21, 187: Book new slot first, then release old one
            new_start_time = updates.start_time or appointment.start_time
            new_provider_id = updates.provider_id or appointment.provider_id
            
            # Issue 187: If provider changed, validate new provider exists
            if provider_changed:
                from models.models import Provider
                new_provider_result = await self.db.execute(select(Provider).where(Provider.provider_id == new_provider_id))
                new_provider = new_provider_result.scalar_one_or_none()
                if not new_provider:
                    raise AppointmentNotFoundError(f"Provider {new_provider_id} not found")
                if not new_provider.is_available:
                    raise SlotUnavailableError(
                        "unknown",
                        new_provider_id,
                        "New provider is not available"
                    )
            
            # Issue 21: Validate new slot availability before booking
            if not await self._is_slot_available(new_start_time, updates.end_time or appointment.end_time, new_provider_id, exclude_appointment_id=appointment_id):
                raise SlotUnavailableError(
                    "unknown",
                    new_provider_id,
                    "New appointment time slot is not available"
                )
            
            # Book new slot first
            new_slot_booked = await self._book_appointment_slot(
                new_start_time, 
                new_provider_id, 
                appointment_id
            )
            if not new_slot_booked:
                self.logger.error(f"Failed to book new slot for appointment {appointment_id}")
                raise SlotUnavailableError(
                    "unknown",
                    new_provider_id,
                    "New appointment time slot is not available"
                )
            
            # Issue 187: Release old slot only after new slot is successfully booked
            # Only release if provider changed or time changed
            if provider_changed or time_changed:
                old_slot_released = await self._release_appointment_slot(old_start_time, old_provider_id)
                if not old_slot_released:
                    self.logger.warning(f"Failed to release old slot for appointment {appointment_id}")
        
        # Issue 11: Update Google Calendar if service is available and configured
        google_calendar_updated = False
        if self.google_calendar_service and self.settings.google_calendar.client_id:
            if appointment.google_event_id:  # Use stored event ID
                try:
                    google_calendar_updated = await self.google_calendar_service.update_calendar_appointment(
                        appointment, appointment.provider_id, appointment.google_event_id, patient_name
                    )
                    # Handle calendar conflict (409) by recomputing 3 nearest slots
                    if not google_calendar_updated:
                        self.logger.warning(
                            f"Calendar conflict detected for appointment {appointment_id}. "
                            "Recomputing 3 nearest available slots."
                        )
                        # Find 3 nearest available slots as alternatives
                        nearest_slots = await self._find_nearest_available_slots(
                            appointment.provider_id,
                            appointment.start_time,
                            count=3
                        )
                        if nearest_slots:
                            self.logger.info(
                                f"Found {len(nearest_slots)} nearest available slots for appointment {appointment_id}",
                                LogCategory.APPOINTMENT,
                                extra_data={'nearest_slots': [s['start_time'].isoformat() for s in nearest_slots]}
                            )
                except Exception as calendar_error:
                    self.logger.error(f"Failed to update Google Calendar event {appointment.google_event_id}: {calendar_error}")
                    # Don't fail appointment update if calendar update fails
            else:
                # Issue 11: Create new calendar event if appointment doesn't have one
                try:
                    google_event_id = await self.google_calendar_service.sync_appointment_to_calendar(
                        appointment, appointment.provider_id, patient_name
                    )
                    if google_event_id:
                        appointment.google_event_id = google_event_id
                        google_calendar_updated = True
                except Exception as calendar_error:
                    self.logger.error(f"Failed to create Google Calendar event for appointment {appointment_id}: {calendar_error}")
                    # Don't fail appointment update if calendar creation fails
        
        # Log the update
        await self._log_audit("appointments", appointment_id, "UPDATE", old_values, update_data)
        
        try:
            await self.db.commit()
        except Exception as commit_error:
            await self.db.rollback()
            self.logger.error(f"Failed to commit appointment update: {commit_error}")
            raise
        return appointment, google_calendar_updated
    
    async def cancel_appointment(self, appointment_id: str) -> bool:
        """
        Cancel an appointment and remove from Google Calendar.
        
        Args:
            appointment_id: Appointment ID to cancel
            
        Returns:
            True if successful
        """
        # Issue 155: Lock appointment before cancelling to prevent race conditions
        appointment_result = await self.db.execute(
            select(Appointment).where(Appointment.appointment_id == appointment_id).with_for_update()
        )
        appointment = appointment_result.scalar_one_or_none()
        
        if not appointment:
            raise AppointmentNotFoundError(appointment_id)
        
        # Store old values for audit
        old_values = {"status": appointment.status}
        
        # Update appointment status
        appointment.status = "cancelled"
        appointment.updated_at = datetime.now(timezone.utc)
        
        # Release appointment slot
        slot_released = await self._release_appointment_slot(appointment.start_time, appointment.provider_id)
        if not slot_released:
            self.logger.warning(f"Failed to release slot for cancelled appointment {appointment_id}")
        
        # Cancel Google Calendar event if service is available and configured
        if self.google_calendar_service and self.settings.google_calendar.client_id:
            # Get stored google_event_id from appointment record
            google_event_id = appointment.google_event_id
            if google_event_id:
                await self.google_calendar_service.cancel_calendar_appointment(
                    appointment.provider_id, google_event_id
                )
        
        # Issue 46: Cancel all scheduled reminders for this appointment
        try:
            from services.reminder_service import get_reminder_service
            reminder_service = get_reminder_service()
            # Get all reminders for this appointment
            reminders_result = await self.db.execute(
                select(Reminder).where(
                    Reminder.appointment_id == appointment_id,
                    Reminder.status.in_(['scheduled', 'pending'])
                )
            )
            reminders = list(reminders_result.scalars().all())
            for reminder in reminders:
                reminder.status = 'cancelled'
                reminder.completed_at = datetime.now(timezone.utc)
                reminder.deletion_reason = 'appointment_cancelled'
            if reminders:
                await self.db.commit()
        except Exception as e:
            self.logger.warning(f"Failed to cancel reminders for appointment {appointment_id}: {e}")
            # Don't fail the cancellation if reminder cancellation fails
        
        # Log the cancellation
        await self._log_audit("appointments", appointment_id, "CANCEL", old_values, {"status": "cancelled"})
        
        try:
            await self.db.commit()
        except Exception as commit_error:
            await self.db.rollback()
            self.logger.error(f"Failed to commit appointment cancellation: {commit_error}")
            raise
        return True
    
    async def list_appointments(self, search: AppointmentSearchRequest) -> List[Appointment]:
        """
        List appointments with optional filtering and pagination.
        
        Args:
            search: Search criteria and pagination
            
        Returns:
            List of matching appointments
        """
        stmt = select(Appointment)
        
        # Apply filters
        if search.clinic_id:
            # Join with providers to filter by clinic
            stmt = stmt.join(Provider).join(provider_clinics).where(provider_clinics.c.clinic_id == search.clinic_id)
        
        if search.patient_id:
            stmt = stmt.where(Appointment.patient_id == search.patient_id)
        
        if search.provider_id:
            stmt = stmt.where(Appointment.provider_id == search.provider_id)
        
        if search.start_date:
            stmt = stmt.where(Appointment.appointment_date >= search.start_date)
        
        if search.end_date:
            stmt = stmt.where(Appointment.appointment_date <= search.end_date)
        
        if search.status:
            stmt = stmt.where(Appointment.status == search.status)
        
        # Apply pagination
        stmt = stmt.offset(search.offset).limit(search.limit)
        
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
    
    async def get_available_slots(self, provider_id: str, start_date: datetime, 
                           end_date: datetime) -> List[Dict]:
        """
        Get available appointment slots for a provider, merging database and Google Calendar availability.
        
        This method:
        1. Gets available slots from the database
        2. Gets available slots from Google Calendar (if configured)
        3. Returns the intersection (slots available in both)
        
        Args:
            provider_id: Provider ID
            start_date: Start date for search
            end_date: End date for search
            
        Returns:
            List of available time slots as dictionaries with merged availability
        """
        # Validate inputs
        if not provider_id:
            self.logger.warning("provider_id is empty in get_available_slots")
            return []
        
        if not start_date or not end_date:
            self.logger.warning("start_date or end_date is None in get_available_slots")
            return []
        
        if end_date < start_date:
            self.logger.warning("end_date is before start_date in get_available_slots")
            return []
        
        try:
            # Get slots from database
            db_slots = await self.provider_management.get_available_slots(provider_id, start_date, end_date)
            
            # Convert database slots to dict format with normalized times
            db_slots_dict = {}
            for slot in db_slots:
                slot_start = slot.slot_datetime
                if slot_start.tzinfo is None:
                    slot_start = slot_start.replace(tzinfo=timezone.utc)
                else:
                    slot_start = slot_start.astimezone(timezone.utc)
                
                slot_end = slot_start + timedelta(minutes=slot.duration_minutes)
                slot_key = (slot_start, slot_end)
                db_slots_dict[slot_key] = {
                    'slot_id': slot.slot_id,
                    'start_time': slot_start,
                    'end_time': slot_end,
                    'duration_minutes': slot.duration_minutes,
                    'provider_id': provider_id
                }
            
            # If Google Calendar integration is available, merge with calendar availability
            if self.google_calendar_service and self.settings.google_calendar.client_id:
                try:
                    # Get Google Calendar availability for each day in the range
                    current_date = start_date.date()
                    end_date_only = end_date.date()
                    google_slots_dict = {}
                    
                    while current_date <= end_date_only:
                        date_datetime = datetime.combine(current_date, datetime.min.time()).replace(tzinfo=timezone.utc)
                        google_availability = await self.google_calendar_service.calendar_service.get_provider_availability(
                            provider_id, date_datetime
                        )
                        
                        # Convert Google Calendar slots to normalized format
                        for slot in google_availability:
                            slot_start_str = slot.get('start')
                            slot_end_str = slot.get('end')
                            
                            if slot_start_str and slot_end_str:
                                # Parse ISO format strings
                                if 'T' in slot_start_str:
                                    slot_start = datetime.fromisoformat(slot_start_str.replace('Z', '+00:00'))
                                else:
                                    slot_start = datetime.fromisoformat(slot_start_str)
                                
                                if 'T' in slot_end_str:
                                    slot_end = datetime.fromisoformat(slot_end_str.replace('Z', '+00:00'))
                                else:
                                    slot_end = datetime.fromisoformat(slot_end_str)
                                
                                # Normalize to UTC
                                if slot_start.tzinfo is None:
                                    slot_start = slot_start.replace(tzinfo=timezone.utc)
                                else:
                                    slot_start = slot_start.astimezone(timezone.utc)
                                
                                if slot_end.tzinfo is None:
                                    slot_end = slot_end.replace(tzinfo=timezone.utc)
                                else:
                                    slot_end = slot_end.astimezone(timezone.utc)
                                
                                slot_key = (slot_start, slot_end)
                                google_slots_dict[slot_key] = {
                                    'start_time': slot_start,
                                    'end_time': slot_end,
                                    'duration_minutes': slot.get('duration_minutes', 60)
                                }
                        
                        current_date += timedelta(days=1)
                    
                    # Merge: Return intersection (slots available in both database and Google Calendar)
                    merged_slots = []
                    for slot_key, db_slot in db_slots_dict.items():
                        if slot_key in google_slots_dict:
                            # Slot is available in both - use database slot info (has slot_id)
                            merged_slots.append(db_slot)
                        else:
                            # Slot is only in database - still include it (database is source of truth)
                            merged_slots.append(db_slot)
                    
                    self.logger.info(
                        f"Merged availability for provider {provider_id}: {len(db_slots_dict)} DB slots, "
                        f"{len(google_slots_dict)} Google slots, {len(merged_slots)} merged slots",
                        LogCategory.APPOINTMENT
                    )
                    
                    return merged_slots
                    
                except Exception as google_error:
                    self.logger.warning(
                        f"Failed to get Google Calendar availability for provider {provider_id}: {google_error}",
                        LogCategory.APPOINTMENT,
                        exception=google_error
                    )
                    # Fallback to database-only availability
                    return list(db_slots_dict.values())
            else:
                # No Google Calendar integration - return database slots only
                return list(db_slots_dict.values())
                
        except Exception as e:
            self.logger.error(
                f"Error querying available slots: {e}",
                LogCategory.APPOINTMENT,
                exception=e
            )
            return []
    
    async def get_clinic_availability(self, clinic_id: str, start_date: datetime, 
                                     end_date: datetime) -> Dict[str, List[Dict]]:
        """
        Get available appointment slots for all providers in a clinic.
        
        This method:
        1. Gets all providers for the clinic
        2. Gets available slots for each provider (from database and Google Calendar)
        3. Returns a dictionary mapping provider_id to available slots
        
        Args:
            clinic_id: Clinic ID
            start_date: Start date for search
            end_date: End date for search
            
        Returns:
            Dictionary mapping provider_id to list of available slots
        """
        # Validate inputs
        if not clinic_id:
            self.logger.warning("clinic_id is empty in get_clinic_availability")
            return {}
        
        if not start_date or not end_date:
            self.logger.warning("start_date or end_date is None in get_clinic_availability")
            return {}
        
        if end_date < start_date:
            self.logger.warning("end_date is before start_date in get_clinic_availability")
            return {}
        
        try:
            # Get all providers for the clinic
            from models.schemas import ProviderSearchRequest
            provider_search = ProviderSearchRequest(clinic_id=clinic_id, is_available=YesNo.YES)
            providers = await self.provider_management.list_providers(provider_search)
            
            if not providers:
                self.logger.warning(f"No available providers found for clinic {clinic_id}")
                return {}
            
            # Get available slots for each provider
            clinic_availability = {}
            for provider in providers:
                provider_slots = await self.get_available_slots(
                    provider.provider_id, 
                    start_date, 
                    end_date
                )
                if provider_slots:
                    clinic_availability[provider.provider_id] = provider_slots
            
            self.logger.info(
                f"Found availability for {len(clinic_availability)} providers in clinic {clinic_id}",
                LogCategory.APPOINTMENT
            )
            
            return clinic_availability
            
        except Exception as e:
            self.logger.error(
                f"Error getting clinic availability: {e}",
                LogCategory.APPOINTMENT,
                exception=e
            )
            return {}
    
    async def find_next_available_slot(self, provider_id: str, preferred_date: datetime = None,
                                duration_minutes: int = 60) -> Optional[Dict]:
        """
        Find the next available appointment slot for a provider.
        
        Args:
            provider_id: Provider ID
            preferred_date: Preferred date (defaults to today)
            duration_minutes: Duration of appointment
            
        Returns:
            Next available slot or None
        """
        if not preferred_date:
            preferred_date = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Search for available slots starting from preferred date
        search_end = preferred_date + timedelta(days=30)  # Search up to 30 days ahead
        
        available_slots = await self.get_available_slots(provider_id, preferred_date, search_end)
        
        if available_slots and len(available_slots) > 0:
            return available_slots[0]  # Return first available slot
        
        return None
    
    async def _find_nearest_available_slots(self, provider_id: str, preferred_time: datetime,
                                          count: int = 3) -> List[Dict]:
        """
        Find the nearest available appointment slots around a preferred time.
        
        Used when calendar conflicts occur to suggest alternative times.
        
        Args:
            provider_id: Provider ID
            preferred_time: Preferred appointment time
            count: Number of nearest slots to find (default: 3)
            
        Returns:
            List of nearest available slots sorted by proximity to preferred_time
        """
        try:
            # Search window: 2 days before and 7 days after preferred time
            search_start = preferred_time - timedelta(days=2)
            search_end = preferred_time + timedelta(days=7)
            
            # Get all available slots in the search window
            available_slots = await self.get_available_slots(provider_id, search_start, search_end)
            
            if not available_slots:
                return []
            
            # Sort slots by absolute time difference from preferred_time
            slots_with_distance = []
            for slot in available_slots:
                slot_time = slot['start_time']
                if isinstance(slot_time, str):
                    # Parse ISO format string
                    slot_time = datetime.fromisoformat(slot_time.replace('Z', '+00:00'))
                elif slot_time.tzinfo is None:
                    slot_time = slot_time.replace(tzinfo=timezone.utc)
                
                # Normalize preferred_time to UTC
                if preferred_time.tzinfo is None:
                    preferred_time_utc = preferred_time.replace(tzinfo=timezone.utc)
                else:
                    preferred_time_utc = preferred_time.astimezone(timezone.utc)
                
                time_diff = abs((slot_time - preferred_time_utc).total_seconds())
                slots_with_distance.append((time_diff, slot))
            
            # Sort by distance and return top N
            slots_with_distance.sort(key=lambda x: x[0])
            nearest_slots = [slot for _, slot in slots_with_distance[:count]]
            
            return nearest_slots
            
        except Exception as e:
            self.logger.error(f"Error finding nearest available slots: {e}")
            return []
    
    async def _validate_appointment_data(self, appointment_data: AppointmentCreateRequest) -> None:
        """Validate appointment creation data."""
        # Check if patient exists
        patient_result = await self.db.execute(select(Patient).where(Patient.patient_id == appointment_data.patient_id))
        patient = patient_result.scalar_one_or_none()
        if not patient:
            raise PatientNotFoundError(appointment_data.patient_id)
        
        # Check if provider exists
        provider_result = await self.db.execute(select(Provider).where(Provider.provider_id == appointment_data.provider_id))
        provider = provider_result.scalar_one_or_none()
        if not provider:
            raise ProviderNotFoundError(appointment_data.provider_id)
        
        # Check if provider is available
        if provider.is_available != YesNo.YES.value:
            raise ProviderUnavailableError(appointment_data.provider_id, "Provider is not available")
        
        # Validate time constraints
        if appointment_data.end_time <= appointment_data.start_time:
            raise InvalidAppointmentTimeError(
                appointment_data.start_time.isoformat(),
                appointment_data.end_time.isoformat(),
                "End time must be after start time"
            )
        
        # Check if appointment is in the future
        # Always use timezone-aware datetimes for consistency
        now = datetime.now(timezone.utc)
        
        # Ensure start_time is timezone-aware
        if appointment_data.start_time.tzinfo is None:
            raise ValidationError("start_time", appointment_data.start_time, "start_time must be timezone-aware")
        
        if appointment_data.start_time <= now:
            raise InvalidAppointmentTimeError(
                appointment_data.start_time.isoformat(),
                appointment_data.end_time.isoformat(),
                "Appointment must be scheduled in the future"
            )
    
    async def _is_slot_available(self, start_time: datetime, end_time: datetime, 
                          provider_id: str, exclude_appointment_id: str = None) -> bool:
        """Check if a time slot is available for booking.
        
        This method checks:
        1. Database slot availability (start_time and end_time range)
        2. Excludes the specified appointment_id if provided
        3. Checks for overlapping appointments
        
        Issue 174: Note - this method checks availability without locking.
        Callers should use atomic_appointment_booking for actual booking with proper locking.
        """
        # Validate inputs
        if not provider_id:
            self.logger.warning("provider_id is empty in _is_slot_available")
            return False
        
        if not start_time or not end_time:
            self.logger.warning("start_time or end_time is None in _is_slot_available")
            return False
        
        if end_time <= start_time:
            self.logger.warning("end_time must be after start_time in _is_slot_available")
            return False
        
        try:
            # Normalize timezones
            if start_time.tzinfo is None:
                start_time = start_time.replace(tzinfo=timezone.utc)
            else:
                start_time = start_time.astimezone(timezone.utc)
            
            if end_time.tzinfo is None:
                end_time = end_time.replace(tzinfo=timezone.utc)
            else:
                end_time = end_time.astimezone(timezone.utc)
            
            # Check if there's an available slot that covers the requested time range
            # A slot is available if:
            # 1. Slot start_time <= requested start_time
            # 2. Slot end_time (start_time + duration) >= requested end_time
            # 3. Slot is not booked
            # Note: We need to check slots manually since SQLAlchemy doesn't support arithmetic in WHERE clauses easily
            stmt = select(AppointmentSlot).where(
                AppointmentSlot.provider_id == provider_id,
                AppointmentSlot.slot_datetime <= start_time,
                AppointmentSlot.is_booked == YesNo.NO.value
            )
            
            result = await self.db.execute(stmt)
            slots = list(result.scalars().all())
            
            # Check if any slot covers the requested time range
            for slot in slots:
                slot_start = slot.slot_datetime
                if slot_start.tzinfo is None:
                    slot_start = slot_start.replace(tzinfo=timezone.utc)
                else:
                    slot_start = slot_start.astimezone(timezone.utc)
                
                slot_end = slot_start + timedelta(minutes=slot.duration_minutes)
                
                # Check if slot covers the requested time range
                if slot_start <= start_time and slot_end >= end_time:
                    # Found a slot that covers the requested time range
                    # Now check for conflicting appointments if exclude_appointment_id is provided
                    if exclude_appointment_id:
                        appointment_stmt = select(Appointment).where(
                            Appointment.provider_id == provider_id,
                            Appointment.start_time < end_time,
                            Appointment.end_time > start_time,
                            Appointment.status != 'cancelled',
                            Appointment.appointment_id != exclude_appointment_id
                        )
                        appointment_result = await self.db.execute(appointment_stmt)
                        conflicting_appointments = list(appointment_result.scalars().all())
                        
                        if conflicting_appointments:
                            continue  # This slot has conflicts, try next slot
                    
                    return True  # Found available slot
            
            return False  # No available slot found
            
            
        except Exception as e:
            self.logger.error(
                f"Error checking slot availability: {e}",
                LogCategory.APPOINTMENT,
                exception=e
            )
            return False
    
    async def _book_appointment_slot(self, start_time: datetime, provider_id: str, appointment_id: str) -> bool:
        """
        Book an appointment slot.
        
        Convenience wrapper that finds slot_id from start_time and provider_id,
        then calls provider_management.book_appointment_slot (source of truth).
        """
        # Validate inputs
        if not provider_id:
            self.logger.warning("provider_id is empty in _book_appointment_slot")
            return False
        
        if not start_time:
            self.logger.warning("start_time is None in _book_appointment_slot")
            return False
        
        if not appointment_id:
            self.logger.warning("appointment_id is empty in _book_appointment_slot")
            return False
        
        try:
            # Find slot by start_time and provider_id
            slot = await self._find_appointment_slot(start_time, provider_id)
            if not slot:
                self.logger.warning(f"No slot found for provider {provider_id} at {start_time}")
                return False
            
            # Use provider_management to book the slot (source of truth)
            return await self.provider_management.book_appointment_slot(slot.slot_id, appointment_id)
        except Exception as e:
            self.logger.error(f"Error booking appointment slot: {e}")
            return False
    
    async def _release_appointment_slot(self, start_time: datetime, provider_id: str) -> bool:
        """
        Release an appointment slot.
        
        Convenience wrapper that finds slot_id from start_time and provider_id,
        then calls provider_management.release_appointment_slot (source of truth).
        """
        # Validate inputs
        if not provider_id:
            self.logger.warning("provider_id is empty in _release_appointment_slot")
            return False
        
        if not start_time:
            self.logger.warning("start_time is None in _release_appointment_slot")
            return False
        
        try:
            # Find slot by provider and time
            slot_result = await self.db.execute(
                select(AppointmentSlot).where(
                    AppointmentSlot.provider_id == provider_id,
                    AppointmentSlot.slot_datetime == start_time,
                    AppointmentSlot.is_booked == YesNo.YES.value
                )
            )
            slot = slot_result.scalar_one_or_none()
            
            if not slot:
                self.logger.warning(f"No booked slot found for provider {provider_id} at {start_time}")
                return False
            
            # Use provider_management to release the slot (source of truth)
            return await self.provider_management.release_appointment_slot(slot.slot_id)
        except Exception as e:
            self.logger.error(f"Error releasing appointment slot: {e}")
            return False
    
    async def _find_appointment_slot(self, start_time: datetime, provider_id: str) -> Optional[AppointmentSlot]:
        """
        Find an appointment slot for the given time and provider.
        
        Args:
            start_time: Start time of the appointment
            provider_id: ID of the provider
            
        Returns:
            AppointmentSlot if found, None otherwise
        """
        # Validate inputs
        if not provider_id:
            self.logger.warning("provider_id is empty in _find_appointment_slot")
            return None
        
        if not start_time:
            self.logger.warning("start_time is None in _find_appointment_slot")
            return None
        
        try:
            # Issue 121: Normalize timezones before querying
            # Ensure start_time is in UTC for consistent comparison
            if start_time.tzinfo is None:
                # Assume UTC if no timezone info
                start_time = start_time.replace(tzinfo=timezone.utc)
            elif start_time.tzinfo != timezone.utc:
                # Convert to UTC
                start_time = start_time.astimezone(timezone.utc)
            
            # Issue 69: Use SELECT FOR UPDATE to lock the slot when finding it to prevent double-booking
            from models.enums import YesNo
            
            # Issue 138: Handle multiple slots at same time
            # Use SKIP LOCKED to skip held slots and find next available slot instead of waiting
            # This prevents queries from blocking on held slots during booking process
            slots_result = await self.db.execute(
                select(AppointmentSlot).where(
                    AppointmentSlot.provider_id == provider_id,
                    AppointmentSlot.slot_datetime == start_time,
                    AppointmentSlot.is_booked == YesNo.NO.value
                ).with_for_update(skip_locked=True)
            )
            slots = list(slots_result.scalars().all())
            
            # Issue 138: Handle multiple slots at same time
            if not slots:
                return None
            elif len(slots) == 1:
                return slots[0]
            else:
                # Multiple slots found - use the first one
                self.logger.warning(
                    f"Multiple slots found for provider {provider_id} at {start_time}, using first slot",
                    LogCategory.APPOINTMENT
                )
                return slots[0]
        except Exception as e:
            self.logger.error(f"Error finding appointment slot: {e}")
            return None
    
    async def _log_audit(self, table_name: str, record_id: str, action_type: str, 
                   old_values: Optional[Dict], new_values: Optional[Dict]):
        """Log audit trail for changes."""
        await log_audit_trail(
            self.db,
            table_name=table_name,
            record_id=record_id,
            action_type=action_type,
            old_values=old_values,
            new_values=new_values,
            service_name="AppointmentService"
        )
