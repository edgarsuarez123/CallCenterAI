"""
Google Calendar Integration API Routes
REST endpoints for Google Calendar operations including authentication, sync, and management.
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta, timezone
from pydantic import BaseModel
import os
import secrets

from services.database import get_db
from services.google_calendar_service import (
    GoogleCalendarService, GoogleCalendarIntegrationService, GoogleCalendarConfig
)
from services.configuration import get_settings
from models.schemas import SuccessResponse, ErrorResponse

router = APIRouter(prefix="/v1/google-calendar", tags=["google-calendar"])


class AuthenticateProviderRequest(BaseModel):
    auth_code: Optional[str] = None


def get_google_calendar_config() -> GoogleCalendarConfig:
    """Get Google Calendar configuration from application settings."""
    settings = get_settings()
    
    if not settings.google_calendar.client_id or not settings.google_calendar.client_secret.get_secret_value():
        raise HTTPException(
            status_code=500,
            detail="Google Calendar credentials not configured. Please set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET environment variables."
        )
    
    config = GoogleCalendarConfig(
        client_id=settings.google_calendar.client_id,
        client_secret=settings.google_calendar.client_secret.get_secret_value(),
        redirect_uri=settings.google_calendar.redirect_uri
    )
    
    return config


@router.get("/oauth/start")
def start_oauth_flow():
    """
    Start Google Calendar OAuth flow.
    
    This endpoint initiates the OAuth flow by redirecting the user to Google's
    authorization server where they can grant permission for the app to access
    their Google Calendar.
    """
    try:
        # Get environment variables directly
        client_id = os.getenv('GOOGLE_CLIENT_ID')
        client_secret = os.getenv('GOOGLE_CLIENT_SECRET')
        redirect_uri = os.getenv('GOOGLE_REDIRECT_URI', 'http://localhost:8443/api/v1/google-calendar/oauth/callback')
        
        if not client_id or not client_secret:
            raise HTTPException(
                status_code=500,
                detail="Google Calendar credentials not configured. Please set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET environment variables."
            )
        
        print(f"DEBUG: Direct env vars - client_id: {client_id[:20]}..., redirect_uri: {redirect_uri}")
        
        # Generate a random state parameter for security
        state = secrets.token_urlsafe(32)
        
        # Build the OAuth URL directly
        scopes = [
            'https://www.googleapis.com/auth/calendar',
            'https://www.googleapis.com/auth/calendar.events'
        ]
        scopes_str = '+'.join(scopes)
        
        oauth_url = (
            f"https://accounts.google.com/o/oauth2/auth?"
            f"client_id={client_id}&"
            f"redirect_uri={redirect_uri}&"
            f"scope={scopes_str}&"
            f"response_type=code&"
            f"state={state}&"
            f"access_type=offline&"
            f"prompt=consent"
        )
        
        print(f"DEBUG: OAuth URL: {oauth_url[:100]}...")
        
        return RedirectResponse(url=oauth_url)
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to start OAuth flow: {str(e)}"
        )


@router.get("/oauth/callback")
def oauth_callback(
    request: Request,
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None)
):
    """
    Handle Google Calendar OAuth callback.
    
    This endpoint receives the authorization code from Google after the user
    grants permission. The code can then be used to authenticate providers.
    """
    try:
        if error:
            raise HTTPException(
                status_code=400,
                detail=f"OAuth error: {error}"
            )
        
        if not code:
            raise HTTPException(
                status_code=400,
                detail="Authorization code not provided"
            )
        
        # For now, just return the code for manual use
        # In a real implementation, you would store this and associate it with a provider
        return {
            "message": "OAuth callback received successfully",
            "code": code,
            "state": state,
            "next_steps": [
                "Use this authorization code to authenticate a provider",
                "POST to /api/v1/google-calendar/providers/{provider_id}/authenticate with the code",
                "Or use the code in your application to complete the OAuth flow"
            ]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to handle OAuth callback: {str(e)}"
        )


@router.post("/providers/{provider_id}/authenticate", response_model=dict)
def authenticate_provider(
    provider_id: str,
    request: AuthenticateProviderRequest,
    db: Session = Depends(get_db)
):
    """
    Authenticate a provider with Google Calendar.
    
    This endpoint:
    - Initiates OAuth flow for Google Calendar access
    - Stores provider credentials securely
    - Enables calendar synchronization
    - Returns authentication status
    
    If auth_code is provided, completes the OAuth flow.
    Otherwise, returns the authorization URL for the OAuth flow.
    """
    try:
        # Get environment variables directly
        client_id = os.getenv('GOOGLE_CLIENT_ID')
        client_secret = os.getenv('GOOGLE_CLIENT_SECRET')
        redirect_uri = os.getenv('GOOGLE_REDIRECT_URI', 'http://localhost:8443/api/v1/google-calendar/oauth/callback')
        
        if not client_id or not client_secret:
            raise HTTPException(
                status_code=500,
                detail="Google Calendar credentials not configured. Please set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET environment variables."
            )
        
        # Create config object directly
        config = GoogleCalendarConfig(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri
        )
        
        calendar_service = GoogleCalendarService(config, db)
        
        if request.auth_code:
            print(f"DEBUG: Attempting to authenticate provider {provider_id} with auth code: {request.auth_code[:20]}...")
            # Complete OAuth flow
            success = calendar_service.authenticate_provider(provider_id, request.auth_code)
            print(f"DEBUG: Authentication result: {success}")
            
            if success:
                return {
                    "provider_id": provider_id,
                    "status": "authenticated",
                    "message": "Provider successfully authenticated with Google Calendar"
                }
            else:
                print(f"DEBUG: Authentication failed for provider {provider_id}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Failed to authenticate provider with Google Calendar"
                )
        else:
            # Return authorization URL for OAuth flow
            # In a real implementation, you would generate the OAuth URL here
            auth_url = f"https://accounts.google.com/o/oauth2/auth?client_id={config.client_id}&redirect_uri={config.redirect_uri}&scope={'+'.join(config.scopes)}&response_type=code"
            
            return {
                "provider_id": provider_id,
                "status": "pending_authentication",
                "authorization_url": auth_url,
                "message": "Please visit the authorization URL to complete authentication"
            }
            
    except ImportError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google Calendar API not available. Please install google-api-python-client and google-auth-oauthlib"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to authenticate provider: {str(e)}"
        )


@router.get("/providers/{provider_id}/availability", response_model=List[dict])
def get_provider_availability(
    provider_id: str,
    date: datetime,
    db: Session = Depends(get_db)
):
    """
    Get provider's availability from Google Calendar.
    
    Returns available time slots for the specified date
    based on the provider's Google Calendar.
    """
    try:
        # Initialize Google Calendar service
        config = GoogleCalendarConfig(
            client_id="your_google_client_id",
            client_secret="your_google_client_secret",
            redirect_uri="http://localhost:8000/auth/callback"
        )
        
        calendar_service = GoogleCalendarService(config)
        availability = calendar_service.get_provider_availability(provider_id, date)
        
        return [
            {
                "start": slot["start"],
                "end": slot["end"],
                "duration_minutes": slot["duration_minutes"]
            }
            for slot in availability
        ]
    except ImportError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google Calendar API not available"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get provider availability: {str(e)}"
        )


@router.post("/providers/{provider_id}/sync-slots", response_model=dict)
def sync_appointment_slots(
    provider_id: str,
    start_date: datetime,
    end_date: datetime,
    db: Session = Depends(get_db)
):
    """
    Sync appointment slots with Google Calendar availability.
    
    This endpoint:
    - Checks for conflicts between appointment slots and calendar events
    - Identifies unavailable time periods
    - Returns conflict information
    """
    try:
        # Initialize Google Calendar service
        config = GoogleCalendarConfig(
            client_id="your_google_client_id",
            client_secret="your_google_client_secret",
            redirect_uri="http://localhost:8000/auth/callback"
        )
        
        calendar_service = GoogleCalendarService(config)
        conflicts = calendar_service.sync_appointment_slots(
            provider_id, start_date, end_date
        )
        
        return {
            "provider_id": provider_id,
            "date_range": {
                "start_date": start_date,
                "end_date": end_date
            },
            "conflicts": conflicts,
            "conflict_count": len(conflicts),
            "message": f"Found {len(conflicts)} conflicts with Google Calendar"
        }
    except ImportError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google Calendar API not available"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to sync appointment slots: {str(e)}"
        )


@router.post("/events", response_model=dict)
def create_calendar_event(
    provider_id: str,
    appointment_id: str,
    patient_name: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Create a calendar event for an existing appointment.
    
    This endpoint:
    - Creates a Google Calendar event for the appointment
    - Includes patient information and appointment details
    - Sets up reminders and conference call
    - Returns the calendar event ID
    """
    try:
        # Get appointment details
        from services.appointment_service import AppointmentService
        appointment_service = AppointmentService(db)
        appointment = appointment_service.get_appointment(appointment_id)
        
        if not appointment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Appointment {appointment_id} not found"
            )
        
        # Initialize Google Calendar service
        config = GoogleCalendarConfig(
            client_id="your_google_client_id",
            client_secret="your_google_client_secret",
            redirect_uri="http://localhost:8000/auth/callback"
        )
        
        calendar_service = GoogleCalendarService(config)
        integration_service = GoogleCalendarIntegrationService(calendar_service)
        
        # Create calendar event
        event_id = integration_service.sync_appointment_to_calendar(
            appointment, provider_id, patient_name
        )
        
        if event_id:
            return {
                "appointment_id": appointment_id,
                "provider_id": provider_id,
                "google_calendar_event_id": event_id,
                "status": "created",
                "message": "Calendar event created successfully"
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to create calendar event"
            )
            
    except ImportError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google Calendar API not available"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create calendar event: {str(e)}"
        )


@router.put("/events/{event_id}", response_model=SuccessResponse)
def update_calendar_event(
    event_id: str,
    provider_id: str,
    appointment_id: str,
    patient_name: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Update an existing calendar event.
    
    This endpoint:
    - Updates the Google Calendar event with new appointment details
    - Syncs changes from the appointment record
    - Maintains event consistency
    """
    try:
        # Get appointment details
        from services.appointment_service import AppointmentService
        appointment_service = AppointmentService(db)
        appointment = appointment_service.get_appointment(appointment_id)
        
        if not appointment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Appointment {appointment_id} not found"
            )
        
        # Initialize Google Calendar service
        config = GoogleCalendarConfig(
            client_id="your_google_client_id",
            client_secret="your_google_client_secret",
            redirect_uri="http://localhost:8000/auth/callback"
        )
        
        calendar_service = GoogleCalendarService(config)
        integration_service = GoogleCalendarIntegrationService(calendar_service)
        
        # Update calendar event
        success = integration_service.update_calendar_appointment(
            appointment, provider_id, event_id, patient_name
        )
        
        if success:
            return SuccessResponse(
                message=f"Calendar event {event_id} updated successfully"
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to update calendar event"
            )
            
    except ImportError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google Calendar API not available"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update calendar event: {str(e)}"
        )


@router.delete("/events/{event_id}", response_model=SuccessResponse)
def delete_calendar_event(
    event_id: str,
    provider_id: str,
    db: Session = Depends(get_db)
):
    """
    Delete a calendar event.
    
    This endpoint:
    - Removes the Google Calendar event
    - Used when appointments are cancelled
    - Cleans up calendar entries
    """
    try:
        # Initialize Google Calendar service
        config = GoogleCalendarConfig(
            client_id="your_google_client_id",
            client_secret="your_google_client_secret",
            redirect_uri="http://localhost:8000/auth/callback"
        )
        
        calendar_service = GoogleCalendarService(config)
        integration_service = GoogleCalendarIntegrationService(calendar_service)
        
        # Delete calendar event
        success = integration_service.cancel_calendar_appointment(provider_id, event_id)
        
        if success:
            return SuccessResponse(
                message=f"Calendar event {event_id} deleted successfully"
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to delete calendar event"
            )
            
    except ImportError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google Calendar API not available"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete calendar event: {str(e)}"
        )


@router.get("/providers/{provider_id}/status", response_model=dict)
def get_provider_calendar_status(
    provider_id: str,
    db: Session = Depends(get_db)
):
    """
    Get provider's Google Calendar integration status.
    
    Returns information about:
    - Authentication status
    - Calendar access permissions
    - Sync configuration
    - Last sync time
    """
    try:
        # Get environment variables directly
        client_id = os.getenv('GOOGLE_CLIENT_ID')
        client_secret = os.getenv('GOOGLE_CLIENT_SECRET')
        redirect_uri = os.getenv('GOOGLE_REDIRECT_URI', 'http://localhost:8443/api/v1/google-calendar/oauth/callback')
        
        if not client_id or not client_secret:
            raise HTTPException(
                status_code=500,
                detail="Google Calendar credentials not configured. Please set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET environment variables."
            )
        
        # Create config object directly
        config = GoogleCalendarConfig(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri
        )
        
        calendar_service = GoogleCalendarService(config, db)
        
        # Check if provider has stored credentials
        credentials = calendar_service._get_provider_credentials(provider_id)
        is_authenticated = credentials is not None and not credentials.expired
        
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
            "last_checked": datetime.now(timezone.utc)
        }
    except ImportError:
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
            "last_checked": datetime.now(timezone.utc)
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get provider calendar status: {str(e)}"
        )


@router.get("/config", response_model=dict)
def get_google_calendar_config():
    """
    Get Google Calendar integration configuration.
    
    Returns configuration information including:
    - Available features
    - Authentication requirements
    - API status
    - Setup instructions
    """
    try:
        # Check if Google Calendar API is available
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import Flow
        from googleapiclient.discovery import build
        
        return {
            "google_calendar_api_available": True,
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
        return {
            "google_calendar_api_available": False,
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
