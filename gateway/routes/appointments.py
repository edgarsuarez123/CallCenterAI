"""
Appointment Management API Routes
REST endpoints for appointment operations including booking, scheduling, and Google Calendar integration.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime, timedelta

from services.database import get_db
from services.appointment_service import AppointmentService
from services.google_calendar_service import GoogleCalendarIntegrationService, GoogleCalendarConfig
from models.schemas import (
    AppointmentCreateRequest, AppointmentUpdateRequest, AppointmentResponse,
    AppointmentSearchRequest, SuccessResponse, ErrorResponse
)

router = APIRouter(prefix="/v1/appointments", tags=["appointment-management"])


@router.post("/", response_model=dict, status_code=status.HTTP_201_CREATED)
def create_appointment(
    appointment_data: AppointmentCreateRequest,
    patient_name: Optional[str] = None,
    db: Session = Depends(get_db)
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
        # Initialize Google Calendar service (if available)
        google_calendar_service = None
        try:
            # In production, these would come from environment variables
            config = GoogleCalendarConfig(
                client_id="your_google_client_id",
                client_secret="your_google_client_secret",
                redirect_uri="http://localhost:8000/auth/callback"
            )
            google_calendar_service = GoogleCalendarIntegrationService(
                GoogleCalendarService(config)
            )
        except ImportError:
            # Google Calendar API not available
            pass
        
        service = AppointmentService(db, google_calendar_service)
        appointment, google_event_id = service.create_appointment(appointment_data, patient_name)
        
        response_data = {
            "appointment": AppointmentResponse.from_orm(appointment),
            "google_calendar_event_id": google_event_id,
            "message": "Appointment created successfully"
        }
        
        return response_data
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create appointment: {str(e)}"
        )


@router.get("/", response_model=List[AppointmentResponse])
def list_appointments(
    search: AppointmentSearchRequest = Depends(),
    db: Session = Depends(get_db)
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
        appointments = service.list_appointments(search)
        return [AppointmentResponse.from_orm(appointment) for appointment in appointments]
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list appointments: {str(e)}"
        )


@router.get("/{appointment_id}", response_model=AppointmentResponse)
def get_appointment(
    appointment_id: str,
    db: Session = Depends(get_db)
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
        appointment = service.get_appointment(appointment_id)
        
        if not appointment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Appointment {appointment_id} not found"
            )
        
        return AppointmentResponse.from_orm(appointment)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get appointment: {str(e)}"
        )


@router.put("/{appointment_id}", response_model=dict)
def update_appointment(
    appointment_id: str,
    updates: AppointmentUpdateRequest,
    patient_name: Optional[str] = None,
    db: Session = Depends(get_db)
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
        # Initialize Google Calendar service (if available)
        google_calendar_service = None
        try:
            config = GoogleCalendarConfig(
                client_id="your_google_client_id",
                client_secret="your_google_client_secret",
                redirect_uri="http://localhost:8000/auth/callback"
            )
            google_calendar_service = GoogleCalendarIntegrationService(
                GoogleCalendarService(config)
            )
        except ImportError:
            pass
        
        service = AppointmentService(db, google_calendar_service)
        appointment, google_calendar_updated = service.update_appointment(
            appointment_id, updates, patient_name
        )
        
        if not appointment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Appointment {appointment_id} not found"
            )
        
        response_data = {
            "appointment": AppointmentResponse.from_orm(appointment),
            "google_calendar_updated": google_calendar_updated,
            "message": "Appointment updated successfully"
        }
        
        return response_data
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
            detail=f"Failed to update appointment: {str(e)}"
        )


@router.delete("/{appointment_id}", response_model=SuccessResponse)
def cancel_appointment(
    appointment_id: str,
    db: Session = Depends(get_db)
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
        # Initialize Google Calendar service (if available)
        google_calendar_service = None
        try:
            config = GoogleCalendarConfig(
                client_id="your_google_client_id",
                client_secret="your_google_client_secret",
                redirect_uri="http://localhost:8000/auth/callback"
            )
            google_calendar_service = GoogleCalendarIntegrationService(
                GoogleCalendarService(config)
            )
        except ImportError:
            pass
        
        service = AppointmentService(db, google_calendar_service)
        success = service.cancel_appointment(appointment_id)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Appointment {appointment_id} not found"
            )
        
        return SuccessResponse(
            message=f"Appointment {appointment_id} cancelled successfully"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to cancel appointment: {str(e)}"
        )


@router.get("/providers/{provider_id}/available", response_model=List[dict])
def get_available_slots(
    provider_id: str,
    start_date: datetime,
    end_date: datetime,
    db: Session = Depends(get_db)
):
    """
    Get available appointment slots for a provider.
    
    Returns all available time slots within the specified date range.
    Includes slot details and duration information.
    """
    try:
        service = AppointmentService(db)
        slots = service.get_available_slots(provider_id, start_date, end_date)
        
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
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get available slots: {str(e)}"
        )


@router.get("/providers/{provider_id}/next-available", response_model=dict)
def find_next_available_slot(
    provider_id: str,
    preferred_date: Optional[datetime] = None,
    duration_minutes: int = 60,
    db: Session = Depends(get_db)
):
    """
    Find the next available appointment slot for a provider.
    
    Searches for the next available slot starting from the preferred date
    (or today if not specified) up to 30 days in the future.
    """
    try:
        service = AppointmentService(db)
        next_slot = service.find_next_available_slot(provider_id, preferred_date, duration_minutes)
        
        if not next_slot:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No available slots found for provider {provider_id}"
            )
        
        return {
            "provider_id": provider_id,
            "next_available_slot": next_slot,
            "message": "Next available slot found"
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to find next available slot: {str(e)}"
        )


@router.get("/patients/{patient_id}/history", response_model=List[AppointmentResponse])
def get_patient_appointment_history(
    patient_id: str,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db)
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
        
        appointments = service.list_appointments(search)
        return [AppointmentResponse.from_orm(appointment) for appointment in appointments]
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get patient appointment history: {str(e)}"
        )


@router.get("/providers/{provider_id}/schedule", response_model=List[AppointmentResponse])
def get_provider_schedule(
    provider_id: str,
    start_date: datetime,
    end_date: datetime,
    db: Session = Depends(get_db)
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
        
        appointments = service.list_appointments(search)
        return [AppointmentResponse.from_orm(appointment) for appointment in appointments]
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get provider schedule: {str(e)}"
        )


@router.get("/stats", response_model=dict)
def get_appointment_statistics(
    clinic_id: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    db: Session = Depends(get_db)
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
        service = AppointmentService(db)
        
        # Set default date range if not provided
        if not start_date:
            start_date = datetime.now() - timedelta(days=30)
        if not end_date:
            end_date = datetime.now() + timedelta(days=30)
        
        # Create search request
        search = AppointmentSearchRequest(
            clinic_id=clinic_id,
            start_date=start_date,
            end_date=end_date,
            limit=10000  # Large limit for statistics
        )
        
        appointments = service.list_appointments(search)
        
        # Calculate statistics
        total_appointments = len(appointments)
        status_counts = {}
        provider_counts = {}
        
        for appointment in appointments:
            # Count by status
            status = appointment.status
            status_counts[status] = status_counts.get(status, 0) + 1
            
            # Count by provider
            provider_id = appointment.provider_id
            provider_counts[provider_id] = provider_counts.get(provider_id, 0) + 1
        
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
            "generated_at": datetime.now()
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get appointment statistics: {str(e)}"
        )
