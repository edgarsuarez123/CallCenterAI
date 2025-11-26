"""
Availability Service

Provides functions for checking appointment availability using Google Calendar
as the primary source. Supports clinic-configurable business hours, keyword-based
patient appointment detection (English/Spanish), and capacity enforcement.
"""

import logging
import pytz
from datetime import datetime, date, time, timedelta
from typing import Optional, List, Tuple, Dict
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

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
    "patient", "pt", "appt", "appointment", "visit", "consult",
    "checkup", "check-up", "follow-up", "followup", "new patient",
    # Spanish
    "paciente", "cita", "consulta", "visita", "seguimiento",
    "nuevo paciente", "chequeo",
]

# Fallback business hours (if clinic doesn't have them set)
FALLBACK_START = "09:00"
FALLBACK_END = "17:00"


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

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
    event_start: datetime,
    event_end: datetime,
    slot_start: datetime,
    slot_end: datetime
) -> bool:
    """
    Check if two time ranges overlap.
    
    Args:
        event_start: Event start time
        event_end: Event end time
        slot_start: Slot start time
        slot_end: Slot end time
        
    Returns:
        True if ranges overlap, False otherwise
    """
    return event_start < slot_end and event_end > slot_start


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
    parts = time_str.split(':')
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
    target_date: date,
    start_time: str,
    end_time: str,
    duration_mins: int,
    timezone_str: str
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
    if dt_str.endswith('Z'):
        dt_str = dt_str[:-1] + '+00:00'
    return datetime.fromisoformat(dt_str)


# ============================================================================
# CORE AVAILABILITY FUNCTION
# ============================================================================

async def is_slot_available(
    db: AsyncSession,
    provider: Provider,
    slot_start: datetime,
    slot_end: datetime,
    clinic_id: UUID
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
                AvailabilitySlot.status == SlotStatus.BLOCKED
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
                db=db
            )
        except Exception as e:
            logger.warning(f"Google Calendar unavailable, using DB only: {str(e)}")
            gcal_events = []
    else:
        gcal_events = []
    
    # 3. Check each event - patient appointments count, others block
    patient_count_gcal = 0
    for event in gcal_events:
        # Parse event times
        event_start_str = event.get("start", {}).get("dateTime") or event.get("start", {}).get("date")
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
                patient_count_gcal += 1
            else:
                # External event (meeting, personal, etc.) blocks the slot entirely
                logger.debug(f"Slot {slot_start} blocked by external event for provider {provider.id}")
                return False
    
    # 4. Count our database bookings (TENTATIVE/CONFIRMED)
    booking_result = await db.execute(
        select(Booking).where(
            and_(
                Booking.provider_id == provider.id,
                Booking.slot_start < slot_end,
                Booking.slot_end > slot_start,
                Booking.status.in_([BookingStatus.TENTATIVE, BookingStatus.CONFIRMED])
            )
        )
    )
    db_bookings = booking_result.scalars().all()
    booking_count = len(db_bookings)
    
    # 5. Capacity check: patient appointments (GCal + DB) must be < capacity
    total_patient_appointments = patient_count_gcal + booking_count
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
    time_range: Optional[Tuple[str, str]] = None
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
        target_date,
        start_time,
        end_time,
        provider.booking_duration_mins,
        provider.timezone
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
                db=db
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
                Booking.status.in_([BookingStatus.TENTATIVE, BookingStatus.CONFIRMED])
            )
        )
    )
    db_bookings = booking_result.scalars().all()
    
    # Single DB query for blocked slots
    blocked_result = await db.execute(
        select(AvailabilitySlot).where(
            and_(
                AvailabilitySlot.provider_id == provider.id,
                AvailabilitySlot.slot_start < window_end,
                AvailabilitySlot.slot_end > window_start,
                AvailabilitySlot.status == SlotStatus.BLOCKED
            )
        )
    )
    blocked_slots = blocked_result.scalars().all()
    
    # Filter candidates locally
    available_slots = []
    for slot_start, slot_end in candidates:
        # Check if blocked
        is_blocked = any(
            _events_overlap(b.slot_start, b.slot_end, slot_start, slot_end)
            for b in blocked_slots
        )
        if is_blocked:
            continue
        
        # Check Google Calendar events
        patient_count_gcal = 0
        slot_blocked_by_external = False
        
        for event in gcal_events:
            event_start_str = event.get("start", {}).get("dateTime") or event.get("start", {}).get("date")
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
                    patient_count_gcal += 1
                else:
                    slot_blocked_by_external = True
                    break
        
        if slot_blocked_by_external:
            continue
        
        # Count DB bookings for this slot
        booking_count = sum(
            1 for b in db_bookings
            if _events_overlap(b.slot_start, b.slot_end, slot_start, slot_end)
        )
        
        # Capacity check
        total = patient_count_gcal + booking_count
        if total < provider.capacity:
            available_slots.append({
                "start_time": slot_start.isoformat(),
                "end_time": slot_end.isoformat(),
                "provider_id": str(provider.id),
                "provider_name": provider.display_name,
                "date": target_date.isoformat(),
                "remaining_capacity": provider.capacity - total
            })
    
    logger.info(f"Found {len(available_slots)} available slots for provider {provider.id} on {target_date}")
    return available_slots


async def get_next_available_slots(
    db: AsyncSession,
    provider: Provider,
    clinic_id: UUID,
    max_days_ahead: int = 14,
    max_slots: int = 5
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
    end_hour = int(end_time.split(':')[0])
    
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
                day_slots = [
                    s for s in day_slots
                    if datetime.fromisoformat(s["start_time"]) > now
                ]
            
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
    max_slots: int = 5
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
            is_available = await is_slot_available(
                db, provider, slot_start, slot_end, clinic_id
            )
            
            if is_available:
                available_slots.append({
                    "start_time": slot_start.isoformat(),
                    "end_time": slot_end.isoformat(),
                    "provider_id": str(provider.id),
                    "provider_name": provider.display_name,
                    "date": current_date.isoformat(),
                    "day_name": current_date.strftime("%A")
                })
        
        current_date = current_date + timedelta(days=1)
        days_checked += 1
    
    logger.info(f"Found {len(available_slots)} slots at {preferred_time} for provider {provider.id}")
    return available_slots


async def check_and_offer_alternatives(
    db: AsyncSession,
    provider: Provider,
    requested_datetime: datetime,
    clinic_id: UUID,
    max_alternatives: int = 5
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
                "date": slot_start.date().isoformat()
            },
            "alternatives": []
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
            datetime.fromisoformat(s["start_time"]).hour * 60 +
            datetime.fromisoformat(s["start_time"]).minute - requested_minutes
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
                    datetime.fromisoformat(s["start_time"]).hour * 60 +
                    datetime.fromisoformat(s["start_time"]).minute - requested_minutes
                )
            )
            
            # Add unique slots
            for slot in alt_slots:
                if len(alternatives) >= max_alternatives:
                    break
                if slot not in alternatives:
                    alternatives.append(slot)
    
    return {
        "available": False,
        "slot": None,
        "alternatives": alternatives[:max_alternatives]
    }

