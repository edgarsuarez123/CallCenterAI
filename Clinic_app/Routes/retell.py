"""
Retell AI Integration Routes

Tool endpoints called by Retell AI during voice conversations,
and webhooks for call lifecycle events.
"""

import os
import json
import hmac
import hashlib
import logging
from datetime import datetime, date, timezone
from typing import Optional, List, Dict, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func, cast, String
from pydantic import BaseModel

from Clinic_app.common.database import get_db
from Clinic_app.data.models.clinic import Clinic
from Clinic_app.data.models.clinic_integration import ClinicIntegration
from Clinic_app.data.models.provider import Provider
from Clinic_app.data.models.booking import Booking
from Clinic_app.data.models.call_log import CallLog
from Clinic_app.data.enums import BookingStatus
from Clinic_app.services.patient import find_patient, create_patient
from Clinic_app.services.availability import (
    get_available_slots,
    get_next_available_slots
)
from Clinic_app.services.booking import (
    create_tentative_booking,
    confirm_booking,
    cancel_booking,
    reschedule_booking,
    get_patient_bookings,
    get_booking_by_id
)

logger = logging.getLogger(__name__)

# Router setup
retell_router = APIRouter(prefix="/retell", tags=["retell"])


# ============================================================================
# PYDANTIC MODELS
# ============================================================================

class ScheduleRequest(BaseModel):
    """Request for scheduling operations (book/cancel/reschedule)."""
    call_id: str
    clinic_id: UUID
    patient_name: str
    patient_dob: str  # YYYY-MM-DD
    phone: str  # E.164
    email: Optional[str] = None
    intent: str  # "book", "cancel", "reschedule"
    preferred_date: Optional[str] = None  # YYYY-MM-DD
    preferred_time_range: Optional[List[str]] = None  # ["09:00", "12:00"]
    provider_preference: Optional[str] = None
    language: str = "en"
    booking_id: Optional[UUID] = None  # For cancel/reschedule


class ScheduleResponse(BaseModel):
    """Response for scheduling operations."""
    success: bool
    message: str
    booking: Optional[Dict[str, Any]] = None
    hold_token: Optional[UUID] = None
    # Provider clarification
    needs_clarification: bool = False
    provider_options: Optional[List[str]] = None
    # Alternatives
    alternatives: Optional[List[Dict[str, Any]]] = None
    alternatives_same_provider: bool = False
    alternative_provider: Optional[str] = None


class ConfirmRequest(BaseModel):
    """Request to confirm a tentative booking."""
    hold_token: UUID
    clinic_id: UUID


class ConfirmResponse(BaseModel):
    """Response for booking confirmation."""
    success: bool
    message: str
    booking: Optional[Dict[str, Any]] = None


class AvailabilityResponse(BaseModel):
    """Response for availability check."""
    success: bool
    message: str
    slots: List[Dict[str, Any]] = []


class CallStartedWebhook(BaseModel):
    """Webhook payload for call started event."""
    call_id: str
    agent_id: str
    from_number: str
    to_number: str
    direction: str
    timestamp: str


class CallEndedWebhook(BaseModel):
    """Webhook payload for call ended event."""
    call_id: str
    duration_seconds: int
    outcome: str
    timestamp: str


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

async def _get_clinic_by_agent_id(db: AsyncSession, agent_id: str) -> UUID:
    """
    Lookup clinic_id from Retell agent_id.
    
    Args:
        db: Database session
        agent_id: Retell agent identifier
        
    Returns:
        clinic_id UUID
        
    Raises:
        ValueError: If no clinic found for agent
    """
    result = await db.execute(
        select(ClinicIntegration).where(ClinicIntegration.retell_agent_id == agent_id)
    )
    integration = result.scalar_one_or_none()
    
    if not integration:
        logger.warning(f"No clinic found for agent_id: {agent_id}")
        raise ValueError(f"No clinic found for agent_id: {agent_id}")
    
    return integration.clinic_id


async def _find_providers_by_name(
    db: AsyncSession,
    clinic_id: UUID,
    name: str
) -> List[Provider]:
    """
    Find providers matching a name (case-insensitive partial match).
    Returns LIST to handle multiple matches (e.g., "Dr. Maria Lopez", "Dr. Juan Lopez").
    
    Args:
        db: Database session
        clinic_id: Clinic UUID
        name: Provider name to search for
        
    Returns:
        List of matching Provider instances
    """
    result = await db.execute(
        select(Provider).where(
            and_(
                Provider.clinic_id == clinic_id,
                Provider.display_name.ilike(f"%{name}%"),
                Provider.active == True
            )
        )
    )
    return list(result.scalars().all())


async def _get_providers_by_workload(
    db: AsyncSession,
    clinic_id: UUID
) -> List[Provider]:
    """
    Get active providers sorted by workload (least busy first).
    Counts upcoming CONFIRMED bookings per provider for load balancing.
    
    Args:
        db: Database session
        clinic_id: Clinic UUID
        
    Returns:
        List of Provider instances sorted by booking count (ascending)
    """
    now = datetime.now(timezone.utc)
    
    # Subquery to count upcoming confirmed bookings per provider
    booking_count_subq = (
        select(
            Booking.provider_id,
            func.count(Booking.id).label("booking_count")
        )
        .where(
            and_(
                Booking.clinic_id == clinic_id,
                cast(Booking.status, String) == BookingStatus.CONFIRMED.value,
                Booking.slot_start >= now
            )
        )
        .group_by(Booking.provider_id)
        .subquery()
    )
    
    # Get providers with their booking counts, ordered by count ascending
    result = await db.execute(
        select(Provider, func.coalesce(booking_count_subq.c.booking_count, 0).label("count"))
        .outerjoin(booking_count_subq, Provider.id == booking_count_subq.c.provider_id)
        .where(
            and_(
                Provider.clinic_id == clinic_id,
                Provider.active == True
            )
        )
        .order_by(func.coalesce(booking_count_subq.c.booking_count, 0).asc())
    )
    
    # Extract just the Provider objects
    rows = result.all()
    return [row[0] for row in rows]


async def _update_call_log_booking(
    db: AsyncSession,
    call_id: str,
    booking_id: UUID
) -> None:
    """
    Link a tentative booking to a CallLog for cleanup on call_ended.
    
    Args:
        db: Database session
        call_id: Retell call identifier
        booking_id: Booking UUID to track
    """
    result = await db.execute(
        select(CallLog).where(CallLog.retell_call_id == call_id)
    )
    call_log = result.scalar_one_or_none()
    
    if call_log:
        call_log.tentative_booking_id = booking_id
        await db.flush()
        logger.info(f"Updated CallLog {call_log.id} with tentative_booking_id={booking_id}")


def _booking_to_dict(booking: Booking, provider_name: str) -> Dict[str, Any]:
    """Convert Booking model to response dictionary."""
    return {
        "id": str(booking.id),
        "provider_name": provider_name,
        "start_time": booking.slot_start.isoformat(),
        "end_time": booking.slot_end.isoformat(),
        "status": booking.status.value,
        "date": booking.slot_start.date().isoformat()
    }


# ============================================================================
# SIGNATURE VERIFICATION
# ============================================================================

async def verify_retell_signature(
    request: Request,
    body_bytes: bytes
) -> None:
    """
    Verify Retell signature using HMAC-SHA256.
    
    Args:
        request: FastAPI request object
        body_bytes: Raw request body bytes (already read)
        
    Raises:
        HTTPException: If signature is missing or invalid
    """
    # Check if this is a playground/test call (skip verification)
    try:
        if body_bytes:
            body_json = json.loads(body_bytes.decode('utf-8'))
            call_obj = body_json.get("call", {})
            call_id = call_obj.get("call_id", "")
            if call_id == "playground" or call_id.startswith("test_") or call_id.startswith("playground_"):
                return
    except (json.JSONDecodeError, UnicodeDecodeError, KeyError):
        pass
    
    # Get webhook secret
    webhook_secret = os.environ.get("RETELL_WEBHOOK_SECRET", "")
    
    # Skip verification if no secret configured (development mode)
    if not webhook_secret:
        logger.warning("RETELL_WEBHOOK_SECRET not configured - skipping signature verification")
        return
    
    # Extract signature header
    x_retell_signature_raw = (
        request.headers.get("x-retell-signature") or 
        request.headers.get("X-Retell-Signature") or
        request.headers.get("X-RETELL-SIGNATURE")
    )
    
    if not x_retell_signature_raw:
        logger.warning("Missing x-retell-signature header")
        raise HTTPException(
            status_code=401,
            detail={"code": "MISSING_SIGNATURE", "message": "Missing signature header"}
        )
    
    # Parse signature - Retell uses format: v=<timestamp>,d=<signature>
    if x_retell_signature_raw.startswith("v=") and ",d=" in x_retell_signature_raw:
        parts = x_retell_signature_raw.split(",d=", 1)
        x_retell_signature = parts[1] if len(parts) == 2 else x_retell_signature_raw
    else:
        x_retell_signature = x_retell_signature_raw
    
    # Format body for signature verification (Retell SDK format)
    try:
        body_json = json.loads(body_bytes.decode('utf-8'))
        body_for_signature = json.dumps(body_json, separators=(",", ":"), ensure_ascii=False).encode('utf-8')
    except (json.JSONDecodeError, UnicodeDecodeError):
        body_for_signature = body_bytes
    
    # Compute expected signature
    expected = hmac.new(webhook_secret.encode(), body_for_signature, hashlib.sha256).hexdigest()
    
    # Verify signature
    if not hmac.compare_digest(expected, x_retell_signature):
        logger.error("Invalid Retell signature - verification failed")
        raise HTTPException(
            status_code=401,
            detail={"code": "INVALID_SIGNATURE", "message": "Invalid signature"}
        )


# ============================================================================
# TOOL ENDPOINTS
# ============================================================================

@retell_router.post("/schedule", response_model=ScheduleResponse)
async def schedule(
    request: ScheduleRequest,
    db: AsyncSession = Depends(get_db)
) -> ScheduleResponse:
    """
    Main scheduling endpoint for booking, canceling, or rescheduling appointments.
    Called by Retell AI during voice conversations.
    """
    logger.info(f"Schedule request: intent={request.intent}, clinic={request.clinic_id}")
    
    try:
        # 1. Find or create patient
        patient = await find_patient(db, request.clinic_id, request.patient_name, request.patient_dob)
        
        if not patient:
            patient = await create_patient(
                db=db,
                clinic_id=request.clinic_id,
                name=request.patient_name,
                dob=request.patient_dob,
                phone=request.phone,
                email=request.email,
                language=request.language
            )
            logger.info(f"Created new patient: {patient.id}")
        
        # Handle different intents
        if request.intent == "book":
            return await _handle_book_intent(db, request, patient)
        
        elif request.intent == "cancel":
            return await _handle_cancel_intent(db, request, patient)
        
        elif request.intent == "reschedule":
            return await _handle_reschedule_intent(db, request, patient)
        
        else:
            return ScheduleResponse(
                success=False,
                message=f"Unknown intent: {request.intent}"
            )
    
    except ValueError as e:
        logger.warning(f"Validation error in schedule: {str(e)}")
        return ScheduleResponse(success=False, message=str(e))
    
    except Exception as e:
        logger.error(f"Error in schedule endpoint: {str(e)}", exc_info=True)
        await db.rollback()
        return ScheduleResponse(success=False, message="An error occurred while processing your request")


async def _handle_book_intent(
    db: AsyncSession,
    request: ScheduleRequest,
    patient
) -> ScheduleResponse:
    """Handle booking intent - find provider, check availability, create hold."""
    
    # 1. PROVIDER SELECTION
    if request.provider_preference:
        # Patient asked for specific provider
        matching_providers = await _find_providers_by_name(
            db, request.clinic_id, request.provider_preference
        )
        
        if len(matching_providers) == 0:
            return ScheduleResponse(
                success=False,
                message=f"No provider found matching '{request.provider_preference}'"
            )
        
        if len(matching_providers) > 1:
            # Multiple matches - need clarification
            return ScheduleResponse(
                success=False,
                needs_clarification=True,
                provider_options=[p.display_name for p in matching_providers],
                message="Multiple providers match that name. Please specify which one."
            )
        
        # Single match - use this provider
        preferred_provider = matching_providers[0]
        providers_to_check = [preferred_provider]
        
    else:
        # No preference - get all providers sorted by workload (least busy first)
        providers_to_check = await _get_providers_by_workload(db, request.clinic_id)
        preferred_provider = None
    
    if not providers_to_check:
        return ScheduleResponse(
            success=False,
            message="No providers available at this clinic"
        )
    
    # 2. Parse date/time preferences
    target_date = None
    if request.preferred_date:
        try:
            target_date = date.fromisoformat(request.preferred_date)
        except ValueError:
            return ScheduleResponse(
                success=False,
                message=f"Invalid date format: {request.preferred_date}. Use YYYY-MM-DD."
            )
    
    time_range = None
    if request.preferred_time_range and len(request.preferred_time_range) == 2:
        time_range = (request.preferred_time_range[0], request.preferred_time_range[1])
    
    # 3. Check availability for provider(s)
    for provider in providers_to_check:
        if target_date:
            # Check specific date
            slots = await get_available_slots(
                db, provider, target_date, request.clinic_id, time_range
            )
        else:
            # No date specified - get next available
            slots = await get_next_available_slots(
                db, provider, request.clinic_id, max_days_ahead=14, max_slots=5
            )
        
        if slots:
            # Found availability! Create tentative booking
            slot = slots[0]
            slot_start = datetime.fromisoformat(slot["start_time"])
            slot_end = datetime.fromisoformat(slot["end_time"])
            
            try:
                booking, hold_token = await create_tentative_booking(
                    db=db,
                    clinic_id=request.clinic_id,
                    provider_id=provider.id,
                    patient_id=patient.id,
                    slot_start=slot_start,
                    slot_end=slot_end,
                    source="call"
                )
                
                # Update CallLog with booking_id for cleanup
                await _update_call_log_booking(db, request.call_id, booking.id)
                await db.commit()
                
                logger.info(f"Created tentative booking: {booking.id}, hold_token={hold_token}")
                
                return ScheduleResponse(
                    success=True,
                    message=f"Appointment held with {provider.display_name}",
                    booking=_booking_to_dict(booking, provider.display_name),
                    hold_token=hold_token,
                    alternatives=slots[1:5] if len(slots) > 1 else None  # Include other slots as alternatives
                )
                
            except ValueError as e:
                # Slot became unavailable (race condition) - try next
                logger.warning(f"Slot unavailable: {str(e)}")
                continue
    
    # 4. No slots found with any provider
    # If patient had a preference, offer alternatives
    if preferred_provider:
        # First try other dates for same provider
        alt_slots = await get_next_available_slots(
            db, preferred_provider, request.clinic_id, max_days_ahead=14, max_slots=5
        )
        
        if alt_slots:
            return ScheduleResponse(
                success=False,
                message=f"{preferred_provider.display_name} is unavailable on that date. Here are their next available times.",
                alternatives=alt_slots,
                alternatives_same_provider=True
            )
        
        # No availability at all with preferred - offer other providers
        other_providers = [p for p in await _get_providers_by_workload(db, request.clinic_id) 
                          if p.id != preferred_provider.id]
        
        for provider in other_providers:
            other_slots = await get_next_available_slots(
                db, provider, request.clinic_id, max_days_ahead=14, max_slots=3
            )
            if other_slots:
                return ScheduleResponse(
                    success=False,
                    message=f"{preferred_provider.display_name} has no upcoming availability. {provider.display_name} is available.",
                    alternatives=other_slots,
                    alternative_provider=provider.display_name
                )
    
    return ScheduleResponse(
        success=False,
        message="No appointments available. Please try again later or call the front desk."
    )


async def _handle_cancel_intent(
    db: AsyncSession,
    request: ScheduleRequest,
    patient
) -> ScheduleResponse:
    """Handle cancellation intent - find and cancel patient's booking."""
    
    # Find patient's upcoming confirmed bookings
    bookings = await get_patient_bookings(
        db, patient.id, request.clinic_id, [BookingStatus.CONFIRMED]
    )
    
    # Filter to upcoming only
    now = datetime.now(timezone.utc)
    upcoming_bookings = [b for b in bookings if b.slot_start > now]
    
    if not upcoming_bookings:
        return ScheduleResponse(
            success=False,
            message="No upcoming appointments found to cancel"
        )
    
    # If specific booking_id provided, cancel that one
    if request.booking_id:
        booking_to_cancel = next(
            (b for b in upcoming_bookings if b.id == request.booking_id), None
        )
        if not booking_to_cancel:
            return ScheduleResponse(
                success=False,
                message="Specified appointment not found"
            )
    else:
        # Cancel the next upcoming appointment
        booking_to_cancel = min(upcoming_bookings, key=lambda b: b.slot_start)
    
    # Get provider name for response
    provider = await db.get(Provider, booking_to_cancel.provider_id)
    provider_name = provider.display_name if provider else "Unknown"
    
    # Cancel the booking
    await cancel_booking(db, booking_to_cancel.id, request.clinic_id, actor="patient")
    await db.commit()
    
    logger.info(f"Canceled booking: {booking_to_cancel.id}")
    
    return ScheduleResponse(
        success=True,
        message=f"Your appointment on {booking_to_cancel.slot_start.strftime('%B %d at %I:%M %p')} has been canceled",
        booking=_booking_to_dict(booking_to_cancel, provider_name)
    )


async def _handle_reschedule_intent(
    db: AsyncSession,
    request: ScheduleRequest,
    patient
) -> ScheduleResponse:
    """Handle reschedule intent - cancel old booking and create new one."""
    
    # Find booking to reschedule
    if request.booking_id:
        booking_to_reschedule = await get_booking_by_id(db, request.booking_id, request.clinic_id)
    else:
        # Find next upcoming booking
        bookings = await get_patient_bookings(
            db, patient.id, request.clinic_id, [BookingStatus.CONFIRMED]
        )
        now = datetime.now(timezone.utc)
        upcoming = [b for b in bookings if b.slot_start > now]
        booking_to_reschedule = min(upcoming, key=lambda b: b.slot_start) if upcoming else None
    
    if not booking_to_reschedule:
        return ScheduleResponse(
            success=False,
            message="No appointment found to reschedule"
        )
    
    # Parse new date/time
    if not request.preferred_date:
        return ScheduleResponse(
            success=False,
            message="Please specify the new date you'd like to reschedule to"
        )
    
    try:
        new_date = date.fromisoformat(request.preferred_date)
    except ValueError:
        return ScheduleResponse(
            success=False,
            message=f"Invalid date format: {request.preferred_date}"
        )
    
    # Get provider (keep same provider for reschedule)
    provider = await db.get(Provider, booking_to_reschedule.provider_id)
    if not provider:
        return ScheduleResponse(
            success=False,
            message="Provider not found"
        )
    
    time_range = None
    if request.preferred_time_range and len(request.preferred_time_range) == 2:
        time_range = (request.preferred_time_range[0], request.preferred_time_range[1])
    
    # Check availability on new date
    slots = await get_available_slots(db, provider, new_date, request.clinic_id, time_range)
    
    if not slots:
        # Offer alternatives
        alt_slots = await get_next_available_slots(db, provider, request.clinic_id)
        return ScheduleResponse(
            success=False,
            message=f"No availability on {new_date}. Here are the next available times.",
            alternatives=alt_slots,
            alternatives_same_provider=True
        )
    
    # Reschedule to first available slot
    slot = slots[0]
    new_start = datetime.fromisoformat(slot["start_time"])
    new_end = datetime.fromisoformat(slot["end_time"])
    
    try:
        new_booking, hold_token = await reschedule_booking(
            db=db,
            booking_id=booking_to_reschedule.id,
            clinic_id=request.clinic_id,
            new_slot_start=new_start,
            new_slot_end=new_end,
            actor="patient"
        )
        
        # Update CallLog
        await _update_call_log_booking(db, request.call_id, new_booking.id)
        await db.commit()
        
        logger.info(f"Rescheduled booking {booking_to_reschedule.id} to {new_booking.id}")
        
        return ScheduleResponse(
            success=True,
            message=f"Your appointment has been rescheduled to {new_start.strftime('%B %d at %I:%M %p')}",
            booking=_booking_to_dict(new_booking, provider.display_name),
            hold_token=hold_token
        )
        
    except ValueError as e:
        return ScheduleResponse(success=False, message=str(e))


@retell_router.post("/confirm_booking", response_model=ConfirmResponse)
async def confirm_booking_endpoint(
    request: ConfirmRequest,
    db: AsyncSession = Depends(get_db)
) -> ConfirmResponse:
    """
    Confirm a tentative booking.
    Called after patient confirms the appointment details.
    """
    logger.info(f"Confirm booking request: hold_token={request.hold_token}")
    
    try:
        booking = await confirm_booking(db, request.hold_token, request.clinic_id)
        await db.commit()
        
        # Get provider name
        provider = await db.get(Provider, booking.provider_id)
        provider_name = provider.display_name if provider else "Unknown"
        
        logger.info(f"Confirmed booking: {booking.id}")
        
        return ConfirmResponse(
            success=True,
            message=f"Your appointment is confirmed for {booking.slot_start.strftime('%B %d at %I:%M %p')}",
            booking=_booking_to_dict(booking, provider_name)
        )
        
    except ValueError as e:
        logger.warning(f"Confirm booking failed: {str(e)}")
        await db.rollback()
        
        error_msg = str(e)
        if "expired" in error_msg.lower():
            return ConfirmResponse(
                success=False,
                message="The hold has expired. Please start over and select a new time."
            )
        elif "not found" in error_msg.lower():
            return ConfirmResponse(
                success=False,
                message="Booking not found. It may have already been confirmed or canceled."
            )
        else:
            return ConfirmResponse(success=False, message=error_msg)
    
    except Exception as e:
        logger.error(f"Error confirming booking: {str(e)}", exc_info=True)
        await db.rollback()
        return ConfirmResponse(
            success=False,
            message="An error occurred while confirming your appointment"
        )

#was a get changed to post because of retell functionality
async def _get_availability_internal(
    db: AsyncSession,
    clinic_id: UUID,
    date: Optional[str] = None,
    provider_id: Optional[UUID] = None,
    provider_name: Optional[str] = None
) -> AvailabilityResponse:
    """
    Internal function that contains the actual availability logic.
    Called by both GET and POST endpoints.
    """
    logger.info(f"Availability request: clinic={clinic_id}, date={date}, provider_id={provider_id}, provider_name={provider_name}")
    
    try:
        # Get provider(s)
        if provider_name:
            # Look up provider by name (same logic as schedule endpoint)
            matching_providers = await _find_providers_by_name(db, clinic_id, provider_name)
            
            if len(matching_providers) == 0:
                return AvailabilityResponse(
                    success=False,
                    message=f"No provider found matching '{provider_name}'",
                    slots=[]
                )
            
            if len(matching_providers) > 1:
                # Multiple matches - need clarification
                provider_names = [p.display_name for p in matching_providers]
                return AvailabilityResponse(
                    success=False,
                    message=f"Multiple providers match '{provider_name}'. Please specify which one: {', '.join(provider_names)}",
                    slots=[]
                )
            
            # Single match - use this provider
            providers = matching_providers
            
        elif provider_id:
            provider = await db.get(Provider, provider_id)
            if not provider or provider.clinic_id != clinic_id:
                return AvailabilityResponse(
                    success=False,
                    message="Provider not found",
                    slots=[]
                )
            providers = [provider]
        else:
            # Get all active providers sorted by workload
            providers = await _get_providers_by_workload(db, clinic_id)
        
        if not providers:
            return AvailabilityResponse(
                success=False,
                message="No providers available",
                slots=[]
            )
        
        all_slots = []
        
        for provider in providers:
            if date:
                # Check specific date
                try:
                    target_date = datetime.strptime(date, "%Y-%m-%d").date()
                except ValueError:
                    return AvailabilityResponse(
                        success=False,
                        message=f"Invalid date format: {date}. Use YYYY-MM-DD.",
                        slots=[]
                    )
                
                slots = await get_available_slots(db, provider, target_date, clinic_id)
            else:
                # Get next available slots
                slots = await get_next_available_slots(db, provider, clinic_id)
            
            all_slots.extend(slots)
        
        # Sort by start time
        all_slots.sort(key=lambda s: s.get("start_time", ""))
        
        # Limit to reasonable number
        all_slots = all_slots[:50]
        
        return AvailabilityResponse(
            success=True,
            message=f"Found {len(all_slots)} available slots",
            slots=all_slots
        )
        
    except Exception as e:
        logger.error(f"Error getting availability: {str(e)}", exc_info=True)
        return AvailabilityResponse(
            success=False,
            message="An error occurred while checking availability",
            slots=[]
        )


@retell_router.get("/availability", response_model=AvailabilityResponse)
async def get_availability(
    clinic_id: UUID,
    date: Optional[str] = None,
    provider_id: Optional[UUID] = None,
    provider_name: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
) -> AvailabilityResponse:
    """
    Get available appointment slots (GET - for RESTful API).
    Called by Retell AI to offer available times to patients.
    """
    return await _get_availability_internal(db, clinic_id, date, provider_id, provider_name)


@retell_router.post("/availability", response_model=AvailabilityResponse)
async def get_availability_post(
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> AvailabilityResponse:
    """
    Get available appointment slots (POST - for Retell AI).
    Extracts clinic_id from agent_id and parameters from args.
    """
    # Read body once
    body_bytes = await request.body()
    
    # Verify Retell signature using the body bytes
    await verify_retell_signature(request, body_bytes)
    
    # Parse JSON from the same body bytes
    body = json.loads(body_bytes.decode('utf-8'))
    call_obj = body.get("call", {})
    args = body.get("args", {})
    
    # Extract agent_id from call object and look up clinic_id
    agent_id = call_obj.get("agent_id")
    if not agent_id:
        logger.warning("Missing agent_id in Retell request")
        return AvailabilityResponse(
            success=False,
            message="Missing agent_id in request",
            slots=[]
        )
    
    try:
        clinic_id = await _get_clinic_by_agent_id(db, agent_id)
    except ValueError as e:
        logger.error(f"Clinic lookup failed for agent_id {agent_id}: {str(e)}")
        return AvailabilityResponse(
            success=False,
            message="Clinic not found for this agent",
            slots=[]
        )
    
    # Extract other parameters from args
    date = args.get("date")
    provider_name = args.get("provider_name")
    provider_id = None
    if args.get("provider_id"):
        try:
            provider_id = UUID(args.get("provider_id"))
        except (ValueError, TypeError):
            logger.warning(f"Invalid provider_id format: {args.get('provider_id')}")
    
    logger.info(
        f"Availability POST request: agent_id={agent_id}, clinic_id={clinic_id}, "
        f"date={date}, provider_id={provider_id}, provider_name={provider_name}"
    )
    
    # Call the shared logic
    return await _get_availability_internal(db, clinic_id, date, provider_id, provider_name)


# ============================================================================
# WEBHOOK ENDPOINTS
# ============================================================================

@retell_router.post("/webhook/call_started")
async def webhook_call_started(
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> Dict[str, str]:
    """
    Webhook for call started event.
    Creates CallLog entry and identifies clinic.
    """
    # Read body once
    body_bytes = await request.body()
    
    # Verify signature using the body bytes
    await verify_retell_signature(request, body_bytes)
    
    # Parse JSON from the same body bytes
    body = json.loads(body_bytes.decode('utf-8'))
    webhook = CallStartedWebhook(**body)
    
    logger.info(f"Call started: call_id={webhook.call_id}, agent_id={webhook.agent_id}")
    
    try:
        # Lookup clinic by agent_id
        clinic_id = await _get_clinic_by_agent_id(db, webhook.agent_id)
        
        # Determine call type
        call_type = "inbound" if webhook.direction == "inbound" else "outbound_campaign"
        
        # Parse timestamp
        try:
            started_at = datetime.fromisoformat(webhook.timestamp.replace("Z", "+00:00"))
        except ValueError:
            started_at = datetime.now(timezone.utc)
        
        # Create CallLog entry
        call_log = CallLog(
            clinic_id=clinic_id,
            call_type=call_type,
            retell_call_id=webhook.call_id,
            started_at=started_at
        )
        db.add(call_log)
        await db.commit()
        
        logger.info(f"Created CallLog: {call_log.id} for clinic {clinic_id}")
        
        return {"status": "ok", "call_log_id": str(call_log.id)}
        
    except ValueError as e:
        logger.error(f"Error processing call_started: {str(e)}")
        # Still return OK to acknowledge webhook
        return {"status": "ok", "error": str(e)}
    
    except Exception as e:
        logger.error(f"Error in call_started webhook: {str(e)}", exc_info=True)
        await db.rollback()
        return {"status": "ok", "error": "Internal error"}


@retell_router.post("/webhook/call_ended")
async def webhook_call_ended(
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> Dict[str, str]:
    """
    Webhook for call ended event.
    Updates CallLog and releases any unconfirmed tentative bookings.
    """
    # Read body once
    body_bytes = await request.body()
    
    # Verify signature using the body bytes
    await verify_retell_signature(request, body_bytes)
    
    # Parse JSON from the same body bytes
    body = json.loads(body_bytes.decode('utf-8'))
    webhook = CallEndedWebhook(**body)
    
    logger.info(f"Call ended: call_id={webhook.call_id}, outcome={webhook.outcome}")
    
    try:
        # Find CallLog by retell_call_id
        result = await db.execute(
            select(CallLog).where(CallLog.retell_call_id == webhook.call_id)
        )
        call_log = result.scalar_one_or_none()
        
        if not call_log:
            logger.warning(f"CallLog not found for call_id: {webhook.call_id}")
            return {"status": "ok", "warning": "CallLog not found"}
        
        # Parse timestamp
        try:
            ended_at = datetime.fromisoformat(webhook.timestamp.replace("Z", "+00:00"))
        except ValueError:
            ended_at = datetime.now(timezone.utc)
        
        # Update CallLog
        call_log.duration_seconds = webhook.duration_seconds
        call_log.outcome = webhook.outcome
        call_log.ended_at = ended_at
        
        # RELEASE UNCONFIRMED HOLDS
        # If there's a tentative booking that wasn't confirmed, cancel it
        if call_log.tentative_booking_id:
            booking = await db.get(Booking, call_log.tentative_booking_id)
            
            if booking and booking.status == BookingStatus.TENTATIVE:
                logger.info(f"Releasing unconfirmed tentative booking: {booking.id}")
                await cancel_booking(db, booking.id, call_log.clinic_id, actor="call_ended")
                call_log.tentative_booking_id = None
        
        await db.commit()
        
        logger.info(f"Updated CallLog: {call_log.id}, released_hold={call_log.tentative_booking_id is None}")
        
        return {"status": "ok"}
        
    except Exception as e:
        logger.error(f"Error in call_ended webhook: {str(e)}", exc_info=True)
        await db.rollback()
        return {"status": "ok", "error": "Internal error"}

