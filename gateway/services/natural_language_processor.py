"""
Natural Language Processing for CallCenterAI
Handles flexible, conversational understanding of user input
"""

import re
import logging
from typing import Optional, Dict, List, Tuple, Any
from datetime import datetime, date, time
from dataclasses import dataclass
from enum import Enum

class IntentType(Enum):
    APPOINTMENT_BOOKING = "appointment_booking"
    APPOINTMENT_CANCELLATION = "appointment_cancellation"
    APPOINTMENT_RESCHEDULING = "appointment_rescheduling"
    INSURANCE_INQUIRY = "insurance_inquiry"
    DOCTOR_INQUIRY = "doctor_inquiry"
    GENERAL_INQUIRY = "general_inquiry"
    EMERGENCY = "emergency"
    GREETING = "greeting"
    GOODBYE = "goodbye"
    CONFIRMATION = "confirmation"
    NEGATION = "negation"
    UNCLEAR = "unclear"

@dataclass
class ExtractedEntities:
    """Extracted entities from user input"""
    name: Optional[str] = None
    date_of_birth: Optional[str] = None
    insurance_provider: Optional[str] = None
    provider_name: Optional[str] = None
    appointment_date: Optional[str] = None
    appointment_time: Optional[str] = None
    phone_number: Optional[str] = None
    email: Optional[str] = None
    reason: Optional[str] = None

@dataclass
class IntentResult:
    """Result of intent analysis"""
    intent: IntentType
    confidence: float
    entities: ExtractedEntities
    original_text: str
    processed_text: str

class NaturalLanguageProcessor:
    """Advanced natural language processing for conversational AI"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
        # Intent patterns with confidence scores
        self.intent_patterns = {
            IntentType.APPOINTMENT_BOOKING: [
                (r'\b(?:i need|i want|i would like|can i|could i|i\'d like)\s+(?:to\s+)?(?:book|schedule|make|get|set up)\s+(?:an?\s+)?(?:appointment|visit|meeting)\b', 0.9),
                (r'\b(?:book|schedule|make|get|set up)\s+(?:an?\s+)?(?:appointment|visit|meeting)\b', 0.8),
                (r'\b(?:i need|i want|i would like)\s+(?:to\s+)?(?:see|visit|meet with)\s+(?:a\s+)?(?:doctor|physician|provider)\b', 0.8),
                (r'\b(?:when can i|what time can i|is there)\s+(?:see|visit|meet with)\s+(?:a\s+)?(?:doctor|physician|provider)\b', 0.7),
                (r'\b(?:i\'m calling|i called)\s+(?:to\s+)?(?:book|schedule|make|get)\s+(?:an?\s+)?(?:appointment|visit)\b', 0.8),
                (r'\b(?:appointment|visit|meeting)\s+(?:for|with|to see)\b', 0.7),
            ],
            IntentType.APPOINTMENT_CANCELLATION: [
                (r'\b(?:i need|i want|i would like)\s+(?:to\s+)?(?:cancel|stop|remove)\s+(?:my\s+)?(?:appointment|visit|meeting)\b', 0.9),
                (r'\b(?:cancel|stop|remove)\s+(?:my\s+)?(?:appointment|visit|meeting)\b', 0.8),
                (r'\b(?:i can\'t make it|i won\'t be able to make it|i need to cancel)\b', 0.7),
                (r'\b(?:something came up|i have a conflict|i need to reschedule)\b', 0.6),
            ],
            IntentType.APPOINTMENT_RESCHEDULING: [
                (r'\b(?:i need|i want|i would like)\s+(?:to\s+)?(?:reschedule|change|move|postpone)\s+(?:my\s+)?(?:appointment|visit|meeting)\b', 0.9),
                (r'\b(?:reschedule|change|move|postpone)\s+(?:my\s+)?(?:appointment|visit|meeting)\b', 0.8),
                (r'\b(?:can i change|can we change|is it possible to change)\s+(?:my\s+)?(?:appointment|visit|meeting)\b', 0.7),
                (r'\b(?:i want to reschedule|i need to reschedule|i\'d like to reschedule)\b', 0.9),
            ],
            IntentType.INSURANCE_INQUIRY: [
                (r'\b(?:insurance|coverage|benefits|claim|authorization|pre-authorization)\b', 0.8),
                (r'\b(?:i\'m calling about|i need help with|i have questions about)\s+(?:my\s+)?(?:insurance|coverage|benefits)\b', 0.9),
                (r'\b(?:does my insurance|will my insurance|is this covered)\b', 0.8),
            ],
            IntentType.DOCTOR_INQUIRY: [
                (r'\b(?:i\'m a doctor|i\'m calling from|this is dr\.|physician calling)\b', 0.9),
                (r'\b(?:medical records|patient information|referral|consultation)\b', 0.8),
                (r'\b(?:i need to speak with|i need to talk to)\s+(?:a\s+)?(?:doctor|physician|medical staff)\b', 0.7),
            ],
            IntentType.EMERGENCY: [
                (r'\b(?:emergency|urgent|help|911|ambulance|heart attack|stroke|chest pain|can\'t breathe)\b', 0.9),
                (r'\b(?:i need help|this is an emergency|it\'s urgent|i\'m having)\b', 0.8),
            ],
            IntentType.GREETING: [
                (r'\b(?:hello|hi|hey|good morning|good afternoon|good evening)\b', 0.8),
                (r'\b(?:how are you|how\'s it going|how can you help)\b', 0.6),
            ],
            IntentType.GOODBYE: [
                (r'\b(?:goodbye|bye|see you|thank you|thanks|that\'s all|nothing else)\b', 0.8),
                (r'\b(?:i\'m done|that\'s it|no more questions|all set)\b', 0.7),
            ],
            IntentType.CONFIRMATION: [
                (r'\b(?:yes|yeah|yep|sure|okay|ok|correct|right|that\'s right|exactly)\b', 0.8),
                (r'\b(?:sounds good|perfect|great|that works|i agree)\b', 0.7),
            ],
            IntentType.NEGATION: [
                (r'\b(?:no|nope|not|don\'t|doesn\'t|won\'t|can\'t|cannot|never|none)\b', 0.8),
                (r'\b(?:that\'s not|that\'s wrong|incorrect|not right)\b', 0.7),
            ],
            IntentType.GENERAL_INQUIRY: [
                (r'\b(?:what|when|where|how|why|who)\b', 0.6),
                (r'\b(?:i have a question|i need help|can you help|do you know)\b', 0.7),
                (r'\b(?:information|details|tell me|explain)\b', 0.6),
                (r'\b(?:what time is my appointment|when is my appointment|what time is my visit)\b', 0.9),
                (r'\b(?:i want to know|i need to know|can you tell me)\s+(?:about|when|what time)\b', 0.7),
            ]
        }
        
        # Entity extraction patterns
        self.name_patterns = [
            r'\b(?:my name is|i\'m|i am|this is|it\'s|it is|call me|i go by|you can call me)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)(?:\s|$|,|\.)',
            r'\b([A-Z][a-z]+\s+[A-Z][a-z]+)\b',  # First Last format
            r'\b(?:i\'m|i am)\s+([A-Z][a-z]+)\b',  # Just first name
        ]
        
        self.dob_patterns = [
            r'\b(?:born|birthday|date of birth|dob)\s+(?:on\s+)?(\d{1,2}/\d{1,2}/\d{4})',
            r'\b(?:born|birthday|date of birth|dob)\s+(?:on\s+)?(\d{1,2}-\d{1,2}-\d{4})',
            r'\b(?:born|birthday|date of birth|dob)\s+(?:on\s+)?(\w+\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4})',
            r'\b(\d{1,2}/\d{1,2}/\d{4})\b',
            r'\b(\w+\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4})\b',
        ]
        
        self.insurance_patterns = [
            r'\b(?:insurance|coverage|provider)\s+(?:is\s+)?([A-Za-z\s]+?)(?:\s|$|,|\.)',
            r'\b(?:i have|my insurance is|i\'m with)\s+([A-Za-z\s]+?)(?:\s|$|,|\.)',
            r'\b([A-Za-z]+)\s+(?:insurance|coverage)\b',
        ]
        
        self.provider_patterns = [
            r'\b(?:doctor|dr\.?|physician|provider)\s+([A-Za-z\s]+?)(?:\s|$|,|\.)',
            r'\b(?:i want to see|i need to see|i\'d like to see)\s+(?:doctor|dr\.?|physician)?\s*([A-Za-z\s]+?)(?:\s|$|,|\.)',
            r'\b(?:with|for)\s+(?:doctor|dr\.?|physician)?\s*([A-Za-z\s]+?)(?:\s|$|,|\.)',
        ]
        
        self.date_patterns = [
            r'\b(?:on\s+)?(\w+\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4})\b',
            r'\b(?:on\s+)?(\d{1,2}/\d{1,2}/\d{4})\b',
            r'\b(?:on\s+)?(\d{1,2}-\d{1,2}-\d{4})\b',
            r'\b(?:tomorrow|today|next week|next month)\b',
            r'\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b',
        ]
        
        self.time_patterns = [
            r'\b(?:at\s+)?(\d{1,2}:\d{2}\s*(?:am|pm|AM|PM))\b',
            r'\b(?:at\s+)?(\d{1,2}\s*(?:am|pm|AM|PM))\b',
            r'\b(?:at\s+)?(\d{1,2}:\d{2})\b',
            r'\b(?:in the\s+)?(?:morning|afternoon|evening)\b',
            r'\b(?:early|late)\s+(?:morning|afternoon|evening)\b',
        ]

    def process_input(self, user_input: str, context: Dict[str, Any] = None) -> IntentResult:
        """
        Process user input and extract intent and entities
        
        Args:
            user_input: Raw user input text
            context: Optional context from previous interactions
            
        Returns:
            IntentResult with intent, confidence, and extracted entities
        """
        if not user_input or not user_input.strip():
            return IntentResult(
                intent=IntentType.UNCLEAR,
                confidence=0.0,
                entities=ExtractedEntities(),
                original_text=user_input,
                processed_text=""
            )
        
        # Clean and normalize input
        processed_text = self._normalize_text(user_input)
        
        # Extract intent
        intent, confidence = self._extract_intent(processed_text, context)
        
        # Extract entities
        entities = self._extract_entities(processed_text, context)
        
        return IntentResult(
            intent=intent,
            confidence=confidence,
            entities=entities,
            original_text=user_input,
            processed_text=processed_text
        )

    def _normalize_text(self, text: str) -> str:
        """Normalize text for processing"""
        # Convert to lowercase
        text = text.lower().strip()
        
        # Remove extra whitespace
        text = re.sub(r'\s+', ' ', text)
        
        # Handle common contractions
        contractions = {
            "i'm": "i am",
            "i'd": "i would",
            "i'll": "i will",
            "i've": "i have",
            "you're": "you are",
            "you'd": "you would",
            "you'll": "you will",
            "you've": "you have",
            "we're": "we are",
            "we'd": "we would",
            "we'll": "we will",
            "we've": "we have",
            "they're": "they are",
            "they'd": "they would",
            "they'll": "they will",
            "they've": "they have",
            "can't": "cannot",
            "won't": "will not",
            "don't": "do not",
            "doesn't": "does not",
            "didn't": "did not",
            "haven't": "have not",
            "hasn't": "has not",
            "hadn't": "had not",
            "isn't": "is not",
            "aren't": "are not",
            "wasn't": "was not",
            "weren't": "were not",
            "it's": "it is",
            "that's": "that is",
            "there's": "there is",
            "here's": "here is",
            "what's": "what is",
            "where's": "where is",
            "when's": "when is",
            "why's": "why is",
            "how's": "how is",
        }
        
        for contraction, expansion in contractions.items():
            text = text.replace(contraction, expansion)
        
        return text

    def _extract_intent(self, text: str, context: Dict[str, Any] = None) -> Tuple[IntentType, float]:
        """Extract intent from text with confidence scoring"""
        best_intent = IntentType.UNCLEAR
        best_confidence = 0.0
        
        for intent_type, patterns in self.intent_patterns.items():
            for pattern, confidence in patterns:
                if re.search(pattern, text, re.IGNORECASE):
                    if confidence > best_confidence:
                        best_intent = intent_type
                        best_confidence = confidence
        
        # Context-aware adjustments
        if context:
            # If we're in a specific flow, adjust confidence
            current_state = context.get('current_state')
            if current_state == 'appointment_booking' and best_intent == IntentType.APPOINTMENT_BOOKING:
                best_confidence = min(1.0, best_confidence + 0.2)
            elif current_state == 'cancellation' and best_intent == IntentType.APPOINTMENT_CANCELLATION:
                best_confidence = min(1.0, best_confidence + 0.2)
        
        return best_intent, best_confidence

    def _extract_entities(self, text: str, context: Dict[str, Any] = None) -> ExtractedEntities:
        """Extract entities from text"""
        entities = ExtractedEntities()
        
        # Extract name
        entities.name = self._extract_name(text)
        
        # Extract date of birth
        entities.date_of_birth = self._extract_date_of_birth(text)
        
        # Extract insurance provider
        entities.insurance_provider = self._extract_insurance_provider(text)
        
        # Extract provider name
        entities.provider_name = self._extract_provider_name(text)
        
        # Extract appointment date
        entities.appointment_date = self._extract_appointment_date(text)
        
        # Extract appointment time
        entities.appointment_time = self._extract_appointment_time(text)
        
        # Extract phone number
        entities.phone_number = self._extract_phone_number(text)
        
        # Extract email
        entities.email = self._extract_email(text)
        
        return entities

    def _extract_name(self, text: str) -> Optional[str]:
        """Extract name from text"""
        for pattern in self.name_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                name = match.group(1).strip()
                # Clean up the name
                name = re.sub(r'[^\w\s]', '', name)
                name = ' '.join(word.capitalize() for word in name.split())
                if len(name) > 1:  # Avoid single characters
                    return name
        return None

    def _extract_date_of_birth(self, text: str) -> Optional[str]:
        """Extract date of birth from text"""
        for pattern in self.dob_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                # Handle patterns with and without groups
                if match.groups():
                    return match.group(1).strip()
                else:
                    return match.group(0).strip()
        return None

    def _extract_insurance_provider(self, text: str) -> Optional[str]:
        """Extract insurance provider from text"""
        for pattern in self.insurance_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                # Handle patterns with and without groups
                if match.groups():
                    provider = match.group(1).strip()
                else:
                    provider = match.group(0).strip()
                # Clean up the provider name
                provider = re.sub(r'[^\w\s]', '', provider)
                provider = ' '.join(word.capitalize() for word in provider.split())
                if len(provider) > 1:
                    return provider
        return None

    def _extract_provider_name(self, text: str) -> Optional[str]:
        """Extract provider name from text"""
        for pattern in self.provider_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                # Handle patterns with and without groups
                if match.groups():
                    provider = match.group(1).strip()
                else:
                    provider = match.group(0).strip()
                # Clean up the provider name
                provider = re.sub(r'[^\w\s]', '', provider)
                provider = ' '.join(word.capitalize() for word in provider.split())
                if len(provider) > 1:
                    return provider
        return None

    def _extract_appointment_date(self, text: str) -> Optional[str]:
        """Extract appointment date from text"""
        for pattern in self.date_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                # Handle patterns with and without groups
                if match.groups():
                    return match.group(1).strip()
                else:
                    return match.group(0).strip()
        return None

    def _extract_appointment_time(self, text: str) -> Optional[str]:
        """Extract appointment time from text"""
        for pattern in self.time_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                # Handle patterns with and without groups
                if match.groups():
                    return match.group(1).strip()
                else:
                    return match.group(0).strip()
        return None

    def _extract_phone_number(self, text: str) -> Optional[str]:
        """Extract phone number from text"""
        phone_pattern = r'\b(?:\+?1[-.\s]?)?\(?([0-9]{3})\)?[-.\s]?([0-9]{3})[-.\s]?([0-9]{4})\b'
        match = re.search(phone_pattern, text)
        if match:
            return f"({match.group(1)}) {match.group(2)}-{match.group(3)}"
        return None

    def _extract_email(self, text: str) -> Optional[str]:
        """Extract email from text"""
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        match = re.search(email_pattern, text)
        if match:
            return match.group(0)
        return None

    def is_confirmation(self, text: str) -> bool:
        """Check if text is a confirmation"""
        confirmation_words = [
            'yes', 'yeah', 'yep', 'sure', 'okay', 'ok', 'correct', 'right', 
            'that\'s right', 'exactly', 'sounds good', 'perfect', 'great', 
            'that works', 'i agree', 'confirmed', 'confirm'
        ]
        return any(word in text.lower() for word in confirmation_words)

    def is_negation(self, text: str) -> bool:
        """Check if text is a negation"""
        negation_words = [
            'no', 'nope', 'not', 'don\'t', 'doesn\'t', 'won\'t', 'can\'t', 
            'cannot', 'never', 'none', 'that\'s not', 'that\'s wrong', 
            'incorrect', 'not right', 'disagree'
        ]
        return any(word in text.lower() for word in negation_words)

    def is_greeting(self, text: str) -> bool:
        """Check if text is a greeting"""
        greeting_words = [
            'hello', 'hi', 'hey', 'good morning', 'good afternoon', 
            'good evening', 'how are you', 'how\'s it going'
        ]
        return any(word in text.lower() for word in greeting_words)

    def is_goodbye(self, text: str) -> bool:
        """Check if text is a goodbye"""
        goodbye_words = [
            'goodbye', 'bye', 'see you', 'thank you', 'thanks', 
            'that\'s all', 'nothing else', 'i\'m done', 'that\'s it', 
            'no more questions', 'all set'
        ]
        return any(word in text.lower() for word in goodbye_words)
