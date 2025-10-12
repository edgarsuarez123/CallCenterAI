"""
Appointment Management Service
Handles appointment booking, scheduling, and Google Calendar integration.
"""

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime, timedelta
import uuid
import logging

from models.models import Appointment, AppointmentSlot, Patient, Provider, Clinic, AuditLog
from models.schemas import (
    AppointmentCreateRequest, AppointmentUpdateRequest, AppointmentSearchRequest,
    AppointmentResponse, AppointmentSlotCreateRequest
)
from services.crypto import make_ulid_token
from services.google_calendar_service import GoogleCalendarIntegrationService


class AppointmentService:
    """Service for managing appointments and scheduling."""
    
    def __init__(self, db: Session, google_calendar_service: Optional[GoogleCalendarIntegrationService] = None):
        self.db = db
        self.google_calendar_service = google_calendar_service
        self.logger = logging.getLogger(__name__)
    
    def create_appointment(self, appointment_data: AppointmentCreateRequest, 
                         patient_name: str = None) -> Tuple[Optional[Appointment], Optional[str]]:
        """
        Create a new appointment and sync to Google Calendar.
        
        Args:
            appointment_data: Appointment creation request
            patient_name: Patient name for calendar event
            
        Returns:
            Tuple of (appointment_instance, google_calendar_event_id)
        """
        try:
            # Validate appointment data
            if not self._validate_appointment_data(appointment_data):
                raise ValueError("Invalid appointment data")
            
            # Check if appointment slot is available
            if not self._is_slot_available(appointment_data.start_time, appointment_data.end_time, 
                                         appointment_data.provider_id):
                raise ValueError("Appointment slot is not available")
            
            # Generate appointment ID
            appointment_id = make_ulid_token('APPOINTMENT')
            
            # Create appointment record
            appointment = Appointment(
                appointment_id=appointment_id,
                patient_id=appointment_data.patient_id,
                provider_id=appointment_data.provider_id,
                appointment_date=appointment_data.appointment_date,
                start_time=appointment_data.start_time,
                end_time=appointment_data.end_time,
                appointment_type=appointment_data.appointment_type,
                notes_token=appointment_data.notes_token,
                status="scheduled"
            )
            
            self.db.add(appointment)
            self.db.flush()  # Get the appointment_id for slot booking
            
            # Book the appointment slot
            if not self._book_appointment_slot(appointment_data.start_time, appointment_data.provider_id, appointment_id):
                self.db.rollback()
                raise ValueError("Failed to book appointment slot")
            
            # Sync to Google Calendar if service is available
            google_event_id = None
            if self.google_calendar_service:
                google_event_id = self.google_calendar_service.sync_appointment_to_calendar(
                    appointment, appointment_data.provider_id, patient_name
                )
                
                if google_event_id:
                    # TODO: Store google_event_id in appointment record
                    pass
            
            # Log the creation
            self._log_audit("appointments", appointment_id, "CREATE", None, appointment_data.dict())
            
            self.db.commit()
            return appointment, google_event_id
            
        except Exception as e:
            self.db.rollback()
            self.logger.error(f"Failed to create appointment: {str(e)}")
            raise ValueError(f"Failed to create appointment: {str(e)}")
    
    def get_appointment(self, appointment_id: str) -> Optional[Appointment]:
        """Get appointment by ID."""
        return self.db.query(Appointment).filter_by(appointment_id=appointment_id).first()
    
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
        appointment = self.get_appointment(appointment_id)
        if not appointment:
            return None, False
        
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
                raise ValueError("New appointment time is not available")
        
        # Update fields
        update_data = updates.dict(exclude_unset=True)
        for field, value in update_data.items():
            if hasattr(appointment, field):
                setattr(appointment, field, value)
        
        appointment.updated_at = datetime.utcnow()
        
        # Rebook appointment slot if time changed
        if time_changed:
            # Release old slot
            self._release_appointment_slot(appointment.start_time, appointment.provider_id)
            # Book new slot
            self._book_appointment_slot(appointment.start_time, appointment.provider_id, appointment_id)
        
        # Update Google Calendar if service is available
        google_calendar_updated = False
        if self.google_calendar_service:
            # TODO: Get stored google_event_id from appointment record
            google_event_id = None  # Placeholder
            if google_event_id:
                google_calendar_updated = self.google_calendar_service.update_calendar_appointment(
                    appointment, appointment.provider_id, google_event_id, patient_name
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
        appointment = self.get_appointment(appointment_id)
        if not appointment:
            return False
        
        # Store old values for audit
        old_values = {"status": appointment.status}
        
        # Update appointment status
        appointment.status = "cancelled"
        appointment.updated_at = datetime.utcnow()
        
        # Release appointment slot
        self._release_appointment_slot(appointment.start_time, appointment.provider_id)
        
        # Cancel Google Calendar event if service is available
        if self.google_calendar_service:
            # TODO: Get stored google_event_id from appointment record
            google_event_id = None  # Placeholder
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
            query = query.join(Provider).filter(Provider.clinic_id == search.clinic_id)
        
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
            AppointmentSlot.is_booked == "no"
        ).order_by(AppointmentSlot.slot_datetime).all()
        
        available_slots = []
        for slot in slots:
            available_slots.append({
                'slot_id': slot.slot_id,
                'start_time': slot.slot_datetime,
                'end_time': slot.slot_datetime + timedelta(minutes=slot.duration_minutes),
                'duration_minutes': slot.duration_minutes
            })
        
        # If Google Calendar integration is available, cross-reference with calendar availability
        if self.google_calendar_service:
            google_availability = self.google_calendar_service.calendar_service.get_provider_availability(
                provider_id, start_date
            )
            # TODO: Merge and filter slots based on Google Calendar availability
        
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
    
    def _validate_appointment_data(self, appointment_data: AppointmentCreateRequest) -> bool:
        """Validate appointment creation data."""
        # Check if patient exists
        patient = self.db.query(Patient).filter_by(patient_id=appointment_data.patient_id).first()
        if not patient:
            return False
        
        # Check if provider exists
        provider = self.db.query(Provider).filter_by(provider_id=appointment_data.provider_id).first()
        if not provider:
            return False
        
        # Check if provider is available
        if provider.is_available != "yes":
            return False
        
        # Validate time constraints
        if appointment_data.end_time <= appointment_data.start_time:
            return False
        
        # Check if appointment is in the future
        # Handle timezone-aware datetimes
        now = datetime.now()
        if appointment_data.start_time.tzinfo is not None:
            # If start_time is timezone-aware, make now timezone-aware too
            from datetime import timezone
            now = now.replace(tzinfo=timezone.utc)
        
        if appointment_data.start_time <= now:
            return False
        
        return True
    
    def _is_slot_available(self, start_time: datetime, end_time: datetime, 
                          provider_id: str, exclude_appointment_id: str = None) -> bool:
        """Check if a time slot is available for booking."""
        # Check if the appointment slot is available
        slot = self.db.query(AppointmentSlot).filter(
            AppointmentSlot.provider_id == provider_id,
            AppointmentSlot.slot_datetime == start_time,
            AppointmentSlot.is_booked == "no"
        ).first()
        
        return slot is not None
    
    def _book_appointment_slot(self, start_time: datetime, provider_id: str, appointment_id: str) -> bool:
        """Book an appointment slot."""
        # Find the corresponding appointment slot
        slot = self.db.query(AppointmentSlot).filter(
            AppointmentSlot.provider_id == provider_id,
            AppointmentSlot.slot_datetime == start_time,
            AppointmentSlot.is_booked == "no"
        ).first()
        
        if slot:
            slot.is_booked = "yes"
            slot.booked_by_appointment_id = appointment_id
            slot.updated_at = datetime.utcnow()
            return True
        
        return False
    
    def _release_appointment_slot(self, start_time: datetime, provider_id: str) -> bool:
        """Release an appointment slot."""
        # Find the corresponding appointment slot
        slot = self.db.query(AppointmentSlot).filter(
            AppointmentSlot.provider_id == provider_id,
            AppointmentSlot.slot_datetime == start_time,
            AppointmentSlot.is_booked == "yes"
        ).first()
        
        if slot:
            slot.is_booked = "no"
            slot.booked_by_appointment_id = None
            slot.updated_at = datetime.utcnow()
            return True
        
        return False
    
    def _log_audit(self, table_name: str, record_id: str, action_type: str, 
                   old_values: Optional[Dict], new_values: Optional[Dict]):
        """Log audit trail for changes."""
        details = ""
        if old_values:
            details += f"Old values: {old_values}. "
        if new_values:
            details += f"New values: {new_values}"
        
        audit_log = AuditLog(
            log_id=f"LOG_{make_ulid_token('AUDIT')[:8]}",
            table_name=table_name,
            record_id=record_id,
            action_type=action_type,
            details=details,
            user_id="system",  # TODO: Get from auth context
            ip_address="127.0.0.1",  # TODO: Get from request context
            user_agent="AppointmentService"
        )
        self.db.add(audit_log)
