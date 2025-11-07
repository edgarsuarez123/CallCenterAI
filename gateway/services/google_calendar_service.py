"""
Google Calendar Integration Service
Handles appointment synchronization with Google Calendar for providers and clinics.
"""

from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
import json
import logging
import os
from dataclasses import dataclass
from services.configuration import get_settings

# Get configuration
settings = get_settings()

# Google Calendar API imports
try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import Flow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    GOOGLE_CALENDAR_AVAILABLE = True
except ImportError:
    GOOGLE_CALENDAR_AVAILABLE = False
    # Create mock classes for when Google Calendar API is not available
    class Credentials:
        pass
    class Flow:
        pass
    class Request:
        pass
    class build:
        pass
    class HttpError(Exception):
        pass
    logging.warning("Google Calendar API not available. Install google-api-python-client and google-auth-oauthlib")

from models.models import Appointment, AppointmentSlot, Provider, Clinic
from models.schemas import AppointmentCreateRequest, AppointmentResponse


@dataclass
class GoogleCalendarConfig:
    """Configuration for Google Calendar integration."""
    client_id: str
    client_secret: str
    redirect_uri: str
    scopes: List[str] = None
    
    def __post_init__(self):
        if self.scopes is None:
            self.scopes = [
                'https://www.googleapis.com/auth/calendar',
                'https://www.googleapis.com/auth/calendar.events'
            ]


class GoogleCalendarService:
    """Service for Google Calendar integration and appointment synchronization."""

    def __init__(self, config: GoogleCalendarConfig, db_session=None):
        if not GOOGLE_CALENDAR_AVAILABLE:
            raise ImportError("Google Calendar API not available. Install required packages.")

        self.config = config
        self.service = None
        self.logger = logging.getLogger(__name__)
        self.db_session = db_session
        
        # Initialize credentials service if database session is provided
        if db_session:
            from services.google_calendar_credentials_service import GoogleCalendarCredentialsService
            self.credentials_service = GoogleCalendarCredentialsService(db_session)
        else:
            self.credentials_service = None
    
    def authenticate_provider(self, provider_id: str, auth_code: str = None) -> bool:
        """
        Authenticate a provider with Google Calendar.
        
        Args:
            provider_id: Provider ID
            auth_code: Authorization code from OAuth flow
            
        Returns:
            True if authentication successful
        """
        try:
            if auth_code:
                auth_code_preview = auth_code[:20] if len(auth_code) > 20 else auth_code
                self.logger.info(f"Starting OAuth flow for provider {provider_id} with auth code: {auth_code_preview}...")
                
                # Complete OAuth flow with authorization code
                flow = Flow.from_client_config(
                    {
                        "web": {
                            "client_id": self.config.client_id,
                            "client_secret": self.config.client_secret,
                            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                            "token_uri": "https://oauth2.googleapis.com/token",
                            "redirect_uris": [self.config.redirect_uri]
                        }
                    },
                    scopes=self.config.scopes
                )
                flow.redirect_uri = self.config.redirect_uri
                
                self.logger.info(f"Exchanging authorization code for tokens...")
                # Exchange authorization code for credentials
                flow.fetch_token(code=auth_code)
                self.logger.info(f"Successfully exchanged authorization code for tokens")
                credentials = flow.credentials
                
                # Store credentials for provider
                if self.credentials_service:
                    self.credentials_service.store_credentials(provider_id, credentials)
                else:
                    self.logger.warning("No database session provided, credentials not persisted")
                
            else:
                # Get stored credentials
                if self.credentials_service:
                    credentials = self.credentials_service.get_credentials(provider_id)
                else:
                    credentials = None
                    
                if not credentials:
                    return False
                
                # Refresh credentials if needed
                if credentials.expired and credentials.refresh_token:
                    credentials.refresh(Request())
                    # Save refreshed credentials
                    if self.credentials_service:
                        self.credentials_service.store_credentials(provider_id, credentials)
                        self.logger.info(f"Auto-refreshed and saved Google Calendar credentials for provider {provider_id}")
            
            # Build service with credentials
            self.service = build('calendar', 'v3', credentials=credentials)
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to authenticate provider {provider_id}: {str(e)}")
            self.logger.error(f"Exception type: {type(e).__name__}")
            import traceback
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            return False
    
    def create_calendar_event(self, provider_id: str, appointment: Appointment, 
                            patient_name: str = None) -> Optional[str]:
        """
        Create a calendar event for an appointment.
        
        Args:
            provider_id: Provider ID
            appointment: Appointment instance
            patient_name: Patient name (if available)
            
        Returns:
            Google Calendar event ID or None if failed
        """
        try:
            if not self.authenticate_provider(provider_id):
                return None
            
            # Get clinic and provider information
            clinic_info = self._get_clinic_info(provider_id)
            provider_email = self._get_provider_email(provider_id)
            
            # Prepare event data
            hipaa_compliant = settings.google_calendar.hipaa_compliant
            
            if hipaa_compliant and patient_name:
                # With BAA: Show patient name in summary
                summary = f'{clinic_info["clinic_name"]} - {patient_name}'
            else:
                # Without BAA: Show patient ID in summary
                summary = f'{clinic_info["clinic_name"]} - Patient {appointment.patient_id}'
            
            event_data = {
                'summary': summary,
                'description': self._format_appointment_description(appointment, patient_name, clinic_info),
                'start': {
                    'dateTime': appointment.start_time.isoformat(),
                    'timeZone': clinic_info["timezone"],
                },
                'end': {
                    'dateTime': appointment.end_time.isoformat(),
                    'timeZone': clinic_info["timezone"],
                },
                'attendees': [
                    {'email': provider_email},
                ],
                'reminders': {
                    'useDefault': False,
                    'overrides': [
                        {'method': 'email', 'minutes': 24 * 60},  # 1 day before
                        {'method': 'popup', 'minutes': 30},       # 30 minutes before
                    ],
                },
                'conferenceData': {
                    'createRequest': {
                        'requestId': f"callcenter-{appointment.appointment_id}",
                        'conferenceSolutionKey': {'type': 'hangoutsMeet'}
                    }
                }
            }
            
            # Create the event
            event = self.service.events().insert(
                calendarId='primary',
                body=event_data,
                conferenceDataVersion=1
            ).execute()
            
            self.logger.info(f"Created calendar event {event['id']} for appointment {appointment.appointment_id}")
            return event['id']
            
        except HttpError as e:
            self.logger.error(f"Google Calendar API error: {str(e)}")
            return None
        except Exception as e:
            self.logger.error(f"Failed to create calendar event: {str(e)}")
            return None
    
    def update_calendar_event(self, provider_id: str, event_id: str, 
                            appointment: Appointment, patient_name: str = None) -> bool:
        """
        Update an existing calendar event.
        
        Args:
            provider_id: Provider ID
            event_id: Google Calendar event ID
            appointment: Updated appointment instance
            patient_name: Patient name (if available)
            
        Returns:
            True if successful
        """
        try:
            if not self.authenticate_provider(provider_id):
                return False
            
            # Get existing event
            event = self.service.events().get(
                calendarId='primary',
                eventId=event_id
            ).execute()
            
            # Update event data
            event['summary'] = f'Appointment - {appointment.appointment_type}'
            event['description'] = self._format_appointment_description(appointment, patient_name)
            event['start'] = {
                'dateTime': appointment.start_time.isoformat(),
                'timeZone': 'America/New_York',
            }
            event['end'] = {
                'dateTime': appointment.end_time.isoformat(),
                'timeZone': 'America/New_York',
            }
            
            # Update the event
            updated_event = self.service.events().update(
                calendarId='primary',
                eventId=event_id,
                body=event
            ).execute()
            
            self.logger.info(f"Updated calendar event {event_id} for appointment {appointment.appointment_id}")
            return True
            
        except HttpError as e:
            self.logger.error(f"Google Calendar API error: {str(e)}")
            return False
        except Exception as e:
            self.logger.error(f"Failed to update calendar event: {str(e)}")
            return False
    
    def delete_calendar_event(self, provider_id: str, event_id: str) -> bool:
        """
        Delete a calendar event.
        
        Args:
            provider_id: Provider ID
            event_id: Google Calendar event ID
            
        Returns:
            True if successful
        """
        try:
            if not self.authenticate_provider(provider_id):
                return False
            
            self.service.events().delete(
                calendarId='primary',
                eventId=event_id
            ).execute()
            
            self.logger.info(f"Deleted calendar event {event_id}")
            return True
            
        except HttpError as e:
            self.logger.error(f"Google Calendar API error: {str(e)}")
            return False
        except Exception as e:
            self.logger.error(f"Failed to delete calendar event: {str(e)}")
            return False
    
    def sync_appointment_slots(self, provider_id: str, clinic_id: str, 
                             start_date: datetime, end_date: datetime) -> List[Dict]:
        """
        Sync appointment slots with Google Calendar availability.
        
        Args:
            provider_id: Provider ID
            clinic_id: Clinic ID
            start_date: Start date for sync
            end_date: End date for sync
            
        Returns:
            List of calendar events that conflict with appointment slots
        """
        try:
            if not self.authenticate_provider(provider_id):
                return []
            
            # Get calendar events in date range
            events_result = self.service.events().list(
                calendarId='primary',
                timeMin=start_date.isoformat() + 'Z',
                timeMax=end_date.isoformat() + 'Z',
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            events = events_result.get('items', [])
            conflicts = []
            
            for event in events:
                # Check if event conflicts with appointment slots
                if self._is_appointment_conflict(event):
                    conflicts.append({
                        'event_id': event['id'],
                        'summary': event.get('summary', 'No title'),
                        'start': event['start'].get('dateTime', event['start'].get('date')),
                        'end': event['end'].get('dateTime', event['end'].get('date')),
                        'conflict_type': 'calendar_event'
                    })
            
            return conflicts
            
        except Exception as e:
            self.logger.error(f"Failed to sync appointment slots: {str(e)}")
            return []
    
    def get_provider_availability(self, provider_id: str, date: datetime) -> List[Dict]:
        """
        Get provider's availability from Google Calendar.
        
        Args:
            provider_id: Provider ID
            date: Date to check availability
            
        Returns:
            List of available time slots
        """
        try:
            if not self.authenticate_provider(provider_id):
                return []
            
            start_of_day = date.replace(hour=0, minute=0, second=0, microsecond=0)
            end_of_day = start_of_day + timedelta(days=1)
            
            # Get calendar events for the day
            events_result = self.service.events().list(
                calendarId='primary',
                timeMin=start_of_day.isoformat() + 'Z',
                timeMax=end_of_day.isoformat() + 'Z',
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            events = events_result.get('items', [])
            
            # Calculate available slots (simplified - assumes 8 AM to 5 PM business hours)
            available_slots = []
            current_time = start_of_day.replace(hour=8, minute=0)
            end_time = start_of_day.replace(hour=17, minute=0)
            
            while current_time < end_time:
                slot_end = current_time + timedelta(hours=1)
                
                # Check if this slot conflicts with any events
                if not self._time_slot_conflicts(current_time, slot_end, events):
                    available_slots.append({
                        'start': current_time.isoformat(),
                        'end': slot_end.isoformat(),
                        'duration_minutes': 60
                    })
                
                current_time += timedelta(hours=1)
            
            return available_slots
            
        except Exception as e:
            self.logger.error(f"Failed to get provider availability: {str(e)}")
            return []
    
    def _format_appointment_description(self, appointment: Appointment, patient_name: str = None, clinic_info: dict = None) -> str:
        """Format appointment description for calendar event."""
        description = f"Appointment Type: {appointment.appointment_type}\n"
        description += f"Appointment ID: {appointment.appointment_id}\n"
        
        if clinic_info:
            description += f"Clinic: {clinic_info['clinic_name']}\n"
            description += f"Phone: {clinic_info['phone_number']}\n"
        
        # HIPAA-compliant patient identification
        from services.configuration import get_settings
        settings = get_settings()
        hipaa_compliant = settings.google_calendar.hipaa_compliant
        
        if hipaa_compliant and patient_name:
            # With Google Workspace BAA: Show patient name
            description += f"Patient: {patient_name}\n"
        else:
            # Without BAA: Show patient ID only (no PHI)
            description += f"Patient ID: {appointment.patient_id}\n"
            description += "(Look up patient details in system using Patient ID)\n"
        
        if appointment.notes_token:
            description += f"Notes: [Tokenized - {appointment.notes_token}]\n"
        
        description += f"Duration: {appointment.duration_minutes} minutes\n"
        description += f"Created: {appointment.created_at.strftime('%Y-%m-%d %H:%M')}\n"
        description += "Booked via CallCenterAI"
        
        return description
    
    def _is_appointment_conflict(self, event: Dict) -> bool:
        """Check if a calendar event conflicts with appointment scheduling."""
        # Skip all-day events
        if 'date' in event['start']:
            return False
        
        # Skip events marked as "free" or "tentative"
        if event.get('transparency') == 'transparent':
            return False
        
        # Skip declined events
        if event.get('attendees'):
            for attendee in event['attendees']:
                if attendee.get('self') and attendee.get('responseStatus') == 'declined':
                    return False
        
        return True
    
    def _time_slot_conflicts(self, start_time: datetime, end_time: datetime, events: List[Dict]) -> bool:
        """Check if a time slot conflicts with any calendar events."""
        for event in events:
            if 'dateTime' in event['start']:
                event_start = datetime.fromisoformat(event['start']['dateTime'].replace('Z', '+00:00'))
                event_end = datetime.fromisoformat(event['end']['dateTime'].replace('Z', '+00:00'))
                
                # Check for overlap
                if (start_time < event_end and end_time > event_start):
                    return True
        
        return False
    
    def _get_provider_email(self, provider_id: str) -> str:
        """Get provider's email address from database."""
        if not provider_id:
            self.logger.warning("Provider ID is empty, using fallback email")
            return "provider-unknown@clinic.com"
        
        try:
            from models.models import Provider
            if not self.db:
                self.logger.warning("No database session available, using fallback email")
                return f"provider-{provider_id}@clinic.com"
            
            provider = self.db.query(Provider).filter(Provider.provider_id == provider_id).first()
            if provider and provider.email:
                return provider.email
            else:
                # Fallback to clinic-specific email format
                return f"provider-{provider_id}@clinic.com"
        except Exception as e:
            self.logger.warning(f"Failed to get provider email for {provider_id}: {e}")
            return f"provider-{provider_id}@clinic.com"
    
    def _get_clinic_info(self, provider_id: str) -> dict:
        """Get clinic information for a provider."""
        if not provider_id:
            self.logger.warning("Provider ID is empty, using default clinic info")
            return {
                "clinic_name": "Medical Center",
                "timezone": "America/New_York",
                "phone_number": "+14071234567"
            }
        
        try:
            from models.models import Provider, Clinic
            if not self.db:
                self.logger.warning("No database session available, using default clinic info")
                return {
                    "clinic_name": "Medical Center",
                    "timezone": "America/New_York",
                    "phone_number": "+14071234567"
                }
            
            # Get provider's clinic through appointment slots or direct relationship
            provider = self.db.query(Provider).filter(Provider.provider_id == provider_id).first()
            if provider:
                # Try to get clinic info from appointment slots
                from models.models import AppointmentSlot
                slot = self.db.query(AppointmentSlot).filter(
                    AppointmentSlot.provider_id == provider_id
                ).first()
                if slot and slot.clinic_id:
                    clinic = self.db.query(Clinic).filter(Clinic.clinic_id == slot.clinic_id).first()
                    if clinic and clinic.clinic_id:
                        return {
                            "clinic_name": clinic.clinic_name or "Medical Center",
                            "timezone": clinic.timezone or "America/New_York",
                            "phone_number": clinic.phone_number or "+14071234567"
                        }
            
            # Fallback to default values
            return {
                "clinic_name": "Medical Center",
                "timezone": "America/New_York",
                "phone_number": "+14071234567"
            }
        except Exception as e:
            self.logger.warning(f"Failed to get clinic info for provider {provider_id}: {e}")
            return {
                "clinic_name": "Medical Center",
                "timezone": "America/New_York",
                "phone_number": "+14071234567"
            }
    
    def _get_provider_credentials(self, provider_id: str) -> Optional[Credentials]:
        """Get provider's stored Google Calendar credentials."""
        if self.credentials_service:
            return self.credentials_service.get_credentials(provider_id)
        else:
            self.logger.warning(f"No database session provided, cannot retrieve credentials for provider {provider_id}")
            return None


class GoogleCalendarIntegrationService:
    """High-level service for Google Calendar integration with appointment management."""
    
    def __init__(self, calendar_service: GoogleCalendarService):
        self.calendar_service = calendar_service
        self.logger = logging.getLogger(__name__)
    
    def sync_appointment_to_calendar(self, appointment: Appointment, provider_id: str, 
                                   patient_name: str = None) -> Optional[str]:
        """
        Sync an appointment to Google Calendar.
        
        Args:
            appointment: Appointment instance
            provider_id: Provider ID
            patient_name: Patient name (if available)
            
        Returns:
            Google Calendar event ID or None if failed
        """
        try:
            event_id = self.calendar_service.create_calendar_event(
                provider_id, appointment, patient_name
            )
            
            if event_id:
                self.logger.info(f"Successfully synced appointment {appointment.appointment_id} to calendar")
                # TODO: Store event_id in appointment record for future updates/deletions
            
            return event_id
            
        except Exception as e:
            self.logger.error(f"Failed to sync appointment to calendar: {str(e)}")
            return None
    
    def update_calendar_appointment(self, appointment: Appointment, provider_id: str,
                                  event_id: str, patient_name: str = None) -> bool:
        """
        Update an appointment in Google Calendar.
        
        Args:
            appointment: Updated appointment instance
            provider_id: Provider ID
            event_id: Google Calendar event ID
            patient_name: Patient name (if available)
            
        Returns:
            True if successful
        """
        try:
            success = self.calendar_service.update_calendar_event(
                provider_id, event_id, appointment, patient_name
            )
            
            if success:
                self.logger.info(f"Successfully updated calendar event {event_id}")
            
            return success
            
        except Exception as e:
            self.logger.error(f"Failed to update calendar appointment: {str(e)}")
            return False
    
    def cancel_calendar_appointment(self, provider_id: str, event_id: str) -> bool:
        """
        Cancel an appointment in Google Calendar.
        
        Args:
            provider_id: Provider ID
            event_id: Google Calendar event ID
            
        Returns:
            True if successful
        """
        try:
            success = self.calendar_service.delete_calendar_event(provider_id, event_id)
            
            if success:
                self.logger.info(f"Successfully cancelled calendar event {event_id}")
            
            return success
            
        except Exception as e:
            self.logger.error(f"Failed to cancel calendar appointment: {str(e)}")
            return False


# Singleton instance
_google_calendar_service: Optional[GoogleCalendarService] = None


def get_google_calendar_service() -> GoogleCalendarService:
    """Get the global GoogleCalendarService instance."""
    global _google_calendar_service
    if _google_calendar_service is None:
        from services.configuration import get_settings
        settings = get_settings()
        _google_calendar_service = GoogleCalendarService(
            config=settings.google_calendar,
            db_session=None
        )
    return _google_calendar_service