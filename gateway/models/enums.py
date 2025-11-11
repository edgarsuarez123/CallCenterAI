"""
Shared enums for models and schemas.
Prevents circular import between models.py and schemas.py
"""
from enum import Enum

class YesNo(str, Enum):
    YES = "yes"
    NO = "no"

class CallStatus(str, Enum):
    INITIALIZING = "initializing"
    INITIATED = "initiated"
    ACTIVE = "active"
    RINGING = "ringing"
    ANSWERED = "answered"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    BUSY = "busy"
    NO_ANSWER = "no_answer"

class PriorityLevel(str, Enum):
    NORMAL = "normal"
    EMERGENCY = "emergency"

class SubscriptionTier(str, Enum):
    BASIC = "basic"
    PROFESSIONAL = "professional"
    ENTERPRISE = "enterprise"

class LicenseStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    EXPIRED = "expired"
    CANCELLED = "cancelled"

class BillingCycle(str, Enum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ANNUAL = "annual"

class LanguageCode(str, Enum):
    """Supported language codes."""
    ENGLISH = "en"
    SPANISH = "es"
    AUTO = "auto"