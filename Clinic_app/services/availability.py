"""
Availability Service

Provides functions for checking appointment availability using Google Calendar
as the primary source. Supports clinic-configurable business hours, keyword-based
patient appointment detection (English/Spanish), and capacity enforcement.
"""

import logging
import pytz
from datetime import datetime, date, time, timedelta
from typing import Optional, List, Tuple, Dict, Set
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, cast, String

from Clinic_app.data.models.clinic import Clinic
from Clinic_app.data.models.provider import Provider
from Clinic_app.data.models.booking import Booking
from Clinic_app.data.models.availability_slot import AvailabilitySlot
from Clinic_app.data.enums import BookingStatus, SlotStatus
from Clinic_app.services.google_calendar import GoogleCalendarService

logger = logging.getLogger(__name__)

# Patient appointment keywords (English + Spanish)
# Events with these keywords in the title count toward capacity instead of blocking
PATIENT_KEYWORDS = [
    # English
    "patient",
    "pt",
    "appt",
    "appointment",
    "visit",
    "consult",
    "checkup",
    "check-up",
    "follow-up",
    "followup",
    "new patient",
    # Spanish
    "paciente",
    "cita",
    "consulta",
    "visita",
    "seguimiento",
    "nuevo paciente",
    "chequeo",
]

# Fallback business hours (if clinic doesn't have them set)
FALLBACK_START = "09:00"
FALLBACK_END = "17:00"


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================


async def _get_existing_booking_ids(
    db: AsyncSession, clinic_id: UUID, provider_id: UUID, booking_ids: Set[UUID]
) -> Set[UUID]:
    """
    Check which booking_ids exist in DB as TENTATIVE or CONFIRMED.

    Args:
        db: Database session
        clinic_id: Clinic UUID (tenant isolation)
        provider_id: Provider UUID
        booking_ids: Set of booking UUIDs to check

    Returns:
        Set of booking_ids that exist in DB as TENTATIVE or CONFIRMED
    """
    if not booking_ids:
        return set()

    result = await db.execute(
        select(Booking.id).where(
            and_(
                Booking.clinic_id == clinic_id,
                Booking.provider_id == provider_id,
                Booking.id.in_(booking_ids),
                cast(Booking.status, String).in_(
                    [BookingStatus.TENTATIVE.value, BookingStatus.CONFIRMED.value]
                ),
            )
        )
    )
    existing_ids = {row[0] for row in result.all()}
    return existing_ids


def _is_patient_appointment(event: Dict) -> bool:
    """
    Determine if a Google Calendar event is a patient appointment.

    Patient appointments count toward capacity instead of blocking the slot entirely.

    Detection methods:
    1. Event has source: "callcenter_ai" in extended properties (our bookings)
    2. Event title contains patient-related keywords (manual appointments)

    Args:
        event: Google Calendar event dictionary

    Returns:
        True if patient appointment, False if external/blocking event
    """
    # Check for our booking metadata
    metadata = GoogleCalendarService.parse_extended_properties(event)
    if metadata and metadata.get("source") == "callcenter_ai":
        return True

    # Check for patient keywords in title
    title = event.get("summary", "").lower()
    for keyword in PATIENT_KEYWORDS:
        if keyword in title:
            return True

    return False


def _events_overlap(
    event_start: datetime, event_end: datetime, slot_start: datetime, slot_end: datetime
) -> bool:
    """
    Check if two time ranges overlap.

    Normalizes all datetimes to UTC for comparison to ensure timezone-aware
    datetimes are compared correctly regardless of their original timezone.

    Args:
        event_start: Event start time (timezone-aware)
        event_end: Event end time (timezone-aware)
        slot_start: Slot start time (timezone-aware)
        slot_end: Slot end time (timezone-aware)

    Returns:
        True if ranges overlap, False otherwise
    """
    # Normalize all datetimes to UTC for consistent comparison
    if event_start.tzinfo is None:
        raise ValueError("event_start must be timezone-aware")
    if event_end.tzinfo is None:
        raise ValueError("event_end must be timezone-aware")
    if slot_start.tzinfo is None:
        raise ValueError("slot_start must be timezone-aware")
    if slot_end.tzinfo is None:
        raise ValueError("slot_end must be timezone-aware")

    # Convert to UTC for comparison
    event_start_utc = event_start.astimezone(pytz.UTC)
    event_end_utc = event_end.astimezone(pytz.UTC)
    slot_start_utc = slot_start.astimezone(pytz.UTC)
    slot_end_utc = slot_end.astimezone(pytz.UTC)

    # Check overlap: ranges overlap if event_start < slot_end AND event_end > slot_start
    return event_start_utc < slot_end_utc and event_end_utc > slot_start_utc


def _parse_time(time_str: str) -> time:
    """
    Parse HH:MM string to time object.

    Args:
        time_str: Time string in HH:MM format

    Returns:
        time object

    Raises:
        ValueError: If format is invalid
    """
    parts = time_str.split(":")
    if len(parts) != 2:
        raise ValueError(f"Invalid time format: {time_str}. Expected HH:MM")

    hour, minute = int(parts[0]), int(parts[1])
    return time(hour, minute)


def _get_clinic_business_hours(clinic: Clinic) -> Tuple[str, str]:
    """
    Get business hours from clinic or return fallback defaults.

    Args:
        clinic: Clinic model instance

    Returns:
        Tuple of (start_time, end_time) in HH:MM format
    """
    start = clinic.business_hours_start if clinic.business_hours_start else FALLBACK_START
    end = clinic.business_hours_end if clinic.business_hours_end else FALLBACK_END
    return (start, end)


def _generate_candidate_slots(
    target_date: date, start_time: str, end_time: str, duration_mins: int, timezone_str: str
) -> List[Tuple[datetime, datetime]]:
    """
    Generate candidate appointment slots for a date.

    Args:
        target_date: Date to generate slots for
        start_time: Start time in HH:MM format
        end_time: End time in HH:MM format
        duration_mins: Slot duration in minutes
        timezone_str: Provider's timezone (e.g., "America/New_York")

    Returns:
        List of (slot_start, slot_end) datetime tuples in provider's timezone
    """
    tz = pytz.timezone(timezone_str)

    start = _parse_time(start_time)
    end = _parse_time(end_time)

    # Create timezone-aware datetimes
    current = tz.localize(datetime.combine(target_date, start))
    end_dt = tz.localize(datetime.combine(target_date, end))

    slots = []
    while current + timedelta(minutes=duration_mins) <= end_dt:
        slot_end = current + timedelta(minutes=duration_mins)
        slots.append((current, slot_end))
        current = slot_end

    return slots


def _parse_gcal_datetime(dt_str: str) -> datetime:
    """
    Parse Google Calendar datetime string to datetime object.

    Args:
        dt_str: RFC3339 datetime string from Google Calendar

    Returns:
        Timezone-aware datetime object
    """
    # Handle Z suffix for UTC
    if dt_str.endswith("Z"):
        dt_str = dt_str[:-1] + "+00:00"
    return datetime.fromisoformat(dt_str)


# ============================================================================
# CORE AVAILABILITY FUNCTION
# ============================================================================


async def is_slot_available(
    db: AsyncSession, provider: Provider, slot_start: datetime, slot_end: datetime, clinic_id: UUID
) -> bool:
    """
    Check if a specific slot is available for booking.

    Checks:
    1. AvailabilitySlot for BLOCKED status
    2. Google Calendar for external events (blocks) vs patient appointments (capacity)
    3. Database bookings (TENTATIVE/CONFIRMED) count toward capacity

    Args:
        db: Database session
        provider: Provider model instance
        slot_start: Slot start datetime (timezone-aware)
        slot_end: Slot end datetime (timezone-aware)
        clinic_id: Clinic UUID for authentication

    Returns:
        True if slot is available, False otherwise
    """
    # 1. Check AvailabilitySlot for BLOCKED status
    blocked_result = await db.execute(
        select(AvailabilitySlot).where(
            and_(
                AvailabilitySlot.provider_id == provider.id,
                AvailabilitySlot.slot_start < slot_end,
                AvailabilitySlot.slot_end > slot_start,
                cast(AvailabilitySlot.status, String) == SlotStatus.BLOCKED.value,
            )
        )
    )
    if blocked_result.scalar_one_or_none():
        logger.debug(f"Slot {slot_start} blocked for provider {provider.id}")
        return False

    # 2. Fetch Google Calendar events for slot window
    if provider.google_calendar_id:
        try:
            gcal_events = await GoogleCalendarService.list_events(
                calendar_id=provider.google_calendar_id,
                time_min=slot_start,
                time_max=slot_end,
                clinic_id=clinic_id,
                db=db,
            )
        except Exception as e:
            logger.warning(f"Google Calendar unavailable, using DB only: {str(e)}")
            gcal_events = []
    else:
        gcal_events = []

    # 3. Count our database bookings (TENTATIVE/CONFIRMED) - authoritative source
    booking_result = await db.execute(
        select(Booking).where(
            and_(
                Booking.provider_id == provider.id,
                Booking.slot_start < slot_end,
                Booking.slot_end > slot_start,
                cast(Booking.status, String).in_(
                    [BookingStatus.TENTATIVE.value, BookingStatus.CONFIRMED.value]
                ),
            )
        )
    )
    db_bookings = booking_result.scalars().all()
    booking_count = len(db_bookings)

    # 4. Extract booking_ids from GCal events to check for duplicates
    gcal_booking_ids = set()
    for event in gcal_events:
        if _is_patient_appointment(event):
            # Extract booking_id from extended properties
            metadata = GoogleCalendarService.parse_extended_properties(event)
            if metadata and metadata.get("source") == "callcenter_ai":
                booking_id_str = metadata.get("booking_id")
                if booking_id_str:
                    try:
                        gcal_booking_ids.add(UUID(booking_id_str))
                    except (ValueError, TypeError):
                        pass  # Invalid UUID, skip

    # 5. Check which GCal booking_ids exist in DB (to avoid double-counting)
    existing_booking_ids = await _get_existing_booking_ids(
        db, clinic_id, provider.id, gcal_booking_ids
    )

    # 6. Count GCal events that DON'T have matching DB bookings (orphaned/manual events)
    patient_count_gcal = 0
    for event in gcal_events:
        # Parse event times
        event_start_str = event.get("start", {}).get("dateTime") or event.get("start", {}).get(
            "date"
        )
        event_end_str = event.get("end", {}).get("dateTime") or event.get("end", {}).get("date")

        if not event_start_str or not event_end_str:
            continue

        try:
            event_start = _parse_gcal_datetime(event_start_str)
            event_end = _parse_gcal_datetime(event_end_str)
        except (ValueError, AttributeError):
            continue

        # Check if overlaps
        if _events_overlap(event_start, event_end, slot_start, slot_end):
            if _is_patient_appointment(event):
                # Check if this event has a booking_id that exists in DB
                metadata = GoogleCalendarService.parse_extended_properties(event)
                if metadata and metadata.get("source") == "callcenter_ai":
                    booking_id_str = metadata.get("booking_id")
                    if booking_id_str:
                        try:
                            event_booking_id = UUID(booking_id_str)
                            # Only count if booking doesn't exist in DB (orphaned event)
                            if event_booking_id not in existing_booking_ids:
                                patient_count_gcal += 1
                        except (ValueError, TypeError):
                            # Invalid UUID, count it (manual event)
                            patient_count_gcal += 1
                    else:
                        # No booking_id, count it (manual event)
                        patient_count_gcal += 1
                else:
                    # Manual event (not from callcenter_ai), count it
                    patient_count_gcal += 1
            else:
                # External event (meeting, personal, etc.) blocks the slot entirely
                logger.debug(
                    f"Slot {slot_start} blocked by external event for provider {provider.id}"
                )
                return False

    # 7. Capacity check: patient appointments (DB + orphaned GCal) must be < capacity
    total_patient_appointments = booking_count + patient_count_gcal
    available = total_patient_appointments < provider.capacity

    logger.debug(
        f"Slot {slot_start} for provider {provider.id}: "
        f"gcal_patients={patient_count_gcal}, db_bookings={booking_count}, "
        f"capacity={provider.capacity}, available={available}"
    )

    return available


# ============================================================================
# SEARCH FUNCTIONS
# ============================================================================


async def get_available_slots(
    db: AsyncSession,
    provider: Provider,
    target_date: date,
    clinic_id: UUID,
    time_range: Optional[Tuple[str, str]] = None,
) -> List[Dict]:
    """
    Get all available slots for a provider on a specific date.

    Uses single Google Calendar API call for efficiency.

    Args:
        db: Database session
        provider: Provider model instance
        target_date: Date to check
        clinic_id: Clinic UUID
        time_range: Optional (start, end) in HH:MM format. If None, uses clinic business hours.

    Returns:
        List of available slot dictionaries with start_time, end_time, provider info
    """
    # Get clinic for business hours
    clinic = await db.get(Clinic, clinic_id)
    if not clinic:
        raise ValueError(f"Clinic {clinic_id} not found")

    # Determine time range
    if time_range:
        start_time, end_time = time_range
    else:
        start_time, end_time = _get_clinic_business_hours(clinic)

    logger.info(
        f"Getting available slots for provider {provider.id} on {target_date} "
        f"({start_time}-{end_time})"
    )

    # Generate candidate slots
    candidates = _generate_candidate_slots(
        target_date, start_time, end_time, provider.booking_duration_mins, provider.timezone
    )

    if not candidates:
        return []

    # Build time window for batch queries
    window_start = candidates[0][0]
    window_end = candidates[-1][1]

    # Single Google Calendar API call for entire window
    if provider.google_calendar_id:
        try:
            gcal_events = await GoogleCalendarService.list_events(
                calendar_id=provider.google_calendar_id,
                time_min=window_start,
                time_max=window_end,
                clinic_id=clinic_id,
                db=db,
            )
        except Exception as e:
            logger.warning(f"Google Calendar unavailable: {str(e)}")
            gcal_events = []
    else:
        gcal_events = []

    # Single DB query for bookings in window
    booking_result = await db.execute(
        select(Booking).where(
            and_(
                Booking.provider_id == provider.id,
                Booking.slot_start < window_end,
                Booking.slot_end > window_start,
                cast(Booking.status, String).in_(
                    [BookingStatus.TENTATIVE.value, BookingStatus.CONFIRMED.value]
                ),
            )
        )
    )
    db_bookings = booking_result.scalars().all()

    # Log what bookings were found
    logger.info(
        f"Found {len(db_bookings)} bookings in window for provider {provider.id} on {target_date}. "
        f"Window: {window_start} (tzinfo={window_start.tzinfo}) to {window_end} (tzinfo={window_end.tzinfo})"
    )
    for b in db_bookings:
        logger.info(
            f"Booking {b.id}: slot_start={b.slot_start} (tzinfo={b.slot_start.tzinfo}), "
            f"slot_end={b.slot_end} (tzinfo={b.slot_end.tzinfo}), status={b.status}"
        )

    # Extract booking_ids from GCal events to check for duplicates
    gcal_booking_ids = set()
    for event in gcal_events:
        if _is_patient_appointment(event):
            metadata = GoogleCalendarService.parse_extended_properties(event)
            if metadata and metadata.get("source") == "callcenter_ai":
                booking_id_str = metadata.get("booking_id")
                if booking_id_str:
                    try:
                        gcal_booking_ids.add(UUID(booking_id_str))
                    except (ValueError, TypeError):
                        pass  # Invalid UUID, skip

    # Check which GCal booking_ids exist in DB (to avoid double-counting)
    # Also get all DB booking IDs in the window to check against GCal events
    existing_booking_ids = await _get_existing_booking_ids(
        db, clinic_id, provider.id, gcal_booking_ids
    )

    # Get all DB booking IDs in the window (not just from GCal events) for comprehensive matching
    all_db_booking_ids_in_window = {b.id for b in db_bookings}

    # Single DB query for blocked slots
    blocked_result = await db.execute(
        select(AvailabilitySlot).where(
            and_(
                AvailabilitySlot.provider_id == provider.id,
                AvailabilitySlot.slot_start < window_end,
                AvailabilitySlot.slot_end > window_start,
                cast(AvailabilitySlot.status, String) == SlotStatus.BLOCKED.value,
            )
        )
    )
    blocked_slots = blocked_result.scalars().all()

    # Filter candidates locally
    available_slots = []
    for slot_start, slot_end in candidates:
        # Check if blocked
        is_blocked = any(
            _events_overlap(b.slot_start, b.slot_end, slot_start, slot_end) for b in blocked_slots
        )
        if is_blocked:
            continue

        # First, check for external blocking events (non-patient appointments that block the slot)
        slot_blocked_by_external = False
        for event in gcal_events:
            event_start_str = event.get("start", {}).get("dateTime") or event.get("start", {}).get(
                "date"
            )
            event_end_str = event.get("end", {}).get("dateTime") or event.get("end", {}).get("date")

            if not event_start_str or not event_end_str:
                continue

            try:
                event_start = _parse_gcal_datetime(event_start_str)
                event_end = _parse_gcal_datetime(event_end_str)
            except (ValueError, AttributeError):
                continue

            if _events_overlap(event_start, event_end, slot_start, slot_end):
                if not _is_patient_appointment(event):
                    slot_blocked_by_external = True
                    break

        if slot_blocked_by_external:
            continue

        # Count DB bookings for this slot first
        booking_count = 0
        overlapping_booking_ids = set()  # Track which booking_ids overlap with this slot
        overlapping_bookings = (
            []
        )  # Track booking objects that overlap with this slot (for time comparison)
        for b in db_bookings:
            # Log the comparison
            logger.info(
                f"Comparing slot {slot_start} (tzinfo={slot_start.tzinfo}) to {slot_end} (tzinfo={slot_end.tzinfo}) "
                f"with booking {b.id} slot_start={b.slot_start} (tzinfo={b.slot_start.tzinfo}) "
                f"slot_end={b.slot_end} (tzinfo={b.slot_end.tzinfo})"
            )
            overlaps = _events_overlap(b.slot_start, b.slot_end, slot_start, slot_end)
            logger.info(f"Overlap result for booking {b.id}: {overlaps}")
            if overlaps:
                booking_count += 1
                overlapping_booking_ids.add(b.id)  # Track this booking_id
                overlapping_bookings.append(b)  # Track booking object for time comparison
                logger.info(
                    f"Booking {b.id} overlaps with slot {slot_start} - count={booking_count}"
                )

        # Count Google Calendar patient appointments for this slot
        # Exclude events that correspond to DB bookings we already counted (prevents double-counting)
        patient_count_gcal = 0
        for event in gcal_events:
            event_start_str = event.get("start", {}).get("dateTime") or event.get("start", {}).get(
                "date"
            )
            event_end_str = event.get("end", {}).get("dateTime") or event.get("end", {}).get("date")

            if not event_start_str or not event_end_str:
                continue

            try:
                event_start = _parse_gcal_datetime(event_start_str)
                event_end = _parse_gcal_datetime(event_end_str)
            except (ValueError, AttributeError):
                continue

            if _events_overlap(event_start, event_end, slot_start, slot_end):
                if _is_patient_appointment(event):
                    # Check if this event corresponds to a DB booking we already counted for this slot
                    metadata = GoogleCalendarService.parse_extended_properties(event)
                    logger.info(
                        f"GCal event for slot {slot_start}: metadata={metadata}, "
                        f"overlapping_booking_ids={list(overlapping_booking_ids)}"
                    )
                    if metadata and metadata.get("source") == "callcenter_ai":
                        booking_id_str = metadata.get("booking_id")
                        if booking_id_str:
                            try:
                                event_booking_id = UUID(booking_id_str)
                                # Don't count if this booking_id is already counted in DB bookings for this slot
                                if event_booking_id in overlapping_booking_ids:
                                    logger.info(
                                        f"Skipping GCal event for booking {event_booking_id} - already counted in DB bookings for slot {slot_start}"
                                    )
                                    continue
                                # Also check if booking exists in DB at all (orphaned event check)
                                # Check both existing_booking_ids (from GCal events) and all_db_booking_ids_in_window
                                if (
                                    event_booking_id not in existing_booking_ids
                                    and event_booking_id not in all_db_booking_ids_in_window
                                ):
                                    logger.info(
                                        f"Counting orphaned GCal event for booking {event_booking_id} (not in DB) for slot {slot_start}"
                                    )
                                    patient_count_gcal += 1
                                else:
                                    logger.info(
                                        f"Skipping GCal event for booking {event_booking_id} - exists in DB (in existing_booking_ids={event_booking_id in existing_booking_ids} or all_db_booking_ids_in_window={event_booking_id in all_db_booking_ids_in_window}) for slot {slot_start}"
                                    )
                            except (ValueError, TypeError) as e:
                                # Invalid UUID, count it (manual event)
                                logger.info(
                                    f"GCal event has invalid booking_id UUID '{booking_id_str}': {e} - counting as manual event for slot {slot_start}"
                                )
                                patient_count_gcal += 1
                        else:
                            # No booking_id, count it (manual event)
                            logger.info(
                                f"GCal event has no booking_id in metadata - counting as manual event for slot {slot_start}"
                            )
                            patient_count_gcal += 1
                    else:
                        # Manual event (not from callcenter_ai) or no metadata
                        # Check if this GCal event corresponds to a DB booking by comparing event IDs
                        # If booking.google_event_id matches this event's ID, they're the same appointment
                        event_id = event.get("id")
                        is_same_as_db_booking = False
                        if event_id:
                            # First check overlapping bookings (most common case)
                            for b in overlapping_bookings:
                                if b.google_event_id == event_id:
                                    is_same_as_db_booking = True
                                    logger.info(
                                        f"Skipping GCal event (no metadata) - matches DB booking {b.id} "
                                        f"via google_event_id={event_id} for slot {slot_start}"
                                    )
                                    break

                            # Also check all DB bookings in window (in case booking doesn't overlap this slot but event does)
                            if not is_same_as_db_booking:
                                for b in db_bookings:
                                    if b.google_event_id == event_id:
                                        is_same_as_db_booking = True
                                        logger.info(
                                            f"Skipping GCal event (no metadata) - matches DB booking {b.id} "
                                            f"via google_event_id={event_id} (booking doesn't overlap slot but event does) for slot {slot_start}"
                                        )
                                        break

                        if not is_same_as_db_booking:
                            # Manual event (not from callcenter_ai) or different event, count it
                            logger.info(
                                f"GCal event is not from callcenter_ai (source={metadata.get('source') if metadata else 'None'}) "
                                f"and doesn't match any DB booking google_event_id - counting for slot {slot_start}"
                            )
                            patient_count_gcal += 1

        # Capacity check: DB bookings + orphaned GCal events (excluding those already counted in DB)
        total = booking_count + patient_count_gcal
        logger.info(
            f"Slot {slot_start} capacity check: gcal_patients={patient_count_gcal}, "
            f"db_bookings={booking_count}, total={total}, capacity={provider.capacity}, "
            f"available={total < provider.capacity}, remaining_capacity={provider.capacity - total if total < provider.capacity else 0}"
        )
        if total < provider.capacity:
            available_slots.append(
                {
                    "start_time": slot_start.isoformat(),
                    "end_time": slot_end.isoformat(),
                    "provider_id": str(provider.id),
                    "provider_name": provider.display_name,
                    "date": target_date.isoformat(),
                    "remaining_capacity": provider.capacity - total,
                }
            )
        else:
            logger.info(
                f"Slot {slot_start} filtered out: at capacity (total={total}, capacity={provider.capacity})"
            )

    logger.info(
        f"Found {len(available_slots)} available slots for provider {provider.id} on {target_date}. "
        f"Total candidates: {len(candidates)}, Total bookings in window: {len(db_bookings)}"
    )
    return available_slots


async def get_next_available_slots(
    db: AsyncSession,
    provider: Provider,
    clinic_id: UUID,
    max_days_ahead: int = 14,
    max_slots: int = 5,
) -> List[Dict]:
    """
    Find the next available slots starting from today.

    Use case: Patient says "I want to book an appointment" (no date/time preference)

    Args:
        db: Database session
        provider: Provider model instance
        clinic_id: Clinic UUID
        max_days_ahead: Maximum days to search forward
        max_slots: Maximum number of slots to return

    Returns:
        List of available slot dictionaries sorted by date/time
    """
    logger.info(f"Finding next {max_slots} available slots for provider {provider.id}")

    # Get provider's timezone
    tz = pytz.timezone(provider.timezone)
    now = datetime.now(tz)

    # Start from today or tomorrow depending on time
    clinic = await db.get(Clinic, clinic_id)
    if not clinic:
        raise ValueError(f"Clinic {clinic_id} not found")

    _, end_time = _get_clinic_business_hours(clinic)
    end_hour = int(end_time.split(":")[0])

    # If past business hours, start tomorrow
    current_date = now.date()
    if now.hour >= end_hour:
        current_date = current_date + timedelta(days=1)

    available_slots = []
    days_checked = 0

    while len(available_slots) < max_slots and days_checked < max_days_ahead:
        # Skip weekends (optional, can be made configurable)
        if current_date.weekday() < 5:  # Monday = 0, Friday = 4
            day_slots = await get_available_slots(db, provider, current_date, clinic_id)

            # Filter out past times if checking today
            if current_date == now.date():
                day_slots = [s for s in day_slots if datetime.fromisoformat(s["start_time"]) > now]

            available_slots.extend(day_slots)

        current_date = current_date + timedelta(days=1)
        days_checked += 1

    # Return only up to max_slots
    result = available_slots[:max_slots]
    logger.info(f"Found {len(result)} next available slots for provider {provider.id}")
    return result


async def find_slot_at_time(
    db: AsyncSession,
    provider: Provider,
    preferred_time: str,
    clinic_id: UUID,
    max_days_ahead: int = 14,
    max_slots: int = 5,
) -> List[Dict]:
    """
    Find available slots at a specific time across multiple days.

    Use case: Patient says "I need a 10am appointment" (any day)

    Args:
        db: Database session
        provider: Provider model instance
        preferred_time: Preferred time in HH:MM format
        clinic_id: Clinic UUID
        max_days_ahead: Maximum days to search forward
        max_slots: Maximum number of slots to return

    Returns:
        List of available slot dictionaries at the preferred time
    """
    logger.info(f"Finding slots at {preferred_time} for provider {provider.id}")

    # Parse preferred time
    preferred = _parse_time(preferred_time)

    # Get provider's timezone
    tz = pytz.timezone(provider.timezone)
    now = datetime.now(tz)

    # Start from today or tomorrow
    current_date = now.date()

    # If preferred time has passed today, start tomorrow
    today_slot_time = tz.localize(datetime.combine(current_date, preferred))
    if today_slot_time <= now:
        current_date = current_date + timedelta(days=1)

    available_slots = []
    days_checked = 0

    while len(available_slots) < max_slots and days_checked < max_days_ahead:
        # Skip weekends
        if current_date.weekday() < 5:
            # Build the specific slot
            slot_start = tz.localize(datetime.combine(current_date, preferred))
            slot_end = slot_start + timedelta(minutes=provider.booking_duration_mins)

            # Check if available
            is_available = await is_slot_available(db, provider, slot_start, slot_end, clinic_id)

            if is_available:
                available_slots.append(
                    {
                        "start_time": slot_start.isoformat(),
                        "end_time": slot_end.isoformat(),
                        "provider_id": str(provider.id),
                        "provider_name": provider.display_name,
                        "date": current_date.isoformat(),
                        "day_name": current_date.strftime("%A"),
                    }
                )

        current_date = current_date + timedelta(days=1)
        days_checked += 1

    logger.info(
        f"Found {len(available_slots)} slots at {preferred_time} for provider {provider.id}"
    )
    return available_slots


async def check_and_offer_alternatives(
    db: AsyncSession,
    provider: Provider,
    requested_datetime: datetime,
    clinic_id: UUID,
    max_alternatives: int = 5,
) -> Dict:
    """
    Check if a specific slot is available, offer alternatives if not.

    Use case: Patient says "I want Thursday at 3pm"

    Args:
        db: Database session
        provider: Provider model instance
        requested_datetime: Requested appointment datetime (timezone-aware)
        clinic_id: Clinic UUID
        max_alternatives: Maximum alternatives to return if unavailable

    Returns:
        Dict with "available" bool, "slot" if available, "alternatives" if not
    """
    logger.info(f"Checking slot {requested_datetime} for provider {provider.id}")

    slot_start = requested_datetime
    slot_end = slot_start + timedelta(minutes=provider.booking_duration_mins)

    # Check if requested slot is available
    is_available = await is_slot_available(db, provider, slot_start, slot_end, clinic_id)

    if is_available:
        return {
            "available": True,
            "slot": {
                "start_time": slot_start.isoformat(),
                "end_time": slot_end.isoformat(),
                "provider_id": str(provider.id),
                "provider_name": provider.display_name,
                "date": slot_start.date().isoformat(),
            },
            "alternatives": [],
        }

    # Not available - find alternatives
    logger.info(f"Slot {requested_datetime} unavailable, finding alternatives")

    alternatives = []
    requested_date = slot_start.date()

    # First, try same day with different times
    same_day_slots = await get_available_slots(db, provider, requested_date, clinic_id)

    # Sort by proximity to requested time
    requested_minutes = slot_start.hour * 60 + slot_start.minute
    same_day_slots.sort(
        key=lambda s: abs(
            datetime.fromisoformat(s["start_time"]).hour * 60
            + datetime.fromisoformat(s["start_time"]).minute
            - requested_minutes
        )
    )
    alternatives.extend(same_day_slots[:max_alternatives])

    # If need more, check surrounding days
    if len(alternatives) < max_alternatives:
        # Get provider's timezone for time comparisons
        tz = pytz.timezone(provider.timezone)

        for day_offset in [1, -1, 2, -2, 3]:
            if len(alternatives) >= max_alternatives:
                break

            alt_date = requested_date + timedelta(days=day_offset)

            # Skip past dates
            if alt_date < datetime.now(tz).date():
                continue

            # Skip weekends
            if alt_date.weekday() >= 5:
                continue

            alt_slots = await get_available_slots(db, provider, alt_date, clinic_id)

            # Sort by proximity to requested time
            alt_slots.sort(
                key=lambda s: abs(
                    datetime.fromisoformat(s["start_time"]).hour * 60
                    + datetime.fromisoformat(s["start_time"]).minute
                    - requested_minutes
                )
            )

            # Add unique slots
            for slot in alt_slots:
                if len(alternatives) >= max_alternatives:
                    break
                if slot not in alternatives:
                    alternatives.append(slot)

    return {"available": False, "slot": None, "alternatives": alternatives[:max_alternatives]}
