"""
Provider Management API Routes
REST endpoints for provider operations including creation, scheduling, and availability.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta

from services.database import get_db
from services.provider_management import ProviderManagementService
from models.schemas import (
    ProviderCreateRequest, ProviderUpdateRequest, ProviderResponse,
    ProviderSearchRequest, AppointmentSlotCreateRequest, AppointmentSlotResponse,
    SuccessResponse, ErrorResponse
)

router = APIRouter(prefix="/v1/providers", tags=["provider-management"])


@router.post("/", response_model=ProviderResponse, status_code=status.HTTP_201_CREATED)
def add_provider(
    clinic_id: str,
    provider_data: ProviderCreateRequest,
    db: Session = Depends(get_db)
):
    """
    Add a new provider to a clinic.
    
    This endpoint:
    - Creates a new provider record
    - Associates the provider with the specified clinic
    - Validates provider limits based on clinic license
    - Logs the creation in audit trail
    """
    try:
        service = ProviderManagementService(db)
        provider = service.add_provider(clinic_id, provider_data)
        return ProviderResponse.from_orm(provider)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to add provider: {str(e)}"
        )


@router.get("/", response_model=List[ProviderResponse])
def list_providers(
    search: ProviderSearchRequest = Depends(),
    db: Session = Depends(get_db)
):
    """
    List providers with optional filtering and pagination.
    
    Supports filtering by:
    - Clinic ID
    - Specialty (partial match)
    - Availability status
    
    Includes pagination with limit and offset.
    """
    try:
        service = ProviderManagementService(db)
        providers = service.list_providers(search)
        return [ProviderResponse.from_orm(provider) for provider in providers]
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list providers: {str(e)}"
        )


@router.get("/{provider_id}", response_model=ProviderResponse)
def get_provider(
    provider_id: str,
    db: Session = Depends(get_db)
):
    """
    Get a specific provider by ID.
    
    Returns complete provider information including:
    - Basic provider details
    - Specialty and credentials
    - Availability status
    - License information
    """
    try:
        service = ProviderManagementService(db)
        provider = service.get_provider(provider_id)
        
        if not provider:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Provider {provider_id} not found"
            )
        
        return ProviderResponse.from_orm(provider)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get provider: {str(e)}"
        )


@router.put("/{provider_id}", response_model=ProviderResponse)
def update_provider(
    provider_id: str,
    updates: ProviderUpdateRequest,
    db: Session = Depends(get_db)
):
    """
    Update provider information.
    
    Supports updating:
    - Basic provider information
    - Specialty and credentials
    - Availability status
    - License information
    
    All changes are logged in the audit trail.
    """
    try:
        service = ProviderManagementService(db)
        provider = service.update_provider(provider_id, updates)
        
        if not provider:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Provider {provider_id} not found"
            )
        
        return ProviderResponse.from_orm(provider)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update provider: {str(e)}"
        )


@router.put("/{provider_id}/availability", response_model=SuccessResponse)
def set_provider_availability(
    provider_id: str,
    is_available: bool,
    db: Session = Depends(get_db)
):
    """
    Set provider availability status.
    
    This operation:
    - Updates the provider's availability status
    - Logs the change in audit trail
    - Affects appointment booking availability
    """
    try:
        service = ProviderManagementService(db)
        success = service.set_provider_availability(provider_id, is_available)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Provider {provider_id} not found"
            )
        
        status_text = "available" if is_available else "unavailable"
        return SuccessResponse(
            message=f"Provider {provider_id} set to {status_text}"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update provider availability: {str(e)}"
        )


@router.post("/{provider_id}/slots", response_model=List[AppointmentSlotResponse])
def create_appointment_slots(
    provider_id: str,
    clinic_id: str,
    start_date: datetime,
    end_date: datetime,
    duration_minutes: int = 60,
    business_hours: Optional[Dict[str, str]] = None,
    db: Session = Depends(get_db)
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
    """
    try:
        service = ProviderManagementService(db)
        slots = service.create_appointment_slots(
            provider_id, clinic_id, start_date, end_date, duration_minutes, business_hours
        )
        return [AppointmentSlotResponse.from_orm(slot) for slot in slots]
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create appointment slots: {str(e)}"
        )


@router.get("/{provider_id}/slots/available", response_model=List[AppointmentSlotResponse])
def get_available_slots(
    provider_id: str,
    start_date: datetime,
    end_date: datetime,
    db: Session = Depends(get_db)
):
    """
    Get available appointment slots for a provider.
    
    Returns all available (unbooked) appointment slots
    within the specified date range.
    """
    try:
        service = ProviderManagementService(db)
        slots = service.get_available_slots(provider_id, start_date, end_date)
        return [AppointmentSlotResponse.from_orm(slot) for slot in slots]
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get available slots: {str(e)}"
        )


@router.get("/{provider_id}/schedule/{date}", response_model=List[AppointmentSlotResponse])
def get_provider_schedule(
    provider_id: str,
    date: datetime,
    db: Session = Depends(get_db)
):
    """
    Get provider's schedule for a specific date.
    
    Returns all appointment slots (booked and available)
    for the specified date.
    """
    try:
        service = ProviderManagementService(db)
        slots = service.get_provider_schedule(provider_id, date)
        return [AppointmentSlotResponse.from_orm(slot) for slot in slots]
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get provider schedule: {str(e)}"
        )


@router.put("/slots/{slot_id}/book", response_model=SuccessResponse)
def book_appointment_slot(
    slot_id: str,
    appointment_id: str,
    db: Session = Depends(get_db)
):
    """
    Book an appointment slot.
    
    This operation:
    - Marks the slot as booked
    - Associates the slot with the appointment
    - Logs the booking in audit trail
    - Validates slot availability
    """
    try:
        service = ProviderManagementService(db)
        success = service.book_appointment_slot(slot_id, appointment_id)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Slot {slot_id} is not available for booking"
            )
        
        return SuccessResponse(
            message=f"Slot {slot_id} booked for appointment {appointment_id}"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to book appointment slot: {str(e)}"
        )


@router.put("/slots/{slot_id}/release", response_model=SuccessResponse)
def release_appointment_slot(
    slot_id: str,
    db: Session = Depends(get_db)
):
    """
    Release a booked appointment slot.
    
    This operation:
    - Marks the slot as available
    - Removes the appointment association
    - Logs the release in audit trail
    """
    try:
        service = ProviderManagementService(db)
        success = service.release_appointment_slot(slot_id)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Slot {slot_id} not found"
            )
        
        return SuccessResponse(
            message=f"Slot {slot_id} released and made available"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to release appointment slot: {str(e)}"
        )


@router.get("/{provider_id}/stats", response_model=dict)
def get_provider_stats(
    provider_id: str,
    db: Session = Depends(get_db)
):
    """
    Get provider statistics and information.
    
    Returns comprehensive statistics including:
    - Basic provider information
    - Availability status
    - Appointment slot statistics
    - Schedule information
    """
    try:
        service = ProviderManagementService(db)
        provider = service.get_provider(provider_id)
        
        if not provider:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Provider {provider_id} not found"
            )
        
        # Get slot statistics for the next 30 days
        end_date = datetime.now() + timedelta(days=30)
        available_slots = service.get_available_slots(provider_id, datetime.now(), end_date)
        
        # Get today's schedule
        today_schedule = service.get_provider_schedule(provider_id, datetime.now())
        
        return {
            "provider_id": provider_id,
            "name_token": provider.name_token,
            "title": provider.title,
            "specialty": provider.specialty,
            "license_number": provider.license_number,
            "npi_number": provider.npi_number,
            "is_available": provider.is_available,
            "statistics": {
                "available_slots_next_30_days": len(available_slots),
                "today_schedule_slots": len(today_schedule),
                "booked_slots_today": len([s for s in today_schedule if s.is_booked == "yes"])
            },
            "created_at": provider.created_at,
            "updated_at": provider.updated_at
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get provider statistics: {str(e)}"
        )
