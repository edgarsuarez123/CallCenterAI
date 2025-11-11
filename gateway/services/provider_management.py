"""
Provider Management Service
Handles all business logic for provider operations including creation, scheduling, and availability.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone, timedelta

# Atlantic Standard Time (UTC-4)
AST = timezone(timedelta(hours=-4))
from zoneinfo import ZoneInfo

from models.models import Provider, AppointmentSlot, Clinic
from models.enums import YesNo
from models.schemas import (
    ProviderCreateRequest, ProviderUpdateRequest, ProviderSearchRequest,
    AppointmentSlotCreateRequest
)
from services.crypto import make_ulid_token
from services.audit_utils import log_audit_trail
from services.structured_logging import get_logger, LogCategory


class ProviderManagementService:
    """Service for managing provider operations and scheduling."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def add_provider(self, clinic_id: str, provider_data: ProviderCreateRequest) -> Provider:
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
        # Validate inputs
        if not clinic_id or not isinstance(clinic_id, str) or not clinic_id.strip():
            raise ValueError("clinic_id cannot be empty")
        
        if not provider_data:
            raise ValueError("provider_data cannot be None")
        
        try:
            # Verify clinic exists
            clinic_result = await self.db.execute(select(Clinic).where(Clinic.clinic_id == clinic_id))
            clinic = clinic_result.scalar_one_or_none()
            if not clinic:
                raise ValueError(f"Clinic {clinic_id} not found")
            
            # Check provider limit
            if not await self._check_provider_limit(clinic_id):
                raise ValueError(f"Provider limit exceeded for clinic {clinic_id}")
            
            # Generate unique provider ID
            provider_id = f"PROVIDER_{clinic_id}_{make_ulid_token('PROVIDER')[:8]}"
            
            # Create provider record
            provider = Provider(
                provider_id=provider_id,
                name_token=provider_data.name_token,
                title=provider_data.title,
                specialty=provider_data.specialty,
                email=provider_data.email,
                is_available="yes"
            )
            
            self.db.add(provider)
            await self.db.flush()  # Get the provider_id for audit
            
            # Log the creation
            await self._log_audit("providers", provider_id, "CREATE", None, provider_data.model_dump())
            
            # Commit with error handling
            try:
                await self.db.commit()
            except Exception as commit_error:
                await self.db.rollback()
                raise ValueError(f"Failed to commit provider: {str(commit_error)}")
            
            return provider
            
        except IntegrityError as e:
            await self.db.rollback()
            raise ValueError(f"Provider already exists: {str(e)}")
        except ValueError:
            # Re-raise ValueError as-is
            raise
        except Exception as e:
            await self.db.rollback()
            raise ValueError(f"Failed to add provider: {str(e)}")
    
    async def get_provider(self, provider_id: str) -> Optional[Provider]:
        """Get provider by ID."""
        result = await self.db.execute(
            select(Provider).where(Provider.provider_id == provider_id, Provider.is_deleted == 'no')
        )
        return result.scalar_one_or_none()
    
    async def update_provider(self, provider_id: str, updates: ProviderUpdateRequest) -> Optional[Provider]:
        """
        Update provider information.
        
        Args:
            provider_id: Provider ID to update
            updates: Update request data
            
        Returns:
            Updated provider instance or None if not found
        """
        # Validate inputs
        if not provider_id or not isinstance(provider_id, str) or not provider_id.strip():
            return None
        
        if not updates:
            return None
        
        provider = await self.get_provider(provider_id)
        if not provider:
            return None
        
        try:
            # Store old values for audit
            old_values = {
                "name_token": provider.name_token,
                "title": provider.title,
                "specialty": provider.specialty,
                "email": provider.email,
                "is_available": provider.is_available
            }
            
            # Update fields
            update_data = updates.model_dump(exclude_unset=True)
            for field, value in update_data.items():
                if hasattr(provider, field):
                    setattr(provider, field, value)
            
            provider.updated_at = datetime.now(AST)
            
            # Log the update
            await self._log_audit("providers", provider_id, "UPDATE", old_values, update_data)
            
            # Commit with error handling
            try:
                await self.db.commit()
            except Exception as commit_error:
                await self.db.rollback()
                raise ValueError(f"Failed to commit provider update: {str(commit_error)}")
            
            return provider
        except Exception as e:
            await self.db.rollback()
            raise ValueError(f"Failed to update provider: {str(e)}")
    
    async def list_providers(self, search: ProviderSearchRequest) -> List[Provider]:
        """
        List providers with optional filtering and pagination.
        
        Providers can be associated with a clinic via:
        1. Direct relationship (Provider.clinic_id)
        2. Many-to-many relationship (provider_clinics table)
        
        This method checks both relationships when clinic_id is provided.
        
        Args:
            search: Search criteria and pagination
            
        Returns:
            List of matching providers
        """
        # Base filter conditions
        filter_conditions = []
        if hasattr(Provider, 'is_deleted'):
            filter_conditions.append(Provider.is_deleted == 'no')
        
        # Get providers from direct relationship
        providers = []
        if search.clinic_id:
            # Direct relationship: Provider.clinic_id == clinic_id
            direct_conditions = filter_conditions.copy()
            direct_conditions.append(Provider.clinic_id == search.clinic_id)
            
            if search.specialty:
                direct_conditions.append(Provider.specialty.ilike(f"{search.specialty}%"))
            if search.name:
                direct_conditions.append(Provider.name_token.ilike(f"{search.name}%"))
            if search.is_available:
                direct_conditions.append(Provider.is_available == search.is_available.value)
            
            direct_stmt = select(Provider).where(*direct_conditions)
            direct_result = await self.db.execute(direct_stmt)
            providers = list(direct_result.scalars().all())
            
            # Also check many-to-many relationship and combine results
            from models.models import provider_clinics
            many_to_many_conditions = filter_conditions.copy()
            many_to_many_conditions.append(provider_clinics.c.clinic_id == search.clinic_id)
            
            if search.specialty:
                many_to_many_conditions.append(Provider.specialty.ilike(f"{search.specialty}%"))
            if search.name:
                many_to_many_conditions.append(Provider.name_token.ilike(f"{search.name}%"))
            if search.is_available:
                many_to_many_conditions.append(Provider.is_available == search.is_available.value)
            
            many_to_many_stmt = select(Provider).join(provider_clinics).where(*many_to_many_conditions)
            many_to_many_result = await self.db.execute(many_to_many_stmt)
            many_to_many_providers = list(many_to_many_result.scalars().all())
            
            # Combine results and remove duplicates (by provider_id)
            provider_dict = {p.provider_id: p for p in providers}
            for p in many_to_many_providers:
                if p.provider_id not in provider_dict:
                    provider_dict[p.provider_id] = p
            
            providers = list(provider_dict.values())
        else:
            # No clinic_id filter - query all providers
            stmt = select(Provider).where(*filter_conditions)
            
            if search.specialty:
                stmt = stmt.where(Provider.specialty.ilike(f"{search.specialty}%"))
            if search.name:
                stmt = stmt.where(Provider.name_token.ilike(f"{search.name}%"))
            if search.is_available:
                stmt = stmt.where(Provider.is_available == search.is_available.value)
            
            result = await self.db.execute(stmt)
            providers = list(result.scalars().all())
        
        # Apply pagination
        if search.offset:
            providers = providers[search.offset:]
        if search.limit:
            providers = providers[:search.limit]
        
        return providers
    
    async def set_provider_availability(self, provider_id: str, is_available: bool) -> bool:
        """
        Set provider availability status.
        
        Args:
            provider_id: Provider ID
            is_available: Availability status
            
        Returns:
            True if successful, False if provider not found
        """
        # Validate inputs
        if not provider_id or not isinstance(provider_id, str) or not provider_id.strip():
            return False
        
        provider = await self.get_provider(provider_id)
        if not provider:
            return False
        
        try:
            old_status = provider.is_available
            provider.is_available = "yes" if is_available else "no"
            provider.updated_at = datetime.now(AST)
            
            # Log the change
            await self._log_audit("providers", provider_id, "UPDATE_AVAILABILITY", 
                           {"is_available": old_status}, {"is_available": provider.is_available})
            
            # Commit with error handling
            try:
                await self.db.commit()
            except Exception as commit_error:
                await self.db.rollback()
                raise ValueError(f"Failed to commit availability update: {str(commit_error)}")
            
            return True
        except Exception as e:
            await self.db.rollback()
            raise ValueError(f"Failed to set provider availability: {str(e)}")
    
    async def create_appointment_slots(self, provider_id: str, clinic_id: str, 
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
        # Validate inputs
        if not provider_id or not isinstance(provider_id, str) or not provider_id.strip():
            raise ValueError("provider_id cannot be empty")
        
        if not clinic_id or not isinstance(clinic_id, str) or not clinic_id.strip():
            raise ValueError("clinic_id cannot be empty")
        
        if not start_date or not isinstance(start_date, datetime):
            raise ValueError("start_date must be a valid datetime")
        
        if not end_date or not isinstance(end_date, datetime):
            raise ValueError("end_date must be a valid datetime")
        
        if end_date < start_date:
            raise ValueError("end_date must be after start_date")
        
        if duration_minutes <= 0:
            raise ValueError("duration_minutes must be positive")
        
        # Verify provider exists
        provider = await self.get_provider(provider_id)
        if not provider:
            raise ValueError(f"Provider {provider_id} not found")
        
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
        try:
            # Use AST timezone for DST-aware slot creation
            tz = ZoneInfo("America/Puerto_Rico")  # AST timezone
            current_date = start_date.replace(tzinfo=tz)
            
            while current_date <= end_date:
                day_name = current_date.strftime("%A").lower()
                
                if day_name in business_hours and business_hours[day_name] != "CLOSED":
                    # Parse business hours (e.g., "08:00-17:00")
                    hours_str = business_hours[day_name]
                    try:
                        start_hour, end_hour, is_overnight = self._parse_business_hours(hours_str)
                        
                        # Create slots for this day - will skip non-existent DST times
                        day_slots = await self._create_day_slots(
                            provider_id, clinic_id, current_date, 
                            start_hour, end_hour, duration_minutes, is_overnight
                        )
                        created_slots.extend(day_slots)
                    except Exception as e:
                        # Skip DST transition hour or invalid hours
                        logger = get_logger("provider_management")
                        logger.warning(
                            f"Skipping DST transition for {current_date.date()}: {e}",
                            LogCategory.PROVIDER
                        )
                        continue
                
                current_date += timedelta(days=1)
            
            # Log the creation
            await self._log_audit("appointment_slots", f"BULK_{provider_id}", "CREATE_BULK", 
                           None, {"count": len(created_slots), "provider_id": provider_id})
            
            # Commit with error handling
            try:
                await self.db.commit()
            except Exception as commit_error:
                await self.db.rollback()
                raise ValueError(f"Failed to commit appointment slots: {str(commit_error)}")
            
            return created_slots
        except Exception as e:
            await self.db.rollback()
            raise ValueError(f"Failed to create appointment slots: {str(e)}")
    
    async def create_appointment_slot(self, slot_data: AppointmentSlotCreateRequest) -> AppointmentSlot:
        """
        Create a single appointment slot.
        
        Args:
            slot_data: Slot creation request
            
        Returns:
            Created appointment slot
            
        Raises:
            ValueError: If provider or clinic not found
        """
        # Validate inputs
        if not slot_data:
            raise ValueError("slot_data cannot be None")
        
        if not slot_data.provider_id or not isinstance(slot_data.provider_id, str) or not slot_data.provider_id.strip():
            raise ValueError("provider_id cannot be empty")
        
        if not slot_data.clinic_id or not isinstance(slot_data.clinic_id, str) or not slot_data.clinic_id.strip():
            raise ValueError("clinic_id cannot be empty")
        
        if not slot_data.slot_datetime or not isinstance(slot_data.slot_datetime, datetime):
            raise ValueError("slot_datetime must be a valid datetime")
        
        if slot_data.duration_minutes <= 0:
            raise ValueError("duration_minutes must be positive")
        
        try:
            # Verify provider exists
            provider = await self.get_provider(slot_data.provider_id)
            if not provider:
                raise ValueError(f"Provider {slot_data.provider_id} not found")
            
            # Verify clinic exists
            clinic_result = await self.db.execute(select(Clinic).where(Clinic.clinic_id == slot_data.clinic_id))
            clinic = clinic_result.scalar_one_or_none()
            if not clinic:
                raise ValueError(f"Clinic {slot_data.clinic_id} not found")
            
            # Generate slot ID
            slot_id = make_ulid_token('SLOT')
            
            # Create slot
            slot = AppointmentSlot(
                slot_id=slot_id,
                provider_id=slot_data.provider_id,
                clinic_id=slot_data.clinic_id,
                slot_datetime=slot_data.slot_datetime,
                duration_minutes=slot_data.duration_minutes,
                is_booked="no"
            )
            
            self.db.add(slot)
            
            # Commit with error handling
            try:
                await self.db.commit()
                await self.db.refresh(slot)
            except Exception as commit_error:
                await self.db.rollback()
                raise ValueError(f"Failed to commit appointment slot: {str(commit_error)}")
            
            # Log the creation
            await self._log_audit("appointment_slots", slot_id, "CREATE", None, {
                "provider_id": slot_data.provider_id,
                "clinic_id": slot_data.clinic_id,
                "slot_datetime": slot_data.slot_datetime.isoformat(),
                "duration_minutes": slot_data.duration_minutes
            })
            
            return slot
        except ValueError:
            # Re-raise ValueError as-is
            raise
        except Exception as e:
            await self.db.rollback()
            raise ValueError(f"Failed to create appointment slot: {str(e)}")
    
    async def get_available_slots(self, provider_id: str, start_date: datetime, 
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
        # Validate inputs
        if not provider_id or not isinstance(provider_id, str) or not provider_id.strip():
            return []
        
        if not start_date or not isinstance(start_date, datetime):
            return []
        
        if not end_date or not isinstance(end_date, datetime):
            return []
        
        if end_date < start_date:
            return []
        
        try:
            stmt = select(AppointmentSlot).where(
                AppointmentSlot.provider_id == provider_id,
                AppointmentSlot.slot_datetime >= start_date,
                AppointmentSlot.slot_datetime <= end_date,
                AppointmentSlot.is_booked == YesNo.NO.value
            ).order_by(AppointmentSlot.slot_datetime)
            result = await self.db.execute(stmt)
            return list(result.scalars().all())
        except Exception as e:
            logger = get_logger("provider_management")
            logger.error(
                f"Error querying available slots: {e}",
                LogCategory.PROVIDER,
                exception=e
            )
            return []
    
    async def book_appointment_slot(self, slot_id: str, appointment_id: str) -> bool:
        """
        Book an appointment slot.
        
        Args:
            slot_id: Appointment slot ID
            appointment_id: Appointment ID
            
        Returns:
            True if successful, False if slot not available
        """
        # Validate inputs
        if not slot_id or not isinstance(slot_id, str) or not slot_id.strip():
            return False
        
        if not appointment_id or not isinstance(appointment_id, str) or not appointment_id.strip():
            return False
        
        try:
            result = await self.db.execute(select(AppointmentSlot).where(AppointmentSlot.slot_id == slot_id))
            slot = result.scalar_one_or_none()
            if not slot or slot.is_booked == YesNo.YES.value:
                return False
            
            old_values = {
                "is_booked": slot.is_booked,
                "booked_by_appointment_id": slot.booked_by_appointment_id
            }
            
            slot.is_booked = "yes"
            slot.booked_by_appointment_id = appointment_id
            slot.updated_at = datetime.now(AST)
            
            # Log the booking
            await self._log_audit("appointment_slots", slot_id, "BOOK", 
                           old_values, {"is_booked": "yes", "appointment_id": appointment_id})
            
            # Commit with error handling
            try:
                await self.db.commit()
            except Exception as commit_error:
                await self.db.rollback()
                raise ValueError(f"Failed to commit slot booking: {str(commit_error)}")
            
            return True
        except Exception as e:
            await self.db.rollback()
            raise ValueError(f"Failed to book appointment slot: {str(e)}")
    
    async def release_appointment_slot(self, slot_id: str) -> bool:
        """
        Release a booked appointment slot.
        
        Args:
            slot_id: Appointment slot ID
            
        Returns:
            True if successful, False if slot not found
        """
        # Validate inputs
        if not slot_id or not isinstance(slot_id, str) or not slot_id.strip():
            return False
        
        try:
            result = await self.db.execute(select(AppointmentSlot).where(AppointmentSlot.slot_id == slot_id))
            slot = result.scalar_one_or_none()
            if not slot:
                return False
            
            old_values = {
                "is_booked": slot.is_booked,
                "booked_by_appointment_id": slot.booked_by_appointment_id
            }
            
            # Issue 18: Use enum instead of string literal
            slot.is_booked = YesNo.NO.value
            slot.booked_by_appointment_id = None
            slot.updated_at = datetime.now(AST)
            
            # Log the release
            await self._log_audit("appointment_slots", slot_id, "RELEASE", 
                           old_values, {"is_booked": "no", "appointment_id": None})
            
            # Commit with error handling
            try:
                await self.db.commit()
            except Exception as commit_error:
                await self.db.rollback()
                raise ValueError(f"Failed to commit slot release: {str(commit_error)}")
            
            return True
        except Exception as e:
            await self.db.rollback()
            raise ValueError(f"Failed to release appointment slot: {str(e)}")
    
    async def get_provider_schedule(self, provider_id: str, date: datetime) -> List[AppointmentSlot]:
        """
        Get provider's schedule for a specific date.
        
        Args:
            provider_id: Provider ID
            date: Date to get schedule for
            
        Returns:
            List of appointment slots for the date
        """
        # Validate inputs
        if not provider_id or not isinstance(provider_id, str) or not provider_id.strip():
            return []
        
        if not date or not isinstance(date, datetime):
            return []
        
        try:
            start_of_day = date.replace(hour=0, minute=0, second=0, microsecond=0)
            end_of_day = start_of_day + timedelta(days=1)
            
            stmt = select(AppointmentSlot).where(
                AppointmentSlot.provider_id == provider_id,
                AppointmentSlot.slot_datetime >= start_of_day,
                AppointmentSlot.slot_datetime < end_of_day
            ).order_by(AppointmentSlot.slot_datetime)
            result = await self.db.execute(stmt)
            return list(result.scalars().all())
        except Exception as e:
            logger = get_logger("provider_management")
            logger.error(
                f"Error querying provider schedule: {e}",
                LogCategory.PROVIDER,
                exception=e
            )
            return []
    
    async def _check_provider_limit(self, clinic_id: str) -> bool:
        """Check if clinic has reached provider limit."""
        # Validate input
        if not clinic_id or not isinstance(clinic_id, str) or not clinic_id.strip():
            return False
        
        try:
            # Get clinic license to check provider limit
            from models.models import ClinicLicense
            license_result = await self.db.execute(select(ClinicLicense).where(ClinicLicense.clinic_id == clinic_id))
            license = license_result.scalar_one_or_none()
            
            if not license or not license.max_providers:
                return True  # No limit or unlimited
            
            # Count current providers
            # Note: This assumes we'll add clinic_id to Provider model
            # For now, we'll return True
            # provider_count = self.db.query(Provider).filter_by(clinic_id=clinic_id).count()
            # return provider_count < license.max_providers
            
            return True  # TODO: Implement when clinic_id is added to Provider model
        except Exception as e:
            logger = get_logger("provider_management")
            logger.error(
                f"Error checking provider limit: {e}",
                LogCategory.PROVIDER,
                exception=e
            )
            return False
    
    def _parse_business_hours(self, hours_str: str) -> tuple:
        """Parse business hours string supporting overnight shifts (e.g., '08:00-17:00' or '22:00-06:00')."""
        # Validate input
        if not hours_str or not isinstance(hours_str, str) or not hours_str.strip():
            from services.exceptions import ValidationError
            raise ValidationError(
                "business_hours",
                hours_str,
                "Hours string cannot be empty"
            )
        
        try:
            parts = hours_str.split('-')
            if len(parts) != 2:
                raise ValueError("Hours string must contain exactly one '-' separator")
            
            start_str, end_str = parts
            if not start_str or not end_str:
                raise ValueError("Start and end times cannot be empty")
            
            start_parts = start_str.split(':')
            end_parts = end_str.split(':')
            
            if len(start_parts) < 1 or len(end_parts) < 1:
                raise ValueError("Time format must include hour")
            
            start_hour = int(start_parts[0])
            end_hour = int(end_parts[0])
            
            # Validate hour ranges
            if start_hour < 0 or start_hour > 23:
                raise ValueError(f"Start hour must be between 0 and 23, got {start_hour}")
            
            if end_hour < 0 or end_hour > 23:
                raise ValueError(f"End hour must be between 0 and 23, got {end_hour}")
            
            # Return tuple with overnight flag
            is_overnight = end_hour <= start_hour
            return start_hour, end_hour, is_overnight
        except (ValueError, IndexError) as e:
            from services.exceptions import ValidationError
            raise ValidationError(
                "business_hours",
                hours_str,
                f"Invalid hours format. Expected format: 'HH:MM-HH:MM'. Error: {str(e)}"
            )
    
    async def _create_day_slots(self, provider_id: str, clinic_id: str, date: datetime,
                         start_hour: int, end_hour: int, duration_minutes: int, is_overnight: bool = False) -> List[AppointmentSlot]:
        """Create appointment slots for a single day, supporting overnight shifts."""
        import uuid
        
        slots = []
        current_time = date.replace(hour=start_hour, minute=0, second=0, microsecond=0)
        
        # Handle overnight shifts
        if is_overnight:
            end_time = (date + timedelta(days=1)).replace(
                hour=end_hour, minute=0, second=0, microsecond=0
            )
        else:
            end_time = date.replace(hour=end_hour, minute=0, second=0, microsecond=0)
        
        while current_time < end_time:
            # Use UUID to ensure unique slot IDs
            slot_id = f"SLOT_{provider_id}_{current_time.strftime('%Y%m%d_%H%M')}_{uuid.uuid4().hex[:8]}"
            
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
            service_name="ProviderManagementService"
        )
