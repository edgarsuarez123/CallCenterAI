"""
Appointment Management API Routes
REST endpoints for appointment operations including booking, scheduling, and Google Calendar integration.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, func

from services.database import get_async_db
from services.appointment_service import AppointmentService
from services.google_calendar_service import (
    GoogleCalendarIntegrationService, 
    GoogleCalendarConfig,
    GoogleCalendarService
)
from services.configuration import get_settings
from services.structured_logging import get_logger, LogCategory
from models.schemas import (
    AppointmentCreateRequest, AppointmentUpdateRequest, AppointmentResponse,
    AppointmentSearchRequest, SuccessResponse,
    AppointmentCreateResponse
)
from models.models import Appointment

# Get configuration
settings = get_settings()

# Initialize logger
logger = get_logger("appointments")


async def _get_google_calendar_service(db: AsyncSession) -> Optional[GoogleCalendarIntegrationService]:
    """
    Initialize Google Calendar service if credentials are available.
    
    Args:
        db: Database session
        
    Returns:
        GoogleCalendarIntegrationService instance or None if not available
    """
    try:
        client_id = settings.google_calendar.client_id
        client_secret = settings.google_calendar.client_secret.get_secret_value()
        redirect_uri = settings.google_calendar.redirect_uri
        
        if client_id and client_secret:
            config = GoogleCalendarConfig(
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri=redirect_uri
            )
            calendar_service = GoogleCalendarService(config, db)
            return GoogleCalendarIntegrationService(calendar_service)
    except (ImportError, Exception) as e:
        logger.warning(
            f"Failed to initialize Google Calendar service: {e}",
            LogCategory.API,
            extra_data={"error": str(e)}
        )
    
    return None

router = APIRouter(prefix="/appointments", tags=["appointment-management"])


@router.post("/", response_model=AppointmentCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_appointment(
    appointment_data: AppointmentCreateRequest,
    patient_name: Optional[str] = None,
    db: AsyncSession = Depends(get_async_db)
):
    """
    Create a new appointment and sync to Google Calendar.
    
    This endpoint:
    - Validates appointment data and slot availability
    - Creates the appointment record
    - Books the corresponding appointment slot
    - Syncs to Google Calendar (if configured)
    - Logs all operations in audit trail
    
    Returns both appointment details and Google Calendar event ID.
    """
    try:
        google_calendar_service = await _get_google_calendar_service(db)
        service = AppointmentService(db, google_calendar_service)
        appointment, google_event_id = await service.create_appointment(appointment_data, patient_name)
        
        logger.info(
            f"Appointment created: {appointment.appointment_id}",
            LogCategory.API,
            extra_data={
                "appointment_id": appointment.appointment_id,
                "provider_id": appointment.provider_id,
                "patient_id": appointment.patient_id,
                "google_event_id": google_event_id
            }
        )
        
        return AppointmentCreateResponse(
            appointment=AppointmentResponse.model_validate(appointment),
            google_event_id=google_event_id,
            message="Appointment created successfully"
        )
    except ValueError as e:
        logger.warning(
            f"Validation error creating appointment: {e}",
            LogCategory.API,
            extra_data={"error": str(e), "appointment_data": appointment_data.model_dump() if hasattr(appointment_data, 'model_dump') else str(appointment_data)}
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(
            f"Failed to create appointment: {e}",
            LogCategory.API,
            exception=e,
            extra_data={"appointment_data": appointment_data.model_dump() if hasattr(appointment_data, 'model_dump') else str(appointment_data)}
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create appointment. Please try again later."
        )


@router.get("/", response_model=List[AppointmentResponse])
async def list_appointments(
    search: AppointmentSearchRequest = Depends(),
    db: AsyncSession = Depends(get_async_db)
):
    """
    List appointments with optional filtering and pagination.
    
    Supports filtering by:
    - Clinic ID
    - Patient ID
    - Provider ID
    - Date range
    - Appointment status
    
    Includes pagination with limit and offset.
    """
    try:
        service = AppointmentService(db)
        appointments = await service.list_appointments(search)
        
        logger.info(
            f"Listed {len(appointments)} appointments",
            LogCategory.API,
            extra_data={
                "count": len(appointments),
                "filters": {
                    "clinic_id": search.clinic_id,
                    "patient_id": search.patient_id,
                    "provider_id": search.provider_id,
                    "status": search.status
                }
            }
        )
        
        return [AppointmentResponse.model_validate(appointment) for appointment in appointments]
    except Exception as e:
        logger.error(
            f"Failed to list appointments: {e}",
            LogCategory.API,
            exception=e,
            extra_data={"search": search.model_dump() if hasattr(search, 'model_dump') else str(search)}
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve appointments. Please try again later."
        )


@router.get("/{appointment_id}", response_model=AppointmentResponse)
async def get_appointment(
    appointment_id: str,
    db: AsyncSession = Depends(get_async_db)
):
    """
    Get a specific appointment by ID.
    
    Returns complete appointment information including:
    - Appointment details
    - Patient and provider information
    - Time and duration
    - Status and notes
    """
    try:
        service = AppointmentService(db)
        appointment = await service.get_appointment(appointment_id)
        
        if not appointment:
            logger.warning(
                f"Appointment not found: {appointment_id}",
                LogCategory.API,
                extra_data={"appointment_id": appointment_id}
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Appointment {appointment_id} not found"
            )
        
        return AppointmentResponse.model_validate(appointment)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Failed to get appointment {appointment_id}: {e}",
            LogCategory.API,
            exception=e,
            extra_data={"appointment_id": appointment_id}
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get appointment: {str(e)}"
        )


@router.put("/{appointment_id}", response_model=dict)
async def update_appointment(
    appointment_id: str,
    updates: AppointmentUpdateRequest,
    patient_name: Optional[str] = None,
    db: AsyncSession = Depends(get_async_db)
):
    """
    Update an appointment and sync changes to Google Calendar.
    
    This endpoint:
    - Validates update data and new slot availability
    - Updates the appointment record
    - Rebooks appointment slot if time changed
    - Updates Google Calendar event (if configured)
    - Logs all changes in audit trail
    
    Returns updated appointment and Google Calendar sync status.
    """
    try:
        google_calendar_service = await _get_google_calendar_service(db)
        service = AppointmentService(db, google_calendar_service)
        appointment, google_calendar_updated = await service.update_appointment(
            appointment_id, updates, patient_name
        )
        
        if not appointment:
            logger.warning(
                f"Appointment not found for update: {appointment_id}",
                LogCategory.API,
                extra_data={"appointment_id": appointment_id}
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Appointment {appointment_id} not found"
            )
        
        logger.info(
            f"Appointment updated: {appointment_id}",
            LogCategory.API,
            extra_data={
                "appointment_id": appointment_id,
                "google_calendar_updated": google_calendar_updated,
                "updates": updates.model_dump() if hasattr(updates, 'model_dump') else str(updates)
            }
        )
        
        response_data = {
            "appointment": AppointmentResponse.model_validate(appointment),
            "google_calendar_updated": google_calendar_updated,
            "message": "Appointment updated successfully"
        }
        
        return response_data
    except HTTPException:
        raise
    except ValueError as e:
        logger.warning(
            f"Validation error updating appointment {appointment_id}: {e}",
            LogCategory.API,
            extra_data={"appointment_id": appointment_id, "error": str(e)}
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(
            f"Failed to update appointment {appointment_id}: {e}",
            LogCategory.API,
            exception=e,
            extra_data={"appointment_id": appointment_id}
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update appointment: {str(e)}"
        )


@router.delete("/{appointment_id}", response_model=SuccessResponse)
async def cancel_appointment(
    appointment_id: str,
    db: AsyncSession = Depends(get_async_db)
):
    """
    Cancel an appointment and remove from Google Calendar.
    
    This operation:
    - Updates appointment status to cancelled
    - Releases the appointment slot
    - Removes Google Calendar event (if configured)
    - Logs the cancellation in audit trail
    """
    try:
        google_calendar_service = await _get_google_calendar_service(db)
        service = AppointmentService(db, google_calendar_service)
        success = await service.cancel_appointment(appointment_id)
        
        if not success:
            logger.warning(
                f"Appointment not found for cancellation: {appointment_id}",
                LogCategory.API,
                extra_data={"appointment_id": appointment_id}
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Appointment {appointment_id} not found"
            )
        
        logger.info(
            f"Appointment cancelled: {appointment_id}",
            LogCategory.API,
            extra_data={"appointment_id": appointment_id}
        )
        
        return SuccessResponse(
            message=f"Appointment {appointment_id} cancelled successfully"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Failed to cancel appointment {appointment_id}: {e}",
            LogCategory.API,
            exception=e,
            extra_data={"appointment_id": appointment_id}
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to cancel appointment: {str(e)}"
        )


@router.get("/providers/{provider_id}/available", response_model=List[dict])
async def get_available_slots(
    provider_id: str,
    start_date: datetime,
    end_date: datetime,
    db: AsyncSession = Depends(get_async_db)
):
    """
    Get available appointment slots for a provider.
    
    Returns all available time slots within the specified date range.
    Includes slot details and duration information.
    """
    try:
        service = AppointmentService(db)
        slots = await service.get_available_slots(provider_id, start_date, end_date)
        
        logger.info(
            f"Retrieved {len(slots)} available slots for provider {provider_id}",
            LogCategory.API,
            extra_data={
                "provider_id": provider_id,
                "slot_count": len(slots),
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat()
            }
        )
        
        return [
            {
                "slot_id": slot["slot_id"],
                "start_time": slot["start_time"],
                "end_time": slot["end_time"],
                "duration_minutes": slot["duration_minutes"]
            }
            for slot in slots
        ]
    except Exception as e:
        logger.error(
            f"Failed to get available slots for provider {provider_id}: {e}",
            LogCategory.API,
            exception=e,
            extra_data={"provider_id": provider_id, "start_date": start_date.isoformat(), "end_date": end_date.isoformat()}
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get available slots: {str(e)}"
        )


@router.get("/providers/{provider_id}/next-available", response_model=dict)
async def find_next_available_slot(
    provider_id: str,
    preferred_date: Optional[datetime] = None,
    duration_minutes: int = 60,
    db: AsyncSession = Depends(get_async_db)
):
    """
    Find the next available appointment slot for a provider.
    
    Searches for the next available slot starting from the preferred date
    (or today if not specified) up to 30 days in the future.
    """
    try:
        service = AppointmentService(db)
        next_slot = await service.find_next_available_slot(provider_id, preferred_date, duration_minutes)
        
        if not next_slot:
            logger.info(
                f"No available slots found for provider {provider_id}",
                LogCategory.API,
                extra_data={
                    "provider_id": provider_id,
                    "preferred_date": preferred_date.isoformat() if preferred_date else None,
                    "duration_minutes": duration_minutes
                }
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No available slots found for provider {provider_id}"
            )
        
        logger.info(
            f"Found next available slot for provider {provider_id}",
            LogCategory.API,
            extra_data={"provider_id": provider_id, "next_slot": next_slot}
        )
        
        return {
            "provider_id": provider_id,
            "next_available_slot": next_slot,
            "message": "Next available slot found"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Failed to find next available slot for provider {provider_id}: {e}",
            LogCategory.API,
            exception=e,
            extra_data={"provider_id": provider_id}
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to find next available slot: {str(e)}"
        )


@router.get("/patients/{patient_id}/history", response_model=List[AppointmentResponse])
async def get_patient_appointment_history(
    patient_id: str,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_async_db)
):
    """
    Get appointment history for a specific patient.
    
    Returns all appointments for the patient, ordered by date (newest first).
    Includes pagination support.
    """
    try:
        service = AppointmentService(db)
        
        # Create search request for patient appointments
        search = AppointmentSearchRequest(
            patient_id=patient_id,
            limit=limit,
            offset=offset
        )
        
        appointments = await service.list_appointments(search)
        
        logger.info(
            f"Retrieved appointment history for patient {patient_id}",
            LogCategory.API,
            extra_data={
                "patient_id": patient_id,
                "count": len(appointments),
                "limit": limit,
                "offset": offset
            }
        )
        
        return [AppointmentResponse.model_validate(appointment) for appointment in appointments]
    except Exception as e:
        logger.error(
            f"Failed to get patient appointment history for {patient_id}: {e}",
            LogCategory.API,
            exception=e,
            extra_data={"patient_id": patient_id}
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get patient appointment history: {str(e)}"
        )


@router.get("/providers/{provider_id}/schedule", response_model=List[AppointmentResponse])
async def get_provider_schedule(
    provider_id: str,
    start_date: datetime,
    end_date: datetime,
    db: AsyncSession = Depends(get_async_db)
):
    """
    Get provider's appointment schedule for a date range.
    
    Returns all appointments (scheduled, confirmed, etc.) for the provider
    within the specified date range.
    """
    try:
        service = AppointmentService(db)
        
        # Create search request for provider appointments
        search = AppointmentSearchRequest(
            provider_id=provider_id,
            start_date=start_date,
            end_date=end_date,
            limit=1000  # Large limit for schedule view
        )
        
        appointments = await service.list_appointments(search)
        
        logger.info(
            f"Retrieved schedule for provider {provider_id}",
            LogCategory.API,
            extra_data={
                "provider_id": provider_id,
                "count": len(appointments),
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat()
            }
        )
        
        return [AppointmentResponse.model_validate(appointment) for appointment in appointments]
    except Exception as e:
        logger.error(
            f"Failed to get provider schedule for {provider_id}: {e}",
            LogCategory.API,
            exception=e,
            extra_data={"provider_id": provider_id, "start_date": start_date.isoformat(), "end_date": end_date.isoformat()}
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get provider schedule: {str(e)}"
        )


@router.get("/stats", response_model=dict)
async def get_appointment_statistics(
    clinic_id: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    db: AsyncSession = Depends(get_async_db)
):
    """
    Get appointment statistics and analytics.
    
    Returns comprehensive statistics including:
    - Total appointments
    - Appointments by status
    - Provider utilization
    - Date range analytics
    """
    try:
        # Set default date range if not provided
        if not start_date:
            start_date = datetime.now(timezone.utc) - timedelta(days=30)
        if not end_date:
            end_date = datetime.now(timezone.utc) + timedelta(days=30)
        
        # Use database aggregation for efficient statistics calculation
        stmt = select(
            func.count(Appointment.appointment_id).label('total_appointments'),
            Appointment.status,
            Appointment.provider_id
        ).where(
            Appointment.appointment_date >= start_date,
            Appointment.appointment_date <= end_date
        )
        
        if clinic_id:
            # Join with providers to filter by clinic
            from models.models import Provider, provider_clinics
            stmt = stmt.join(Provider).join(provider_clinics).where(
                provider_clinics.c.clinic_id == clinic_id
            )
        
        # Group by status and provider for aggregation
        stmt = stmt.group_by(Appointment.status, Appointment.provider_id)
        
        result = await db.execute(stmt)
        rows = result.all()
        
        # Aggregate results
        total_appointments = sum(row.total_appointments for row in rows)
        status_counts = {}
        provider_counts = {}
        
        for row in rows:
            # Count by status
            status = row.status
            status_counts[status] = status_counts.get(status, 0) + row.total_appointments
            
            # Count by provider
            provider_id = row.provider_id
            provider_counts[provider_id] = provider_counts.get(provider_id, 0) + row.total_appointments
        
        logger.info(
            f"Retrieved appointment statistics",
            LogCategory.API,
            extra_data={
                "clinic_id": clinic_id,
                "total_appointments": total_appointments,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat()
            }
        )
        
        return {
            "date_range": {
                "start_date": start_date,
                "end_date": end_date
            },
            "clinic_id": clinic_id,
            "statistics": {
                "total_appointments": total_appointments,
                "appointments_by_status": status_counts,
                "appointments_by_provider": provider_counts
            },
            "generated_at": datetime.now(timezone.utc)
        }
    except Exception as e:
        logger.error(
            f"Failed to get appointment statistics: {e}",
            LogCategory.API,
            exception=e,
            extra_data={"clinic_id": clinic_id, "start_date": start_date.isoformat() if start_date else None, "end_date": end_date.isoformat() if end_date else None}
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get appointment statistics: {str(e)}"
        )
