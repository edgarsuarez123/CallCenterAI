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

