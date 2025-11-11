"""
Call Flow Utilities
Helper functions extracted from call_flow_service for better organization and testability.
"""

import re
from typing import List, Optional
from datetime import date, datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from models.models import Provider, AppointmentSlot
from models.enums import YesNo
from models.call_flow_models import (
    ProviderOption, DateOption, TimeSlotOption, CallFlowContext
)


# ---------- Extraction Methods ----------

def extract_name(text: str) -> Optional[str]:
    """Extract name from user input with better natural language processing."""
    # Remove common prefixes and suffixes
    text = text.lower().strip()
    
    # Remove common phrases
    prefixes_to_remove = [
        "my name is", "i'm", "i am", "this is", "it's", "it is",
        "call me", "i go by", "you can call me"
    ]
    
    for prefix in prefixes_to_remove:
        if text.startswith(prefix) and len(prefix) < len(text):
            text = text[len(prefix):].strip()
            break
    
    # Remove common suffixes
    suffixes_to_remove = [
        "speaking", "here", "on the phone", "calling"
    ]
    
    for suffix in suffixes_to_remove:
        if text.endswith(suffix) and len(suffix) < len(text):
            text = text[:-len(suffix)].strip()
            break
    
    # Extract name (first two words, capitalized)
    words = text.split()
    if len(words) >= 2:
        name = " ".join(words[:2])
        return name.title()
    elif len(words) == 1:
        return words[0].title()
    
    return None


def extract_date_of_birth(text: str) -> Optional[str]:
    """Extract date of birth from user input."""
    # Simple DOB extraction (in production, use date parsing)
    # Look for patterns like "January 15th, 1990" or "01/15/1990"
    dob_patterns = [
        r'(\d{1,2}/\d{1,2}/\d{4})',
        r'(\d{1,2}-\d{1,2}-\d{4})',
        r'(\w+ \d{1,2}(?:st|nd|rd|th)?,? \d{4})',
        r'(\w+ \d{1,2},? \d{4})',  # For speech: "January 15, 1990"
        r'(\d{1,2} \w+ \d{4})'     # For speech: "15 January 1990"
    ]
    
    for pattern in dob_patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    
    return None


def extract_insurance_provider(text: str) -> Optional[str]:
    """Extract insurance provider from user input with better NLP."""
    text_lower = text.lower().strip()
    
    # Remove common phrases
    phrases_to_remove = [
        "my insurance is", "i have", "i'm with", "i use", "my provider is",
        "i'm covered by", "covered by", "insurance provider", "insurance company"
    ]
    
    for phrase in phrases_to_remove:
        if phrase in text_lower:
            text_lower = text_lower.replace(phrase, "").strip()
            break
    
    # If no common phrases were found, try to extract the insurance name directly
    if not text_lower:
        return None
        
    # Check for known insurance providers first
    insurance_mappings = {
        "blue cross": ["blue cross", "blue cross blue shield", "bcbs"],
        "aetna": ["aetna", "aetna better health"],
        "medicare": ["medicare", "medicare advantage"],
        "medicaid": ["medicaid", "state insurance"],
        "cigna": ["cigna", "cigna health"],
        "humana": ["humana", "humana health"],
        "kaiser": ["kaiser", "kaiser permanente", "kp"],
        "united": ["united healthcare", "united health", "uhc"],
        "anthem": ["anthem", "anthem blue cross"],
        "tricare": ["tricare", "military insurance"]
    }
    
    for provider, keywords in insurance_mappings.items():
        for keyword in keywords:
            if keyword in text_lower:
                return provider.title()
    
    # If no known provider found, accept the cleaned input as the insurance provider
    # Capitalize first letter of each word
    return text_lower.title()


# ---------- Matching Methods ----------

def match_provider(user_input: str, providers: List[ProviderOption]) -> Optional[ProviderOption]:
    """Match user input to a provider with better NLP."""
    user_input_lower = user_input.lower().strip()
    
    # Remove common phrases
    phrases_to_remove = [
        "i'd like to see", "i want to see", "i need to see", "can i see",
        "i would like", "i want", "i need", "book with", "schedule with",
        "make an appointment with", "see", "visit"
    ]
    
    for phrase in phrases_to_remove:
        if phrase in user_input_lower:
            user_input_lower = user_input_lower.replace(phrase, "").strip()
            break
    
    # Try exact matches first
    for provider in providers:
        provider_name_lower = provider.name.lower()
        
        # Check for exact name match
        if provider_name_lower == user_input_lower:
            return provider
    
    # Try last name with word boundaries
    for provider in providers:
        name_parts = provider.name.lower().split()
        for part in name_parts:
            pattern = r'\b' + re.escape(part) + r'\b'
            if re.search(pattern, user_input_lower):
                return provider
    
    return None


def match_date(user_input: str, dates: List[DateOption], context: Optional[CallFlowContext] = None) -> Optional[DateOption]:
    """Match user input to a date with context awareness."""
    user_input_lower = user_input.lower()
    
    # Handle relative references like "the 13th", "13th", "the 15th"
    day_match = re.search(r'(?:the\s+)?(\d{1,2})(?:st|nd|rd|th)?', user_input_lower)
    if day_match:
        day_number = int(day_match.group(1))
        
        # First try to match from context (last mentioned dates)
        if context and context.last_mentioned_dates:
            for mentioned_date in context.last_mentioned_dates:
                if mentioned_date.day == day_number:
                    # Find the corresponding DateOption
                    for date_option in dates:
                        if date_option.date == mentioned_date:
                            return date_option
        
        # Fallback to matching from available dates
        for date_option in dates:
            if date_option.date.day == day_number:
                return date_option
    
    # Handle day names (Monday, Tuesday, etc.)
    for date_option in dates:
        if date_option.day_name.lower() in user_input_lower:
            return date_option
    
    # Handle full date formats (October 13, Oct 13, etc.)
    for date_option in dates:
        if (date_option.date.strftime('%B %d').lower() in user_input_lower or
            date_option.date.strftime('%b %d').lower() in user_input_lower):
            return date_option
    
    return None


def match_time(user_input: str, times: List[TimeSlotOption]) -> Optional[TimeSlotOption]:
    """Match user input to a time with better NLP and natural language support."""
    user_input_lower = user_input.lower().strip()
    
    # First check if the input contains time-related keywords or time words
    time_keywords = ['am', 'pm', 'morning', 'afternoon', 'evening', 'o\'clock', 'oclock', 'time']
    time_words = ['one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten', 'eleven', 'twelve']
    has_time_keywords = any(keyword in user_input_lower for keyword in time_keywords)
    has_time_words = any(word in user_input_lower for word in time_words)
    
    # If no time keywords, time words, or explicit time patterns, don't try to match
    if not has_time_keywords and not has_time_words and not re.search(r'\d{1,2}:\d{2}', user_input_lower):
        return None
    
    # Remove common phrases
    phrases_to_remove = [
        "would be perfect", "works for me", "is good", "sounds good",
        "that works", "i'll take", "i want", "i'd like", "i need",
        "in the afternoon", "in the morning", "in the evening"
    ]
    
    for phrase in phrases_to_remove:
        if phrase in user_input_lower:
            user_input_lower = user_input_lower.replace(phrase, "").strip()
            break
    
    # Handle natural language time expressions
    
    # Convert word numbers to digits (one -> 1, two -> 2, etc.)
    word_to_number = {
        'one': '1', 'two': '2', 'three': '3', 'four': '4', 'five': '5',
        'six': '6', 'seven': '7', 'eight': '8', 'nine': '9', 'ten': '10',
        'eleven': '11', 'twelve': '12'
    }
    
    for word, number in word_to_number.items():
        user_input_lower = user_input_lower.replace(word, number)
    
    # Handle "1 PM", "1:00 PM", "1:30 PM" patterns - be more strict
    time_patterns = [
        (r'(\d{1,2}):(\d{2})\s*(am|pm)', 3),  # "1:30 PM" - 3 groups
        (r'(\d{1,2})\s*(am|pm)', 2),          # "1 PM" - 2 groups
        (r'(\d{1,2}):(\d{2})', 2),            # "1:30" - 2 groups
    ]
    
    # Use the single digit pattern if there are time keywords or time words
    if has_time_keywords or has_time_words:
        time_patterns.append((r'(\d{1,2})', 1))  # "1" or "nine" - 1 group
    
    for pattern, expected_groups in time_patterns:
        match = re.search(pattern, user_input_lower)
        if match:
            hour = int(match.group(1))
            # Safely access group 2 if it exists
            minute = 0
            if expected_groups > 1 and match.lastindex and match.lastindex >= 2:
                minute_str = match.group(2)
                if minute_str and minute_str.isdigit():
                    minute = int(minute_str)
            # Safely access group 3 if it exists
            period = None
            if expected_groups > 2 and match.lastindex and match.lastindex >= 3:
                period = match.group(3)
            
            # Convert to 24-hour format
            if period == 'pm' and hour != 12:
                hour += 12
            elif period == 'am' and hour == 12:
                hour = 0
            elif period is None:
                # No AM/PM specified - assume morning for medical appointments
                # If hour is 1-11, assume AM; if 12, assume PM; if 13-23, assume PM
                # Hour is already correct, no conversion needed
                pass
            
            # Find exact matching time slot first
            for time_option in times:
                if time_option.start_time.hour == hour and time_option.start_time.minute == minute:
                    return time_option
            
            # If no exact match, find the closest available time
            if times and len(times) > 0:
                # Find the closest time slot, preferring later times when there's a tie
                target_time = hour * 60 + minute  # Convert to minutes for comparison
                closest_time = min(times, key=lambda t: (abs(t.start_time.hour * 60 + t.start_time.minute - target_time), -t.start_time.hour * 60 - t.start_time.minute))
                return closest_time
    
    # Handle natural language time expressions (morning, afternoon, evening)
    if 'morning' in user_input_lower:
        # Match to times between 8 AM and 12 PM
        for time_option in times:
            if 8 <= time_option.start_time.hour < 12:
                return time_option
    elif 'afternoon' in user_input_lower:
        # Match to times between 12 PM and 5 PM
        for time_option in times:
            if 12 <= time_option.start_time.hour < 17:
                return time_option
    elif 'evening' in user_input_lower:
        # Match to times between 5 PM and 8 PM
        for time_option in times:
            if 17 <= time_option.start_time.hour < 20:
                return time_option
    
    return None


# ---------- Data Retrieval Methods ----------

async def get_available_providers(db: AsyncSession, clinic_id: str, logger) -> List[ProviderOption]:
    """Get available providers for the clinic."""
    # Validate clinic_id
    if not clinic_id:
        logger.warning("clinic_id is empty in get_available_providers")
        return []
    
    try:
        # Use ProviderManagementService to get providers (handles both direct and many-to-many relationships)
        from services.provider_management import ProviderManagementService
        from models.schemas import ProviderSearchRequest
        
        provider_service = ProviderManagementService(db)
        provider_search = ProviderSearchRequest(
            clinic_id=clinic_id,
            is_available=YesNo.YES
        )
        providers = await provider_service.list_providers(provider_search)
    except Exception as e:
        logger.error(f"Error querying providers: {e}")
        return []
    
    return [
        ProviderOption(
            provider_id=p.provider_id,
            name=p.name_token,
            title=p.title,
            specialty=p.specialty,
            is_available=True
        )
        for p in providers
    ]


async def get_available_dates(db: AsyncSession, provider_id: str, logger) -> List[DateOption]:
    """Get available dates for a provider."""
    # Validate provider_id
    if not provider_id:
        logger.warning("provider_id is empty in get_available_dates")
        return []
    
    try:
        # Get next 14 days
        start_date = datetime.now(timezone.utc) + timedelta(days=1)
        end_date = start_date + timedelta(days=14)
        
        available_dates = []
        current_date = start_date
        
        while current_date <= end_date:
            # Only include weekdays (Monday=0, Sunday=6)
            if current_date.weekday() < 5:  # Monday=0, Tuesday=1, ..., Friday=4
                # Check if provider has slots on this date
                slots_result = await db.execute(
                    select(AppointmentSlot).where(
                        AppointmentSlot.provider_id == provider_id,
                        AppointmentSlot.slot_datetime >= current_date,
                        AppointmentSlot.slot_datetime < current_date + timedelta(days=1),
                        AppointmentSlot.is_booked == YesNo.NO.value
                    )
                )
                slots = len(list(slots_result.scalars().all()))
                
                if slots > 0:
                    available_dates.append(DateOption(
                        date=current_date.date(),
                        day_name=current_date.strftime('%A'),
                        is_available=True,
                        available_slots=slots
                    ))
            
            current_date += timedelta(days=1)
        
        return available_dates
    except Exception as e:
        logger.error(f"Error querying available dates: {e}")
        return []


async def get_available_times(db: AsyncSession, provider_id: str, appointment_date: date, logger) -> List[TimeSlotOption]:
    """Get available time slots for a provider on a specific date."""
    # Validate inputs
    if not provider_id:
        logger.warning("provider_id is empty in get_available_times")
        return []
    
    if not appointment_date:
        logger.warning("appointment_date is None in get_available_times")
        return []
    
    try:
        # Create timezone-aware datetime for the start of day
        start_of_day = datetime.combine(appointment_date, datetime.min.time()).replace(tzinfo=timezone.utc)
        end_of_day = start_of_day + timedelta(days=1)
        
        slots_result = await db.execute(
            select(AppointmentSlot).where(
                AppointmentSlot.provider_id == provider_id,
                AppointmentSlot.slot_datetime >= start_of_day,
                AppointmentSlot.slot_datetime < end_of_day,
                AppointmentSlot.is_booked == YesNo.NO.value
            ).order_by(AppointmentSlot.slot_datetime)
        )
        slots = list(slots_result.scalars().all())
    except Exception as e:
        logger.error(f"Error querying available times: {e}")
        return []
    
    return [
        TimeSlotOption(
            slot_id=slot.slot_id,
            start_time=slot.slot_datetime,
            end_time=slot.slot_datetime + timedelta(minutes=slot.duration_minutes),
            duration_minutes=slot.duration_minutes,
            is_available=True
        )
        for slot in slots
    ]


async def get_provider(db: AsyncSession, provider_id: str) -> Optional[Provider]:
    """Get provider by ID."""
    result = await db.execute(select(Provider).where(Provider.provider_id == provider_id))
    return result.scalar_one_or_none()

