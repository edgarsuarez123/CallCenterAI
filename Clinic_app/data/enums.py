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
# HEDIS CAMPAIGN ENUMS — Outbound Outreach
# ============================================================================


class CampaignStatus(str, Enum):
    """Lifecycle status for outbound calling campaigns."""

    DRAFT = "draft"  # Created but contacts not yet uploaded
    PENDING = "pending"  # Contacts uploaded, ready to start (alias: DRAFT in simple service)
    QUEUED = "queued"  # Ready to run, waiting for worker to pick up
    ACTIVE = "active"  # Worker is actively processing contacts (used by campaign_service)
    RUNNING = "running"  # Worker is actively processing contacts (used by simple campaign)
    PAUSED = "paused"  # Manually paused, can be resumed
    CANCELED = "canceled"  # Manually canceled — can be restarted
    COMPLETED = "completed"  # All contacts processed


class ContactOutcome(str, Enum):
    """
    Outcome recorded per patient contact after an outbound call attempt.

    PENDING   -- Not yet called
    CALLING   -- Call in progress (transient state)
    ACCEPTED  -- Patient agreed / acknowledged the outreach
    DECLINED  -- Patient explicitly declined
    VOICEMAIL -- Reached voicemail, message left
    NO_ANSWER -- Phone rang, no answer, no voicemail
    FAILED    -- Call could not be placed (bad number, carrier error)
    """

    PENDING = "pending"
    CALLING = "calling"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    VOICEMAIL = "voicemail"
    NO_ANSWER = "no_answer"
    FAILED = "failed"


class ContactStatus(str, Enum):
    """
    Full lifecycle state for HEDIS campaign contacts (production use).
    More granular than ContactOutcome — used by the advanced campaign_service.
    """

    PENDING = "pending"  # Not yet attempted
    CALLING = "calling"  # Call in progress right now
    BOOKED = "booked"  # Appointment successfully created in NextGen
    ORDER_AGREED = "order_agreed"  # Order-based gap: patient agreed, staff sends order
    ORDER_DECLINED = "order_declined"  # Order-based gap: patient declined — terminal
    DECLINED = "declined"  # Patient explicitly declined appointment — terminal
    VOICEMAIL = "voicemail"  # Reached voicemail — will retry
    NO_ANSWER = "no_answer"  # No answer — will retry
    ERROR = "error"  # Technical error — will retry
    EXHAUSTED = "exhausted"  # Max attempts reached, no booking — terminal
    HUMAN_REQUESTED = "human_requested"  # Patient asked for human — terminal
    NOT_YET_ELIGIBLE = "not_yet_eligible"  # Preventive visit not yet due — terminal
    EXPIRED = "expired"  # Hospital flu 7-day deadline passed — terminal


class GapType(str, Enum):
    """
    HEDIS care gap types.

    Appointment-based (Playwright books in NextGen):
      preventive_visit, hospital_flu

    Order-based (call summary only — clinic staff sends order manually):
      colorectal, eye_exam, breast_cancer, kidney, afr_cmp

    Excluded (filtered at CSV parse — never enters campaign queue):
      medication_review
    """

    PREVENTIVE_VISIT = "preventive_visit"  # Annual preventive / wellness visit
    HOSPITAL_FLU = "hospital_flu"  # Hospital follow-up within 7 days of discharge
    COLORECTAL = "colorectal"  # Colorectal cancer screening / stool test
    EYE_EXAM = "eye_exam"  # Eye exam / retinal exam
    BREAST_CANCER = "breast_cancer"  # Breast cancer screening / mammogram
    KIDNEY = "kidney"  # Kidney function lab
    AFR_CMP = "afr_cmp"  # Albumin/creatinine ratio + urinalysis
    MEDICATION_REVIEW = "medication_review"  # Excluded — filtered at parse, never called


# Gap types that are appointment-based (Playwright books in NextGen EHR)
APPOINTMENT_BASED_GAP_TYPES: frozenset[GapType] = frozenset(
    {
        GapType.PREVENTIVE_VISIT,
        GapType.HOSPITAL_FLU,
    }
)

# Gap types that are order-based (voice call only — staff sends order manually)
ORDER_BASED_GAP_TYPES: frozenset[GapType] = frozenset(
    {
        GapType.COLORECTAL,
        GapType.EYE_EXAM,
        GapType.BREAST_CANCER,
        GapType.KIDNEY,
        GapType.AFR_CMP,
    }
)
