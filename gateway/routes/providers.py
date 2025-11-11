"""
Provider Management API Routes

REST endpoints for provider operations including creation, scheduling, and availability.
Provides comprehensive provider management with appointment slot scheduling and availability tracking.
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query, Path
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta, timezone

from services.database import get_async_db
from services.provider_management import ProviderManagementService
from services.structured_logging import get_logger, LogCategory
from services.exceptions import (
    CallCenterAIException, ValidationError, ErrorCode
)
from models.schemas import (
    ProviderCreateRequest, ProviderUpdateRequest, ProviderResponse,
    ProviderSearchRequest, AppointmentSlotCreateRequest, AppointmentSlotResponse,
    SuccessResponse
)

# Atlantic Standard Time (UTC-4) - consistent with other services
AST = timezone(timedelta(hours=-4))

router = APIRouter(prefix="/providers", tags=["provider-management"])
logger = get_logger("provider_routes")


@router.post("/", response_model=ProviderResponse, status_code=status.HTTP_201_CREATED)
async def add_provider(
    clinic_id: str = Query(..., min_length=3, max_length=64, description="Clinic ID"),
    provider_data: ProviderCreateRequest = ...,
    db: AsyncSession = Depends(get_async_db)
):
    """
    Add a new provider to a clinic.
    
    This endpoint:
    - Creates a new provider record
    - Associates the provider with the specified clinic
    - Validates provider limits based on clinic license
    - Logs the creation in audit trail
    
    Args:
        clinic_id: ID of the clinic to add the provider to
        provider_data: Provider creation request data
        db: Database session
        
    Returns:
        ProviderResponse with created provider information
    """
    logger.info(
        f"Adding provider to clinic {clinic_id}",
        LogCategory.PROVIDER,
        extra_data={"clinic_id": clinic_id, "title": provider_data.title}
    )
    
    service = ProviderManagementService(db)
    
    # Convert ValueError to ValidationError for consistent error handling
    try:
        provider = await service.add_provider(clinic_id, provider_data)
    except ValueError as e:
        raise ValidationError("provider_data", str(e), str(e))
    
    logger.info(
        f"Provider {provider.provider_id} created successfully",
        LogCategory.PROVIDER,
        extra_data={
            "provider_id": provider.provider_id,
            "clinic_id": clinic_id,
            "specialty": provider.specialty
        }
    )
    
    return ProviderResponse.model_validate(provider)


@router.get("/", response_model=List[ProviderResponse])
async def list_providers(
    search: ProviderSearchRequest = Depends(),
    db: AsyncSession = Depends(get_async_db)
):
    """
    List providers with optional filtering and pagination.
    
    Supports filtering by:
    - Clinic ID
    - Specialty (partial match)
    - Availability status
    
    Includes pagination with limit and offset.
    
    Args:
        search: Search criteria and pagination parameters
        db: Database session
        
    Returns:
        List of ProviderResponse matching the search criteria
    """
    logger.info(
        "Listing providers",
        LogCategory.PROVIDER,
        extra_data={
            "clinic_id": search.clinic_id if search.clinic_id else None,
            "specialty": search.specialty if search.specialty else None,
            "limit": search.limit,
            "offset": search.offset
        }
    )
    
    service = ProviderManagementService(db)
    providers = await service.list_providers(search)
    
    logger.info(
        f"Found {len(providers)} providers",
        LogCategory.PROVIDER,
        extra_data={"count": len(providers)}
    )
    
    return [ProviderResponse.model_validate(provider) for provider in providers]


@router.get("/{provider_id}", response_model=ProviderResponse)
async def get_provider(
    provider_id: str = Path(..., min_length=3, max_length=64, description="Provider ID"),
    db: AsyncSession = Depends(get_async_db)
):
    """
    Get a specific provider by ID.
    
    Returns complete provider information including:
    - Basic provider details
    - Specialty and credentials
    - Availability status
    - License information
    
    Args:
        provider_id: Provider ID to retrieve
        db: Database session
        
    Returns:
        ProviderResponse with provider information
    """
    logger.info(
        f"Getting provider {provider_id}",
        LogCategory.PROVIDER,
        extra_data={"provider_id": provider_id}
    )
    
    service = ProviderManagementService(db)
    provider = await service.get_provider(provider_id)
    
    if not provider:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Provider {provider_id} not found"
        )
    
    return ProviderResponse.model_validate(provider)


@router.put("/{provider_id}", response_model=ProviderResponse)
async def update_provider(
    provider_id: str = Path(..., min_length=3, max_length=64, description="Provider ID"),
    updates: ProviderUpdateRequest = ...,
    db: AsyncSession = Depends(get_async_db)
):
    """
    Update provider information.
    
    Supports updating:
    - Basic provider information
    - Specialty and credentials
    - Availability status
    - License information
    
    All changes are logged in the audit trail.
    
    Args:
        provider_id: Provider ID to update
        updates: Update request data
        db: Database session
        
    Returns:
        ProviderResponse with updated provider information
    """
    logger.info(
        f"Updating provider {provider_id}",
        LogCategory.PROVIDER,
        extra_data={
            "provider_id": provider_id,
            "fields_updated": list(updates.model_dump(exclude_unset=True).keys())
        }
    )
    
    service = ProviderManagementService(db)
    
    # Convert ValueError to ValidationError for consistent error handling
    try:
        provider = await service.update_provider(provider_id, updates)
    except ValueError as e:
        raise ValidationError("updates", str(e), str(e))
    
    if not provider:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Provider {provider_id} not found"
        )
    
    logger.info(
        f"Provider {provider_id} updated successfully",
        LogCategory.PROVIDER,
        extra_data={"provider_id": provider_id}
    )
    
    return ProviderResponse.model_validate(provider)


@router.put("/{provider_id}/availability", response_model=SuccessResponse)
async def set_provider_availability(
    provider_id: str = Path(..., min_length=3, max_length=64, description="Provider ID"),
    is_available: bool = Query(..., description="New availability status"),
    db: AsyncSession = Depends(get_async_db)
):
    """
    Set provider availability status.
    
    This operation:
    - Updates the provider's availability status
    - Logs the change in audit trail
    - Affects appointment booking availability
    
    Args:
        provider_id: Provider ID to update
        is_available: New availability status
        db: Database session
        
    Returns:
        SuccessResponse with confirmation message
    """
    availability_status = "available" if is_available else "unavailable"
    logger.info(
        f"Setting provider {provider_id} availability to {availability_status}",
        LogCategory.PROVIDER,
        extra_data={"provider_id": provider_id, "is_available": is_available}
    )
    
    service = ProviderManagementService(db)
    success = await service.set_provider_availability(provider_id, is_available)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Provider {provider_id} not found"
        )
    
    logger.info(
        f"Provider {provider_id} availability updated to {availability_status}",
        LogCategory.PROVIDER,
        extra_data={"provider_id": provider_id, "is_available": is_available}
    )
    
    return SuccessResponse(
        message=f"Provider {provider_id} set to {availability_status}"
    )


@router.post("/{provider_id}/slots", response_model=List[AppointmentSlotResponse])
async def create_appointment_slots(
    provider_id: str = Path(..., min_length=3, max_length=64, description="Provider ID"),
    clinic_id: str = Query(..., min_length=3, max_length=64, description="Clinic ID"),
    start_date: datetime = Query(..., description="Start date for slot creation"),
    end_date: datetime = Query(..., description="End date for slot creation"),
    duration_minutes: int = Query(60, ge=15, le=480, description="Duration of each slot in minutes"),
    business_hours: Optional[Dict[str, str]] = None,
    db: AsyncSession = Depends(get_async_db)
):
    """
    Create appointment slots for a provider within a date range.
    
    This endpoint:
    - Creates appointment slots based on business hours
    - Supports custom business hours or uses defaults
    - Validates date ranges and duration
    - Creates slots for each day in the range
    
    Default business hours:
    - Monday-Friday: 8:00 AM - 5:00 PM
    - Saturday: 9:00 AM - 1:00 PM
    - Sunday: CLOSED
    
    Args:
        provider_id: Provider ID to create slots for
        clinic_id: Clinic ID
        start_date: Start date for slot creation
        end_date: End date for slot creation
        duration_minutes: Duration of each slot (15-480 minutes)
        business_hours: Optional custom business hours configuration
        db: Database session
        
    Returns:
        List of AppointmentSlotResponse for created slots
    """
    # Validate date range
    if end_date <= start_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="end_date must be after start_date"
        )
    
    # Validate maximum date range (365 days)
    if (end_date - start_date).days > 365:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Date range cannot exceed 365 days"
        )
    
    logger.info(
        f"Creating appointment slots for provider {provider_id}",
        LogCategory.PROVIDER,
        extra_data={
            "provider_id": provider_id,
            "clinic_id": clinic_id,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "duration_minutes": duration_minutes
        }
    )
    
    service = ProviderManagementService(db)
    
    # Convert ValueError to ValidationError for consistent error handling
    try:
        slots = await service.create_appointment_slots(
            provider_id, clinic_id, start_date, end_date, duration_minutes, business_hours
        )
    except ValueError as e:
        raise ValidationError("slot_creation", str(e), str(e))
    
    logger.info(
        f"Created {len(slots)} appointment slots for provider {provider_id}",
        LogCategory.PROVIDER,
        extra_data={
            "provider_id": provider_id,
            "slots_created": len(slots)
        }
    )
    
    return [AppointmentSlotResponse.model_validate(slot) for slot in slots]


@router.get("/{provider_id}/slots/available", response_model=List[AppointmentSlotResponse])
async def get_available_slots(
    provider_id: str = Path(..., min_length=3, max_length=64, description="Provider ID"),
    start_date: datetime = Query(..., description="Start date for search"),
    end_date: datetime = Query(..., description="End date for search"),
    db: AsyncSession = Depends(get_async_db)
):
    """
    Get available appointment slots for a provider.
    
    Returns all available (unbooked) appointment slots
    within the specified date range.
    
    Args:
        provider_id: Provider ID to get slots for
        start_date: Start date for search
        end_date: End date for search
        db: Database session
        
    Returns:
        List of AppointmentSlotResponse for available slots
    """
    # Validate date range
    if end_date <= start_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="end_date must be after start_date"
        )
    
    # Validate maximum date range (365 days)
    if (end_date - start_date).days > 365:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Date range cannot exceed 365 days"
        )
    
    logger.info(
        f"Getting available slots for provider {provider_id}",
        LogCategory.PROVIDER,
        extra_data={
            "provider_id": provider_id,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat()
        }
    )
    
    service = ProviderManagementService(db)
    slots = await service.get_available_slots(provider_id, start_date, end_date)
    
    logger.info(
        f"Found {len(slots)} available slots for provider {provider_id}",
        LogCategory.PROVIDER,
        extra_data={"provider_id": provider_id, "slots_count": len(slots)}
    )
    
    return [AppointmentSlotResponse.model_validate(slot) for slot in slots]


@router.get("/{provider_id}/schedule/{date}", response_model=List[AppointmentSlotResponse])
async def get_provider_schedule(
    provider_id: str = Path(..., min_length=3, max_length=64, description="Provider ID"),
    date: str = Path(..., description="Date in YYYY-MM-DD format"),
    db: AsyncSession = Depends(get_async_db)
):
    """
    Get provider's schedule for a specific date.
    
    Returns all appointment slots (booked and available)
    for the specified date.
    
    Args:
        provider_id: Provider ID to get schedule for
        date: Date in YYYY-MM-DD format
        db: Database session
        
    Returns:
        List of AppointmentSlotResponse for the date
    """
    # Parse date string to datetime
    try:
        parsed_date = datetime.fromisoformat(date).replace(hour=0, minute=0, second=0, microsecond=0)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid date format: {date}. Expected YYYY-MM-DD format."
        )
    
    logger.info(
        f"Getting schedule for provider {provider_id} on {date}",
        LogCategory.PROVIDER,
        extra_data={
            "provider_id": provider_id,
            "date": date
        }
    )
    
    service = ProviderManagementService(db)
    slots = await service.get_provider_schedule(provider_id, parsed_date)
    
    logger.info(
        f"Found {len(slots)} slots for provider {provider_id} on {date}",
        LogCategory.PROVIDER,
        extra_data={
            "provider_id": provider_id,
            "date": date,
            "slots_count": len(slots)
        }
    )
    
    return [AppointmentSlotResponse.model_validate(slot) for slot in slots]


@router.put("/slots/{slot_id}/book", response_model=SuccessResponse)
async def book_appointment_slot(
    slot_id: str = Path(..., min_length=3, max_length=64, description="Appointment slot ID"),
    appointment_id: str = Query(..., min_length=3, max_length=64, description="Appointment ID"),
    db: AsyncSession = Depends(get_async_db)
):
    """
    Book an appointment slot.
    
    This operation:
    - Marks the slot as booked
    - Associates the slot with the appointment
    - Logs the booking in audit trail
    - Validates slot availability
    
    Args:
        slot_id: Appointment slot ID to book
        appointment_id: Appointment ID to associate with the slot
        db: Database session
        
    Returns:
        SuccessResponse with confirmation message
    """
    logger.info(
        f"Booking slot {slot_id} for appointment {appointment_id}",
        LogCategory.PROVIDER,
        extra_data={"slot_id": slot_id, "appointment_id": appointment_id}
    )
    
    service = ProviderManagementService(db)
    success = await service.book_appointment_slot(slot_id, appointment_id)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Slot {slot_id} is not available for booking"
        )
    
    logger.info(
        f"Slot {slot_id} booked successfully for appointment {appointment_id}",
        LogCategory.PROVIDER,
        extra_data={"slot_id": slot_id, "appointment_id": appointment_id}
    )
    
    return SuccessResponse(
        message=f"Slot {slot_id} booked for appointment {appointment_id}"
    )


@router.put("/slots/{slot_id}/release", response_model=SuccessResponse)
async def release_appointment_slot(
    slot_id: str = Path(..., min_length=3, max_length=64, description="Appointment slot ID"),
    db: AsyncSession = Depends(get_async_db)
):
    """
    Release a booked appointment slot.
    
    This operation:
    - Marks the slot as available
    - Removes the appointment association
    - Logs the release in audit trail
    
    Args:
        slot_id: Appointment slot ID to release
        db: Database session
        
    Returns:
        SuccessResponse with confirmation message
    """
    logger.info(
        f"Releasing slot {slot_id}",
        LogCategory.PROVIDER,
        extra_data={"slot_id": slot_id}
    )
    
    service = ProviderManagementService(db)
    success = await service.release_appointment_slot(slot_id)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Slot {slot_id} not found"
        )
    
    logger.info(
        f"Slot {slot_id} released successfully",
        LogCategory.PROVIDER,
        extra_data={"slot_id": slot_id}
    )
    
    return SuccessResponse(
        message=f"Slot {slot_id} released and made available"
    )


@router.get("/{provider_id}/stats", response_model=Dict[str, Any])
async def get_provider_stats(
    provider_id: str = Path(..., min_length=3, max_length=64, description="Provider ID"),
    db: AsyncSession = Depends(get_async_db)
):
    """
    Get provider statistics and information.
    
    Returns comprehensive statistics including:
    - Basic provider information
    - Availability status
    - Appointment slot statistics
    - Schedule information
    
    Args:
        provider_id: Provider ID to get statistics for
        db: Database session
        
    Returns:
        Dictionary with provider information and statistics
    """
    logger.info(
        f"Getting statistics for provider {provider_id}",
        LogCategory.PROVIDER,
        extra_data={"provider_id": provider_id}
    )
    
    service = ProviderManagementService(db)
    provider = await service.get_provider(provider_id)
    
    if not provider:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Provider {provider_id} not found"
        )
    
    # Use timezone-aware datetime for consistency
    now = datetime.now(AST)
    end_date = now + timedelta(days=30)
    
    # Get slot statistics for the next 30 days
    available_slots = await service.get_available_slots(provider_id, now, end_date)
    
    # Get today's schedule
    today_schedule = await service.get_provider_schedule(provider_id, now)
    
    stats = {
        "provider_id": provider_id,
        "name_token": provider.name_token,
        "title": provider.title,
        "specialty": provider.specialty,
        "email": provider.email,
        "is_available": provider.is_available,
        "statistics": {
            "available_slots_next_30_days": len(available_slots),
            "today_schedule_slots": len(today_schedule),
            "booked_slots_today": len([s for s in today_schedule if s.is_booked == "yes"])
        },
        "created_at": provider.created_at.isoformat() if provider.created_at else None,
        "updated_at": provider.updated_at.isoformat() if provider.updated_at else None
    }
    
    logger.info(
        f"Retrieved statistics for provider {provider_id}",
        LogCategory.PROVIDER,
        extra_data={
            "provider_id": provider_id,
            "available_slots": len(available_slots),
            "today_slots": len(today_schedule)
        }
    )
    
    return stats
