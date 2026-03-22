"""
Retell AI Integration Routes

Tool endpoints called by Retell AI during voice conversations,
and webhooks for call lifecycle events.
"""

import os
import json
import hmac
import hashlib
import asyncio
import logging
from datetime import datetime, date, timedelta, timezone
from typing import Optional, List, Dict, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func, cast, String
from pydantic import BaseModel, ConfigDict

from Clinic_app.common.database import get_db
from Clinic_app.data.models.clinic import Clinic
from Clinic_app.data.models.clinic_integration import ClinicIntegration
from Clinic_app.data.models.provider import Provider
from Clinic_app.data.models.booking import Booking
from Clinic_app.data.models.call_log import CallLog
from Clinic_app.data.models.clinic_ehr_config import ClinicEHRConfig
from Clinic_app.data.models.campaign import Campaign
from Clinic_app.data.models.campaign_contact import CampaignContact
from Clinic_app.data.models.campaign_audit import CampaignAudit
from Clinic_app.data.enums import BookingStatus, ContactStatus, CampaignStatus
from Clinic_app.common.encryption import encrypt_phi
from Clinic_app.services.campaign_service import maybe_mark_campaign_completed
from Clinic_app.services.call_summarizer import summarize_transcript_sync
from Clinic_app.services.patient import find_patient, create_patient
from Clinic_app.services.availability import (
    get_available_slots,
    get_next_available_slots
)
from Clinic_app.services.playwright_ehr import playwright_ehr_service
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
    preferred_date: Optional[str] = None  # YYYY-MM-DD (new date for reschedule)
    preferred_time_range: Optional[List[str]] = None  # ["09:00", "12:00"] (new time for reschedule)
    current_appointment_date: Optional[str] = None  # YYYY-MM-DD (existing appointment date to reschedule)
    current_appointment_time_range: Optional[List[str]] = None  # ["09:00", "12:00"] (existing appointment time to reschedule)
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


class EhrToolSlotsResponse(BaseModel):
    """NextGen EHR slots for Retell mid-call tool (human-readable strings)."""
    success: bool
    message: str = ""
    slots: List[str] = []
    slot_details: List[Dict[str, Any]] = []


class EhrBookAppointmentResponse(BaseModel):
    """NextGen booking result for Retell mid-call tool."""
    success: bool
    message: str = ""
    ehr_appointment_id: Optional[str] = None


class CallStartedWebhook(BaseModel):
    """Webhook payload for call started event (can be called as custom function or webhook)."""
    model_config = ConfigDict(extra="ignore")

    call_id: str
    agent_id: str
    from_number: Optional[str] = None
    to_number: Optional[str] = None
    direction: Optional[str] = "inbound"  # Default to inbound if not provided
    timestamp: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class CallEndedWebhook(BaseModel):
    """Webhook payload for call ended event."""
    model_config = ConfigDict(extra="ignore")

    call_id: str
    start_timestamp: Optional[int] = None  # Milliseconds since epoch
    end_timestamp: Optional[int] = None  # Milliseconds since epoch
    disconnection_reason: Optional[str] = None
    timestamp: Optional[str] = None  # ISO format timestamp string
    metadata: Optional[Dict[str, Any]] = None


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
    
    If multiple CallLog entries exist for the same call_id (e.g., in testing),
    uses the most recent one (ordered by started_at DESC).
    
    Args:
        db: Database session
        call_id: Retell call identifier
        booking_id: Booking UUID to track
    """
    result = await db.execute(
        select(CallLog)
        .where(CallLog.retell_call_id == call_id)
        .order_by(CallLog.started_at.desc())
        .limit(1)
    )
    call_log = result.scalar_one_or_none()
    
    if call_log:
        call_log.tentative_booking_id = booking_id
        await db.flush()
        logger.info(f"Updated CallLog {call_log.id} with tentative_booking_id={booking_id}")
    else:
        logger.warning(f"No CallLog found for call_id={call_id}")


def _booking_to_dict(booking: Booking, provider_name: str) -> Dict[str, Any]:
    """Convert Booking model to response dictionary."""
    # Handle both enum and string values for status
    status_value = booking.status.value if hasattr(booking.status, 'value') else booking.status
    
    return {
        "id": str(booking.id),
        "provider_name": provider_name,
        "start_time": booking.slot_start.isoformat(),
        "end_time": booking.slot_end.isoformat(),
        "status": status_value,
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
    Verify Retell webhook signature using HMAC-SHA256.
    
    Implementation matches Retell SDK: HMAC-SHA256(JSON.stringify(body), api_key)
    
    Args:
        request: FastAPI request object
        body_bytes: Raw request body bytes (already read)
        
    Raises:
        HTTPException: If signature is missing or invalid (in production)
    """
    # Get environment mode
    app_env = os.environ.get("APP_ENVIRONMENT", "").lower()
    is_production = app_env in ["production", "prod"]
    
    # Get webhook secret (API key with webhook badge)
    webhook_secret = os.environ.get("RETELL_WEBHOOK_SECRET", "")
    
    # Extract signature header (case-insensitive)
    x_retell_signature_raw = (
        request.headers.get("x-retell-signature") or 
        request.headers.get("X-Retell-Signature") or
        request.headers.get("X-RETELL-SIGNATURE")
    )
    
    # Check if this is a playground/test call (skip verification)
    # Playground calls may have call_id="playground" or no signature header
    try:
        if body_bytes:
            body_json = json.loads(body_bytes.decode('utf-8'))
            # Check multiple possible locations for call_id
            call_id = (
                body_json.get("call_id") or  # Top level
                body_json.get("call", {}).get("call_id") or  # Nested in "call" object
                ""
            )
            if call_id == "playground" or call_id.startswith("test_") or call_id.startswith("playground_"):
                logger.info(f"Skipping signature verification for playground/test call: {call_id}")
                return
    except (json.JSONDecodeError, UnicodeDecodeError, KeyError, AttributeError):
        pass
    
    # Production: Require signature header
    if is_production:
        if not x_retell_signature_raw:
            logger.error("Missing x-retell-signature header in production - rejecting request")
            raise HTTPException(
                status_code=401,
                detail={"code": "MISSING_SIGNATURE", "message": "Missing signature header"}
            )
        
        if not webhook_secret:
            logger.error("RETELL_WEBHOOK_SECRET not configured in production - rejecting request")
            raise HTTPException(
                status_code=500,
                detail={"code": "CONFIGURATION_ERROR", "message": "Webhook secret not configured"}
            )
    
    # Testing/Development: Allow requests without signature (for playground/testing)
    if not x_retell_signature_raw:
        if not is_production:
            logger.warning("Missing x-retell-signature header - allowing request (non-production mode)")
            return
        # Production case already handled above
    
    if not webhook_secret:
        if not is_production:
            logger.warning("RETELL_WEBHOOK_SECRET not configured - skipping signature verification (non-production mode)")
            return
        # Production case already handled above
    
    # Verify signature
    x_retell_signature = x_retell_signature_raw.strip()
    
    # Format body for signature verification (matches Retell SDK's JSON.stringify)
    # Retell SDK uses: JSON.stringify(req.body) which produces compact JSON
    try:
        body_json = json.loads(body_bytes.decode('utf-8'))
        # Use JSON.stringify equivalent: compact JSON with no spaces, sorted keys for consistency
        # Note: Python's json.dumps doesn't sort keys by default, but Retell may not require it
        # Using separators=(",", ":") matches JSON.stringify behavior
        body_for_signature = json.dumps(body_json, separators=(",", ":"), ensure_ascii=False)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        # If body isn't valid JSON, this is an error
        logger.error(f"Invalid JSON in request body: {str(e)}")
        if is_production:
            raise HTTPException(
                status_code=400,
                detail={"code": "INVALID_JSON", "message": "Invalid JSON in request body"}
            )
        # In non-production, allow it
        body_for_signature = body_bytes.decode('utf-8', errors='replace')
    
    # Compute expected signature using HMAC-SHA256
    # Retell SDK: HMAC-SHA256(JSON.stringify(body), api_key) as hex digest
    expected = hmac.new(
        webhook_secret.encode('utf-8'),
        body_for_signature.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    # Verify signature using constant-time comparison
    if not hmac.compare_digest(expected, x_retell_signature):
        # Production: Always reject invalid signatures
        if is_production:
            logger.error(
                f"Invalid Retell signature in production - rejecting request. "
                f"Expected: {expected[:16]}..., Got: {x_retell_signature[:16]}..."
            )
            raise HTTPException(
                status_code=401,
                detail={"code": "INVALID_SIGNATURE", "message": "Invalid signature"}
            )
        
        # Testing/Development: Log warning but allow (for testing scenarios)
        logger.warning(
            f"Signature verification failed in {app_env} mode - allowing request (non-production). "
            f"Expected: {expected[:16]}..., Got: {x_retell_signature[:16]}..."
        )
        logger.debug(f"Body length: {len(body_for_signature)}, Signature header: {x_retell_signature_raw[:50]}...")
        return
    
    # Signature is valid
    logger.debug("Retell signature verification successful")


# ============================================================================
# TOOL ENDPOINTS
# ============================================================================

@retell_router.post("/schedule", response_model=ScheduleResponse)
async def schedule(
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> ScheduleResponse:
    """
    Main scheduling endpoint for booking, canceling, or rescheduling appointments.
    Called by Retell AI during voice conversations.
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
        return ScheduleResponse(
            success=False,
            message="Missing agent_id in request"
        )
    
    try:
        clinic_id = await _get_clinic_by_agent_id(db, agent_id)
    except ValueError as e:
        logger.error(f"Clinic lookup failed for agent_id {agent_id}: {str(e)}")
        return ScheduleResponse(
            success=False,
            message="Clinic not found for this agent"
        )
    
    # Extract call_id from call object
    call_id = call_obj.get("call_id", "")
    
    # Extract parameters from args
    intent = args.get("intent")
    if not intent:
        return ScheduleResponse(
            success=False,
            message="Missing required parameter: intent"
        )
    
    patient_name = args.get("patient_name")
    patient_dob = args.get("patient_dob")
    phone = args.get("phone")
    
    # Validate required fields
    if not patient_name or not patient_dob or not phone:
        return ScheduleResponse(
            success=False,
            message="Missing required parameters: patient_name, patient_dob, and phone are required"
        )
    
    # Build ScheduleRequest object
    schedule_request = ScheduleRequest(
        call_id=call_id,
        clinic_id=clinic_id,
        patient_name=patient_name,
        patient_dob=patient_dob,
        phone=phone,
        email=args.get("email"),
        intent=intent,
        preferred_date=args.get("preferred_date"),
        preferred_time_range=args.get("preferred_time_range"),
        current_appointment_date=args.get("current_appointment_date"),
        current_appointment_time_range=args.get("current_appointment_time_range"),
        provider_preference=args.get("provider_preference"),
        language=args.get("language", "en"),
        booking_id=args.get("booking_id")
    )
    
    logger.info(
        f"Schedule POST request: agent_id={agent_id}, clinic_id={clinic_id}, "
        f"intent={intent}, patient_name={patient_name}"
    )
    
    try:
        # 1. Find or create patient
        patient = await find_patient(db, schedule_request.clinic_id, schedule_request.patient_name, schedule_request.patient_dob)
        
        if not patient:
            patient = await create_patient(
                db=db,
                clinic_id=schedule_request.clinic_id,
                name=schedule_request.patient_name,
                dob=schedule_request.patient_dob,
                phone=schedule_request.phone,
                email=schedule_request.email,
                language=schedule_request.language
            )
            logger.info(f"Created new patient: {patient.id}")
        
        # Handle different intents
        if schedule_request.intent == "book":
            return await _handle_book_intent(db, schedule_request, patient)
        
        elif schedule_request.intent == "cancel":
            return await _handle_cancel_intent(db, schedule_request, patient)
        
        elif schedule_request.intent == "reschedule":
            return await _handle_reschedule_intent(db, schedule_request, patient)
        
        else:
            return ScheduleResponse(
                success=False,
                message=f"Unknown intent: {schedule_request.intent}"
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
    """
    Handle cancellation intent - find and cancel patient's booking.
    
    Logic:
    - Same call (call_id provided): Check CallLog's tentative_booking_id first
    - Different call (no call_id or not in CallLog): Find by patient name, DOB, and date/time
    - Includes both TENTATIVE and CONFIRMED bookings in search
    """
    booking_to_cancel = None
    
    # If booking_id is explicitly provided, use it
    if request.booking_id:
        booking_to_cancel = await get_booking_by_id(db, request.booking_id, request.clinic_id)
        # Verify it's for this patient and clinic
        if booking_to_cancel and (booking_to_cancel.patient_id != patient.id or booking_to_cancel.clinic_id != request.clinic_id):
            booking_to_cancel = None
    
    # If call_id is provided (same call scenario), check CallLog first
    elif request.call_id:
        logger.info(f"Cancel in same call, checking CallLog for call_id={request.call_id}")
        result = await db.execute(
            select(CallLog)
            .where(CallLog.retell_call_id == request.call_id)
            .order_by(CallLog.started_at.desc())
            .limit(1)
        )
        call_log = result.scalar_one_or_none()
        
        if call_log and call_log.tentative_booking_id:
            # Found booking from this call (could be TENTATIVE or CONFIRMED)
            booking_to_cancel = await get_booking_by_id(
                db, call_log.tentative_booking_id, request.clinic_id
            )
            if booking_to_cancel:
                logger.info(f"Found booking from CallLog: {booking_to_cancel.id}, status={booking_to_cancel.status}")
    
    # If not found in CallLog or no call_id (different call scenario)
    # Find by patient name, DOB - use next upcoming appointment
    if not booking_to_cancel:
        logger.info(f"Searching for bookings for patient {patient.id} (different call or not in CallLog)")
        # Include both TENTATIVE and CONFIRMED bookings
        bookings = await get_patient_bookings(
            db, patient.id, request.clinic_id, 
            [BookingStatus.TENTATIVE, BookingStatus.CONFIRMED]
        )
        
        # Filter to upcoming only
        now = datetime.now(timezone.utc)
        upcoming_bookings = [b for b in bookings if b.slot_start > now]
        
        if upcoming_bookings:
            # Cancel the next upcoming appointment
            booking_to_cancel = min(upcoming_bookings, key=lambda b: b.slot_start)
            logger.info(f"Found next upcoming booking to cancel: {booking_to_cancel.id}, date={booking_to_cancel.slot_start.date()}, status={booking_to_cancel.status}")
    
    if not booking_to_cancel:
        return ScheduleResponse(
            success=False,
            message="No upcoming appointments found to cancel"
        )
    
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
    """
    Handle reschedule intent - cancel old booking and create new one.
    
    Logic:
    - Same call (call_id provided): Check CallLog's tentative_booking_id first
    - Different call (no call_id or not in CallLog): Find by patient name, DOB, and date/time
    - Includes both TENTATIVE and CONFIRMED bookings in search
    """
    booking_to_reschedule = None
    
    # If booking_id is explicitly provided, use it
    if request.booking_id:
        booking_to_reschedule = await get_booking_by_id(db, request.booking_id, request.clinic_id)
    
    # If call_id is provided (same call scenario), check CallLog first
    elif request.call_id:
        logger.info(f"Reschedule in same call, checking CallLog for call_id={request.call_id}")
        result = await db.execute(
            select(CallLog)
            .where(CallLog.retell_call_id == request.call_id)
            .order_by(CallLog.started_at.desc())
            .limit(1)
        )
        call_log = result.scalar_one_or_none()
        
        if call_log and call_log.tentative_booking_id:
            # Found tentative booking from this call
            booking_to_reschedule = await get_booking_by_id(
                db, call_log.tentative_booking_id, request.clinic_id
            )
            if booking_to_reschedule:
                logger.info(f"Found booking from CallLog: {booking_to_reschedule.id}, status={booking_to_reschedule.status}")
    
    # If not found in CallLog or no call_id (different call scenario)
    # Find by patient name, DOB, and the specific date/time they mention
    if not booking_to_reschedule:
        logger.info(f"Searching for bookings for patient {patient.id} (different call or not in CallLog)")
        # Include both TENTATIVE and CONFIRMED bookings
        bookings = await get_patient_bookings(
            db, patient.id, request.clinic_id, 
            [BookingStatus.TENTATIVE, BookingStatus.CONFIRMED]
        )
        
        now = datetime.now(timezone.utc)
        upcoming = [b for b in bookings if b.slot_start > now]
        
        if upcoming:
            # If patient specified the current appointment date/time, match by that
            if request.current_appointment_date:
                try:
                    target_date = date.fromisoformat(request.current_appointment_date)
                    matching_by_date = [b for b in upcoming if b.slot_start.date() == target_date]
                    
                    if matching_by_date and request.current_appointment_time_range and len(request.current_appointment_time_range) >= 1:
                        # Also match by time if provided
                        target_time_str = request.current_appointment_time_range[0]  # e.g., "13:00" for 1 PM
                        try:
                            from datetime import time as dt_time
                            target_hour, target_minute = map(int, target_time_str.split(":"))
                            target_time = dt_time(target_hour, target_minute)
                            
                            # Find booking matching both date and time (within 15 minutes tolerance)
                            for booking in matching_by_date:
                                booking_time = booking.slot_start.time()
                                time_diff = abs((booking_time.hour * 60 + booking_time.minute) - 
                                              (target_time.hour * 60 + target_time.minute))
                                if time_diff <= 15:  # Within 15 minutes
                                    booking_to_reschedule = booking
                                    logger.info(f"Found booking matching date {target_date} and time {target_time_str}: {booking_to_reschedule.id}")
                                    break
                            
                            if not booking_to_reschedule and matching_by_date:
                                # If no exact time match, use the first booking on that date
                                booking_to_reschedule = min(matching_by_date, key=lambda b: b.slot_start)
                                logger.info(f"Found booking matching date {target_date} (no time match): {booking_to_reschedule.id}")
                        except (ValueError, IndexError) as e:
                            logger.warning(f"Invalid time format in current_appointment_time_range: {e}")
                            # Fall back to date-only match
                            if matching_by_date:
                                booking_to_reschedule = min(matching_by_date, key=lambda b: b.slot_start)
                                logger.info(f"Found booking matching date {target_date}: {booking_to_reschedule.id}")
                    elif matching_by_date:
                        # Only date match, no time specified
                        booking_to_reschedule = min(matching_by_date, key=lambda b: b.slot_start)
                        logger.info(f"Found booking matching date {target_date}: {booking_to_reschedule.id}")
                    else:
                        # No match for specified date, use next upcoming
                        booking_to_reschedule = min(upcoming, key=lambda b: b.slot_start)
                        logger.info(f"No booking found for date {target_date}, using next upcoming: {booking_to_reschedule.id}")
                except ValueError:
                    # Invalid date format, use next upcoming
                    booking_to_reschedule = min(upcoming, key=lambda b: b.slot_start)
                    logger.info(f"Invalid date format, using next upcoming: {booking_to_reschedule.id}")
            else:
                # No specific date/time mentioned, use next upcoming appointment
                booking_to_reschedule = min(upcoming, key=lambda b: b.slot_start)
                logger.info(f"No specific appointment date mentioned, using next upcoming: {booking_to_reschedule.id}, date={booking_to_reschedule.slot_start.date()}, status={booking_to_reschedule.status}")
    
    if not booking_to_reschedule:
        return ScheduleResponse(
            success=False,
            message="No appointment found to reschedule. Please make sure you have an existing appointment."
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
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> ConfirmResponse:
    """
    Confirm a tentative booking.
    Called after patient confirms the appointment details.
    Extracts clinic_id from agent_id and hold_token from args.
    """
    # Read body once
    body_bytes = await request.body()
    
    # Verify Retell signature using the body bytes
    await verify_retell_signature(request, body_bytes)
    
    # Parse JSON from the same body bytes
    body = json.loads(body_bytes.decode('utf-8'))
    call_obj = body.get("call", {})
    args = body.get("args", {})
    
    # Log the received request for debugging
    logger.info(f"Confirm booking request body: {json.dumps(body, default=str)}")
    
    # Extract agent_id from call object and look up clinic_id
    agent_id = call_obj.get("agent_id")
    if not agent_id:
        logger.warning(f"Missing agent_id in Retell request for confirm_booking. Body: {json.dumps(body, default=str)}")
        return ConfirmResponse(
            success=False,
            message="Missing agent_id in request"
        )
    
    try:
        clinic_id = await _get_clinic_by_agent_id(db, agent_id)
    except ValueError as e:
        logger.error(f"Clinic lookup failed for agent_id {agent_id}: {str(e)}")
        return ConfirmResponse(
            success=False,
            message="Clinic not found for this agent"
        )
    
    # Extract hold_token from args
    hold_token_str = args.get("hold_token")
    if not hold_token_str:
        logger.warning(f"Missing hold_token in confirm_booking request. Args: {json.dumps(args, default=str)}")
        return ConfirmResponse(
            success=False,
            message="Missing required parameter: hold_token"
        )
    
    try:
        hold_token = UUID(hold_token_str)
    except (ValueError, TypeError):
        logger.warning(f"Invalid hold_token format: {hold_token_str}")
        return ConfirmResponse(
            success=False,
            message="Invalid hold_token format"
        )
    
    logger.info(f"Confirm booking request: agent_id={agent_id}, clinic_id={clinic_id}, hold_token={hold_token}")
    
    try:
        booking = await confirm_booking(db, hold_token, clinic_id)
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


def _format_iso_slot_for_voice(iso_start: str) -> str:
    """Turn ISO start_time into a spoken label (HEDIS PRD §10.3)."""
    try:
        s = iso_start.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt.strftime("%A, %B %d at %I:%M %p").replace(" 0", " ")
    except Exception:
        return iso_start


async def _get_ehr_config_row(
    db: AsyncSession, clinic_id: UUID
) -> Optional[ClinicEHRConfig]:
    result = await db.execute(
        select(ClinicEHRConfig).where(ClinicEHRConfig.clinic_id == clinic_id)
    )
    return result.scalar_one_or_none()


def _appt_type_code_for_gap(mapping: Dict[str, Any], gap_type: Optional[str]) -> str:
    """Resolve NextGen appointment type code; default per PRD §10.5."""
    default = "Preventive Care Visit"
    if not gap_type:
        return default
    if isinstance(mapping, dict) and gap_type in mapping:
        return str(mapping[gap_type])
    return default


def _hedis_metadata_from_call(call_obj: Dict[str, Any], webhook_metadata: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Merge metadata from webhook model and raw call object (Retell shape varies)."""
    md = dict(webhook_metadata or {})
    raw_md = call_obj.get("metadata")
    if isinstance(raw_md, dict):
        for k, v in raw_md.items():
            md.setdefault(k, v)
    return md


def _map_disconnection_to_outcome(
    reason: Optional[str],
    has_appointment: bool,
) -> ContactStatus:
    """Map Retell disconnection_reason to ContactStatus for HEDIS campaigns."""
    r = (reason or "").lower()
    if any(x in r for x in ("voicemail", "machine")):
        return ContactStatus.VOICEMAIL
    if any(
        x in r
        for x in (
            "no_answer",
            "dial_no_answer",
            "timeout",
            "inactivity",
            "not_connected",
            "registered_call_timeout",
        )
    ):
        return ContactStatus.NO_ANSWER
    if "busy" in r or "dial_failed" in r:
        return ContactStatus.NO_ANSWER
    if "error" in r:
        return ContactStatus.ERROR
    if any(x in r for x in ("hangup", "ended", "disconnected")):
        return ContactStatus.BOOKED if has_appointment else ContactStatus.DECLINED
    return ContactStatus.ERROR if not has_appointment else ContactStatus.DECLINED


def _extract_transcript_for_summary(call_obj: Dict[str, Any]) -> str:
    """Best-effort transcript extraction from Retell call payload (shape varies by product version)."""
    direct = call_obj.get("transcript")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    tw = call_obj.get("transcript_with_tool_calls")
    if isinstance(tw, str) and tw.strip():
        return tw.strip()
    ca = call_obj.get("call_analysis")
    if isinstance(ca, dict):
        for key in ("transcript", "summary", "call_summary"):
            val = ca.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    return ""


def _transcript_requests_human(transcript: str) -> bool:
    t = transcript.lower()
    return any(
        phrase in t
        for phrase in (
            "speak to a human",
            "talk to a human",
            "real person",
            "representative",
            "speak to someone",
            "call the office",
        )
    )


async def _apply_hedis_call_ended(
    db: AsyncSession,
    call_log: CallLog,
    webhook: CallEndedWebhook,
    raw_call: Dict[str, Any],
    ended_at: datetime,
) -> None:
    """Update CampaignContact + Campaign counters for HEDIS outbound calls."""
    meta = _hedis_metadata_from_call(raw_call, webhook.metadata)
    if meta.get("call_type") != "hedis_campaign":
        return

    ccid_raw = meta.get("campaign_contact_id")
    if not ccid_raw:
        return
    try:
        contact_id = UUID(str(ccid_raw))
    except (ValueError, TypeError):
        logger.warning("HEDIS call_ended: invalid campaign_contact_id %r", ccid_raw)
        return

    contact = await db.get(CampaignContact, contact_id)
    if not contact or contact.clinic_id != call_log.clinic_id:
        logger.warning(
            "HEDIS call_ended: contact missing or wrong clinic id=%s",
            contact_id,
        )
        return

    campaign = await db.get(Campaign, contact.campaign_id)
    if not campaign or campaign.clinic_id != call_log.clinic_id:
        return

    has_appt = bool(contact.ehr_appointment_id and str(contact.ehr_appointment_id).strip())
    outcome = _map_disconnection_to_outcome(webhook.disconnection_reason, has_appt)
    now = datetime.now(timezone.utc)

    if outcome in (
        ContactStatus.VOICEMAIL,
        ContactStatus.NO_ANSWER,
        ContactStatus.ERROR,
    ):
        attempts = contact.attempt_count or 0
        max_a = campaign.max_attempts or 3
        if attempts >= max_a:
            contact.status = ContactStatus.EXHAUSTED.value
            contact.next_attempt_after = None
            campaign.failed_count = (campaign.failed_count or 0) + 1
        else:
            if outcome == ContactStatus.VOICEMAIL:
                hrs = campaign.voicemail_retry_hours or 72
            elif outcome == ContactStatus.NO_ANSWER:
                hrs = campaign.no_answer_retry_hours or 48
            else:
                hrs = campaign.error_retry_hours or 1
            contact.status = ContactStatus.PENDING.value
            contact.next_attempt_after = now + timedelta(hours=int(hrs))
    elif outcome == ContactStatus.BOOKED:
        contact.status = ContactStatus.BOOKED.value
        contact.next_attempt_after = None
        campaign.booked_count = (campaign.booked_count or 0) + 1
    elif outcome == ContactStatus.DECLINED:
        contact.status = ContactStatus.DECLINED.value
        contact.next_attempt_after = None
        campaign.failed_count = (campaign.failed_count or 0) + 1
    else:
        contact.status = outcome.value
        contact.next_attempt_after = None

    call_log.related_id = contact.id

    await maybe_mark_campaign_completed(db, call_log.clinic_id, campaign.id)


@retell_router.post("/tools/get_available_slots", response_model=EhrToolSlotsResponse)
async def ehr_get_available_slots(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> EhrToolSlotsResponse:
    """
    Mid-call: read NextGen availability via Playwright + AgentQL (HEDIS PRD §10.3).
    Must respond quickly; pre-warmed session + selector cache help meet the <3s target.
    """
    body_bytes = await request.body()
    await verify_retell_signature(request, body_bytes)
    body = json.loads(body_bytes.decode("utf-8"))
    call_obj = body.get("call", {})
    args = body.get("args", {})
    metadata = call_obj.get("metadata") or {}

    agent_id = call_obj.get("agent_id")
    if not agent_id:
        return EhrToolSlotsResponse(success=False, message="Missing agent_id in request", slots=[])

    try:
        clinic_id = await _get_clinic_by_agent_id(db, agent_id)
    except ValueError:
        return EhrToolSlotsResponse(success=False, message="Clinic not found for this agent", slots=[])

    cfg = await _get_ehr_config_row(db, clinic_id)
    if not cfg:
        return EhrToolSlotsResponse(success=False, message="EHR is not configured for this clinic", slots=[])

    provider_name = args.get("provider_name") or metadata.get("provider_name")
    if not provider_name:
        return EhrToolSlotsResponse(success=False, message="Missing provider_name", slots=[])

    date_str = args.get("date")
    if not date_str:
        date_str = date.today().isoformat()

    try:
        raw_slots = await playwright_ehr_service.get_available_slots(
            db, clinic_id, provider_name, date_str
        )
    except Exception as e:
        logger.error("get_available_slots EHR error: %s", e, exc_info=True)
        return EhrToolSlotsResponse(
            success=False,
            message="Unable to read schedule from the EHR. Please try again or call the clinic.",
            slots=[],
        )

    voice_labels = [_format_iso_slot_for_voice(s["start_time"]) for s in raw_slots]
    return EhrToolSlotsResponse(
        success=True,
        message=f"Found {len(voice_labels)} available times" if voice_labels else "No open slots in this range",
        slots=voice_labels,
        slot_details=raw_slots,
    )


@retell_router.post("/tools/book_appointment", response_model=EhrBookAppointmentResponse)
async def ehr_book_appointment(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> EhrBookAppointmentResponse:
    """Mid-call: book appointment in NextGen (HEDIS PRD §10.4)."""
    body_bytes = await request.body()
    await verify_retell_signature(request, body_bytes)
    body = json.loads(body_bytes.decode("utf-8"))
    call_obj = body.get("call", {})
    args = body.get("args", {})
    metadata = call_obj.get("metadata") or {}

    agent_id = call_obj.get("agent_id")
    if not agent_id:
        return EhrBookAppointmentResponse(success=False, message="Missing agent_id in request")

    try:
        clinic_id = await _get_clinic_by_agent_id(db, agent_id)
    except ValueError:
        return EhrBookAppointmentResponse(success=False, message="Clinic not found for this agent")

    cfg = await _get_ehr_config_row(db, clinic_id)
    if not cfg:
        return EhrBookAppointmentResponse(success=False, message="EHR is not configured for this clinic")

    provider_name = args.get("provider_name")
    chosen_slot = args.get("chosen_slot")
    patient_name = args.get("patient_name")
    patient_dob = args.get("patient_dob")
    gap_type = args.get("gap_type")

    if not all([provider_name, chosen_slot, patient_name, patient_dob]):
        return EhrBookAppointmentResponse(
            success=False,
            message="Missing required fields: provider_name, chosen_slot, patient_name, patient_dob",
        )

    mapping = cfg.appt_type_mapping if isinstance(cfg.appt_type_mapping, dict) else {}
    appt_code = _appt_type_code_for_gap(mapping, gap_type)

    try:
        result = await playwright_ehr_service.book_appointment(
            db,
            clinic_id,
            provider_name,
            chosen_slot,
            patient_name,
            patient_dob,
            appt_code,
        )
    except Exception as e:
        logger.error("book_appointment EHR error: %s", e, exc_info=True)
        return EhrBookAppointmentResponse(
            success=False,
            message="Booking failed in the EHR. Please try another time or call the clinic.",
        )

    if result.get("success"):
        cc_raw = metadata.get("campaign_contact_id")
        if cc_raw and metadata.get("call_type") == "hedis_campaign":
            try:
                cid = UUID(str(cc_raw))
                row = await db.get(CampaignContact, cid)
                if row and row.clinic_id == clinic_id:
                    ehr_id = result.get("ehr_appointment_id")
                    if ehr_id:
                        row.ehr_appointment_id = str(ehr_id)
            except (ValueError, TypeError):
                logger.warning("book_appointment: invalid campaign_contact_id %r", cc_raw)
        try:
            await db.commit()
        except Exception as exc:
            logger.error("book_appointment commit failed: %s", exc, exc_info=True)
            await db.rollback()
            return EhrBookAppointmentResponse(
                success=False,
                message="Could not save booking reference.",
            )
        return EhrBookAppointmentResponse(
            success=True,
            message="Appointment booked",
            ehr_appointment_id=result.get("ehr_appointment_id"),
        )
    return EhrBookAppointmentResponse(success=False, message=result.get("error", "Booking failed"))


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
    # Retell sends data nested in a "call" object when called as webhook
    # When called as custom function, data might be in "call" object or at top level
    call_obj = body.get("call", body)  # Try "call" object first, fallback to body
    webhook = CallStartedWebhook.model_validate(call_obj)
    
    logger.info(f"Call started: call_id={webhook.call_id}, agent_id={webhook.agent_id}")
    
    try:
        # Lookup clinic by agent_id
        clinic_id = await _get_clinic_by_agent_id(db, webhook.agent_id)
        
        # Determine call type (default to inbound if not provided)
        direction = webhook.direction or "inbound"
        call_type = "inbound" if direction == "inbound" else "outbound_campaign"
        
        # Parse timestamp (use current time if not provided)
        if webhook.timestamp:
            try:
                started_at = datetime.fromisoformat(webhook.timestamp.replace("Z", "+00:00"))
            except ValueError:
                started_at = datetime.now(timezone.utc)
        else:
            started_at = datetime.now(timezone.utc)
        
        # Create CallLog entry
        call_log = CallLog(
            clinic_id=clinic_id,
            call_type=call_type,
            retell_call_id=webhook.call_id,
            started_at=started_at
        )
        meta = _hedis_metadata_from_call(call_obj, webhook.metadata)
        if meta.get("call_type") == "hedis_campaign" and meta.get("campaign_contact_id"):
            try:
                cid = UUID(str(meta["campaign_contact_id"]))
                contact = await db.get(CampaignContact, cid)
                if contact and contact.clinic_id == clinic_id:
                    call_log.related_id = contact.id
            except (ValueError, TypeError):
                logger.warning("call_started: invalid campaign_contact_id in metadata")

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
    # Retell sends data nested in a "call" object when called as webhook
    # When called as custom function, data might be in "call" object or at top level
    call_obj = body.get("call", body)  # Try "call" object first, fallback to body
    webhook = CallEndedWebhook.model_validate(call_obj)
    
    # Extract outcome (use disconnection_reason if available, otherwise default)
    outcome_str = webhook.disconnection_reason if webhook.disconnection_reason else "unknown"
    logger.info(f"Call ended: call_id={webhook.call_id}, outcome={outcome_str}")
    
    try:
        # Find CallLog by retell_call_id
        # If multiple exist (e.g., in testing), use the most recent one
        result = await db.execute(
            select(CallLog)
            .where(CallLog.retell_call_id == webhook.call_id)
            .order_by(CallLog.started_at.desc())
            .limit(1)
        )
        call_log = result.scalar_one_or_none()
        
        if not call_log:
            logger.warning(f"CallLog not found for call_id: {webhook.call_id}")
            return {"status": "ok", "warning": "CallLog not found"}
        
        # Calculate duration from timestamps (Retell sends milliseconds since epoch)
        duration_seconds = None
        if webhook.start_timestamp and webhook.end_timestamp:
            duration_seconds = (webhook.end_timestamp - webhook.start_timestamp) // 1000  # Convert ms to seconds
        
        # Extract outcome from disconnection_reason
        outcome = webhook.disconnection_reason if webhook.disconnection_reason else "unknown"
        
        # Parse timestamp (Retell sends milliseconds since epoch)
        if webhook.end_timestamp:
            ended_at = datetime.fromtimestamp(webhook.end_timestamp / 1000, tz=timezone.utc)
        else:
            # Fallback to timestamp string if provided
            if webhook.timestamp:
                try:
                    ended_at = datetime.fromisoformat(webhook.timestamp.replace("Z", "+00:00"))
                except ValueError:
                    ended_at = datetime.now(timezone.utc)
            else:
                ended_at = datetime.now(timezone.utc)
        
        # Update CallLog
        if duration_seconds is not None:
            call_log.duration_seconds = duration_seconds
        call_log.outcome = outcome
        call_log.ended_at = ended_at
        
        # RELEASE UNCONFIRMED HOLDS
        # If there's a tentative booking that wasn't confirmed, cancel it
        if call_log.tentative_booking_id:
            booking = await db.get(Booking, call_log.tentative_booking_id)
            
            if booking and booking.status == BookingStatus.TENTATIVE:
                logger.info(f"Releasing unconfirmed tentative booking: {booking.id}")
                await cancel_booking(db, booking.id, call_log.clinic_id, actor="call_ended")
                call_log.tentative_booking_id = None

        try:
            await _apply_hedis_call_ended(db, call_log, webhook, call_obj, ended_at)
        except Exception as exc:
            logger.error("HEDIS call_ended handling failed: %s", exc, exc_info=True)
        
        await db.commit()
        
        logger.info(f"Updated CallLog: {call_log.id}, released_hold={call_log.tentative_booking_id is None}")
        
        return {"status": "ok"}
        
    except Exception as e:
        logger.error(f"Error in call_ended webhook: {str(e)}", exc_info=True)
        await db.rollback()
        return {"status": "ok", "error": "Internal error"}


@retell_router.post("/webhook/call_analyzed")
async def webhook_call_analyzed(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    """
    Post-call analysis: one-sentence Claude summary + CampaignAudit row for HEDIS campaigns.
    Raw transcript is not persisted.
    """
    body_bytes = await request.body()
    await verify_retell_signature(request, body_bytes)
    body = json.loads(body_bytes.decode("utf-8"))
    call_obj = body.get("call", body)

    call_id = call_obj.get("call_id") or ""
    agent_id = call_obj.get("agent_id")
    if not agent_id:
        return {"status": "ok", "warning": "missing agent_id"}

    try:
        clinic_id = await _get_clinic_by_agent_id(db, agent_id)
    except ValueError:
        return {"status": "ok", "error": "clinic not found"}

    meta = _hedis_metadata_from_call(call_obj, call_obj.get("metadata"))
    if meta.get("call_type") != "hedis_campaign":
        return {"status": "ok"}

    cc_raw = meta.get("campaign_contact_id")
    if not cc_raw:
        return {"status": "ok", "warning": "missing campaign_contact_id"}
    try:
        contact_id = UUID(str(cc_raw))
    except (ValueError, TypeError):
        return {"status": "ok", "error": "invalid campaign_contact_id"}

    contact = await db.get(CampaignContact, contact_id)
    if not contact or contact.clinic_id != clinic_id:
        return {"status": "ok", "error": "contact not found"}

    transcript = _extract_transcript_for_summary(call_obj)
    try:
        summary = await asyncio.to_thread(
            summarize_transcript_sync,
            transcript,
            contact.gap_type,
        )
    except Exception as exc:
        logger.error("call_analyzed Claude summary failed: %s", exc, exc_info=True)
        summary = "Call summary unavailable."

    pname = meta.get("patient_name")
    name_enc = encrypt_phi(str(pname)) if pname else None
    summary_enc = encrypt_phi(summary)

    if (
        contact.status == ContactStatus.DECLINED.value
        and _transcript_requests_human(transcript)
    ):
        contact.status = ContactStatus.HUMAN_REQUESTED.value

    ended_ms = call_obj.get("end_timestamp")
    if isinstance(ended_ms, (int, float)):
        called_at = datetime.fromtimestamp(ended_ms / 1000, tz=timezone.utc)
    else:
        called_at = datetime.now(timezone.utc)

    audit = CampaignAudit(
        campaign_contact_id=contact.id,
        campaign_id=contact.campaign_id,
        clinic_id=clinic_id,
        retell_call_id=str(call_id),
        outcome=contact.status,
        patient_name_encrypted=name_enc,
        call_summary_encrypted=summary_enc,
        ehr_appointment_id=contact.ehr_appointment_id,
        attempt_number=contact.attempt_count or 1,
        called_at=called_at,
    )
    db.add(audit)
    try:
        await db.flush()
        await db.commit()
    except Exception as exc:
        logger.error("call_analyzed commit failed: %s", exc, exc_info=True)
        await db.rollback()
        return {"status": "ok", "error": "commit failed"}

    return {"status": "ok", "audit_id": str(audit.id)}

