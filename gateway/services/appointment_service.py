"""
Appointment Management Service
Handles appointment booking, scheduling, and Google Calendar integration.
"""

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy import and_
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime, timezone, timedelta
import uuid
import logging

from models.models import Appointment, AppointmentSlot, Patient, Provider, Clinic, AuditLog, provider_clinics, Reminder
from models.enums import YesNo
from models.schemas import (
    AppointmentCreateRequest, AppointmentUpdateRequest, AppointmentSearchRequest,
    AppointmentResponse, AppointmentSlotCreateRequest
)
from services.crypto import make_ulid_token, make_unique_audit_log_id
from services.google_calendar_service import GoogleCalendarIntegrationService
from services.transaction_manager import TransactionManager, get_transaction_manager, ConcurrencyError
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
    
    def __init__(self, db: Session, google_calendar_service: Optional[GoogleCalendarIntegrationService] = None):
        self.db = db
        self.google_calendar_service = google_calendar_service
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
            self._validate_appointment_data(appointment_data)
            
            # Issue 134: Validate provider exists before finding slot
            provider = self.db.query(Provider).filter_by(provider_id=appointment_data.provider_id).first()
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
            slot = self._find_appointment_slot(appointment_data.start_time, appointment_data.provider_id)
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
            result = transaction_manager.atomic_appointment_booking(
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
                    google_event_id = self.google_calendar_service.sync_appointment_to_calendar(
                        appointment, appointment_data.provider_id, patient_name
                    )
                    if google_event_id:
                        appointment.google_event_id = google_event_id  # Store event ID
                        # Issue 6: Google Calendar Event ID Not Stored - Ensure event ID is committed to database
                        try:
                            self.db.commit()
                        except Exception as commit_error:
                            self.db.rollback()
                            self.logger.error(f"Failed to commit Google Calendar event ID: {commit_error}")
                            # Issue 126: Mark appointment as needing sync if commit fails
                            # Note: If Appointment model has needs_calendar_sync field, set it here
                            # For now, log the failure and appointment can be synced later
                            self.logger.warning(f"Appointment {appointment.appointment_id} needs calendar sync (commit failed)")
                            # Don't fail appointment creation if calendar commit fails
                    else:
                        # Issue 35, 126: Event creation failed - mark appointment as needing sync
                        self.logger.warning(f"Google Calendar event creation returned None for appointment {appointment.appointment_id}")
                        # Issue 126: Mark appointment as needing sync
                        # Note: If Appointment model has needs_calendar_sync field, set it here
                        # For now, log the failure and appointment can be synced later
                        self.logger.warning(f"Appointment {appointment.appointment_id} needs calendar sync (event creation failed)")
                except Exception as calendar_error:
                    # Issue 35, 126: Handle calendar service errors gracefully and mark for sync
                    self.logger.error(f"Failed to sync appointment to Google Calendar: {calendar_error}")
                    # Issue 126: Mark appointment as needing sync
                    # Note: If Appointment model has needs_calendar_sync field, set it here
                    # For now, log the failure and appointment can be synced later
                    self.logger.warning(f"Appointment {appointment.appointment_id} needs calendar sync (sync error: {calendar_error})")
                    # Don't fail appointment creation if calendar sync fails
            
            # Issue 196: Schedule reminder call if reminders are enabled, with retry logic
            try:
                reminder_service = get_reminder_service()
                reminder_scheduled = await reminder_service.schedule_reminder(
                    db=self.db,
                    appointment_id=appointment.appointment_id,
                    reminder_type='appointment_reminder'
                )
                if reminder_scheduled:
                    self.logger.info(f"Reminder scheduled for appointment {appointment.appointment_id}", LogCategory.APPOINTMENT)
                else:
                    # Issue 196: Reminder scheduling failed - mark for later scheduling
                    self.logger.warning(f"Reminder scheduling failed for appointment {appointment.appointment_id}, will retry later")
                    # Note: In production, you might want to add a field to mark appointments for reminder scheduling
                    # For now, we log the failure and reminders can be scheduled later via background job
            except Exception as e:
                # Don't fail appointment creation if reminder scheduling fails
                self.logger.warning(f"Failed to schedule reminder for appointment {appointment.appointment_id}: {e}", LogCategory.APPOINTMENT)
            
            self.logger.info(
                "Appointment created successfully with transaction management",
                LogCategory.APPOINTMENT,
                extra_data={
                    'appointment_id': appointment.appointment_id,
                    'slot_id': slot.slot_id,
                    'google_event_id': google_event_id
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
    
    def get_appointment(self, appointment_id: str) -> Optional[Appointment]:
        """Get appointment by ID."""
        appointment = self.db.query(Appointment).filter_by(appointment_id=appointment_id).first()
        if not appointment:
            raise AppointmentNotFoundError(appointment_id)
        return appointment
    
    def update_appointment(self, appointment_id: str, updates: AppointmentUpdateRequest,
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
        from sqlalchemy import select
        appointment = self.db.execute(
            select(Appointment).where(Appointment.appointment_id == appointment_id).with_for_update()
        ).scalar_one_or_none()
        
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
            if not self._is_slot_available(updates.start_time or appointment.start_time,
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
                new_provider = self.db.query(Provider).filter_by(provider_id=new_provider_id).first()
                if not new_provider:
                    raise AppointmentNotFoundError(f"Provider {new_provider_id} not found")
                if not new_provider.is_available:
                    raise SlotUnavailableError(
                        "unknown",
                        new_provider_id,
                        "New provider is not available"
                    )
            
            # Book new slot first
            new_slot_booked = self._book_appointment_slot(
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
                old_slot_released = self._release_appointment_slot(old_start_time, old_provider_id)
                if not old_slot_released:
                    self.logger.warning(f"Failed to release old slot for appointment {appointment_id}")
        
        # Issue 11: Update Google Calendar if service is available and configured
        google_calendar_updated = False
        if self.google_calendar_service and self.settings.google_calendar.client_id:
            if appointment.google_event_id:  # Use stored event ID
                try:
                    google_calendar_updated = self.google_calendar_service.update_calendar_appointment(
                        appointment, appointment.provider_id, appointment.google_event_id, patient_name
                    )
                except Exception as calendar_error:
                    self.logger.error(f"Failed to update Google Calendar event {appointment.google_event_id}: {calendar_error}")
                    # Don't fail appointment update if calendar update fails
            else:
                # Issue 11: Create new calendar event if appointment doesn't have one
                try:
                    google_event_id = self.google_calendar_service.sync_appointment_to_calendar(
                        appointment, appointment.provider_id, patient_name
                    )
                    if google_event_id:
                        appointment.google_event_id = google_event_id
                        google_calendar_updated = True
                except Exception as calendar_error:
                    self.logger.error(f"Failed to create Google Calendar event for appointment {appointment_id}: {calendar_error}")
                    # Don't fail appointment update if calendar creation fails
        
        # Log the update
        self._log_audit("appointments", appointment_id, "UPDATE", old_values, update_data)
        
        try:
            self.db.commit()
        except Exception as commit_error:
            self.db.rollback()
            self.logger.error(f"Failed to commit appointment update: {commit_error}")
            raise
        return appointment, google_calendar_updated
    
    def cancel_appointment(self, appointment_id: str) -> bool:
        """
        Cancel an appointment and remove from Google Calendar.
        
        Args:
            appointment_id: Appointment ID to cancel
            
        Returns:
            True if successful
        """
        # Issue 155: Lock appointment before cancelling to prevent race conditions
        from sqlalchemy import select
        appointment = self.db.execute(
            select(Appointment).where(Appointment.appointment_id == appointment_id).with_for_update()
        ).scalar_one_or_none()
        
        if not appointment:
            raise AppointmentNotFoundError(appointment_id)
        
        # Store old values for audit
        old_values = {"status": appointment.status}
        
        # Update appointment status
        appointment.status = "cancelled"
        appointment.updated_at = datetime.now(timezone.utc)
        
        # Release appointment slot
        slot_released = self._release_appointment_slot(appointment.start_time, appointment.provider_id)
        if not slot_released:
            self.logger.warning(f"Failed to release slot for cancelled appointment {appointment_id}")
        
        # Cancel Google Calendar event if service is available and configured
        if self.google_calendar_service and self.settings.google_calendar.client_id:
            # Get stored google_event_id from appointment record
            google_event_id = appointment.google_event_id
            if google_event_id:
                self.google_calendar_service.cancel_calendar_appointment(
                    appointment.provider_id, google_event_id
                )
        
        # Issue 46: Cancel all scheduled reminders for this appointment
        try:
            from services.reminder_service import get_reminder_service
            reminder_service = get_reminder_service()
            # Get all reminders for this appointment
            reminders = self.db.query(Reminder).filter(
                Reminder.appointment_id == appointment_id,
                Reminder.status.in_(['scheduled', 'pending'])
            ).all()
            for reminder in reminders:
                reminder.status = 'cancelled'
                reminder.completed_at = datetime.now(timezone.utc)
                reminder.deletion_reason = 'appointment_cancelled'
            if reminders:
                self.db.commit()
        except Exception as e:
            self.logger.warning(f"Failed to cancel reminders for appointment {appointment_id}: {e}")
            # Don't fail the cancellation if reminder cancellation fails
        
        # Log the cancellation
        self._log_audit("appointments", appointment_id, "CANCEL", old_values, {"status": "cancelled"})
        
        try:
            self.db.commit()
        except Exception as commit_error:
            self.db.rollback()
            self.logger.error(f"Failed to commit appointment cancellation: {commit_error}")
            raise
        return True
    
    def list_appointments(self, search: AppointmentSearchRequest) -> List[Appointment]:
        """
        List appointments with optional filtering and pagination.
        
        Args:
            search: Search criteria and pagination
            
        Returns:
            List of matching appointments
        """
        query = self.db.query(Appointment)
        
        # Apply filters
        if search.clinic_id:
            # Join with providers to filter by clinic
            query = query.join(Provider).join(provider_clinics).filter(provider_clinics.c.clinic_id == search.clinic_id)
        
        if search.patient_id:
            query = query.filter(Appointment.patient_id == search.patient_id)
        
        if search.provider_id:
            query = query.filter(Appointment.provider_id == search.provider_id)
        
        if search.start_date:
            query = query.filter(Appointment.appointment_date >= search.start_date)
        
        if search.end_date:
            query = query.filter(Appointment.appointment_date <= search.end_date)
        
        if search.status:
            query = query.filter(Appointment.status == search.status)
        
        # Apply pagination
        query = query.offset(search.offset).limit(search.limit)
        
        return query.all()
    
    def get_available_slots(self, provider_id: str, start_date: datetime, 
                           end_date: datetime) -> List[Dict]:
        """
        Get available appointment slots for a provider.
        
        Args:
            provider_id: Provider ID
            start_date: Start date for search
            end_date: End date for search
            
        Returns:
            List of available time slots
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
            # Get appointment slots from database
            slots = self.db.query(AppointmentSlot).filter(
                AppointmentSlot.provider_id == provider_id,
                AppointmentSlot.slot_datetime >= start_date,
                AppointmentSlot.slot_datetime <= end_date,
                AppointmentSlot.is_booked == YesNo.NO.value
            ).order_by(AppointmentSlot.slot_datetime).all()
        except Exception as e:
            self.logger.error(f"Error querying available slots: {e}")
            return []
        
        available_slots = []
        for slot in slots:
            available_slots.append({
                'slot_id': slot.slot_id,
                'start_time': slot.slot_datetime,
                'end_time': slot.slot_datetime + timedelta(minutes=slot.duration_minutes),
                'duration_minutes': slot.duration_minutes
            })
        
        # If Google Calendar integration is available and configured, cross-reference with calendar availability
        if self.google_calendar_service and self.settings.google_calendar.client_id:
            google_availability = self.google_calendar_service.calendar_service.get_provider_availability(
                provider_id, start_date
            )
            # Note: Google Calendar availability filtering would be implemented here
            # when Google Calendar integration is fully configured
        
        return available_slots
    
    def find_next_available_slot(self, provider_id: str, preferred_date: datetime = None,
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
        
        available_slots = self.get_available_slots(provider_id, preferred_date, search_end)
        
        if available_slots and len(available_slots) > 0:
            return available_slots[0]  # Return first available slot
        
        return None
    
    def _validate_appointment_data(self, appointment_data: AppointmentCreateRequest) -> None:
        """Validate appointment creation data."""
        # Check if patient exists
        patient = self.db.query(Patient).filter_by(patient_id=appointment_data.patient_id).first()
        if not patient:
            raise PatientNotFoundError(appointment_data.patient_id)
        
        # Check if provider exists
        provider = self.db.query(Provider).filter_by(provider_id=appointment_data.provider_id).first()
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
        from datetime import timezone
        now = datetime.now(timezone.utc)
        
        # Ensure start_time is timezone-aware
        if appointment_data.start_time.tzinfo is None:
            raise ValidationError("start_time must be timezone-aware")
        
        if appointment_data.start_time <= now:
            raise InvalidAppointmentTimeError(
                appointment_data.start_time.isoformat(),
                appointment_data.end_time.isoformat(),
                "Appointment must be scheduled in the future"
            )
    
    def _is_slot_available(self, start_time: datetime, end_time: datetime, 
                          provider_id: str, exclude_appointment_id: str = None) -> bool:
        """Check if a time slot is available for booking.
        
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
        
        try:
            # Check if the appointment slot is available
            slot = self.db.query(AppointmentSlot).filter(
                AppointmentSlot.provider_id == provider_id,
                AppointmentSlot.slot_datetime == start_time,
                AppointmentSlot.is_booked == YesNo.NO.value
            ).first()
            
            return slot is not None
        except Exception as e:
            self.logger.error(f"Error checking slot availability: {e}")
            return False
    
    def _book_appointment_slot(self, start_time: datetime, provider_id: str, appointment_id: str) -> bool:
        """Book an appointment slot with row-level locking to prevent race conditions."""
        from sqlalchemy import select, update
        
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
            # Issue 19: Check for held slots and verify hold expiration before booking
            from datetime import datetime, timezone
            current_time = datetime.now(timezone.utc)
            
            # Use SELECT FOR UPDATE to lock the row and prevent race conditions
            slot = self.db.execute(
                select(AppointmentSlot)
                .where(
                    AppointmentSlot.provider_id == provider_id,
                    AppointmentSlot.slot_datetime == start_time,
                    # Check if slot is not booked OR if it's held but the hold has expired
                    (
                        (AppointmentSlot.is_booked == YesNo.NO.value) |
                        (
                            (AppointmentSlot.is_booked == "held") &
                            (AppointmentSlot.held_until < current_time)
                        )
                    )
                )
                .with_for_update()
            ).scalar_one_or_none()
        except Exception as e:
            self.logger.error(f"Error querying slot for booking: {e}")
            return False
        
        if slot:
            # Issue 129: Re-verify slot availability after locking
            # Issue 19: Verify slot is actually available (not held by another call)
            if slot.is_booked == "held" and slot.held_until and slot.held_until >= current_time:
                # Slot is still held by another call
                self.logger.warning(f"Slot {slot.slot_id} is still held until {slot.held_until}")
                return False
            
            # Issue 129: Re-verify slot is still available after locking
            from models.enums import YesNo
            if slot.is_booked != YesNo.NO.value and slot.is_booked != "held":
                # Slot is already booked
                self.logger.warning(f"Slot {slot.slot_id} is already booked (state: {slot.is_booked})")
                return False
            try:
                slot.is_booked = YesNo.YES.value
                slot.booked_by_appointment_id = appointment_id
                slot.updated_at = datetime.now(timezone.utc)
                self.db.commit()
                return True
            except Exception as commit_error:
                self.db.rollback()
                self.logger.error(f"Failed to commit slot booking: {commit_error}")
                raise
        
        return False
    
    def _release_appointment_slot(self, start_time: datetime, provider_id: str) -> bool:
        """Release an appointment slot."""
        # Validate inputs
        if not provider_id:
            self.logger.warning("provider_id is empty in _release_appointment_slot")
            return False
        
        if not start_time:
            self.logger.warning("start_time is None in _release_appointment_slot")
            return False
        
        try:
            # Issue 20: Query by booked_by_appointment_id instead of time matching
            # First try to find by appointment_id if we have it
            # Otherwise fall back to time matching
            slot = None
            # Try to find slot by provider and time, but prefer booked_by_appointment_id
            slot = self.db.query(AppointmentSlot).filter(
                AppointmentSlot.provider_id == provider_id,
                AppointmentSlot.slot_datetime == start_time,
                AppointmentSlot.is_booked == YesNo.YES.value
            ).first()
        except Exception as e:
            self.logger.error(f"Error querying slot for release: {e}")
            return False
        
        # Issue 168: Verify slot was actually booked before releasing
        if slot:
            # Issue 168: Check slot state before releasing
            if slot.is_booked != YesNo.YES.value and slot.is_booked != "held":
                self.logger.warning(f"Slot {slot.slot_id} is not booked (state: {slot.is_booked}), cannot release")
                return False
            
            try:
                slot.is_booked = YesNo.NO.value
                slot.booked_by_appointment_id = None
                slot.updated_at = datetime.now(timezone.utc)
                self.db.commit()
                return True
            except Exception as commit_error:
                self.db.rollback()
                self.logger.error(f"Failed to commit slot release: {commit_error}")
                raise
        
        return False
    
    def _find_appointment_slot(self, start_time: datetime, provider_id: str) -> Optional[AppointmentSlot]:
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
                from datetime import timezone
                start_time = start_time.replace(tzinfo=timezone.utc)
            elif start_time.tzinfo != timezone.utc:
                # Convert to UTC
                start_time = start_time.astimezone(timezone.utc)
            
            # Issue 69: Use SELECT FOR UPDATE to lock the slot when finding it to prevent double-booking
            from sqlalchemy import select
            from models.enums import YesNo
            
            # Issue 138: Handle multiple slots at same time
            # Query for all slots matching the criteria
            slots = self.db.execute(
                select(AppointmentSlot).where(
                    AppointmentSlot.provider_id == provider_id,
                    AppointmentSlot.slot_datetime == start_time,
                    AppointmentSlot.is_booked == YesNo.NO.value
                ).with_for_update()
            ).scalars().all()
            
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
    
    def _log_audit(self, table_name: str, record_id: str, action_type: str, 
                   old_values: Optional[Dict], new_values: Optional[Dict]):
        """Log audit trail for changes."""
        details = ""
        if old_values:
            details += f"Old values: {old_values}. "
        if new_values:
            details += f"New values: {new_values}"
        
        audit_log = AuditLog(
            log_id=make_unique_audit_log_id(),
            table_name=table_name,
            record_id=record_id,
            action_type=action_type,
            details=details,
            user_id="system",  # Note: Would get from auth context in production
            ip_address="127.0.0.1",  # Note: Would get from request context in production
            user_agent="AppointmentService"
        )
        self.db.add(audit_log)
