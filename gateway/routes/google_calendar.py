"""
Google Calendar Integration API Routes

REST endpoints for Google Calendar operations including authentication, sync, and management.
Provides comprehensive Google Calendar integration for appointment synchronization and availability management.
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional, Dict
from datetime import datetime, timezone
from pydantic import BaseModel
import secrets

from services.database import get_async_db
from services.google_calendar_service import (
    GoogleCalendarService, GoogleCalendarIntegrationService, GoogleCalendarConfig
)
from services.configuration import get_settings
from services.structured_logging import get_logger, LogCategory
from services.exceptions import (
    CallCenterAIException, ValidationError, ErrorCode, ExternalServiceUnavailableError
)
from models.schemas import SuccessResponse
from services.appointment_service import AppointmentService

# Get configuration
settings = get_settings()

# Initialize logger
logger = get_logger("google_calendar")

router = APIRouter(prefix="/google-calendar", tags=["google-calendar"])

# OAuth state storage (in production, use Redis or database)
_oauth_states: Dict[str, str] = {}


class AuthenticateProviderRequest(BaseModel):
    """Request model for provider authentication."""
    auth_code: Optional[str] = None


async def _get_google_calendar_config(db: AsyncSession) -> GoogleCalendarConfig:
    """
    Helper function to get Google Calendar configuration.
    
    Args:
        db: Database session (for potential future use)
        
    Returns:
        GoogleCalendarConfig instance
        
    Raises:
        HTTPException: If credentials are not configured
    """
    client_id = settings.google_calendar.client_id
    client_secret = settings.google_calendar.client_secret.get_secret_value() if settings.google_calendar.client_secret else None
    redirect_uri = settings.google_calendar.redirect_uri
    
    if not client_id or not client_secret:
        logger.warning(
            "Google Calendar credentials not configured",
            LogCategory.CONFIG,
            extra_data={"has_client_id": bool(client_id), "has_client_secret": bool(client_secret)}
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google Calendar credentials not configured. Please set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET environment variables."
        )
    
    return GoogleCalendarConfig(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri
    )


async def _get_google_calendar_service(db: AsyncSession) -> GoogleCalendarService:
    """
    Helper function to get Google Calendar service instance.
    
    Args:
        db: Database session
        
    Returns:
        GoogleCalendarService instance
        
    Raises:
        HTTPException: If credentials are not configured or API is unavailable
    """
    try:
        config = await _get_google_calendar_config(db)
        return GoogleCalendarService(config, db)
    except ImportError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google Calendar API not available. Please install google-api-python-client and google-auth-oauthlib"
        )


@router.get("/oauth/start")
async def start_oauth_flow(
    db: AsyncSession = Depends(get_async_db)
):
    """
    Start Google Calendar OAuth flow.
    
    This endpoint initiates the OAuth flow by redirecting the user to Google's
    authorization server where they can grant permission for the app to access
    their Google Calendar.
    
    Args:
        db: Database session
        
    Returns:
        RedirectResponse to Google OAuth authorization page
        
    Raises:
        HTTPException 503: Google Calendar credentials not configured
        HTTPException 500: Internal server error
    """
    try:
        config = await _get_google_calendar_config(db)
        
        logger.info(
            "Starting Google Calendar OAuth flow",
            LogCategory.AUTHENTICATION,
            extra_data={"redirect_uri": config.redirect_uri}
        )
        
        # Generate a random state parameter for CSRF protection
        state = secrets.token_urlsafe(32)
        # Store state for validation (in production, use Redis or database)
        _oauth_states[state] = "pending"
        
        # Build the OAuth URL
        scopes = [
            'https://www.googleapis.com/auth/calendar',
            'https://www.googleapis.com/auth/calendar.events'
        ]
        scopes_str = '+'.join(scopes)
        
        oauth_url = (
            f"https://accounts.google.com/o/oauth2/auth?"
            f"client_id={config.client_id}&"
            f"redirect_uri={config.redirect_uri}&"
            f"scope={scopes_str}&"
            f"response_type=code&"
            f"state={state}&"
            f"access_type=offline&"
            f"prompt=consent"
        )
        
        logger.info(
            "OAuth URL generated successfully",
            LogCategory.AUTHENTICATION,
            extra_data={"state": state[:8] + "..."}  # Log partial state for debugging
        )
        
        return RedirectResponse(url=oauth_url)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.critical(
            f"Unexpected error starting OAuth flow: {e}",
            LogCategory.EXCEPTION,
            exception=e
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while starting the OAuth flow"
        )


@router.get("/oauth/callback")
async def oauth_callback(
    code: Optional[str] = Query(None, description="Authorization code from Google"),
    state: Optional[str] = Query(None, description="State parameter for CSRF protection"),
    error: Optional[str] = Query(None, description="Error from OAuth flow"),
    db: AsyncSession = Depends(get_async_db)
):
    """
    Handle Google Calendar OAuth callback.
    
    This endpoint receives the authorization code from Google after the user
    grants permission. The code should be used immediately to authenticate a provider.
    
    **Security Note**: The authorization code is not returned in the response for security.
    It should be used server-side to complete authentication.
    
    Args:
        code: Authorization code from Google
        state: State parameter for CSRF protection
        error: Error from OAuth flow (if any)
        db: Database session
        
    Returns:
        Dictionary with callback status and next steps
        
    Raises:
        HTTPException 400: OAuth error or missing code
        HTTPException 500: Internal server error
    """
    try:
        if error:
            logger.warning(
                f"OAuth error received: {error}",
                LogCategory.AUTHENTICATION,
                extra_data={"error": error, "state": state[:8] + "..." if state else None}
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"OAuth error: {error}"
            )
        
        if not code:
            logger.warning(
                "OAuth callback received without authorization code",
                LogCategory.AUTHENTICATION,
                extra_data={"state": state[:8] + "..." if state else None}
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Authorization code not provided"
            )
        
        # Validate state parameter (CSRF protection)
        if state and state not in _oauth_states:
            logger.warning(
                "OAuth callback received with invalid state parameter",
                LogCategory.SECURITY,
                extra_data={"state": state[:8] + "..." if state else None}
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid state parameter. Possible CSRF attack."
            )
        
        # Remove used state
        if state:
            _oauth_states.pop(state, None)
        
        logger.info(
            "OAuth callback received successfully",
            LogCategory.AUTHENTICATION,
            extra_data={"code_length": len(code), "has_state": bool(state)}
        )
        
        # Security: Don't return the code in the response
        # In production, you would:
        # 1. Store the code temporarily (e.g., in Redis with short TTL)
        # 2. Associate it with a session or provider
        # 3. Return a token or redirect URL that can be used to complete authentication
        
        return {
            "message": "OAuth callback received successfully",
            "status": "success",
            "next_steps": [
                "Use the authorization code to authenticate a provider",
                "POST to /api/v1/google-calendar/providers/{provider_id}/authenticate with the code in the request body",
                "The code should be used within 10 minutes"
            ],
            "note": "Authorization code has been received and is ready for use"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.critical(
            f"Unexpected error handling OAuth callback: {e}",
            LogCategory.EXCEPTION,
            exception=e
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while handling the OAuth callback"
        )


@router.post("/providers/{provider_id}/authenticate", response_model=dict)
async def authenticate_provider(
    provider_id: str,
    request: AuthenticateProviderRequest,
    db: AsyncSession = Depends(get_async_db)
):
    """
    Authenticate a provider with Google Calendar.
    
    This endpoint:
    - Completes OAuth flow for Google Calendar access using authorization code
    - Stores provider credentials securely (encrypted)
    - Enables calendar synchronization
    - Returns authentication status
    
    If auth_code is provided, completes the OAuth flow.
    Otherwise, returns the authorization URL for the OAuth flow.
    
    Args:
        provider_id: Provider ID to authenticate
        request: Authentication request with optional auth_code
        db: Database session
        
    Returns:
        Dictionary with authentication status and information
        
    Raises:
        HTTPException 400: Invalid request or authentication failed
        HTTPException 503: Google Calendar API not available or credentials not configured
        HTTPException 500: Internal server error
    """
    try:
        # Validate provider_id
        if not provider_id or len(provider_id.strip()) < 3:
            logger.warning(
                "Invalid provider_id format for authentication",
                LogCategory.VALIDATION,
                extra_data={"provider_id": provider_id}
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="provider_id must be at least 3 characters"
            )
        
        config = await _get_google_calendar_config(db)
        calendar_service = GoogleCalendarService(config, db)
        
        if request.auth_code:
            logger.info(
                f"Authenticating provider {provider_id} with authorization code",
                LogCategory.AUTHENTICATION,
                extra_data={"provider_id": provider_id, "code_length": len(request.auth_code)}
            )
            
            # Complete OAuth flow
            success = await calendar_service.authenticate_provider(provider_id, request.auth_code)
            
            if success:
                logger.info(
                    f"Provider {provider_id} successfully authenticated with Google Calendar",
                    LogCategory.AUTHENTICATION,
                    extra_data={"provider_id": provider_id}
                )
                return {
                    "provider_id": provider_id,
                    "status": "authenticated",
                    "message": "Provider successfully authenticated with Google Calendar"
                }
            else:
                logger.warning(
                    f"Authentication failed for provider {provider_id}",
                    LogCategory.AUTHENTICATION,
                    extra_data={"provider_id": provider_id}
                )
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Failed to authenticate provider with Google Calendar. Please check the authorization code."
                )
        else:
            # Return authorization URL for OAuth flow
            scopes_str = '+'.join(config.scopes)
            auth_url = (
                f"https://accounts.google.com/o/oauth2/auth?"
                f"client_id={config.client_id}&"
                f"redirect_uri={config.redirect_uri}&"
                f"scope={scopes_str}&"
                f"response_type=code&"
                f"access_type=offline&"
                f"prompt=consent"
            )
            
            logger.info(
                f"Returning authorization URL for provider {provider_id}",
                LogCategory.AUTHENTICATION,
                extra_data={"provider_id": provider_id}
            )
            
            return {
                "provider_id": provider_id,
                "status": "pending_authentication",
                "authorization_url": auth_url,
                "message": "Please visit the authorization URL to complete authentication"
            }
            
    except HTTPException:
        raise
    except ImportError:
        logger.error(
            "Google Calendar API not available",
            LogCategory.ERROR,
            extra_data={"provider_id": provider_id}
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google Calendar API not available. Please install google-api-python-client and google-auth-oauthlib"
        )
    except CallCenterAIException as e:
        http_status = e.http_status if hasattr(e, 'http_status') and e.http_status != 500 else (
            status.HTTP_400_BAD_REQUEST if e.error_code == ErrorCode.VALIDATION_ERROR
            else status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        logger.error(
            f"Service error authenticating provider: {e.user_message}",
            LogCategory.ERROR,
            extra_data={"provider_id": provider_id}
        )
        raise HTTPException(
            status_code=http_status,
            detail=e.user_message
        )
    except Exception as e:
        logger.critical(
            f"Unexpected error authenticating provider: {e}",
            LogCategory.EXCEPTION,
            exception=e,
            extra_data={"provider_id": provider_id}
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while authenticating the provider"
        )


@router.get("/providers/{provider_id}/availability", response_model=List[dict])
async def get_provider_availability(
    provider_id: str,
    date: datetime = Query(..., description="Date to get availability for"),
    db: AsyncSession = Depends(get_async_db)
):
    """
    Get provider's availability from Google Calendar.
    
    Returns available time slots for the specified date
    based on the provider's Google Calendar.
    
    Args:
        provider_id: Provider ID to get availability for
        date: Date to get availability for
        db: Database session
        
    Returns:
        List of dictionaries with availability slots (start, end, duration_minutes)
        
    Raises:
        HTTPException 400: Invalid request parameters
        HTTPException 503: Google Calendar API not available or credentials not configured
        HTTPException 500: Internal server error
    """
    try:
        # Validate provider_id
        if not provider_id or len(provider_id.strip()) < 3:
            logger.warning(
                "Invalid provider_id format for availability query",
                LogCategory.VALIDATION,
                extra_data={"provider_id": provider_id}
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="provider_id must be at least 3 characters"
            )
        
        logger.info(
            f"Getting availability for provider {provider_id} on {date.date()}",
            LogCategory.API,
            extra_data={"provider_id": provider_id, "date": date.isoformat()}
        )
        
        calendar_service = await _get_google_calendar_service(db)
        availability = await calendar_service.get_provider_availability(provider_id, date)
        
        logger.info(
            f"Retrieved {len(availability)} availability slots for provider {provider_id}",
            LogCategory.API,
            extra_data={"provider_id": provider_id, "slots_count": len(availability)}
        )
        
        return [
            {
                "start": slot["start"],
                "end": slot["end"],
                "duration_minutes": slot["duration_minutes"]
            }
            for slot in availability
        ]
        
    except HTTPException:
        raise
    except ImportError:
        logger.error(
            "Google Calendar API not available",
            LogCategory.ERROR,
            extra_data={"provider_id": provider_id}
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google Calendar API not available"
        )
    except CallCenterAIException as e:
        http_status = e.http_status if hasattr(e, 'http_status') and e.http_status != 500 else (
            status.HTTP_400_BAD_REQUEST if e.error_code == ErrorCode.VALIDATION_ERROR
            else status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        logger.error(
            f"Service error getting provider availability: {e.user_message}",
            LogCategory.ERROR,
            extra_data={"provider_id": provider_id}
        )
        raise HTTPException(
            status_code=http_status,
            detail=e.user_message
        )
    except Exception as e:
        logger.critical(
            f"Unexpected error getting provider availability: {e}",
            LogCategory.EXCEPTION,
            exception=e,
            extra_data={"provider_id": provider_id}
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while retrieving provider availability"
        )


@router.post("/providers/{provider_id}/sync-slots", response_model=dict)
async def sync_appointment_slots(
    provider_id: str,
    start_date: datetime = Query(..., description="Start date for sync"),
    end_date: datetime = Query(..., description="End date for sync"),
    db: AsyncSession = Depends(get_async_db)
):
    """
    Sync appointment slots with Google Calendar availability.
    
    This endpoint:
    - Checks for conflicts between appointment slots and calendar events
    - Identifies unavailable time periods
    - Returns conflict information
    
    Args:
        provider_id: Provider ID to sync slots for
        start_date: Start date for sync
        end_date: End date for sync
        db: Database session
        
    Returns:
        Dictionary with conflict information and statistics
        
    Raises:
        HTTPException 400: Invalid date range or request parameters
        HTTPException 503: Google Calendar API not available or credentials not configured
        HTTPException 500: Internal server error
    """
    try:
        # Validate provider_id
        if not provider_id or len(provider_id.strip()) < 3:
            logger.warning(
                "Invalid provider_id format for slot sync",
                LogCategory.VALIDATION,
                extra_data={"provider_id": provider_id}
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="provider_id must be at least 3 characters"
            )
        
        # Validate date range
        if end_date < start_date:
            logger.warning(
                "Invalid date range for slot sync",
                LogCategory.VALIDATION,
                extra_data={
                    "provider_id": provider_id,
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat()
                }
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="end_date must be after start_date"
            )
        
        logger.info(
            f"Syncing appointment slots for provider {provider_id}",
            LogCategory.API,
            extra_data={
                "provider_id": provider_id,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat()
            }
        )
        
        calendar_service = await _get_google_calendar_service(db)
        conflicts = await calendar_service.sync_appointment_slots(
            provider_id, start_date, end_date
        )
        
        logger.info(
            f"Found {len(conflicts)} conflicts for provider {provider_id}",
            LogCategory.API,
            extra_data={
                "provider_id": provider_id,
                "conflict_count": len(conflicts)
            }
        )
        
        return {
            "provider_id": provider_id,
            "date_range": {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat()
            },
            "conflicts": conflicts,
            "conflict_count": len(conflicts),
            "message": f"Found {len(conflicts)} conflicts with Google Calendar"
        }
        
    except HTTPException:
        raise
    except ImportError:
        logger.error(
            "Google Calendar API not available",
            LogCategory.ERROR,
            extra_data={"provider_id": provider_id}
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google Calendar API not available"
        )
    except CallCenterAIException as e:
        http_status = e.http_status if hasattr(e, 'http_status') and e.http_status != 500 else (
            status.HTTP_400_BAD_REQUEST if e.error_code == ErrorCode.VALIDATION_ERROR
            else status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        logger.error(
            f"Service error syncing appointment slots: {e.user_message}",
            LogCategory.ERROR,
            extra_data={"provider_id": provider_id}
        )
        raise HTTPException(
            status_code=http_status,
            detail=e.user_message
        )
    except Exception as e:
        logger.critical(
            f"Unexpected error syncing appointment slots: {e}",
            LogCategory.EXCEPTION,
            exception=e,
            extra_data={"provider_id": provider_id}
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while syncing appointment slots"
        )


@router.post("/events", response_model=dict)
async def create_calendar_event(
    provider_id: str = Query(..., min_length=3, max_length=64, description="Provider ID"),
    appointment_id: str = Query(..., min_length=3, max_length=64, description="Appointment ID"),
    patient_name: Optional[str] = Query(None, description="Patient name (optional)"),
    db: AsyncSession = Depends(get_async_db)
):
    """
    Create a calendar event for an existing appointment.
    
    This endpoint:
    - Creates a Google Calendar event for the appointment
    - Includes patient information and appointment details
    - Sets up reminders and conference call
    - Returns the calendar event ID
    
    Args:
        provider_id: Provider ID for the appointment
        appointment_id: Appointment ID to create calendar event for
        patient_name: Optional patient name
        db: Database session
        
    Returns:
        Dictionary with calendar event information
        
    Raises:
        HTTPException 404: Appointment not found
        HTTPException 400: Failed to create calendar event
        HTTPException 503: Google Calendar API not available or credentials not configured
        HTTPException 500: Internal server error
    """
    try:
        logger.info(
            f"Creating calendar event for appointment {appointment_id}",
            LogCategory.API,
            extra_data={
                "provider_id": provider_id,
                "appointment_id": appointment_id
            }
        )
        
        # Get appointment details
        appointment_service = AppointmentService(db)
        appointment = await appointment_service.get_appointment(appointment_id)
        
        if not appointment:
            logger.warning(
                f"Appointment {appointment_id} not found for calendar event creation",
                LogCategory.API,
                extra_data={"appointment_id": appointment_id, "provider_id": provider_id}
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Appointment {appointment_id} not found"
            )
        
        calendar_service = await _get_google_calendar_service(db)
        integration_service = GoogleCalendarIntegrationService(calendar_service)
        
        # Create calendar event
        event_id = await integration_service.sync_appointment_to_calendar(
            appointment, provider_id, patient_name
        )
        
        if event_id:
            logger.info(
                f"Calendar event created successfully for appointment {appointment_id}",
                LogCategory.API,
                extra_data={
                    "appointment_id": appointment_id,
                    "provider_id": provider_id,
                    "event_id": event_id
                }
            )
            return {
                "appointment_id": appointment_id,
                "provider_id": provider_id,
                "google_calendar_event_id": event_id,
                "status": "created",
                "message": "Calendar event created successfully"
            }
        else:
            logger.warning(
                f"Failed to create calendar event for appointment {appointment_id}",
                LogCategory.API,
                extra_data={"appointment_id": appointment_id, "provider_id": provider_id}
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to create calendar event"
            )
            
    except HTTPException:
        raise
    except ImportError:
        logger.error(
            "Google Calendar API not available",
            LogCategory.ERROR,
            extra_data={"appointment_id": appointment_id, "provider_id": provider_id}
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google Calendar API not available"
        )
    except CallCenterAIException as e:
        http_status = e.http_status if hasattr(e, 'http_status') and e.http_status != 500 else (
            status.HTTP_400_BAD_REQUEST if e.error_code == ErrorCode.VALIDATION_ERROR
            else status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        logger.error(
            f"Service error creating calendar event: {e.user_message}",
            LogCategory.ERROR,
            extra_data={"appointment_id": appointment_id, "provider_id": provider_id}
        )
        raise HTTPException(
            status_code=http_status,
            detail=e.user_message
        )
    except Exception as e:
        logger.critical(
            f"Unexpected error creating calendar event: {e}",
            LogCategory.EXCEPTION,
            exception=e,
            extra_data={"appointment_id": appointment_id, "provider_id": provider_id}
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while creating the calendar event"
        )


@router.put("/events/{event_id}", response_model=SuccessResponse)
async def update_calendar_event(
    event_id: str,
    provider_id: str = Query(..., min_length=3, max_length=64, description="Provider ID"),
    appointment_id: str = Query(..., min_length=3, max_length=64, description="Appointment ID"),
    patient_name: Optional[str] = Query(None, description="Patient name (optional)"),
    db: AsyncSession = Depends(get_async_db)
):
    """
    Update an existing calendar event.
    
    This endpoint:
    - Updates the Google Calendar event with new appointment details
    - Syncs changes from the appointment record
    - Maintains event consistency
    
    Args:
        event_id: Google Calendar event ID to update
        provider_id: Provider ID for the appointment
        appointment_id: Appointment ID to sync
        patient_name: Optional patient name
        db: Database session
        
    Returns:
        SuccessResponse with confirmation message
        
    Raises:
        HTTPException 404: Appointment not found
        HTTPException 400: Failed to update calendar event
        HTTPException 503: Google Calendar API not available or credentials not configured
        HTTPException 500: Internal server error
    """
    try:
        logger.info(
            f"Updating calendar event {event_id} for appointment {appointment_id}",
            LogCategory.API,
            extra_data={
                "event_id": event_id,
                "appointment_id": appointment_id,
                "provider_id": provider_id
            }
        )
        
        # Get appointment details
        appointment_service = AppointmentService(db)
        appointment = await appointment_service.get_appointment(appointment_id)
        
        if not appointment:
            logger.warning(
                f"Appointment {appointment_id} not found for calendar event update",
                LogCategory.API,
                extra_data={"appointment_id": appointment_id, "event_id": event_id}
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Appointment {appointment_id} not found"
            )
        
        calendar_service = await _get_google_calendar_service(db)
        integration_service = GoogleCalendarIntegrationService(calendar_service)
        
        # Update calendar event
        success = await integration_service.update_calendar_appointment(
            appointment, provider_id, event_id, patient_name
        )
        
        if success:
            logger.info(
                f"Calendar event {event_id} updated successfully",
                LogCategory.API,
                extra_data={"event_id": event_id, "appointment_id": appointment_id}
            )
            return SuccessResponse(
                message=f"Calendar event {event_id} updated successfully"
            )
        else:
            logger.warning(
                f"Failed to update calendar event {event_id}",
                LogCategory.API,
                extra_data={"event_id": event_id, "appointment_id": appointment_id}
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to update calendar event"
            )
            
    except HTTPException:
        raise
    except ImportError:
        logger.error(
            "Google Calendar API not available",
            LogCategory.ERROR,
            extra_data={"event_id": event_id, "appointment_id": appointment_id}
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google Calendar API not available"
        )
    except CallCenterAIException as e:
        http_status = e.http_status if hasattr(e, 'http_status') and e.http_status != 500 else (
            status.HTTP_400_BAD_REQUEST if e.error_code == ErrorCode.VALIDATION_ERROR
            else status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        logger.error(
            f"Service error updating calendar event: {e.user_message}",
            LogCategory.ERROR,
            extra_data={"event_id": event_id, "appointment_id": appointment_id}
        )
        raise HTTPException(
            status_code=http_status,
            detail=e.user_message
        )
    except Exception as e:
        logger.critical(
            f"Unexpected error updating calendar event: {e}",
            LogCategory.EXCEPTION,
            exception=e,
            extra_data={"event_id": event_id, "appointment_id": appointment_id}
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while updating the calendar event"
        )


@router.delete("/events/{event_id}", response_model=SuccessResponse)
async def delete_calendar_event(
    event_id: str,
    provider_id: str = Query(..., min_length=3, max_length=64, description="Provider ID"),
    db: AsyncSession = Depends(get_async_db)
):
    """
    Delete a calendar event.
    
    This endpoint:
    - Removes the Google Calendar event
    - Used when appointments are cancelled
    - Cleans up calendar entries
    
    Args:
        event_id: Google Calendar event ID to delete
        provider_id: Provider ID
        db: Database session
        
    Returns:
        SuccessResponse with confirmation message
        
    Raises:
        HTTPException 400: Failed to delete calendar event
        HTTPException 503: Google Calendar API not available or credentials not configured
        HTTPException 500: Internal server error
    """
    try:
        logger.info(
            f"Deleting calendar event {event_id} for provider {provider_id}",
            LogCategory.API,
            extra_data={"event_id": event_id, "provider_id": provider_id}
        )
        
        calendar_service = await _get_google_calendar_service(db)
        integration_service = GoogleCalendarIntegrationService(calendar_service)
        
        # Delete calendar event
        success = await integration_service.cancel_calendar_appointment(provider_id, event_id)
        
        if success:
            logger.info(
                f"Calendar event {event_id} deleted successfully",
                LogCategory.API,
                extra_data={"event_id": event_id, "provider_id": provider_id}
            )
            return SuccessResponse(
                message=f"Calendar event {event_id} deleted successfully"
            )
        else:
            logger.warning(
                f"Failed to delete calendar event {event_id}",
                LogCategory.API,
                extra_data={"event_id": event_id, "provider_id": provider_id}
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to delete calendar event"
            )
            
    except HTTPException:
        raise
    except ImportError:
        logger.error(
            "Google Calendar API not available",
            LogCategory.ERROR,
            extra_data={"event_id": event_id, "provider_id": provider_id}
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google Calendar API not available"
        )
    except CallCenterAIException as e:
        http_status = e.http_status if hasattr(e, 'http_status') and e.http_status != 500 else (
            status.HTTP_400_BAD_REQUEST if e.error_code == ErrorCode.VALIDATION_ERROR
            else status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        logger.error(
            f"Service error deleting calendar event: {e.user_message}",
            LogCategory.ERROR,
            extra_data={"event_id": event_id, "provider_id": provider_id}
        )
        raise HTTPException(
            status_code=http_status,
            detail=e.user_message
        )
    except Exception as e:
        logger.critical(
            f"Unexpected error deleting calendar event: {e}",
            LogCategory.EXCEPTION,
            exception=e,
            extra_data={"event_id": event_id, "provider_id": provider_id}
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while deleting the calendar event"
        )


@router.get("/providers/{provider_id}/status", response_model=dict)
async def get_provider_calendar_status(
    provider_id: str,
    db: AsyncSession = Depends(get_async_db)
):
    """
    Get provider's Google Calendar integration status.
    
    Returns information about:
    - Authentication status
    - Calendar access permissions
    - Sync configuration
    - Last sync time
    
    Args:
        provider_id: Provider ID to get status for
        db: Database session
        
    Returns:
        Dictionary with integration status and feature availability
        
    Raises:
        HTTPException 500: Internal server error
    """
    try:
        # Validate provider_id
        if not provider_id or len(provider_id.strip()) < 3:
            logger.warning(
                "Invalid provider_id format for status query",
                LogCategory.VALIDATION,
                extra_data={"provider_id": provider_id}
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="provider_id must be at least 3 characters"
            )
        
        logger.info(
            f"Getting Google Calendar status for provider {provider_id}",
            LogCategory.API,
            extra_data={"provider_id": provider_id}
        )
        
        try:
            config = await _get_google_calendar_config(db)
            calendar_service = GoogleCalendarService(config, db)
            
            # Check if provider has stored credentials
            # Note: _get_provider_credentials is a public method (single underscore)
            credentials = await calendar_service._get_provider_credentials(provider_id)
            is_authenticated = credentials is not None and not credentials.expired
            
            logger.info(
                f"Retrieved calendar status for provider {provider_id}",
                LogCategory.API,
                extra_data={
                    "provider_id": provider_id,
                    "is_authenticated": is_authenticated
                }
            )
            
            return {
                "provider_id": provider_id,
                "google_calendar_authenticated": is_authenticated,
                "integration_status": "active" if is_authenticated else "pending_authentication",
                "features": {
                    "event_creation": is_authenticated,
                    "availability_sync": is_authenticated,
                    "conflict_detection": is_authenticated,
                    "reminder_management": is_authenticated
                },
                "last_checked": datetime.now(timezone.utc).isoformat()
            }
            
        except HTTPException:
            # Re-raise HTTP exceptions (e.g., credentials not configured)
            raise
        except ImportError:
            logger.warning(
                "Google Calendar API not available",
                LogCategory.ERROR,
                extra_data={"provider_id": provider_id}
            )
            return {
                "provider_id": provider_id,
                "google_calendar_authenticated": False,
                "integration_status": "unavailable",
                "error": "Google Calendar API not available",
                "features": {
                    "event_creation": False,
                    "availability_sync": False,
                    "conflict_detection": False,
                    "reminder_management": False
                },
                "last_checked": datetime.now(timezone.utc).isoformat()
            }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.critical(
            f"Unexpected error getting provider calendar status: {e}",
            LogCategory.EXCEPTION,
            exception=e,
            extra_data={"provider_id": provider_id}
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while retrieving provider calendar status"
        )


@router.get("/config", response_model=dict)
async def get_google_calendar_config_endpoint(
    db: AsyncSession = Depends(get_async_db)
):
    """
    Get Google Calendar integration configuration.
    
    Returns configuration information including:
    - Available features
    - Authentication requirements
    - API status
    - Setup instructions
    
    Args:
        db: Database session
        
    Returns:
        Dictionary with configuration and feature information
    """
    try:
        logger.info(
            "Getting Google Calendar configuration",
            LogCategory.API
        )
        
        # Check if Google Calendar API is available
        try:
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import Flow
            from googleapiclient.discovery import build
            
            # Check if credentials are configured
            try:
                config = await _get_google_calendar_config(db)
                credentials_configured = True
            except HTTPException:
                credentials_configured = False
            
            return {
                "google_calendar_api_available": True,
                "credentials_configured": credentials_configured,
                "features": {
                    "provider_authentication": True,
                    "event_creation": True,
                    "event_updates": True,
                    "event_deletion": True,
                    "availability_sync": True,
                    "conflict_detection": True,
                    "conference_calls": True,
                    "reminders": True
                },
                "authentication_required": True,
                "oauth_scopes": [
                    "https://www.googleapis.com/auth/calendar",
                    "https://www.googleapis.com/auth/calendar.events"
                ],
                "setup_instructions": [
                    "1. Create a Google Cloud Project",
                    "2. Enable Google Calendar API",
                    "3. Create OAuth 2.0 credentials",
                    "4. Configure redirect URI",
                    "5. Set environment variables for client ID and secret"
                ]
            }
        except ImportError:
            logger.warning(
                "Google Calendar API not available",
                LogCategory.ERROR
            )
            return {
                "google_calendar_api_available": False,
                "credentials_configured": False,
                "features": {
                    "provider_authentication": False,
                    "event_creation": False,
                    "event_updates": False,
                    "event_deletion": False,
                    "availability_sync": False,
                    "conflict_detection": False,
                    "conference_calls": False,
                    "reminders": False
                },
                "authentication_required": False,
                "error": "Google Calendar API not available. Install google-api-python-client and google-auth-oauthlib",
                "setup_instructions": [
                    "1. Install required packages: pip install google-api-python-client google-auth-oauthlib",
                    "2. Create a Google Cloud Project",
                    "3. Enable Google Calendar API",
                    "4. Create OAuth 2.0 credentials",
                    "5. Configure environment variables"
                ]
            }
    except Exception as e:
        logger.critical(
            f"Unexpected error getting Google Calendar configuration: {e}",
            LogCategory.EXCEPTION,
            exception=e
        )
        # Return error response instead of raising exception for config endpoint
        return {
            "google_calendar_api_available": False,
            "credentials_configured": False,
            "error": f"Failed to get configuration: {str(e)}",
            "features": {
                "provider_authentication": False,
                "event_creation": False,
                "event_updates": False,
                "event_deletion": False,
                "availability_sync": False,
                "conflict_detection": False,
                "conference_calls": False,
                "reminders": False
            }
        }
