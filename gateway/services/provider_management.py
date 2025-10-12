"""
Provider Management Service
Handles all business logic for provider operations including creation, scheduling, and availability.
"""

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
import uuid

from models.models import Provider, AppointmentSlot, Clinic, AuditLog
from models.schemas import (
    ProviderCreateRequest, ProviderUpdateRequest, ProviderSearchRequest,
    ProviderResponse, AppointmentSlotCreateRequest
)
from services.crypto import make_ulid_token


class ProviderManagementService:
    """Service for managing provider operations and scheduling."""
    
    def __init__(self, db: Session):
        self.db = db
    
    def add_provider(self, clinic_id: str, provider_data: ProviderCreateRequest) -> Provider:
        """
        Add a new provider to a clinic.
        
        Args:
            clinic_id: Clinic ID
            provider_data: Provider creation request data
            
        Returns:
            Created provider instance
            
        Raises:
            ValueError: If clinic doesn't exist or data is invalid
            IntegrityError: If provider already exists
        """
        try:
            # Verify clinic exists
            clinic = self.db.query(Clinic).filter_by(clinic_id=clinic_id).first()
            if not clinic:
                raise ValueError(f"Clinic {clinic_id} not found")
            
            # Check provider limit
            if not self._check_provider_limit(clinic_id):
                raise ValueError(f"Provider limit exceeded for clinic {clinic_id}")
            
            # Generate unique provider ID
            provider_id = f"PROVIDER_{clinic_id}_{make_ulid_token('PROVIDER')[:8]}"
            
            # Create provider record
            provider = Provider(
                provider_id=provider_id,
                name_token=provider_data.name_token,
                title=provider_data.title,
                specialty=provider_data.specialty,
                license_number=provider_data.license_number,
                npi_number=provider_data.npi_number,
                email=provider_data.email,
                is_available="yes"
            )
            
            self.db.add(provider)
            self.db.flush()  # Get the provider_id for audit
            
            # Log the creation
            self._log_audit("providers", provider_id, "CREATE", None, provider_data.dict())
            
            self.db.commit()
            return provider
            
        except IntegrityError as e:
            self.db.rollback()
            raise ValueError(f"Provider with NPI {provider_data.npi_number} already exists")
        except Exception as e:
            self.db.rollback()
            raise ValueError(f"Failed to add provider: {str(e)}")
    
    def get_provider(self, provider_id: str) -> Optional[Provider]:
        """Get provider by ID."""
        return self.db.query(Provider).filter_by(provider_id=provider_id).first()
    
    def update_provider(self, provider_id: str, updates: ProviderUpdateRequest) -> Optional[Provider]:
        """
        Update provider information.
        
        Args:
            provider_id: Provider ID to update
            updates: Update request data
            
        Returns:
            Updated provider instance or None if not found
        """
        provider = self.get_provider(provider_id)
        if not provider:
            return None
        
        # Store old values for audit
        old_values = {
            "name_token": provider.name_token,
            "title": provider.title,
            "specialty": provider.specialty,
            "license_number": provider.license_number,
            "npi_number": provider.npi_number,
            "is_available": provider.is_available
        }
        
        # Update fields
        update_data = updates.dict(exclude_unset=True)
        for field, value in update_data.items():
            if hasattr(provider, field):
                setattr(provider, field, value)
        
        provider.updated_at = datetime.utcnow()
        
        # Log the update
        self._log_audit("providers", provider_id, "UPDATE", old_values, update_data)
        
        self.db.commit()
        return provider
    
    def list_providers(self, search: ProviderSearchRequest) -> List[Provider]:
        """
        List providers with optional filtering and pagination.
        
        Args:
            search: Search criteria and pagination
            
        Returns:
            List of matching providers
        """
        query = self.db.query(Provider)
        
        # Apply filters
        if search.clinic_id:
            # Note: This assumes we have a way to link providers to clinics
            # You might need to add a clinic_id field to Provider model
            pass  # TODO: Implement clinic filtering when clinic_id is added to Provider
        
        if search.specialty:
            query = query.filter(Provider.specialty.ilike(f"%{search.specialty}%"))
        
        if search.is_available:
            query = query.filter(Provider.is_available == search.is_available.value)
        
        # Apply pagination
        query = query.offset(search.offset).limit(search.limit)
        
        return query.all()
    
    def set_provider_availability(self, provider_id: str, is_available: bool) -> bool:
        """
        Set provider availability status.
        
        Args:
            provider_id: Provider ID
            is_available: Availability status
            
        Returns:
            True if successful, False if provider not found
        """
        provider = self.get_provider(provider_id)
        if not provider:
            return False
        
        old_status = provider.is_available
        provider.is_available = "yes" if is_available else "no"
        provider.updated_at = datetime.utcnow()
        
        # Log the change
        self._log_audit("providers", provider_id, "UPDATE_AVAILABILITY", 
                       {"is_available": old_status}, {"is_available": provider.is_available})
        
        self.db.commit()
        return True
    
    def create_appointment_slots(self, provider_id: str, clinic_id: str, 
                                start_date: datetime, end_date: datetime, 
                                duration_minutes: int = 60, 
                                business_hours: Dict[str, str] = None) -> List[AppointmentSlot]:
        """
        Create appointment slots for a provider within a date range.
        
        Args:
            provider_id: Provider ID
            clinic_id: Clinic ID
            start_date: Start date for slots
            end_date: End date for slots
            duration_minutes: Duration of each slot
            business_hours: Business hours configuration
            
        Returns:
            List of created appointment slots
        """
        if not business_hours:
            business_hours = {
                "monday": "08:00-17:00",
                "tuesday": "08:00-17:00", 
                "wednesday": "08:00-17:00",
                "thursday": "08:00-17:00",
                "friday": "08:00-17:00",
                "saturday": "09:00-13:00",
                "sunday": "CLOSED"
            }
        
        created_slots = []
        current_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
        
        while current_date <= end_date:
            day_name = current_date.strftime("%A").lower()
            
            if day_name in business_hours and business_hours[day_name] != "CLOSED":
                # Parse business hours (e.g., "08:00-17:00")
                hours_str = business_hours[day_name]
                start_hour, end_hour = self._parse_business_hours(hours_str)
                
                # Create slots for this day
                day_slots = self._create_day_slots(
                    provider_id, clinic_id, current_date, 
                    start_hour, end_hour, duration_minutes
                )
                created_slots.extend(day_slots)
            
            current_date += timedelta(days=1)
        
        # Log the creation
        self._log_audit("appointment_slots", f"BULK_{provider_id}", "CREATE_BULK", 
                       None, {"count": len(created_slots), "provider_id": provider_id})
        
        self.db.commit()
        return created_slots
    
    def get_available_slots(self, provider_id: str, start_date: datetime, 
                           end_date: datetime) -> List[AppointmentSlot]:
        """
        Get available appointment slots for a provider.
        
        Args:
            provider_id: Provider ID
            start_date: Start date for search
            end_date: End date for search
            
        Returns:
            List of available appointment slots
        """
        return self.db.query(AppointmentSlot).filter(
            AppointmentSlot.provider_id == provider_id,
            AppointmentSlot.slot_datetime >= start_date,
            AppointmentSlot.slot_datetime <= end_date,
            AppointmentSlot.is_booked == "no"
        ).order_by(AppointmentSlot.slot_datetime).all()
    
    def book_appointment_slot(self, slot_id: str, appointment_id: str) -> bool:
        """
        Book an appointment slot.
        
        Args:
            slot_id: Appointment slot ID
            appointment_id: Appointment ID
            
        Returns:
            True if successful, False if slot not available
        """
        slot = self.db.query(AppointmentSlot).filter_by(slot_id=slot_id).first()
        if not slot or slot.is_booked == "yes":
            return False
        
        old_values = {
            "is_booked": slot.is_booked,
            "booked_by_appointment_id": slot.booked_by_appointment_id
        }
        
        slot.is_booked = "yes"
        slot.booked_by_appointment_id = appointment_id
        slot.updated_at = datetime.utcnow()
        
        # Log the booking
        self._log_audit("appointment_slots", slot_id, "BOOK", 
                       old_values, {"is_booked": "yes", "appointment_id": appointment_id})
        
        self.db.commit()
        return True
    
    def release_appointment_slot(self, slot_id: str) -> bool:
        """
        Release a booked appointment slot.
        
        Args:
            slot_id: Appointment slot ID
            
        Returns:
            True if successful, False if slot not found
        """
        slot = self.db.query(AppointmentSlot).filter_by(slot_id=slot_id).first()
        if not slot:
            return False
        
        old_values = {
            "is_booked": slot.is_booked,
            "booked_by_appointment_id": slot.booked_by_appointment_id
        }
        
        slot.is_booked = "no"
        slot.booked_by_appointment_id = None
        slot.updated_at = datetime.utcnow()
        
        # Log the release
        self._log_audit("appointment_slots", slot_id, "RELEASE", 
                       old_values, {"is_booked": "no", "appointment_id": None})
        
        self.db.commit()
        return True
    
    def get_provider_schedule(self, provider_id: str, date: datetime) -> List[AppointmentSlot]:
        """
        Get provider's schedule for a specific date.
        
        Args:
            provider_id: Provider ID
            date: Date to get schedule for
            
        Returns:
            List of appointment slots for the date
        """
        start_of_day = date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = start_of_day + timedelta(days=1)
        
        return self.db.query(AppointmentSlot).filter(
            AppointmentSlot.provider_id == provider_id,
            AppointmentSlot.slot_datetime >= start_of_day,
            AppointmentSlot.slot_datetime < end_of_day
        ).order_by(AppointmentSlot.slot_datetime).all()
    
    def _check_provider_limit(self, clinic_id: str) -> bool:
        """Check if clinic has reached provider limit."""
        # Get clinic license to check provider limit
        from models.models import ClinicLicense
        license = self.db.query(ClinicLicense).filter_by(clinic_id=clinic_id).first()
        
        if not license or not license.max_providers:
            return True  # No limit or unlimited
        
        # Count current providers
        # Note: This assumes we'll add clinic_id to Provider model
        # For now, we'll return True
        # provider_count = self.db.query(Provider).filter_by(clinic_id=clinic_id).count()
        # return provider_count < license.max_providers
        
        return True  # TODO: Implement when clinic_id is added to Provider model
    
    def _parse_business_hours(self, hours_str: str) -> tuple:
        """Parse business hours string (e.g., '08:00-17:00')."""
        try:
            start_str, end_str = hours_str.split('-')
            start_hour = int(start_str.split(':')[0])
            end_hour = int(end_str.split(':')[0])
            return start_hour, end_hour
        except:
            return 8, 17  # Default hours
    
    def _create_day_slots(self, provider_id: str, clinic_id: str, date: datetime,
                         start_hour: int, end_hour: int, duration_minutes: int) -> List[AppointmentSlot]:
        """Create appointment slots for a single day."""
        slots = []
        current_time = date.replace(hour=start_hour, minute=0, second=0, microsecond=0)
        end_time = date.replace(hour=end_hour, minute=0, second=0, microsecond=0)
        
        while current_time < end_time:
            slot_id = f"SLOT_{current_time.strftime('%Y%m%d_%H%M')}_{provider_id}"
            
            slot = AppointmentSlot(
                slot_id=slot_id,
                provider_id=provider_id,
                slot_datetime=current_time,
                duration_minutes=duration_minutes,
                is_booked="no",
                clinic_id=clinic_id
            )
            
            self.db.add(slot)
            slots.append(slot)
            
            current_time += timedelta(minutes=duration_minutes)
        
        return slots
    
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
            user_agent="ProviderManagementService"
        )
        self.db.add(audit_log)
