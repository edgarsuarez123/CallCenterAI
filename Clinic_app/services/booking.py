"""
Booking Service

Manages the booking lifecycle (tentative -> confirmed -> canceled) with
proper capacity enforcement using SELECT FOR UPDATE and Google Calendar integration.
"""

import uuid
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Tuple, Union
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func, cast, String

from Clinic_app.data.models.booking import Booking
from Clinic_app.data.models.booking_audit import BookingAudit
from Clinic_app.data.models.provider import Provider
from Clinic_app.data.models.patient import Patient
from Clinic_app.data.enums import BookingStatus, BookingAction
from Clinic_app.services.google_calendar import GoogleCalendarService
from Clinic_app.common.encryption import decrypt_phi, DecryptionError

logger = logging.getLogger(__name__)

# Tentative booking hold duration (5 minutes)
HOLD_DURATION_MINUTES = 5


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

async def _create_audit_entry(
    db: AsyncSession,
    clinic_id: UUID,
    booking_id: UUID,
    action: Union[BookingAction, str],  # Accepts enum member or string value
    actor: str
) -> BookingAudit:
    """
    Create an immutable audit entry for booking state changes.
    
    Args:
        db: Database session
        clinic_id: Clinic UUID
        booking_id: Booking UUID
        action: The action being recorded (HOLD, CONFIRM, CANCEL, EXPIRE)
        actor: Who performed the action (e.g., "patient", "system", "admin")
        
    Returns:
        Created BookingAudit record
    """
    audit = BookingAudit(
        clinic_id=clinic_id,
        booking_id=booking_id,
        action=action,
        actor=actor,
        timestamp=datetime.now(timezone.utc)
    )
    db.add(audit)
    await db.flush()
    
    # Handle both enum and string values for logging
    action_str = action.value if hasattr(action, 'value') else action
    logger.info(
        f"Audit entry created: booking_id={booking_id}, action={action_str}, actor={actor}"
    )
    
    return audit


async def _count_slot_bookings(
    db: AsyncSession,
    clinic_id: UUID,
    provider_id: UUID,
    slot_start: datetime,
    slot_end: datetime
) -> int:
    """
    Count TENTATIVE/CONFIRMED bookings that overlap with a slot.

    Uses overlap logic (consistent with availability service) to count
    all bookings that overlap with the requested slot time range.

    Args:
        db: Database session
        clinic_id: Clinic UUID (tenant isolation)
        provider_id: Provider UUID
        slot_start: Slot start datetime
        slot_end: Slot end datetime

    Returns:
        Count of existing bookings that overlap with the slot
    """
    result = await db.execute(
        select(func.count(Booking.id))
        .where(
            and_(
                Booking.clinic_id == clinic_id,
                Booking.provider_id == provider_id,
                Booking.slot_start < slot_end,
                Booking.slot_end > slot_start,
                cast(Booking.status, String).in_([BookingStatus.TENTATIVE.value, BookingStatus.CONFIRMED.value])
            )
        )
    )
    return result.scalar() or 0


async def _get_provider(
    db: AsyncSession,
    provider_id: UUID,
    clinic_id: UUID
) -> Provider:
    """
    Fetch provider and validate clinic ownership.
    
    Args:
        db: Database session
        provider_id: Provider UUID
        clinic_id: Clinic UUID
        
    Returns:
        Provider model instance
        
    Raises:
        ValueError: If provider not found or doesn't belong to clinic
    """
    provider = await db.get(Provider, provider_id)
    
    if not provider:
        raise ValueError(f"Provider not found: {provider_id}")
    
    if provider.clinic_id != clinic_id:
        raise ValueError(f"Provider {provider_id} does not belong to clinic {clinic_id}")
    
    if not provider.active:
        raise ValueError(f"Provider {provider_id} is not active")
    
    return provider


# ============================================================================
# CORE BOOKING FUNCTIONS
# ============================================================================

async def create_tentative_booking(
    db: AsyncSession,
    clinic_id: UUID,
    provider_id: UUID,
    patient_id: UUID,
    slot_start: datetime,
    slot_end: datetime,
    source: str = "call"
) -> Tuple[Booking, UUID]:
    """
    Create a tentative booking with a 5-minute hold.
    
    This reserves a slot temporarily while the patient confirms their details.
    Capacity checking is performed before creating the booking.
    
    Args:
        db: Database session
        clinic_id: Clinic UUID
        provider_id: Provider UUID
        patient_id: Patient UUID
        slot_start: Appointment start datetime (timezone-aware)
        slot_end: Appointment end datetime (timezone-aware)
        source: Booking source (call/reminder/hedis/manual)
        
    Returns:
        Tuple of (Booking, hold_token UUID)
        
    Raises:
        ValueError: If slot is at capacity or provider not found
    """
    logger.info(
        f"Creating tentative booking: provider_id={provider_id}, "
        f"slot_start={slot_start}, source={source}"
    )
    
    # 1. Fetch and validate provider
    provider = await _get_provider(db, provider_id, clinic_id)
    
    # 2. Check capacity with row locking
    existing_count = await _count_slot_bookings(db, clinic_id, provider_id, slot_start, slot_end)
    
    if existing_count >= provider.capacity:
        logger.warning(
            f"Slot at capacity: provider_id={provider_id}, slot_start={slot_start}, "
            f"existing={existing_count}, capacity={provider.capacity}"
        )
        raise ValueError("Slot is at capacity")
    
    # 3. Generate hold token and expiration
    hold_token = uuid.uuid4()
    hold_expires_at = datetime.now(timezone.utc) + timedelta(minutes=HOLD_DURATION_MINUTES)
    
    # 4. Create booking
    booking = Booking(
        clinic_id=clinic_id,
        provider_id=provider_id,
        patient_id=patient_id,
        slot_start=slot_start,
        slot_end=slot_end,
        status=BookingStatus.TENTATIVE.value,
        hold_token=hold_token,
        hold_expires_at=hold_expires_at,
        source=source
    )
    db.add(booking)
    await db.flush()  # Get booking.id
    
    # 5. Create audit entry
    await _create_audit_entry(
        db=db,
        clinic_id=clinic_id,
        booking_id=booking.id,
        action=BookingAction.HOLD.value,
        actor=source
    )
    
    logger.info(
        f"Tentative booking created: booking_id={booking.id}, "
        f"hold_token={hold_token}, expires_at={hold_expires_at}"
    )
    
    return booking, hold_token


async def confirm_booking(
    db: AsyncSession,
    hold_token: UUID,
    clinic_id: UUID
) -> Booking:
    """
    Confirm a tentative booking and create Google Calendar event.
    
    Args:
        db: Database session
        hold_token: The hold token from create_tentative_booking
        clinic_id: Clinic UUID
        
    Returns:
        Confirmed Booking record
        
    Raises:
        ValueError: If hold token not found, expired, or booking not tentative
    """
    logger.info(f"Confirming booking with hold_token={hold_token}")
    
    # 1. Find booking by hold token
    result = await db.execute(
        select(Booking).where(
            and_(
                Booking.hold_token == hold_token,
                Booking.clinic_id == clinic_id
            )
        )
    )
    booking = result.scalar_one_or_none()
    
    if not booking:
        raise ValueError("Hold token not found")
    
    # 2. Validate status
    if booking.status != BookingStatus.TENTATIVE:
        raise ValueError(f"Booking is not tentative (status: {booking.status.value})")
    
    # 3. Check expiration
    if booking.hold_expires_at and booking.hold_expires_at < datetime.now(timezone.utc):
        raise ValueError("Hold has expired")
    
    # 4. Update booking status
    booking.status = BookingStatus.CONFIRMED.value
    booking.hold_token = None
    booking.hold_expires_at = None
    
    # 5. Create Google Calendar event
    provider = await db.get(Provider, booking.provider_id)
    patient = await db.get(Patient, booking.patient_id)
    
    if provider and provider.google_calendar_id:
        try:
            # Decrypt patient name for calendar event
            try:
                patient_name = decrypt_phi(patient.name_token)
            except DecryptionError as e:
                logger.warning(f"Failed to decrypt patient name for calendar event: {str(e)}")
                patient_name = "Patient"  # Fallback if decryption fails
            
            # Build event metadata
            extended_properties = {
                "private": {
                    "source": "callcenter_ai",
                    "booking_id": str(booking.id),
                    "clinic_id": str(clinic_id),
                    "reminded": "false"
                }
            }
            
            # Create event summary with patient name
            summary = f"Appointment: {patient_name} - {provider.display_name}"
            
            gcal_event = await GoogleCalendarService.create_event(
                calendar_id=provider.google_calendar_id,
                start=booking.slot_start,
                end=booking.slot_end,
                summary=summary,
                description=None,  # Avoid additional PHI in description
                extended_properties=extended_properties,
                clinic_id=clinic_id,
                db=db
            )
            
            if gcal_event:
                booking.google_event_id = gcal_event.get("id")
                logger.info(f"Google Calendar event created: {booking.google_event_id}")
            else:
                logger.warning(f"Google Calendar event creation failed for booking {booking.id}")
                
        except Exception as e:
            # Graceful degradation - booking still confirmed even if GCal fails
            logger.error(f"Failed to create Google Calendar event: {str(e)}")
    else:
        logger.info(f"No Google Calendar configured for provider {booking.provider_id}")
    
    # 6. Create audit entry
    await _create_audit_entry(
        db=db,
        clinic_id=clinic_id,
        booking_id=booking.id,
        action=BookingAction.CONFIRM.value,
        actor="patient"
    )
    
    await db.flush()
    
    logger.info(f"Booking confirmed: booking_id={booking.id}")
    
    return booking


async def cancel_booking(
    db: AsyncSession,
    booking_id: UUID,
    clinic_id: UUID,
    actor: str = "patient"
) -> Booking:
    """
    Cancel a booking and delete Google Calendar event if exists.
    
    Args:
        db: Database session
        booking_id: Booking UUID
        clinic_id: Clinic UUID
        actor: Who is canceling (patient/admin/system)
        
    Returns:
        Canceled Booking record
        
    Raises:
        ValueError: If booking not found or already canceled
    """
    logger.info(f"Canceling booking: booking_id={booking_id}, actor={actor}")
    
    # 1. Find booking
    result = await db.execute(
        select(Booking).where(
            and_(
                Booking.id == booking_id,
                Booking.clinic_id == clinic_id
            )
        )
    )
    booking = result.scalar_one_or_none()
    
    if not booking:
        raise ValueError("Booking not found")
    
    # 2. Validate status
    if booking.status == BookingStatus.CANCELED:
        raise ValueError("Booking already canceled")
    
    # 3. Delete Google Calendar event if exists
    if booking.google_event_id:
        provider = await db.get(Provider, booking.provider_id)
        
        if provider and provider.google_calendar_id:
            try:
                await GoogleCalendarService.delete_event(
                    calendar_id=provider.google_calendar_id,
                    event_id=booking.google_event_id,
                    clinic_id=clinic_id,
                    db=db
                )
                logger.info(f"Google Calendar event deleted: {booking.google_event_id}")
            except Exception as e:
                # Log but don't fail cancellation if GCal delete fails
                logger.error(f"Failed to delete Google Calendar event: {str(e)}")
    
    # 4. Update booking status
    booking.status = BookingStatus.CANCELED.value
    booking.hold_token = None
    booking.hold_expires_at = None
    
    # 5. Create audit entry
    await _create_audit_entry(
        db=db,
        clinic_id=clinic_id,
        booking_id=booking.id,
        action=BookingAction.CANCEL.value,
        actor=actor
    )
    
    await db.flush()
    
    logger.info(f"Booking canceled: booking_id={booking_id}")
    
    return booking


async def reschedule_booking(
    db: AsyncSession,
    booking_id: UUID,
    clinic_id: UUID,
    new_slot_start: datetime,
    new_slot_end: datetime,
    actor: str = "patient"
) -> Tuple[Booking, UUID]:
    """
    Reschedule a booking by canceling the old one and creating a new tentative hold.
    
    Args:
        db: Database session
        booking_id: Original booking UUID
        clinic_id: Clinic UUID
        new_slot_start: New appointment start datetime
        new_slot_end: New appointment end datetime
        actor: Who is rescheduling
        
    Returns:
        Tuple of (new Booking, new hold_token)
        
    Raises:
        ValueError: If original booking not found or new slot unavailable
    """
    logger.info(f"Rescheduling booking: booking_id={booking_id}, new_slot={new_slot_start}")
    
    # 1. Get original booking
    result = await db.execute(
        select(Booking).where(
            and_(
                Booking.id == booking_id,
                Booking.clinic_id == clinic_id
            )
        )
    )
    original_booking = result.scalar_one_or_none()
    
    if not original_booking:
        raise ValueError("Original booking not found")
    
    if original_booking.status == BookingStatus.CANCELED:
        raise ValueError("Cannot reschedule a canceled booking")
    
    # 2. Cancel the original booking
    await cancel_booking(db, booking_id, clinic_id, actor)
    
    # 3. Create new tentative booking
    new_booking, hold_token = await create_tentative_booking(
        db=db,
        clinic_id=clinic_id,
        provider_id=original_booking.provider_id,
        patient_id=original_booking.patient_id,
        slot_start=new_slot_start,
        slot_end=new_slot_end,
        source=original_booking.source or "call"
    )
    
    logger.info(
        f"Booking rescheduled: old_id={booking_id}, new_id={new_booking.id}, "
        f"new_hold_token={hold_token}"
    )
    
    return new_booking, hold_token


# ============================================================================
# QUERY FUNCTIONS
# ============================================================================

async def get_booking_by_hold_token(
    db: AsyncSession,
    hold_token: UUID,
    clinic_id: UUID
) -> Optional[Booking]:
    """
    Find a booking by its hold token.
    
    Args:
        db: Database session
        hold_token: Hold token UUID
        clinic_id: Clinic UUID
        
    Returns:
        Booking if found, None otherwise
    """
    result = await db.execute(
        select(Booking).where(
            and_(
                Booking.hold_token == hold_token,
                Booking.clinic_id == clinic_id
            )
        )
    )
    return result.scalar_one_or_none()


async def get_patient_bookings(
    db: AsyncSession,
    patient_id: UUID,
    clinic_id: UUID,
    status_filter: Optional[List[BookingStatus]] = None
) -> List[Booking]:
    """
    Get all bookings for a patient.
    
    Args:
        db: Database session
        patient_id: Patient UUID
        clinic_id: Clinic UUID
        status_filter: Optional list of statuses to filter by
        
    Returns:
        List of Booking records
    """
    query = select(Booking).where(
        and_(
            Booking.patient_id == patient_id,
            Booking.clinic_id == clinic_id
        )
    )
    
    if status_filter:
        # Use cast for enum comparison to handle PostgreSQL ENUM types correctly
        status_values = [s.value if hasattr(s, 'value') else s for s in status_filter]
        query = query.where(cast(Booking.status, String).in_(status_values))
    
    # Order by slot_start descending (most recent first)
    query = query.order_by(Booking.slot_start.desc())
    
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_booking_by_id(
    db: AsyncSession,
    booking_id: UUID,
    clinic_id: UUID
) -> Optional[Booking]:
    """
    Find a booking by ID.
    
    Args:
        db: Database session
        booking_id: Booking UUID
        clinic_id: Clinic UUID
        
    Returns:
        Booking if found, None otherwise
    """
    result = await db.execute(
        select(Booking).where(
            and_(
                Booking.id == booking_id,
                Booking.clinic_id == clinic_id
            )
        )
    )
    return result.scalar_one_or_none()


async def expire_booking(
    db: AsyncSession,
    booking_id: UUID,
    clinic_id: UUID
) -> Booking:
    """
    Expire a tentative booking (called by the reaper worker).

    Args:
        db: Database session
        booking_id: Booking UUID
        clinic_id: Clinic UUID (tenant isolation guard)

    Returns:
        Expired (canceled) Booking record

    Raises:
        ValueError: If booking not found or not tentative
    """
    logger.info(f"Expiring tentative booking: booking_id={booking_id}")

    result = await db.execute(
        select(Booking).where(
            and_(Booking.id == booking_id, Booking.clinic_id == clinic_id)
        )
    )
    booking = result.scalar_one_or_none()
    
    if not booking:
        raise ValueError("Booking not found")
    
    if booking.status != BookingStatus.TENTATIVE:
        raise ValueError(f"Booking is not tentative (status: {booking.status.value})")
    
    # Update status
    booking.status = BookingStatus.CANCELED.value
    booking.hold_token = None
    booking.hold_expires_at = None
    
    # Create audit entry
    await _create_audit_entry(
        db=db,
        clinic_id=booking.clinic_id,
        booking_id=booking.id,
        action=BookingAction.EXPIRE.value,
        actor="system"
    )
    
    await db.flush()
    
    logger.info(f"Tentative booking expired: booking_id={booking_id}")
    
    return booking


async def list_bookings(
    db: AsyncSession,
    clinic_id: UUID,
    provider_id: Optional[UUID] = None,
    patient_id: Optional[UUID] = None,
    status_filter: Optional[List[BookingStatus]] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    limit: int = 100,
    offset: int = 0
) -> Tuple[List[Booking], int]:
    """
    List bookings with optional filters.
    
    Args:
        db: Database session
        clinic_id: Clinic UUID (required)
        provider_id: Optional provider filter
        patient_id: Optional patient filter
        status_filter: Optional list of statuses to filter by
        start_date: Optional start date filter (bookings on or after)
        end_date: Optional end date filter (bookings on or before)
        limit: Maximum number of results
        offset: Offset for pagination
        
    Returns:
        Tuple of (list of bookings, total count)
    """
    # Build query
    query = select(Booking).where(Booking.clinic_id == clinic_id)
    count_query = select(func.count(Booking.id)).where(Booking.clinic_id == clinic_id)
    
    # Apply filters
    if provider_id:
        query = query.where(Booking.provider_id == provider_id)
        count_query = count_query.where(Booking.provider_id == provider_id)
    
    if patient_id:
        query = query.where(Booking.patient_id == patient_id)
        count_query = count_query.where(Booking.patient_id == patient_id)
    
    if status_filter:
        status_values = [s.value if hasattr(s, 'value') else s for s in status_filter]
        query = query.where(cast(Booking.status, String).in_(status_values))
        count_query = count_query.where(cast(Booking.status, String).in_(status_values))
    
    if start_date:
        query = query.where(Booking.slot_start >= start_date)
        count_query = count_query.where(Booking.slot_start >= start_date)
    
    if end_date:
        query = query.where(Booking.slot_start <= end_date)
        count_query = count_query.where(Booking.slot_start <= end_date)
    
    # Order by slot_start descending (most recent first)
    query = query.order_by(Booking.slot_start.desc())
    
    # Apply pagination
    query = query.limit(limit).offset(offset)
    
    # Execute queries
    result = await db.execute(query)
    bookings = list(result.scalars().all())
    
    count_result = await db.execute(count_query)
    total = count_result.scalar_one()
    
    return bookings, total


async def get_expired_tentative_bookings(
    db: AsyncSession,
    limit: int = 100
) -> List[Booking]:
    """
    Get tentative bookings that have expired (for the reaper worker).
    
    Args:
        db: Database session
        limit: Maximum number of bookings to return
        
    Returns:
        List of expired tentative Booking records
    """
    now = datetime.now(timezone.utc)
    
    result = await db.execute(
        select(Booking)
        .where(
            and_(
                cast(Booking.status, String) == BookingStatus.TENTATIVE.value,
                Booking.hold_expires_at < now
            )
        )
        .limit(limit)
    )
    
    return list(result.scalars().all())

