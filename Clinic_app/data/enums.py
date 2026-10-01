# Clinic_app/data/enums.py
from enum import Enum


class SlotStatus(str, Enum):
    """Status for availability slots."""
    FREE = "free"  # available to book
    BOOKED = "booked"  # already has a booking
    BLOCKED = "blocked"  # intentionally unavailable


class SlotSource(str, Enum):
    """Source of availability slot data."""
    CSV = "csv"  # imported from CSV
    GCAL = "gcal"  # synced from Google Calendar


class BookingStatus(str, Enum):
    """Status for bookings."""
    TENTATIVE = "tentative"  # temporary hold
    CONFIRMED = "confirmed"  # finalized booking
    CANCELED = "canceled"  # canceled appointment


class BookingAction(str, Enum):
    """Actions that can be performed on bookings (for audit log)."""
    HOLD = "hold"  # Temporary reservation placed
    CONFIRM = "confirm"  # Booking confirmed
    CANCEL = "cancel"  # Booking canceled
    EXPIRE = "expire"  # Tentative hold expired (reaper)


class CallStatus(str, Enum):
    """Status for call sessions."""
    ACTIVE = "active"  # call in progress
    ENDED = "ended"  # call completed normally
    TRANSFERRED = "transferred"  # call transferred to staff
    FAILED = "failed"  # call failed/abandoned


class CallState(str, Enum):
    """State machine for call flow."""
    GREETING = "greeting"  # Initial greeting or clinic intro
    INTENT_DETECTION = "intent_detection"  # Waiting for user intent
    BOOKING_INFO = "booking_info"  # Gathering patient info
    BOOKING_CONFIRM = "booking_confirm"  # Confirming appointment details
    CANCEL_VERIFICATION = "cancel_verification"  # Verifying which appointment to cancel
    RESCHEDULE_SELECT = "reschedule_select"  # Gathering new time for reschedule
    FAQ_RESPONSE = "faq_response"  # Answering general question via template
    TRANSFER_LIVE = "transfer_live"  # Deciding to forward call to human staff
    END_CALL = "end_call"  # Wrap-up or goodbye


# ============================================================================
# CAMPAIGN SYSTEM ENUMS (Outbound HEDIS Outreach)
# ============================================================================

class CampaignStatus(str, Enum):
    """Lifecycle status for outbound calling campaigns."""
    DRAFT = "draft"          # Created but contacts not yet uploaded
    QUEUED = "queued"        # Ready to run, waiting for worker to pick up
    RUNNING = "running"      # Worker is actively processing contacts
    PAUSED = "paused"        # Manually paused, can be resumed
    COMPLETED = "completed"  # All contacts processed


class ContactOutcome(str, Enum):
    """
    Outcome recorded per patient contact after an outbound call attempt.

    PENDING  -- Not yet called
    CALLING  -- Call in progress (transient state)
    ACCEPTED -- Patient agreed / acknowledged the outreach
    DECLINED -- Patient explicitly declined
    VOICEMAIL -- Reached voicemail, message left
    NO_ANSWER -- Phone rang, no answer, no voicemail
    FAILED   -- Call could not be placed (bad number, carrier error)
    """
    PENDING = "pending"
    CALLING = "calling"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    VOICEMAIL = "voicemail"
    NO_ANSWER = "no_answer"
    FAILED = "failed"
