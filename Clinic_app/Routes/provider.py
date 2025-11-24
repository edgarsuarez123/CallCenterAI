"""
Admin routes for provider management.

Handles provider CRUD operations and time blocking.
Routes handle database operations directly (no service layer).
"""

import logging
from typing import Optional, List, Any, Dict
from uuid import UUID
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, delete
from sqlalchemy.exc import IntegrityError
from pydantic import BaseModel, field_validator

from Clinic_app.common.database import get_db
from Clinic_app.data.models.provider import Provider
from Clinic_app.data.models.clinic import Clinic
from Clinic_app.data.models.availability_slot import AvailabilitySlot
from Clinic_app.data.enums import SlotStatus, SlotSource
from Clinic_app.services.google_calendar import (
    GoogleCalendarService,
    GoogleCalendarNotFoundError,
    GoogleCalendarAuthError
)

logger = logging.getLogger(__name__)

# Router setup
provider_router = APIRouter(prefix="/admin", tags=["admin", "providers"])

# Validation constants
DEFAULT_BOOKING_DURATION_MINS = 30
DEFAULT_CAPACITY = 1

# Validation helper functions
def validate_timezone(timezone: str) -> bool:
    """
    Validate IANA timezone format (basic check).
    
    Args:
        timezone: Timezone string to validate
        
    Returns:
        True if format looks valid, False otherwise
    """
    # Basic validation: should contain "/" (e.g., "America/New_York")
    # More thorough validation can use pytz or zoneinfo, but basic check is fine for Phase 1
    if not timezone or len(timezone) < 3:
        return False
    # Check for common IANA timezone format: Continent/City
    parts = timezone.split("/")
    if len(parts) < 2:
        return False
    return True


# Error helper functions (reuse pattern from admin.py)
def raise_not_found(resource: str, id: UUID):
    """Raise 404 with standardized format."""
    raise HTTPException(
        status_code=404,
        detail={
            "code": "NOT_FOUND",
            "message": f"{resource} not found",
            "resource": resource,
            "id": str(id)
        }
    )


def raise_validation_error(message: str, field: str = None):
    """Raise 400 with validation error format."""
    detail = {
        "code": "VALIDATION_ERROR",
        "message": message
    }
    if field:
        detail["field"] = field
    raise HTTPException(status_code=400, detail=detail)


def raise_conflict_error(message: str, code: str = "CONFLICT"):
    """Raise 409 for unique constraint violations."""
    raise HTTPException(
        status_code=409,
        detail={
            "code": code,
            "message": message
        }
    )


# Pydantic Models

class APIResponse(BaseModel):
    """Standardized API response wrapper."""
    success: bool
    data: Optional[Any] = None
    error: Optional[Dict[str, Any]] = None
    message: Optional[str] = None


class ProviderBase(BaseModel):
    """Base provider model."""
    display_name: str
    google_calendar_id: Optional[str] = None
    timezone: str
    booking_duration_mins: int = DEFAULT_BOOKING_DURATION_MINS
    capacity: int = DEFAULT_CAPACITY
    active: bool = True
    external_id: Optional[str] = None

    @field_validator('timezone')
    @classmethod
    def validate_timezone(cls, v):
        if not validate_timezone(v):
            raise ValueError("timezone must be a valid IANA timezone (e.g., 'America/New_York')")
        return v

    @field_validator('booking_duration_mins')
    @classmethod
    def validate_booking_duration(cls, v):
        if v < 1:
            raise ValueError("booking_duration_mins must be a positive integer (>= 1)")
        return v

    @field_validator('capacity')
    @classmethod
    def validate_capacity(cls, v):
        if v < 1:
            raise ValueError("capacity must be a positive integer (>= 1)")
        return v

    @field_validator('display_name')
    @classmethod
    def validate_display_name(cls, v):
        if not v or not v.strip():
            raise ValueError("display_name is required and cannot be empty")
        return v.strip()

    @field_validator('google_calendar_id')
    @classmethod
    def validate_google_calendar_id(cls, v):
        if v is not None and not v.strip():
            raise ValueError("google_calendar_id cannot be empty string if provided")
        return v.strip() if v else None


class ProviderCreateRequest(ProviderBase):
    """Request model for creating a provider."""
    pass


class ProviderUpdateRequest(BaseModel):
    """Request model for updating a provider."""
    display_name: Optional[str] = None
    google_calendar_id: Optional[str] = None
    timezone: Optional[str] = None
    booking_duration_mins: Optional[int] = None
    capacity: Optional[int] = None
    active: Optional[bool] = None
    external_id: Optional[str] = None

    @field_validator('timezone')
    @classmethod
    def validate_timezone(cls, v):
        if v is not None and not validate_timezone(v):
            raise ValueError("timezone must be a valid IANA timezone (e.g., 'America/New_York')")
        return v

    @field_validator('booking_duration_mins')
    @classmethod
    def validate_booking_duration(cls, v):
        if v is not None and v < 1:
            raise ValueError("booking_duration_mins must be a positive integer (>= 1)")
        return v

    @field_validator('capacity')
    @classmethod
    def validate_capacity(cls, v):
        if v is not None and v < 1:
            raise ValueError("capacity must be a positive integer (>= 1)")
        return v

    @field_validator('display_name')
    @classmethod
    def validate_display_name(cls, v):
        if v is not None and (not v or not v.strip()):
            raise ValueError("display_name cannot be empty")
        return v.strip() if v else None

    @field_validator('google_calendar_id')
    @classmethod
    def validate_google_calendar_id(cls, v):
        if v is not None and not v.strip():
            raise ValueError("google_calendar_id cannot be empty string if provided")
        return v.strip() if v else None


class ProviderResponse(BaseModel):
    """Response model for provider data."""
    id: UUID
    clinic_id: UUID
    display_name: str
    google_calendar_id: Optional[str]
    timezone: str
    booking_duration_mins: int
    capacity: int
    active: bool
    external_id: Optional[str]

    class Config:
        from_attributes = True


class BlockTimeRequest(BaseModel):
    """Request model for blocking time."""
    start_datetime: datetime
    end_datetime: datetime

    @field_validator('end_datetime')
    @classmethod
    def validate_end_after_start(cls, v, info):
        if 'start_datetime' in info.data and v <= info.data['start_datetime']:
            raise ValueError("end_datetime must be after start_datetime")
        return v


class UnblockTimeRequest(BaseModel):
    """Request model for unblocking time."""
    start_datetime: datetime
    end_datetime: datetime

    @field_validator('end_datetime')
    @classmethod
    def validate_end_after_start(cls, v, info):
        if 'start_datetime' in info.data and v <= info.data['start_datetime']:
            raise ValueError("end_datetime must be after start_datetime")
        return v


# Route Handlers

@provider_router.post("/clinics/{clinic_id}/providers", response_model=APIResponse)
async def create_provider(
    clinic_id: UUID,
    request: ProviderCreateRequest,
    db: AsyncSession = Depends(get_db)
) -> APIResponse:
    """Create a new provider for a clinic."""
    try:
        logger.info(f"Creating provider: clinic_id={clinic_id}, display_name={request.display_name}")
        
        # Check clinic exists
        clinic = await db.get(Clinic, clinic_id)
        if not clinic:
            raise_not_found("Clinic", clinic_id)
        
        # Validate Google Calendar access if provided
        if request.google_calendar_id:
            try:
                await GoogleCalendarService.validate_calendar_access(
                    calendar_id=request.google_calendar_id,
                    clinic_id=clinic_id,
                    db=db
                )
            except GoogleCalendarNotFoundError as e:
                logger.warning(f"Google Calendar validation failed: calendar_id={request.google_calendar_id}, clinic_id={clinic_id}")
                raise_validation_error(f"Google Calendar not accessible: {str(e)}", "google_calendar_id")
            except GoogleCalendarAuthError as e:
                logger.warning(f"Google Calendar auth failed: calendar_id={request.google_calendar_id}, clinic_id={clinic_id}")
                raise_validation_error(f"Google Calendar authentication failed: {str(e)}", "google_calendar_id")
        
        # Create provider
        provider = Provider(
            clinic_id=clinic_id,
            display_name=request.display_name,
            google_calendar_id=request.google_calendar_id,
            timezone=request.timezone,
            booking_duration_mins=request.booking_duration_mins,
            capacity=request.capacity,
            active=request.active,
            external_id=request.external_id
        )
        db.add(provider)
        await db.commit()
        
        logger.info(f"Provider created: provider_id={provider.id}, clinic_id={clinic_id}, display_name={provider.display_name}")
        
        return APIResponse(
            success=True,
            data=ProviderResponse.model_validate(provider),
            message="Provider created successfully"
        )
        
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError as e:
        await db.rollback()
        logger.error(f"Database integrity error creating provider: {str(e)}", exc_info=True)
        raise_conflict_error("Database constraint violation", "CONSTRAINT_VIOLATION")
    except Exception as e:
        await db.rollback()
        logger.error(f"Unexpected error creating provider: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "code": "INTERNAL_ERROR",
                "message": "Failed to create provider"
            }
        )


@provider_router.get("/providers/{provider_id}", response_model=APIResponse)
async def get_provider(
    provider_id: UUID,
    db: AsyncSession = Depends(get_db)
) -> APIResponse:
    """Get provider by ID."""
    provider = await db.get(Provider, provider_id)
    if not provider:
        raise_not_found("Provider", provider_id)
    
    return APIResponse(
        success=True,
        data=ProviderResponse.model_validate(provider)
    )


@provider_router.put("/providers/{provider_id}", response_model=APIResponse)
async def update_provider(
    provider_id: UUID,
    request: ProviderUpdateRequest,
    db: AsyncSession = Depends(get_db)
) -> APIResponse:
    """Update provider."""
    provider = await db.get(Provider, provider_id)
    if not provider:
        raise_not_found("Provider", provider_id)
    
    try:
        logger.info(f"Updating provider: provider_id={provider_id}")
        
        # Check if google_calendar_id is being updated
        update_data = request.model_dump(exclude_unset=True)
        
        if "google_calendar_id" in update_data and update_data["google_calendar_id"]:
            # Validate new calendar access
            try:
                await GoogleCalendarService.validate_calendar_access(
                    calendar_id=update_data["google_calendar_id"],
                    clinic_id=provider.clinic_id,
                    db=db
                )
            except GoogleCalendarNotFoundError as e:
                logger.warning(f"Google Calendar validation failed: calendar_id={update_data['google_calendar_id']}, provider_id={provider_id}")
                raise_validation_error(f"Google Calendar not accessible: {str(e)}", "google_calendar_id")
            except GoogleCalendarAuthError as e:
                logger.warning(f"Google Calendar auth failed: calendar_id={update_data['google_calendar_id']}, provider_id={provider_id}")
                raise_validation_error(f"Google Calendar authentication failed: {str(e)}", "google_calendar_id")
        
        # Update fields
        for field, value in update_data.items():
            setattr(provider, field, value)
        
        await db.commit()
        logger.info(f"Provider updated: provider_id={provider_id}")
        
        return APIResponse(
            success=True,
            data=ProviderResponse.model_validate(provider),
            message="Provider updated successfully"
        )
        
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError as e:
        await db.rollback()
        logger.error(f"Database integrity error updating provider: {str(e)}", exc_info=True)
        raise_conflict_error("Database constraint violation", "CONSTRAINT_VIOLATION")
    except Exception as e:
        await db.rollback()
        logger.error(f"Unexpected error updating provider: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "code": "INTERNAL_ERROR",
                "message": "Failed to update provider"
            }
        )


@provider_router.get("/clinics/{clinic_id}/providers", response_model=APIResponse)
async def list_providers(
    clinic_id: UUID,
    active_only: bool = Query(False, description="Filter to only active providers"),
    db: AsyncSession = Depends(get_db)
) -> APIResponse:
    """List providers for a clinic."""
    # Check clinic exists
    clinic = await db.get(Clinic, clinic_id)
    if not clinic:
        raise_not_found("Clinic", clinic_id)
    
    # Build query
    stmt = select(Provider).where(Provider.clinic_id == clinic_id)
    if active_only:
        stmt = stmt.where(Provider.active == True)
    
    result = await db.execute(stmt)
    providers = result.scalars().all()
    
    logger.info(f"Listed providers: clinic_id={clinic_id}, count={len(providers)}, active_only={active_only}")
    
    return APIResponse(
        success=True,
        data=[ProviderResponse.model_validate(provider) for provider in providers]
    )


@provider_router.post("/providers/{provider_id}/block-time", response_model=APIResponse)
async def block_time(
    provider_id: UUID,
    request: BlockTimeRequest,
    db: AsyncSession = Depends(get_db)
) -> APIResponse:
    """Block time periods for a provider."""
    provider = await db.get(Provider, provider_id)
    if not provider:
        raise_not_found("Provider", provider_id)
    
    try:
        logger.info(f"Blocking time: provider_id={provider_id}, start={request.start_datetime}, end={request.end_datetime}")
        
        # Check if slot already exists
        stmt = select(AvailabilitySlot).where(
            and_(
                AvailabilitySlot.provider_id == provider_id,
                AvailabilitySlot.slot_start == request.start_datetime,
                AvailabilitySlot.slot_end == request.end_datetime
            )
        )
        result = await db.execute(stmt)
        existing = result.scalar_one_or_none()
        
        if existing:
            # Update existing slot to BLOCKED
            existing.status = SlotStatus.BLOCKED
            existing.source = SlotSource.GCAL  # Mark as manually blocked
            slot = existing
        else:
            # Create new blocked slot
            slot = AvailabilitySlot(
                clinic_id=provider.clinic_id,
                provider_id=provider_id,
                slot_start=request.start_datetime,
                slot_end=request.end_datetime,
                status=SlotStatus.BLOCKED,
                source=SlotSource.GCAL
            )
            db.add(slot)
        
        await db.commit()
        logger.info(f"Time blocked: provider_id={provider_id}, slot_id={slot.id}")
        
        return APIResponse(
            success=True,
            data={
                "id": str(slot.id),
                "provider_id": str(provider_id),
                "slot_start": slot.slot_start.isoformat(),
                "slot_end": slot.slot_end.isoformat(),
                "status": slot.status.value
            },
            message="Time blocked successfully"
        )
        
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError as e:
        await db.rollback()
        logger.error(f"Database integrity error blocking time: {str(e)}", exc_info=True)
        raise_conflict_error("Database constraint violation", "CONSTRAINT_VIOLATION")
    except Exception as e:
        await db.rollback()
        logger.error(f"Unexpected error blocking time: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "code": "INTERNAL_ERROR",
                "message": "Failed to block time"
            }
        )


@provider_router.post("/providers/{provider_id}/unblock-time", response_model=APIResponse)
async def unblock_time(
    provider_id: UUID,
    request: UnblockTimeRequest,
    db: AsyncSession = Depends(get_db)
) -> APIResponse:
    """Unblock time periods for a provider."""
    provider = await db.get(Provider, provider_id)
    if not provider:
        raise_not_found("Provider", provider_id)
    
    try:
        logger.info(f"Unblocking time: provider_id={provider_id}, start={request.start_datetime}, end={request.end_datetime}")
        
        # Find matching blocked slots in the time range
        # Slots that overlap with the requested time range
        stmt = select(AvailabilitySlot).where(
            and_(
                AvailabilitySlot.provider_id == provider_id,
                AvailabilitySlot.status == SlotStatus.BLOCKED,
                or_(
                    # Slot starts within range
                    and_(
                        AvailabilitySlot.slot_start >= request.start_datetime,
                        AvailabilitySlot.slot_start < request.end_datetime
                    ),
                    # Slot ends within range
                    and_(
                        AvailabilitySlot.slot_end > request.start_datetime,
                        AvailabilitySlot.slot_end <= request.end_datetime
                    ),
                    # Slot completely contains range
                    and_(
                        AvailabilitySlot.slot_start <= request.start_datetime,
                        AvailabilitySlot.slot_end >= request.end_datetime
                    ),
                    # Range completely contains slot
                    and_(
                        AvailabilitySlot.slot_start >= request.start_datetime,
                        AvailabilitySlot.slot_end <= request.end_datetime
                    )
                )
            )
        )
        result = await db.execute(stmt)
        blocked_slots = result.scalars().all()
        
        if not blocked_slots:
            return APIResponse(
                success=True,
                data={"unblocked_count": 0},
                message="No blocked slots found in the specified time range"
            )
        
        # Delete the blocked slots
        slot_ids = [slot.id for slot in blocked_slots]
        unblocked_count = len(slot_ids)
        
        if slot_ids:
            stmt = delete(AvailabilitySlot).where(
                AvailabilitySlot.id.in_(slot_ids)
            )
            await db.execute(stmt)
        
        await db.commit()
        logger.info(f"Time unblocked: provider_id={provider_id}, unblocked_count={unblocked_count}")
        
        return APIResponse(
            success=True,
            data={"unblocked_count": unblocked_count},
            message=f"Unblocked {unblocked_count} time slot(s)"
        )
        
    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Unexpected error unblocking time: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "code": "INTERNAL_ERROR",
                "message": "Failed to unblock time"
            }
        )

