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


# ── HEDIS Campaign Enums ───────────────────────────────────────────────────────

class CampaignStatus(str, Enum):
    """Lifecycle state of a HEDIS outreach campaign (batch)."""
    PENDING = "pending"        # Created, not yet started
    ACTIVE = "active"          # Worker is actively placing calls
    PAUSED = "paused"          # Manually paused by staff
    COMPLETED = "completed"    # All contacts reached a final state
    CANCELED = "canceled"      # Manually canceled


class ContactStatus(str, Enum):
    """Lifecycle state of a single patient contact within a campaign."""
    PENDING = "pending"        # Not yet attempted
    CALLING = "calling"        # Call in progress right now
    BOOKED = "booked"          # Appointment successfully created in NextGen
    DECLINED = "declined"      # Patient explicitly declined
    VOICEMAIL = "voicemail"    # Reached voicemail — will retry
    NO_ANSWER = "no_answer"    # No answer — will retry
    ERROR = "error"            # Technical error — will retry
    EXHAUSTED = "exhausted"    # Max attempts reached, no booking


class GapType(str, Enum):
    """HEDIS care gap types. Drives Retell agent script and NextGen appt type mapping."""
    COLORECTAL_CANCER_SCREENING = "colorectal_cancer_screening"
    BREAST_CANCER_SCREENING = "breast_cancer_screening"
    CERVICAL_CANCER_SCREENING = "cervical_cancer_screening"
    DIABETES_HBA1C = "diabetes_hba1c"
    DIABETES_EYE_EXAM = "diabetes_eye_exam"
    DIABETES_NEPHROPATHY = "diabetes_nephropathy"
    HYPERTENSION_CONTROL = "hypertension_control"
    DEPRESSION_SCREENING = "depression_screening"
    WELL_CHILD_VISIT = "well_child_visit"
    ADOLESCENT_WELL_CARE = "adolescent_well_care"
    ADULT_BMI_ASSESSMENT = "adult_bmi_assessment"
    MEDICATION_ADHERENCE_DIABETES = "medication_adherence_diabetes"
    MEDICATION_ADHERENCE_HYPERTENSION = "medication_adherence_hypertension"
    OTHER = "other"  # Fallback for Claude parsing edge cases

