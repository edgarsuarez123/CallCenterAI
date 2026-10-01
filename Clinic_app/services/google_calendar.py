"""
Google Calendar Service

Provides async Google Calendar API integration for booking management.
Handles authentication, CRUD operations, error handling, and thread pool execution.
"""

import json
import asyncio
import time
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime
from uuid import UUID
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import logging

from Clinic_app.data.models.clinic_integration import ClinicIntegration

logger = logging.getLogger(__name__)

# Thread pool executor for blocking API calls
_executor = ThreadPoolExecutor(max_workers=10)


# Custom Exceptions
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
    def _validate_service_account_json(json_data: Dict) -> bool:
        """
        Validate service account JSON has required fields.

        Args:
            json_data: Parsed JSON dictionary

        Returns:
            True if valid, False otherwise
        """
        required_fields = ["type", "project_id", "private_key_id", "private_key", "client_email"]
        return all(key in json_data for key in required_fields)

    @staticmethod
    async def get_credentials(clinic_id: UUID, db: AsyncSession):
        """
        Get service account credentials for clinic.

        Args:
            clinic_id: UUID of the clinic
            db: Database session

        Returns:
            google.oauth2.service_account.Credentials object

        Raises:
            GoogleCalendarAuthError: If clinic_integration not found or JSON invalid
        """
        # Fetch ClinicIntegration
        stmt = select(ClinicIntegration).where(ClinicIntegration.clinic_id == clinic_id)
        result = await db.execute(stmt)
        integration = result.scalar_one_or_none()

        if not integration:
            raise GoogleCalendarAuthError(f"ClinicIntegration not found for clinic_id: {clinic_id}")

        # Parse service account JSON — must be a JSON object, never a file path (M5: path traversal prevention)
        json_str = integration.google_service_account_json
        if not json_str or not json_str.strip().startswith("{"):
            raise GoogleCalendarAuthError(
                "google_service_account_json must contain JSON content, not a file path"
            )
        try:
            json_data = json.loads(json_str)
        except json.JSONDecodeError as e:
            raise GoogleCalendarAuthError(f"Invalid service account JSON: {e}")

        # Validate JSON structure
        if not GoogleCalendarService._validate_service_account_json(json_data):
            raise GoogleCalendarAuthError("Service account JSON missing required fields")

        # Create credentials
        try:
            credentials = service_account.Credentials.from_service_account_info(json_data)
            return credentials
        except Exception as e:
            raise GoogleCalendarAuthError(f"Failed to create credentials: {e}")

    @staticmethod
    async def get_calendar_service(clinic_id: UUID, db: AsyncSession):
        """
        Get Google Calendar API v3 service client.

        Args:
            clinic_id: UUID of the clinic
            db: Database session

        Returns:
            googleapiclient.discovery.Resource (Calendar API service)

        Raises:
            GoogleCalendarAuthError: On auth failures
        """
        credentials = await GoogleCalendarService.get_credentials(clinic_id, db)

        try:
            service = build("calendar", "v3", credentials=credentials)
            return service
        except Exception as e:
            raise GoogleCalendarAuthError(f"Failed to build calendar service: {e}")

    @staticmethod
    def _is_rate_limit_error(error: HttpError) -> bool:
        """Check if error is a rate limit error (HTTP 429)."""
        return error.resp.status == 429

    @staticmethod
    def _should_retry_error(error: HttpError) -> bool:
        """Check if error should be retried."""
        retryable_statuses = [429, 500, 502, 503, 504]
        return error.resp.status in retryable_statuses

    @staticmethod
    async def _execute_with_retry(
        operation_name: str,
        clinic_id: UUID,
        calendar_id: str,
        sync_func,
        db: AsyncSession,
        graceful_degradation: bool = False,
        return_on_404: Optional[Any] = None,
        **log_context,
    ) -> Optional[Any]:
        """
        Execute a Google Calendar API operation with retry logic.

        Args:
            operation_name: Name of operation for logging
            clinic_id: Clinic UUID
            calendar_id: Calendar ID
            sync_func: Synchronous function to execute (will be wrapped in thread pool)
            db: Database session
            graceful_degradation: If True, return None/return_on_404 on failure instead of raising
            return_on_404: Value to return on 404 error (default: None)
            **log_context: Additional context for logging

        Returns:
            Result of operation, or None/return_on_404 if graceful_degradation=True and operation failed

        Raises:
            GoogleCalendarAuthError: On 403 errors (always raised)
            GoogleCalendarError: On other errors if graceful_degradation=False
        """
        start_time = time.time()
        max_attempts = 3
        last_error = None

        for attempt in range(max_attempts):
            try:
                result = await GoogleCalendarService._run_in_thread(sync_func)
                duration_ms = int((time.time() - start_time) * 1000)
                logger.info(
                    "Google Calendar API operation successful",
                    extra={
                        "clinic_id": str(clinic_id),
                        "calendar_id": calendar_id,
                        "operation": operation_name,
                        "attempt": attempt + 1,
                        "duration_ms": duration_ms,
                        **log_context,
                    },
                )
                return result

            except HttpError as e:
                last_error = e

                # Handle 404 (not found)
                if e.resp.status == 404:
                    duration_ms = int((time.time() - start_time) * 1000)
                    logger.warning(
                        "Google Calendar resource not found",
                        extra={
                            "clinic_id": str(clinic_id),
                            "calendar_id": calendar_id,
                            "operation": operation_name,
                            "error_code": e.resp.status,
                            "duration_ms": duration_ms,
                            **log_context,
                        },
                    )
                    return return_on_404

                # Handle 403 (access denied) - always raise
                if e.resp.status == 403:
                    duration_ms = int((time.time() - start_time) * 1000)
                    logger.error(
                        "Google Calendar API access denied",
                        extra={
                            "clinic_id": str(clinic_id),
                            "calendar_id": calendar_id,
                            "operation": operation_name,
                            "error_code": e.resp.status,
                            "duration_ms": duration_ms,
                            **log_context,
                        },
                    )
                    raise GoogleCalendarAuthError(f"Access denied to calendar {calendar_id}")

                # Don't retry on non-retryable errors
                if not GoogleCalendarService._should_retry_error(e):
                    break

                # Retry logic
                if attempt < max_attempts - 1:
                    # Calculate backoff delay
                    if GoogleCalendarService._is_rate_limit_error(e):
                        # Enhanced backoff for rate limits: 5s, 10s, 20s
                        delay = [5, 10, 20][min(attempt, 2)]
                    else:
                        # Standard backoff: 1s, 2s, 4s
                        delay = 2**attempt

                    logger.warning(
                        "Google Calendar API operation failed, retrying",
                        extra={
                            "clinic_id": str(clinic_id),
                            "calendar_id": calendar_id,
                            "operation": operation_name,
                            "error_code": e.resp.status,
                            "attempt": attempt + 1,
                            "max_attempts": max_attempts,
                            "retry_delay": delay,
                            **log_context,
                        },
                    )
                    await asyncio.sleep(delay)
                else:
                    # Last attempt failed
                    break

            except Exception as e:
                last_error = e
                if attempt < max_attempts - 1:
                    delay = 2**attempt
                    await asyncio.sleep(delay)
                else:
                    break

        # All retries exhausted
        duration_ms = int((time.time() - start_time) * 1000)
        error_code = (
            last_error.resp.status if (last_error and isinstance(last_error, HttpError)) else None
        )

        if graceful_degradation:
            logger.warning(
                "Google Calendar API operation failed after retries - graceful degradation",
                extra={
                    "clinic_id": str(clinic_id),
                    "calendar_id": calendar_id,
                    "operation": operation_name,
                    "error_code": error_code,
                    "attempts": max_attempts,
                    "duration_ms": duration_ms,
                    **log_context,
                },
            )
            return None
        else:
            logger.error(
                "Google Calendar API operation failed after retries",
                extra={
                    "clinic_id": str(clinic_id),
                    "calendar_id": calendar_id,
                    "operation": operation_name,
                    "error_code": error_code,
                    "attempts": max_attempts,
                    "duration_ms": duration_ms,
                    **log_context,
                },
                exc_info=True,
            )
            if isinstance(last_error, HttpError):
                raise GoogleCalendarError(f"Failed {operation_name}: {last_error}")
            else:
                raise GoogleCalendarError(f"Failed {operation_name}: {last_error}")

    @staticmethod
    def build_extended_properties(
        booking_id: UUID, clinic_id: UUID, reminded: bool = False
    ) -> Dict:
        """
        Build extended properties metadata dict.

        Args:
            booking_id: UUID of the booking
            clinic_id: UUID of the clinic
            reminded: Whether reminder has been sent

        Returns:
            Dict with extendedProperties.private structure
        """
        return {
            "extendedProperties": {
                "private": {
                    "source": "callcenter_ai",
                    "booking_id": str(booking_id),
                    "clinic_id": str(clinic_id),
                    "reminded": "true" if reminded else "false",
                }
            }
        }

    @staticmethod
    def parse_extended_properties(event: Dict) -> Optional[Dict]:
        """
        Extract extended properties from event.

        Args:
            event: Google Calendar event dictionary

        Returns:
            Dict with private extended properties or None if not found
        """
        return event.get("extendedProperties", {}).get("private")

    @staticmethod
    def count_overlapping_events(
        events: List[Dict], slot_start: datetime, slot_end: datetime
    ) -> int:
        """
        Count events that overlap with a time slot.

        Args:
            events: List of Google Calendar event dictionaries
            slot_start: Start datetime of the slot
            slot_end: End datetime of the slot

        Returns:
            Count of overlapping events
        """
        count = 0
        for event in events:
            event_start_str = event.get("start", {}).get("dateTime") or event.get("start", {}).get(
                "date"
            )
            event_end_str = event.get("end", {}).get("dateTime") or event.get("end", {}).get("date")

            if not event_start_str or not event_end_str:
                continue

            # Parse datetime strings (RFC3339 format)
            try:
                event_start = datetime.fromisoformat(event_start_str.replace("Z", "+00:00"))
                event_end = datetime.fromisoformat(event_end_str.replace("Z", "+00:00"))

                # Overlap logic: event.start < slot_end AND event.end > slot_start
                if event_start < slot_end and event_end > slot_start:
                    count += 1
            except (ValueError, AttributeError):
                # Skip events with invalid datetime formats
                continue

        return count

    @staticmethod
    async def list_events(
        calendar_id: str,
        time_min: datetime,
        time_max: datetime,
        clinic_id: UUID,
        db: AsyncSession,
        filter_by_source: Optional[str] = None,
    ) -> List[Dict]:
        """
        List events from Google Calendar API.

        Args:
            calendar_id: Provider's google_calendar_id
            time_min: Start datetime (timezone-aware)
            time_max: End datetime (timezone-aware)
            clinic_id: For authentication
            db: Database session
            filter_by_source: Optional filter (e.g., "callcenter_ai")

        Returns:
            List of event dictionaries
        """
        service = await GoogleCalendarService.get_calendar_service(clinic_id, db)

        # Format datetimes as RFC3339
        time_min_str = time_min.isoformat()
        time_max_str = time_max.isoformat()

        def _list_events_sync():
            """Synchronous function to list events."""
            return (
                service.events()
                .list(
                    calendarId=calendar_id,
                    timeMin=time_min_str,
                    timeMax=time_max_str,
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )

        # Execute with retry logic (graceful degradation - return empty list on failure)
        response = await GoogleCalendarService._execute_with_retry(
            operation_name="list_events",
            clinic_id=clinic_id,
            calendar_id=calendar_id,
            sync_func=_list_events_sync,
            db=db,
            graceful_degradation=True,
            return_on_404=None,
            event_count=0,
        )

        if response is None:
            return []

        # Handle case where response might be a list (from return_on_404) or a dict
        if isinstance(response, list):
            events = response
        else:
            events = response.get("items", [])

        # Filter by source if requested
        if filter_by_source:
            filtered_events = []
            for event in events:
                metadata = GoogleCalendarService.parse_extended_properties(event)
                if metadata and metadata.get("source") == filter_by_source:
                    filtered_events.append(event)
            events = filtered_events

        return events

    @staticmethod
    async def create_event(
        calendar_id: str,
        start: datetime,
        end: datetime,
        summary: str,
        description: Optional[str],
        extended_properties: Dict,
        clinic_id: UUID,
        db: AsyncSession,
    ) -> Optional[Dict]:
        """
        Create new calendar event.

        Args:
            calendar_id: Provider's google_calendar_id
            start: Start datetime (timezone-aware, RFC3339 format)
            end: End datetime (timezone-aware, RFC3339 format)
            summary: Event title
            description: Optional event description
            extended_properties: Dict with extendedProperties structure
            clinic_id: For authentication
            db: Database session

        Returns:
            Event dictionary with 'id' field, or None if creation failed (graceful degradation)
        """
        service = await GoogleCalendarService.get_calendar_service(clinic_id, db)

        # Format datetimes as RFC3339
        # Get timezone string from datetime object
        timezone_str = None
        if start.tzinfo:
            if hasattr(start.tzinfo, "zone"):
                timezone_str = start.tzinfo.zone
            elif hasattr(start.tzinfo, "key"):
                timezone_str = start.tzinfo.key

        event_body = {
            "summary": summary,
            "start": {"dateTime": start.isoformat()},
            "end": {"dateTime": end.isoformat()},
            **extended_properties,
        }

        if timezone_str:
            event_body["start"]["timeZone"] = timezone_str
            event_body["end"]["timeZone"] = timezone_str

        if description:
            event_body["description"] = description

        def _create_event_sync():
            """Synchronous function to create event."""
            return service.events().insert(calendarId=calendar_id, body=event_body).execute()

        # Execute with retry logic (graceful degradation - allow booking to proceed if GCal fails)
        event = await GoogleCalendarService._execute_with_retry(
            operation_name="create_event",
            clinic_id=clinic_id,
            calendar_id=calendar_id,
            sync_func=_create_event_sync,
            db=db,
            graceful_degradation=True,
        )

        if event:
            logger.info(
                "Google Calendar event created successfully",
                extra={
                    "clinic_id": str(clinic_id),
                    "calendar_id": calendar_id,
                    "event_id": event.get("id"),
                },
            )

        return event

    @staticmethod
    async def update_event(
        calendar_id: str,
        event_id: str,
        start: Optional[datetime],
        end: Optional[datetime],
        summary: Optional[str],
        extended_properties: Optional[Dict],
        clinic_id: UUID,
        db: AsyncSession,
    ) -> Optional[Dict]:
        """
        Update existing calendar event.

        Args:
            calendar_id: Provider's google_calendar_id
            event_id: Google Calendar event ID
            start: Optional new start datetime (timezone-aware)
            end: Optional new end datetime (timezone-aware)
            summary: Optional new summary
            extended_properties: Optional new extended properties
            clinic_id: For authentication
            db: Database session

        Returns:
            Updated event dictionary, or None if event not found
        """
        service = await GoogleCalendarService.get_calendar_service(clinic_id, db)

        # Fetch existing event first (with retry)
        def _get_event_sync():
            return service.events().get(calendarId=calendar_id, eventId=event_id).execute()

        existing_event = await GoogleCalendarService._execute_with_retry(
            operation_name="get_event_for_update",
            clinic_id=clinic_id,
            calendar_id=calendar_id,
            sync_func=_get_event_sync,
            db=db,
            graceful_degradation=False,
            event_id=event_id,
        )

        if existing_event is None:
            return None

        # Merge updates
        if start:
            timezone_str = None
            if start.tzinfo:
                if hasattr(start.tzinfo, "zone"):
                    timezone_str = start.tzinfo.zone
                elif hasattr(start.tzinfo, "key"):
                    timezone_str = start.tzinfo.key

            existing_event["start"] = {"dateTime": start.isoformat()}
            if timezone_str:
                existing_event["start"]["timeZone"] = timezone_str

        if end:
            timezone_str = None
            if end.tzinfo:
                if hasattr(end.tzinfo, "zone"):
                    timezone_str = end.tzinfo.zone
                elif hasattr(end.tzinfo, "key"):
                    timezone_str = end.tzinfo.key

            existing_event["end"] = {"dateTime": end.isoformat()}
            if timezone_str:
                existing_event["end"]["timeZone"] = timezone_str
        if summary:
            existing_event["summary"] = summary
        if extended_properties:
            existing_event.update(extended_properties)

        # Update event (with retry)
        def _update_event_sync():
            return (
                service.events()
                .update(calendarId=calendar_id, eventId=event_id, body=existing_event)
                .execute()
            )

        event = await GoogleCalendarService._execute_with_retry(
            operation_name="update_event",
            clinic_id=clinic_id,
            calendar_id=calendar_id,
            sync_func=_update_event_sync,
            db=db,
            graceful_degradation=False,
            event_id=event_id,
        )

        return event

    @staticmethod
    async def delete_event(
        calendar_id: str, event_id: str, clinic_id: UUID, db: AsyncSession
    ) -> bool:
        """
        Delete calendar event.

        Args:
            calendar_id: Provider's google_calendar_id
            event_id: Google Calendar event ID
            clinic_id: For authentication
            db: Database session

        Returns:
            True if deleted, False if event not found
        """
        service = await GoogleCalendarService.get_calendar_service(clinic_id, db)

        def _delete_event_sync():
            service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
            return True

        # Execute with retry logic (return False on 404, raise on other errors)
        result = await GoogleCalendarService._execute_with_retry(
            operation_name="delete_event",
            clinic_id=clinic_id,
            calendar_id=calendar_id,
            sync_func=_delete_event_sync,
            db=db,
            graceful_degradation=False,
            return_on_404=False,
            event_id=event_id,
        )

        return result if result is not None else False

    @staticmethod
    async def delete_multiple_events(
        calendar_id: str, event_ids: List[str], clinic_id: UUID, db: AsyncSession
    ) -> Dict[str, bool]:
        """
        Delete multiple calendar events in parallel (optimized).

        Creates service client once and reuses it for all deletions.

        Args:
            calendar_id: Provider's google_calendar_id
            event_ids: List of Google Calendar event IDs
            clinic_id: For authentication
            db: Database session

        Returns:
            Dict mapping event_id -> True (success) or False (failed)
        """
        start_time = time.time()
        operation = "delete_multiple_events"

        try:
            # Create service client once (optimization)
            service = await GoogleCalendarService.get_calendar_service(clinic_id, db)

            async def _delete_single_event(event_id: str) -> Tuple[str, bool]:
                """Helper to delete a single event with retry logic."""

                def _delete_sync():
                    service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
                    return True

                # Execute with retry logic
                try:
                    result = await GoogleCalendarService._execute_with_retry(
                        operation_name="delete_event_bulk",
                        clinic_id=clinic_id,
                        calendar_id=calendar_id,
                        sync_func=_delete_sync,
                        db=db,
                        graceful_degradation=True,
                        return_on_404=False,
                        event_id=event_id,
                    )
                    return (event_id, result if result is not None else False)
                except Exception as e:
                    logger.warning(
                        "Failed to delete event in bulk operation",
                        extra={
                            "clinic_id": str(clinic_id),
                            "calendar_id": calendar_id,
                            "event_id": event_id,
                            "error": str(e),
                        },
                    )
                    return (event_id, False)

            # Delete all events in parallel
            delete_tasks = [_delete_single_event(event_id) for event_id in event_ids]
            results = await asyncio.gather(*delete_tasks, return_exceptions=True)

            # Build result dict
            result_dict = {}
            for result in results:
                if isinstance(result, Exception):
                    logger.warning(
                        "Exception in bulk delete operation",
                        extra={
                            "clinic_id": str(clinic_id),
                            "calendar_id": calendar_id,
                            "error": str(result),
                        },
                    )
                    # Can't determine which event_id failed, skip it
                    continue
                event_id, success = result
                result_dict[event_id] = success

            duration_ms = int((time.time() - start_time) * 1000)
            success_count = sum(1 for v in result_dict.values() if v)
            logger.info(
                "Google Calendar bulk delete operation completed",
                extra={
                    "clinic_id": str(clinic_id),
                    "calendar_id": calendar_id,
                    "operation": operation,
                    "total_events": len(event_ids),
                    "successful": success_count,
                    "failed": len(event_ids) - success_count,
                    "duration_ms": duration_ms,
                },
            )

            return result_dict

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error(
                "Google Calendar bulk delete operation failed",
                extra={
                    "clinic_id": str(clinic_id),
                    "calendar_id": calendar_id,
                    "operation": operation,
                    "error": str(e),
                    "duration_ms": duration_ms,
                },
                exc_info=True,
            )
            # Return all False on service client creation failure
            return {event_id: False for event_id in event_ids}

    @staticmethod
    async def get_event(
        calendar_id: str, event_id: str, clinic_id: UUID, db: AsyncSession
    ) -> Optional[Dict]:
        """
        Retrieve specific event by ID.

        Args:
            calendar_id: Provider's google_calendar_id
            event_id: Google Calendar event ID
            clinic_id: For authentication
            db: Database session

        Returns:
            Event dictionary or None if not found
        """
        service = await GoogleCalendarService.get_calendar_service(clinic_id, db)

        def _get_event_sync():
            return service.events().get(calendarId=calendar_id, eventId=event_id).execute()

        # Execute with retry logic (return None on 404, raise on other errors)
        event = await GoogleCalendarService._execute_with_retry(
            operation_name="get_event",
            clinic_id=clinic_id,
            calendar_id=calendar_id,
            sync_func=_get_event_sync,
            db=db,
            graceful_degradation=False,
            return_on_404=None,
            event_id=event_id,
        )

        return event

    @staticmethod
    async def validate_calendar_access(calendar_id: str, clinic_id: UUID, db: AsyncSession) -> bool:
        """
        Validate that service account can access the calendar.

        Args:
            calendar_id: Provider's google_calendar_id
            clinic_id: For authentication
            db: Database session

        Returns:
            True if accessible, False if not found or not shared

        Raises:
            GoogleCalendarNotFoundError: If calendar not accessible
        """
        service = await GoogleCalendarService.get_calendar_service(clinic_id, db)

        def _get_calendar_sync():
            return service.calendars().get(calendarId=calendar_id).execute()

        # Execute with retry logic (raise exception on 404/403, not graceful degradation)
        try:
            result = await GoogleCalendarService._execute_with_retry(
                operation_name="validate_calendar_access",
                clinic_id=clinic_id,
                calendar_id=calendar_id,
                sync_func=_get_calendar_sync,
                db=db,
                graceful_degradation=False,
            )

            # If result is None, it means 404 was returned
            if result is None:
                raise GoogleCalendarNotFoundError(
                    f"Calendar {calendar_id} not found or not shared with service account"
                )

            return True

        except GoogleCalendarAuthError:
            # Re-raise auth errors as-is
            raise
        except GoogleCalendarError:
            # Re-raise other Google Calendar errors as GoogleCalendarNotFoundError
            raise GoogleCalendarNotFoundError("Failed to validate calendar access")
