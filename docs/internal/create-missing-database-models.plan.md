<!-- 835f46f6-c662-48dd-8241-c989a46f0554 59f6250a-bb32-4511-8227-b5067a532244 -->
# Google Calendar Service Implementation Plan

## Overview

Create `Clinic_app/services/google_calendar.py` that provides async Google Calendar API integration for booking management. The service will authenticate using service account credentials stored in `ClinicIntegration`, and handle all calendar operations required for Phase 1 booking functionality.

## Key Requirements from PRD

### Authentication

- Use service account JSON from `ClinicIntegration.google_service_account_json`
- Support both JSON string and file path formats
- Create delegated credentials for domain-wide delegation (if needed)

### Event Operations

- **List events**: Fetch events for availability checking (with time range filtering)
- **Create event**: When booking is confirmed (with metadata)
- **Update event**: For reschedules
- **Delete event**: For cancellations
- **Get event**: Retrieve specific event by ID

### Metadata Handling

All events must include `extendedProperties.private`:

```json
{
  "source": "callcenter_ai",
  "booking_id": "<uuid>",
  "clinic_id": "<uuid>",
  "reminded": "false"
}
```

**Why Extended Properties?**
- `booking_id` exists before Google Calendar event creation (created when Booking record is created)
- Enables finding patient's existing booking by `booking_id` (not just event title)
- Filter "callcenter_ai" events vs manual events
- Track reminder status (`reminded: true/false`)
- Recover events if `google_event_id` is NULL (event creation failed)
- Audit and debugging

### Event Filtering Rules

- **Availability checking**: ALL events block capacity (regardless of source)
- **Patient lookup**: Filter by `source = "callcenter_ai"` to find our bookings

## Implementation Details

### File Structure

```
Clinic_app/
├── services/
│   ├── __init__.py (NEW)
│   └── google_calendar.py (NEW)
```

### Service Account JSON Handling

**What is Service Account JSON?**

- Google's authentication credentials file (JSON format) that allows the backend to access Google Calendar API
- Contains: service account email (system account, NOT the clinic's email), private key, project ID
- **Important**: Service account email is NOT the clinic/provider's Google account email
  - Service account: `callcenter-ai@your-project.iam.gserviceaccount.com` (system account, created in GCP)
  - Provider's calendar: `dr.smith@gmail.com` (actual Google account that owns the calendar)
- One service account per clinic, stored in `ClinicIntegration.google_service_account_json`
- **Setup requirement**: Each provider's Google Calendar must be shared with the service account email (giving it read/write permissions)
- The backend authenticates as the service account, then accesses calendars that have been shared with it

**Multi-Clinic Architecture:**
- Each clinic can have its own service account (recommended) OR share one service account
- Service account JSON is stored per clinic in `ClinicIntegration.google_service_account_json`
- The `clinic_id` parameter determines which service account to use

**Implementation:**
- Check if `google_service_account_json` is a file path (starts with `/` or `C:\` or relative path)
- If file path: Read and parse JSON file
- If JSON string: Parse directly
- **Validation**: Validate JSON structure on `ClinicIntegration` creation/update
  - Required fields: `type`, `project_id`, `private_key_id`, `private_key`, `client_email`
  - Raise validation error if JSON is invalid
- **No caching for Phase 1**: Parse credentials on each call (fast enough, ~1-6ms)
- Service account credentials don't expire (long-lived)

### Async Compatibility (Thread Pool Executor)

**Critical**: All Google Calendar API operations are **blocking** (synchronous). They MUST run in a thread pool to avoid blocking the async event loop.

**Operations requiring thread pool:**
- `list_events()` - HTTP GET (blocking)
- `create_event()` - HTTP POST (blocking)
- `update_event()` - HTTP PUT (blocking)
- `delete_event()` - HTTP DELETE (blocking)
- `get_event()` - HTTP GET (blocking)

**Implementation:**
- Use `ThreadPoolExecutor` (works on Python 3.8+, more compatible than `asyncio.to_thread()`)
- Create executor with `max_workers=10`
- Wrap ALL API calls in `loop.run_in_executor(executor, lambda: sync_function())`
- This prevents blocking the FastAPI event loop, allowing concurrent requests

### Core Functions

#### 1. `get_credentials(clinic_id: UUID, db: AsyncSession) -> google.auth.credentials.Credentials`

- Fetch `ClinicIntegration` by `clinic_id`
- Parse `google_service_account_json` (file or string)
- Validate JSON structure (required fields)
- Create `google.oauth2.service_account.Credentials` from JSON
- Return credentials object
- **Error handling**: Raise `GoogleCalendarAuthError` if clinic_integration not found or JSON invalid

#### 2. `get_calendar_service(clinic_id: UUID, db: AsyncSession) -> googleapiclient.discovery.Resource`

- Get credentials using `get_credentials()`
- Build Google Calendar API v3 service client
- Return service object
- **Error handling**: Raise `GoogleCalendarAuthError` on auth failures

#### 3. `list_events(calendar_id: str, time_min: datetime, time_max: datetime, clinic_id: UUID, db: AsyncSession, filter_by_source: Optional[str] = None) -> List[Dict]`

- Fetch events from Google Calendar API
- Parameters:
  - `calendar_id`: Provider's `google_calendar_id`
  - `time_min`, `time_max`: Timezone-aware datetime objects (RFC3339 format)
  - `clinic_id`: For authentication
  - `db`: Database session
  - `filter_by_source`: Optional filter (e.g., "callcenter_ai" for patient lookup)
- API call: `GET /calendar/v3/calendars/{calendarId}/events?timeMin=...&timeMax=...&singleEvents=true&orderBy=startTime`
- Filter events by `extendedProperties.private.source` if `filter_by_source` provided
- Parse and return list of event dictionaries
- **Error handling**: Retry with exponential backoff (3 attempts), log errors, return empty list on failure
- **Thread pool**: Run blocking API call in thread pool

#### 4. `create_event(calendar_id: str, start: datetime, end: datetime, summary: str, description: Optional[str], extended_properties: Dict, clinic_id: UUID, db: AsyncSession) -> Dict`

- Create new calendar event
- Parameters:
  - `start`, `end`: Timezone-aware datetime objects (keep provider timezone, format as RFC3339)
  - `summary`: Event title (e.g., "Appointment with John Smith")
  - `description`: Optional event description
  - `extended_properties`: Dict with `source`, `booking_id`, `clinic_id`, `reminded`
  - **Note**: `booking_id` exists before event creation (created when Booking record is created)
- API call: `POST /calendar/v3/calendars/{calendarId}/events`
- Return event dictionary with `id` field
- **Error handling**: Retry with exponential backoff, allow booking to proceed if GCal fails (graceful degradation)
- **Thread pool**: Run blocking API call in thread pool

#### 5. `update_event(calendar_id: str, event_id: str, start: Optional[datetime], end: Optional[datetime], summary: Optional[str], extended_properties: Optional[Dict], clinic_id: UUID, db: AsyncSession) -> Dict`

- Update existing calendar event
- Fetch existing event first, merge updates
- API call: `PUT /calendar/v3/calendars/{calendarId}/events/{eventId}`
- Return updated event dictionary
- **Error handling**: Handle 404 (event not found), retry on transient errors
- **Thread pool**: Run blocking API call in thread pool

#### 6. `delete_event(calendar_id: str, event_id: str, clinic_id: UUID, db: AsyncSession) -> bool`

- Delete calendar event
- API call: `DELETE /calendar/v3/calendars/{calendarId}/events/{eventId}`
- Return `True` on success, `False` if event not found
- **Error handling**: Handle 404 gracefully (return False), retry on transient errors
- **Thread pool**: Run blocking API call in thread pool

#### 7. `get_event(calendar_id: str, event_id: str, clinic_id: UUID, db: AsyncSession) -> Optional[Dict]`

- Retrieve specific event by ID
- API call: `GET /calendar/v3/calendars/{calendarId}/events/{eventId}`
- Return event dictionary or `None` if not found
- **Error handling**: Handle 404 gracefully (return None)
- **Thread pool**: Run blocking API call in thread pool

#### 8. `count_overlapping_events(events: List[Dict], slot_start: datetime, slot_end: datetime) -> int`

- Helper function to count events that overlap with a time slot
- Overlap logic: `event.start < slot_end AND event.end > slot_start`
- Return count of overlapping events
- Used by availability service for capacity checking

#### 9. `build_extended_properties(booking_id: UUID, clinic_id: UUID, reminded: bool = False) -> Dict`

- Helper function to create extended properties metadata dict
- Returns properly formatted `extendedProperties.private` structure
- Ensures consistent metadata format across all operations

#### 10. `parse_extended_properties(event: Dict) -> Optional[Dict]`

- Helper function to extract metadata from event
- Returns `private` extended properties dict or `None` if not found
- Used for filtering and finding bookings by `booking_id`

#### 11. `validate_calendar_access(calendar_id: str, clinic_id: UUID, db: AsyncSession) -> bool`

- Validate that service account can access the calendar
- Test calendar access before saving provider record
- Called on provider creation/update
- Return `True` if accessible, `False` if not found or not shared
- **Error handling**: Raise `GoogleCalendarNotFoundError` if calendar not accessible

### Error Handling & Retry Logic

#### Custom Exceptions

```python
class GoogleCalendarError(Exception):
    """Base exception for Google Calendar operations."""
    pass

class GoogleCalendarAuthError(GoogleCalendarError):
    """Authentication/authorization failures."""
    pass

class GoogleCalendarNotFoundError(GoogleCalendarError):
    """Event or calendar not found."""
    pass

class GoogleCalendarRateLimitError(GoogleCalendarError):
    """Rate limit exceeded."""
    pass
```

#### Retry Strategy

- Use `tenacity` library (already in requirements.txt)
- **Rate limit detection**: Detect HTTP 429 (rate limit) errors
- **Enhanced backoff for rate limits**: Longer delays (5s, 10s, 20s) for rate limits
- **Standard backoff**: 1s, 2s, 4s for other transient errors
- Max 3 attempts
- Retry on: 429 (rate limit), 500, 502, 503, 504
- Don't retry on: 400, 401, 403, 404

**Google Calendar API Rate Limits:**
- 1,000,000 requests/day (free tier)
- 300 requests/100 seconds/user (per-minute limit)
- 10 requests/second (burst limit)

#### Graceful Degradation

- If Google Calendar API fails after all retries, allow booking to proceed
- Store `google_event_id` as `NULL` if event creation fails
- Failed sync operations deferred to Phase 2 (background queue)
- Log all failures for manual review

### Timezone Handling

- **Keep provider timezone**: Don't convert to UTC
- All datetime parameters should be timezone-aware
- Format datetimes as RFC3339 (Google Calendar API accepts timezone-aware datetimes)
- Use provider's timezone from `Provider.timezone` field
- RFC3339 format: `YYYY-MM-DDTHH:MM:SS+/-HH:MM` or `YYYY-MM-DDTHH:MM:SSZ`
- Python's `datetime.isoformat()` produces RFC3339-compatible output

### Structured Error Logging

**Essential for debugging and monitoring:**

- Log all Google Calendar API operations with context
- Include: `clinic_id`, `calendar_id`, `operation`, `error_code`, `retry_count`, `duration_ms`
- No PHI in logs (no patient names, phone numbers, etc.)
- Log successful operations (for audit trail)
- Log failures with full context (for debugging)
- Use structured logging format (JSON or key-value pairs)

### Integration Points

#### With Booking Service (Future)

- `create_event()` called when booking status changes to `CONFIRMED`
- `update_event()` called when booking is rescheduled
- `delete_event()` called when booking is canceled
- Store `google_event_id` in `Booking.google_event_id`
- Use `booking_id` (exists before event creation) in extended properties

#### With Availability Service (Future)

- `list_events()` called to check existing events for capacity
- `count_overlapping_events()` used to determine if slot is available
- Filter by `source` when needed (find patient's bookings)

#### With Database Models

- `ClinicIntegration`: Source of service account JSON (validate on create/update)
- `Provider`: Contains `google_calendar_id` (validate calendar access on create/update)
- `Booking`: Stores `google_event_id` after event creation

## Dependencies

### Python Packages (verify in requirements.txt)

- `google-auth==2.23.4` ✅
- `google-auth-oauthlib==1.1.0` ✅
- `google-api-python-client==2.108.0` ✅
- `tenacity==8.2.3` ✅ (for retry logic)

### Additional Packages (may need to add)

- `pytz` or `zoneinfo` (Python 3.9+) for timezone handling
- Note: Python 3.8+ required (use `ThreadPoolExecutor`, not `asyncio.to_thread()`)

## Testing Strategy

### Unit Tests (Phase 1)

- Mock Google Calendar API responses
- Test retry logic (including rate limit handling)
- Test timezone conversions (RFC3339 formatting)
- Test event filtering by `source`
- Test extended properties helpers (`build_extended_properties`, `parse_extended_properties`)
- Test error scenarios (invalid credentials, rate limits, 404s)
- Test calendar validation
- Test service account JSON validation

### Integration Tests (Future)

- Test with real Google Calendar (test account)
- Test error scenarios (invalid credentials, rate limits)
- Test graceful degradation (allow booking if GCal fails)

## Implementation Order

1. **Create service file structure**
   - Create `Clinic_app/services/__init__.py`
   - Create `Clinic_app/services/google_calendar.py` with class structure

2. **Implement authentication**
   - `get_credentials()` function with JSON validation
   - `get_calendar_service()` function
   - Handle JSON string vs file path
   - Service account JSON validation

3. **Implement thread pool executor**
   - Create `ThreadPoolExecutor` instance
   - Add helper method to run blocking calls in thread pool

4. **Implement core CRUD operations (all with thread pool)**
   - `list_events()` with filtering
   - `create_event()` with metadata
   - `update_event()`
   - `delete_event()`
   - `get_event()`

5. **Add helper functions**
   - `count_overlapping_events()`
   - `build_extended_properties()`
   - `parse_extended_properties()`
   - `validate_calendar_access()`

6. **Add error handling**
   - Custom exception classes
   - Retry decorators using `tenacity` (with rate limit detection)
   - Enhanced backoff for rate limits
   - Graceful degradation (allow booking if GCal fails)

7. **Add structured logging**
   - Log all API calls (without sensitive data)
   - Log errors with context (clinic_id, calendar_id, operation, error_code, retry_count)
   - No PHI in logs

8. **Add unit tests**
   - Test all operations with mocked API responses
   - Test retry logic and rate limit handling
   - Test extended properties helpers
   - Test calendar validation

## Code Structure Example

```python
# Clinic_app/services/google_calendar.py
import json
import os
import asyncio
from typing import Optional, List, Dict
from datetime import datetime
from uuid import UUID
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy.ext.asyncio import AsyncSession
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import logging

logger = logging.getLogger(__name__)

# Thread pool executor for blocking API calls
_executor = ThreadPoolExecutor(max_workers=10)

class GoogleCalendarError(Exception):
    """Base exception for Google Calendar operations."""
    pass

class GoogleCalendarAuthError(GoogleCalendarError):
    """Authentication/authorization failures."""
    pass

class GoogleCalendarNotFoundError(GoogleCalendarError):
    """Event or calendar not found."""
    pass

class GoogleCalendarRateLimitError(GoogleCalendarError):
    """Rate limit exceeded."""
    pass

class GoogleCalendarService:
    """Service for Google Calendar API operations."""
    
    @staticmethod
    async def _run_in_thread(func):
        """Run blocking function in thread pool."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(_executor, func)
    
    @staticmethod
    async def get_credentials(clinic_id: UUID, db: AsyncSession):
        """Get service account credentials for clinic."""
        # Implementation with validation
        pass
    
    @staticmethod
    async def list_events(...):
        """List events in time range."""
        # Implementation with thread pool
        pass
    
    @staticmethod
    def build_extended_properties(booking_id: UUID, clinic_id: UUID, reminded: bool = False) -> Dict:
        """Build extended properties metadata dict."""
        pass
    
    @staticmethod
    def parse_extended_properties(event: Dict) -> Optional[Dict]:
        """Extract extended properties from event."""
        pass
    
    # ... other methods ...
```

## Success Criteria

- Service can authenticate using `ClinicIntegration.google_service_account_json`
- Can list events for availability checking
- Can create events with proper metadata (including `booking_id`)
- Can update events for reschedules
- Can delete events for cancellations
- Handles errors gracefully with retries (including rate limit detection)
- Logs operations without PHI (structured logging)
- Integrates cleanly with existing database models
- All operations run in thread pool (non-blocking)
- Calendar access validated on provider create/update
- Service account JSON validated on ClinicIntegration create/update
- Unit tests pass

## Notes

- **Failed sync queue**: Deferred to Phase 2 (background worker to retry failed GCal operations)
- **Credential caching**: Deferred to Phase 2 (parse on each call for Phase 1)
- **Python version**: Use `ThreadPoolExecutor` (Python 3.8+ compatible)
- Service will be used by Availability Service and Booking Service (to be implemented in Week 2)
- `booking_id` exists before Google Calendar event creation (created when Booking record is created)

### To-dos

- [ ] Create services directory and __init__.py
- [ ] Implement get_credentials() with JSON validation
- [ ] Implement get_calendar_service()
- [ ] Implement ThreadPoolExecutor wrapper
- [ ] Implement list_events() with thread pool and filtering
- [ ] Implement create_event() with thread pool and metadata
- [ ] Implement update_event() with thread pool
- [ ] Implement delete_event() with thread pool
- [ ] Implement get_event() with thread pool
- [ ] Implement count_overlapping_events() helper
- [ ] Implement build_extended_properties() helper
- [ ] Implement parse_extended_properties() helper
- [ ] Implement validate_calendar_access() helper
- [ ] Add custom exception classes
- [ ] Add retry logic with rate limit detection
- [ ] Add structured error logging
- [ ] Add unit tests
- [ ] Update PRD.md and PHASE_1_IMPLEMENTATION.md with failed sync queue deferred to Phase 2

