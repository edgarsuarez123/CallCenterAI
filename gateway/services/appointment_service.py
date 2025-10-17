"""
Appointment Management Service
Handles appointment booking, scheduling, and Google Calendar integration.
"""

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy import and_
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime, timezone
import uuid
import logging

from models.models import Appointment, AppointmentSlot, Patient, Provider, Clinic, AuditLog, provider_clinics
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
        # Get transaction manager
        transaction_manager = get_transaction_manager(self.db)
        
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
            
            # Validate appointment data
            self._validate_appointment_data(appointment_data)
            
            # Find the appointment slot to book
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
            
            # Generate appointment ID
            appointment_id = make_ulid_token('APPOINTMENT')
            
            # Prepare appointment data for atomic booking
            appointment_dict = {
                'appointment_id': appointment_id,
                'appointment_date': appointment_data.appointment_date,
                'start_time': appointment_data.start_time,
                'end_time': appointment_data.end_time,
                'appointment_type': appointment_data.appointment_type,
                'duration_minutes': (appointment_data.end_time - appointment_data.start_time).total_seconds() / 60
            }
            
            # Get clinic_id for usage counter updates
            provider = self.db.query(Provider).filter_by(provider_id=appointment_data.provider_id).first()
            if not provider:
                raise ProviderNotFoundError(appointment_data.provider_id)
            
            # Get clinic_id from slot
            clinic_id = slot.clinic_id
            
            # Perform atomic appointment booking
            result = transaction_manager.atomic_appointment_booking(
                appointment_data=appointment_dict,
                slot_id=slot.slot_id,
                patient_id=appointment_data.patient_id,
                provider_id=appointment_data.provider_id,
                clinic_id=clinic_id
            )
            
            appointment = result['appointment']
            
            # Sync to Google Calendar if service is available and configured
            google_event_id = None
            if self.google_calendar_service and self.settings.google_calendar.client_id:
                try:
                    google_event_id = self.google_calendar_service.sync_appointment_to_calendar(
                        appointment, appointment_data.provider_id, patient_name
                    )
                    if google_event_id:
                        appointment.google_event_id = google_event_id  # Store event ID
                except Exception as e:
                    self.logger.warning(f"Failed to sync appointment to Google Calendar: {e}")
            
            # Schedule reminder call if reminders are enabled
            try:
                reminder_service = get_reminder_service()
                await reminder_service.schedule_reminder(
                    db=self.db,
                    appointment_id=appointment.appointment_id,
                    reminder_type='appointment_reminder'
                )
                self.logger.info(f"Reminder scheduled for appointment {appointment.appointment_id}", LogCategory.APPOINTMENT)
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
        appointment = self.get_appointment(appointment_id)  # This will raise AppointmentNotFoundError if not found
        
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
        
        # Rebook appointment slot if time changed
        if time_changed:
            # Release old slot
            self._release_appointment_slot(appointment.start_time, appointment.provider_id)
            # Book new slot
            self._book_appointment_slot(appointment.start_time, appointment.provider_id, appointment_id)
        
        # Update Google Calendar if service is available and configured
        google_calendar_updated = False
        if self.google_calendar_service and self.settings.google_calendar.client_id:
            if appointment.google_event_id:  # Use stored event ID
                google_calendar_updated = self.google_calendar_service.update_calendar_appointment(
                    appointment, appointment.provider_id, appointment.google_event_id, patient_name
                )
        
        # Log the update
        self._log_audit("appointments", appointment_id, "UPDATE", old_values, update_data)
        
        self.db.commit()
        return appointment, google_calendar_updated
    
    def cancel_appointment(self, appointment_id: str) -> bool:
        """
        Cancel an appointment and remove from Google Calendar.
        
        Args:
            appointment_id: Appointment ID to cancel
            
        Returns:
            True if successful
        """
        appointment = self.get_appointment(appointment_id)  # This will raise AppointmentNotFoundError if not found
        
        # Store old values for audit
        old_values = {"status": appointment.status}
        
        # Update appointment status
        appointment.status = "cancelled"
        appointment.updated_at = datetime.now(timezone.utc)
        
        # Release appointment slot
        self._release_appointment_slot(appointment.start_time, appointment.provider_id)
        
        # Cancel Google Calendar event if service is available and configured
        if self.google_calendar_service and self.settings.google_calendar.client_id:
            # Get stored google_event_id from appointment record
            google_event_id = appointment.google_event_id
            if google_event_id:
                self.google_calendar_service.cancel_calendar_appointment(
                    appointment.provider_id, google_event_id
                )
        
        # Log the cancellation
        self._log_audit("appointments", appointment_id, "CANCEL", old_values, {"status": "cancelled"})
        
        self.db.commit()
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
        # Get appointment slots from database
        slots = self.db.query(AppointmentSlot).filter(
            AppointmentSlot.provider_id == provider_id,
            AppointmentSlot.slot_datetime >= start_date,
            AppointmentSlot.slot_datetime <= end_date,
            AppointmentSlot.is_booked == YesNo.NO.value
        ).order_by(AppointmentSlot.slot_datetime).all()
        
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
            preferred_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Search for available slots starting from preferred date
        search_end = preferred_date + timedelta(days=30)  # Search up to 30 days ahead
        
        available_slots = self.get_available_slots(provider_id, preferred_date, search_end)
        
        if available_slots:
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
        """Check if a time slot is available for booking."""
        # Check if the appointment slot is available
        slot = self.db.query(AppointmentSlot).filter(
            AppointmentSlot.provider_id == provider_id,
            AppointmentSlot.slot_datetime == start_time,
            AppointmentSlot.is_booked == YesNo.NO.value
        ).first()
        
        return slot is not None
    
    def _book_appointment_slot(self, start_time: datetime, provider_id: str, appointment_id: str) -> bool:
        """Book an appointment slot with row-level locking to prevent race conditions."""
        from sqlalchemy import select, update
        
        # Use SELECT FOR UPDATE to lock the row and prevent race conditions
        slot = self.db.execute(
            select(AppointmentSlot)
            .where(
                AppointmentSlot.provider_id == provider_id,
                AppointmentSlot.slot_datetime == start_time,
                AppointmentSlot.is_booked == YesNo.NO.value
            )
            .with_for_update()
        ).scalar_one_or_none()
        
        if slot:
            slot.is_booked = YesNo.YES.value
            slot.booked_by_appointment_id = appointment_id
            slot.updated_at = datetime.now(timezone.utc)
            self.db.commit()
            return True
        
        return False
    
    def _release_appointment_slot(self, start_time: datetime, provider_id: str) -> bool:
        """Release an appointment slot."""
        # Find the corresponding appointment slot
        slot = self.db.query(AppointmentSlot).filter(
            AppointmentSlot.provider_id == provider_id,
            AppointmentSlot.slot_datetime == start_time,
            AppointmentSlot.is_booked == YesNo.YES.value
        ).first()
        
        if slot:
            slot.is_booked = YesNo.NO.value
            slot.booked_by_appointment_id = None
            slot.updated_at = datetime.now(timezone.utc)
            return True
        
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
        return self.db.query(AppointmentSlot).filter(
            and_(
                AppointmentSlot.provider_id == provider_id,
                AppointmentSlot.slot_datetime == start_time,
                AppointmentSlot.is_booked == 'no'
            )
        ).first()
    
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
