"""
Intelligent Response Router Service

Automatically routes user input to either scripted responses (TextSource) 
or AI-generated responses (WebSocket) based on question type and complexity.

Goal: Minimize OpenAI token usage while maintaining conversational quality.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Tuple, List
from dataclasses import dataclass

from services.structured_logging import get_logger, LogCategory
from services.natural_language_processor import IntentType
from services.call_orchestrator import CallContext
from services.bilingual_manager import LanguageCode

logger = get_logger("response_router")


@dataclass
class RouterResponseResult:
    """Result of response routing decision."""
    text: str
    is_scripted: bool
    template_key: Optional[str] = None
    tokens_used: int = 0


class ResponseRouter:
    """Automatically routes to scripted or AI responses based on question type."""
    
    # Pattern matching for scripted responses
    SCRIPTED_PATTERNS = {
        "office_hours": ["hours", "open", "closed", "when", "schedule"],
        "location": ["address", "location", "where", "directions"],
        "contact": ["phone", "call", "contact", "number"],
        "services": ["services", "offer", "provide", "what do you do"],
        "greeting": ["hello", "hi", "help", "assistance"],
        "appointment_start": ["appointment", "schedule", "book", "make an appointment"],
        "appointment_confirm": ["confirm", "yes", "correct", "that's right"],
        "transfer": ["speak to", "talk to", "human", "person", "staff"],
        "insurance": ["insurance", "coverage", "benefits", "copay"],
        "prescription": ["prescription", "refill", "medication", "medicine"],
    }
    
    # Scripted response templates with variable substitution
    SCRIPTED_TEMPLATES = {
        "office_hours": "Our office hours are {hours}. We are open {days}.",
        "location": "We are located at {address}. {directions}",
        "contact": "You can reach us at {phone}. Our main number is {phone}.",
        "services": "We offer {services}. Our main services include {main_services}.",
        "greeting": "Welcome to {clinic_name}. How can I help you today?",
        "appointment_start": "I can help you schedule an appointment. What type of appointment do you need?",
        "appointment_confirm": "Your appointment is scheduled for {date} at {time}. Is there anything else I can help you with?",
        "transfer": "Let me transfer you to a staff member who can assist you further.",
        "insurance": "We accept most major insurance plans including {insurance_plans}. Please have your insurance card ready.",
        "prescription": "For prescription refills, please call our pharmacy at {pharmacy_phone} or use our online portal.",
    }
    
    # Keywords that require dynamic data lookup
    DYNAMIC_DATA_KEYWORDS = [
        "available", "slots", "appointment times", "next available",
        "provider schedule", "doctor available", "when can i see",
        "availability", "free time", "open slots"
    ]
    
    def __init__(self):
        """Initialize the response router."""
        self.logger = logger
    
    async def get_response(
        self,
        user_input: str,
        intent: IntentType,
        call_context: CallContext,
        clinic_config: Dict[str, Any]
    ) -> RouterResponseResult:
        """
        Automatically determine response type and generate response.
        
        Args:
            user_input: User's spoken or typed input
            intent: Classified intent from NLP service
            call_context: Current call context
            clinic_config: Clinic-specific configuration data
            
        Returns:
            RouterResponseResult: Contains response text, scripted flag, and metadata
        """
        # Validate inputs
        if not user_input or not user_input.strip():
            self.logger.warning("Empty user_input in get_response", LogCategory.NLP)
            return RouterResponseResult(
                text="I'm sorry, I didn't catch that. Could you please repeat?",
                is_scripted=True,
                tokens_used=0
            )
        
        try:
            # Safely truncate user_input for logging
            input_preview = user_input[:50] if len(user_input) > 50 else user_input
            self.logger.info(
                f"Routing response for input: '{input_preview}...'",
                LogCategory.NLP,
                extra_data={
                    "intent": intent.value if intent else None,
                    "language": call_context.language.value if call_context.language else None,
                    "clinic_id": call_context.clinic_id
                }
            )
            
            # Issue 98: Pass context to pattern matching for context-aware matching
            template_key = self._match_scripted_pattern(user_input, context=call_context)
            
            if template_key:
                # Use scripted response (0 tokens)
                response_text = self._generate_scripted_response(template_key, clinic_config)
                self.logger.info(
                    f"Using scripted response for pattern: {template_key}",
                    LogCategory.NLP,
                    extra_data={"template_key": template_key}
                )
                return RouterResponseResult(
                    text=response_text,
                    is_scripted=True,
                    template_key=template_key,
                    tokens_used=0
                )
            
            # Check if requires dynamic data (Google Calendar, etc.)
            if self._requires_dynamic_data(user_input):
                response_text = await self._generate_dynamic_response(
                    user_input, call_context, clinic_config
                )
                self.logger.info(
                    "Using dynamic data response",
                    LogCategory.NLP,
                    extra_data={"tokens_used": "~50"}
                )
                return RouterResponseResult(
                    text=response_text,
                    is_scripted=False,
                    tokens_used=50  # Estimated for calendar queries
                )
            
            # Default to AI for complex questions
            response_text = await self._generate_ai_response(user_input, call_context)
            self.logger.info(
                "Using AI-generated response",
                LogCategory.NLP,
                extra_data={"tokens_used": "~200"}
            )
            return RouterResponseResult(
                text=response_text,
                is_scripted=False,
                tokens_used=200  # Estimated for complex AI responses
            )
            
        except Exception as e:
            self.logger.error(f"Error in response routing: {e}", exc_info=True)
            # Fallback to generic scripted response
            return RouterResponseResult(
                text="I'm sorry, I didn't understand that. Could you please repeat?",
                is_scripted=True,
                template_key="greeting",
                tokens_used=0
            )
    
    def _match_scripted_pattern(self, user_input: str, context: Optional[CallContext] = None) -> Optional[str]:
        """Check if input matches known scripted patterns with context awareness."""
        user_lower = user_input.lower()
        
        # Issue 98: Consider conversation context when matching patterns
        # Get conversation history from context if available
        conversation_context = []
        if context and hasattr(context, 'conversation_history'):
            conversation_context = context.conversation_history[-5:] if len(context.conversation_history) > 5 else context.conversation_history
        
        # Issue 98: Check context for appointment-related keywords
        in_appointment_flow = False
        if conversation_context:
            for msg in conversation_context:
                content = msg.get('content', '').lower() if isinstance(msg, dict) else str(msg).lower()
                if any(word in content for word in ['appointment', 'book', 'schedule', 'cita', 'agendar']):
                    in_appointment_flow = True
                    break
        
        # Define context-aware patterns to avoid false matches
        context_patterns = {
            "office_hours": {
                "keywords": ["hours", "open", "closed", "when"],
                "exclude": ["appointment", "schedule", "book", "meeting"]
            },
            "location": {
                "keywords": ["address", "location", "where"],
                "exclude": ["phone", "number", "call"]
            },
            "contact": {
                "keywords": ["phone", "call", "contact", "number"],
                "exclude": ["address", "location", "where"]
            },
            "services": {
                "keywords": ["services", "offer", "provide"],
                "exclude": ["appointment", "schedule", "book"]
            },
            "greeting": {
                "keywords": ["hello", "hi", "hey", "welcome"],
                "exclude": []
            },
            "confirmation": {
                "keywords": ["yes", "no", "confirm", "correct"],
                "exclude": [],
                # Issue 98: In appointment flow, "yes" likely means confirmation, not greeting
                "context_check": lambda ctx, in_flow=in_appointment_flow, user_lower_check=user_lower: in_flow if 'yes' in user_lower_check else True
            },
            "general_faq": {
                "keywords": ["what is", "how do i", "tell me about"],
                "exclude": ["appointment", "schedule", "book", "phone", "address"]
            }
        }
        
        # Issue 98: Check for context-aware matches with scoring
        scores = {}
        for key, config in context_patterns.items():
            # Issue 98: Check context-specific conditions
            context_check = config.get("context_check")
            if context_check and not context_check(context):
                continue  # Skip this pattern if context check fails
            
            # Count matching keywords
            keyword_matches = sum(1 for keyword in config["keywords"] if keyword in user_lower)
            
            # Check for exclusion keywords
            exclusion_matches = sum(1 for exclude in config["exclude"] if exclude in user_lower)
            
            # Score based on keyword matches minus exclusions
            if keyword_matches > 0 and exclusion_matches == 0:
                scores[key] = keyword_matches
        
        if not scores or len(scores) == 0:
            return None
        
        # Return pattern with highest score (with validation)
        try:
            max_item = max(scores.items(), key=lambda x: x[1])
            return max_item[0] if max_item else None
        except ValueError:
            # Empty scores dict
            return None
    
    def _generate_scripted_response(self, template_key: str, config: Dict[str, Any]) -> str:
        """Generate scripted response with variable substitution."""
        # Validate template_key
        if not template_key or template_key not in self.SCRIPTED_TEMPLATES:
            self.logger.warning(f"Invalid template_key: {template_key}", LogCategory.NLP)
            return "I can help you with that."
        
        template = self.SCRIPTED_TEMPLATES.get(template_key, "I can help you with that.")
        
        # Default values for missing config
        defaults = {
            "clinic_name": "our clinic",
            "hours": "Monday-Friday 9AM-5PM",
            "days": "Monday through Friday",
            "address": "our main location",
            "directions": "",
            "phone": "our main number",
            "services": "comprehensive healthcare services",
            "main_services": "general medicine, preventive care, and specialized treatments",
            "insurance_plans": "Blue Cross, Aetna, Cigna, and Medicare",
            "pharmacy_phone": "our pharmacy",
            "date": "",
            "time": ""
        }
        
        # Issue 99: Validate that required variables are present
        # Merge config with defaults
        merged_config = {**defaults, **config}
        
        # Issue 99: Check for required variables in template
        import re
        required_vars = set(re.findall(r'\{(\w+)\}', template))
        missing_vars = required_vars - set(merged_config.keys())
        
        if missing_vars:
            # Issue 99: Log missing variables and use defaults
            self.logger.warning(
                f"Missing template variables {missing_vars} for {template_key}, using defaults",
                LogCategory.NLP
            )
            # Add missing variables with context-appropriate defaults
            for var in missing_vars:
                if var in defaults:
                    merged_config[var] = defaults[var]
                else:
                    # Issue 99: Use context-appropriate default
                    merged_config[var] = "information"  # Generic default
        
        try:
            return template.format(**merged_config)
        except KeyError as e:
            # Issue 99: Handle missing variables gracefully
            missing_var = str(e).strip("'\"")
            self.logger.warning(f"Missing template variable '{missing_var}' for {template_key}, using default")
            # Issue 99: Return template with placeholders replaced with defaults
            default_value = merged_config.get(missing_var, "information")
            return template.replace(f"{{{missing_var}}}", default_value)
    
    def _requires_dynamic_data(self, user_input: str) -> bool:
        """Check if question requires dynamic data lookup."""
        user_lower = user_input.lower()
        return any(keyword in user_lower for keyword in self.DYNAMIC_DATA_KEYWORDS)
    
    async def _generate_dynamic_response(
        self, user_input: str, context: CallContext, config: Dict[str, Any]
    ) -> str:
        """Generate response with dynamic data (calendar, etc.)."""
        try:
            # Query Google Calendar for availability
            from services.google_calendar_service import get_google_calendar_service
            calendar_service = get_google_calendar_service()
            
            # Get available slots for the next week
            start_date = datetime.now()
            end_date = start_date + timedelta(days=7)
            
            # Use metadata to store provider info (with validation)
            provider_id = context.metadata.get('provider_id') if context.metadata else None
            if not provider_id:
                self.logger.warning("provider_id not found in context metadata", LogCategory.NLP)
                return "I can help you check availability. Please provide a provider name."
            
            # Issue 58: Validate provider exists in database
            try:
                from services.database import get_db_session
                with get_db_session() as db:
                    from models.models import Provider
                    provider = db.query(Provider).filter_by(provider_id=provider_id).first()
                    if not provider:
                        self.logger.warning(f"Provider {provider_id} not found in database", LogCategory.NLP)
                        return "I can help you check availability. Please provide a valid provider name."
            except Exception as db_error:
                self.logger.error(f"Failed to validate provider: {db_error}")
                # Continue with provider_id even if validation fails
            
            provider_name = context.metadata.get('provider_name', 'our provider') if context.metadata else 'our provider'
            
            # Validate dates
            if not start_date or not end_date:
                self.logger.warning("Invalid dates for availability check", LogCategory.NLP)
                return "I can help you check availability. Please provide a date range."
            
            if end_date < start_date:
                self.logger.warning("end_date is before start_date", LogCategory.NLP)
                return "I can help you check availability. Please provide a valid date range."
            
            # Issue 59: Handle calendar service errors specifically
            try:
                available_slots = await calendar_service.get_available_slots(
                    provider_id=provider_id,
                    start_date=start_date,
                    end_date=end_date
                )
            except Exception as calendar_error:
                # Issue 59: Handle calendar service errors specifically
                error_type = type(calendar_error).__name__
                if 'authentication' in str(calendar_error).lower() or 'auth' in str(calendar_error).lower():
                    self.logger.error(f"Calendar authentication error: {calendar_error}", LogCategory.NLP)
                    return "I'm sorry, I'm having trouble accessing the calendar. Please contact our staff for availability."
                elif 'network' in str(calendar_error).lower() or 'connection' in str(calendar_error).lower():
                    self.logger.error(f"Calendar network error: {calendar_error}", LogCategory.NLP)
                    return "I'm sorry, I'm having trouble connecting to the calendar. Please try again later."
                else:
                    self.logger.error(f"Calendar service error: {calendar_error}", LogCategory.NLP)
                    return "I'm sorry, I'm having trouble checking availability. Please contact our staff."
            
            # Use AI to format slots naturally with context
            from services.azure_openai_service import get_azure_openai_service
            openai_service = get_azure_openai_service()
            
            # Issue 60: Extract entities from context and pass them to generate_response
            entities = []
            if context.entities:
                entities = context.entities
            elif context.metadata and 'entities' in context.metadata:
                entities = context.metadata['entities']
            
            response_result = await openai_service.generate_response(
                user_input=user_input,
                call_id=context.call_id,
                language=context.language,
                intent=context.current_intent,
                entities=entities if entities else None  # Issue 60: Pass entities
            )
            
            if not response_result or not response_result.response_text:
                self.logger.warning("Empty response from OpenAI service", LogCategory.NLP)
                return "I can help you check availability. Please hold while I look that up."
            
            return response_result.response_text
            
        except Exception as e:
            self.logger.error(f"Error generating dynamic response: {e}")
            # Fallback to generic availability message
            return "I can help you check availability. Please hold while I look that up."
    
    async def _generate_ai_response(
        self, user_input: str, context: CallContext
    ) -> str:
        """Generate AI response for complex questions."""
        try:
            from services.azure_openai_service import get_azure_openai_service
            openai_service = get_azure_openai_service()
            # Issue 60: Extract entities from context and pass them to generate_response
            entities = []
            if context.entities:
                entities = context.entities
            elif context.metadata and 'entities' in context.metadata:
                entities = context.metadata['entities']
            
            response_result = await openai_service.generate_response(
                user_input=user_input,
                call_id=context.call_id,
                language=context.language,
                intent=context.current_intent,
                entities=entities if entities else None  # Issue 60: Pass entities
            )
            
            if not response_result or not response_result.response_text:
                self.logger.warning("Empty response from OpenAI service", LogCategory.NLP)
                return "I'm sorry, I'm having trouble processing that request. Could you please try again?"
            
            return response_result.response_text
        except Exception as e:
            self.logger.error(f"Error generating AI response: {e}")
            return "I'm sorry, I'm having trouble processing that request. Could you please try again?"


# Singleton instance
_response_router: Optional[ResponseRouter] = None


def get_response_router() -> ResponseRouter:
    """Get the global ResponseRouter instance."""
    global _response_router
    if _response_router is None:
        _response_router = ResponseRouter()
    return _response_router
