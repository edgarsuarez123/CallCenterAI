"""
Response Templates

This module defines common response templates for all intents in English and Spanish
with appropriate TTLs. Templates use Python string formatting for variable substitution.

Key Features:
- Bilingual support (English/Spanish)
- Template-based variable substitution
- Organized by intent type with appropriate TTLs
- Validation and variable extraction utilities
"""

from typing import Dict, Any, List, Optional, Set
from dataclasses import dataclass
from enum import Enum

# Import enums from the correct location
from services.natural_language_processor import IntentType
from services.bilingual_manager import LanguageCode


@dataclass
class ResponseTemplate:
    """Response template with metadata."""
    template: str
    ttl: int
    variables: List[str]
    description: str


class TemplateTier(Enum):
    """Template TTL tiers."""
    GREETING = 86400      # 24 hours
    QUESTION = 3600       # 1 hour
    SPECIFIC = 300        # 5 minutes


class ResponseTemplates:
    """
    Collection of response templates organized by intent and language.
    
    Provides template-based responses for common conversational patterns
    to reduce token usage and improve response consistency.
    """
    
    def __init__(self):
        self.templates = self._initialize_templates()
    
    def _initialize_templates(self) -> Dict[IntentType, Dict[LanguageCode, ResponseTemplate]]:
        """Initialize all response templates."""
        return {
            IntentType.GREETING: {
                LanguageCode.ENGLISH: ResponseTemplate(
                    template="Hello! Thank you for calling {clinic_name}. How can I help you today?",
                    ttl=TemplateTier.GREETING.value,
                    variables=["clinic_name"],
                    description="Initial greeting when call is answered"
                ),
                LanguageCode.SPANISH: ResponseTemplate(
                    template="¡Hola! Gracias por llamar a {clinic_name}. ¿Cómo puedo ayudarte hoy?",
                    ttl=TemplateTier.GREETING.value,
                    variables=["clinic_name"],
                    description="Saludo inicial cuando se contesta la llamada"
                )
            },
            
            IntentType.APPOINTMENT_BOOKING: {
                LanguageCode.ENGLISH: ResponseTemplate(
                    template="I'd be happy to help you book an appointment. What's your name?",
                    ttl=TemplateTier.QUESTION.value,
                    variables=[],
                    description="Initial appointment booking question"
                ),
                LanguageCode.SPANISH: ResponseTemplate(
                    template="Estaré encantado de ayudarte a reservar una cita. ¿Cuál es tu nombre?",
                    ttl=TemplateTier.QUESTION.value,
                    variables=[],
                    description="Pregunta inicial para reservar cita"
                )
            },
            
            IntentType.APPOINTMENT_INQUIRY: {
                LanguageCode.ENGLISH: ResponseTemplate(
                    template="I can help you with information about your appointment. What's your name?",
                    ttl=TemplateTier.QUESTION.value,
                    variables=[],
                    description="Initial appointment inquiry question"
                ),
                LanguageCode.SPANISH: ResponseTemplate(
                    template="Puedo ayudarte con información sobre tu cita. ¿Cuál es tu nombre?",
                    ttl=TemplateTier.QUESTION.value,
                    variables=[],
                    description="Pregunta inicial para consulta de cita"
                )
            },
            
            IntentType.APPOINTMENT_CANCELLATION: {
                LanguageCode.ENGLISH: ResponseTemplate(
                    template="I can help you cancel your appointment. What's your name?",
                    ttl=TemplateTier.QUESTION.value,
                    variables=[],
                    description="Initial appointment cancellation question"
                ),
                LanguageCode.SPANISH: ResponseTemplate(
                    template="Puedo ayudarte a cancelar tu cita. ¿Cuál es tu nombre?",
                    ttl=TemplateTier.QUESTION.value,
                    variables=[],
                    description="Pregunta inicial para cancelar cita"
                )
            },
            
            IntentType.APPOINTMENT_RESCHEDULING: {
                LanguageCode.ENGLISH: ResponseTemplate(
                    template="I can help you reschedule your appointment. What's your name?",
                    ttl=TemplateTier.QUESTION.value,
                    variables=[],
                    description="Initial appointment rescheduling question"
                ),
                LanguageCode.SPANISH: ResponseTemplate(
                    template="Puedo ayudarte a reprogramar tu cita. ¿Cuál es tu nombre?",
                    ttl=TemplateTier.QUESTION.value,
                    variables=[],
                    description="Pregunta inicial para reprogramar cita"
                )
            },
            
            IntentType.PROVIDER_INQUIRY: {
                LanguageCode.ENGLISH: ResponseTemplate(
                    template="I can help you find information about our providers. Which doctor would you like to see?",
                    ttl=TemplateTier.QUESTION.value,
                    variables=[],
                    description="Provider selection question"
                ),
                LanguageCode.SPANISH: ResponseTemplate(
                    template="Puedo ayudarte a encontrar información sobre nuestros proveedores. ¿Qué doctor te gustaría ver?",
                    ttl=TemplateTier.QUESTION.value,
                    variables=[],
                    description="Pregunta de selección de proveedor"
                )
            },
            
            IntentType.CLINIC_INQUIRY: {
                LanguageCode.ENGLISH: ResponseTemplate(
                    template="I can help you with information about our clinic. What would you like to know?",
                    ttl=TemplateTier.QUESTION.value,
                    variables=[],
                    description="General clinic information question"
                ),
                LanguageCode.SPANISH: ResponseTemplate(
                    template="Puedo ayudarte con información sobre nuestra clínica. ¿Qué te gustaría saber?",
                    ttl=TemplateTier.QUESTION.value,
                    variables=[],
                    description="Pregunta general sobre información de la clínica"
                )
            },
            
            IntentType.BILLING_INQUIRY: {
                LanguageCode.ENGLISH: ResponseTemplate(
                    template="I can help you with billing questions. What's your name or account number?",
                    ttl=TemplateTier.QUESTION.value,
                    variables=[],
                    description="Billing inquiry question"
                ),
                LanguageCode.SPANISH: ResponseTemplate(
                    template="Puedo ayudarte con preguntas de facturación. ¿Cuál es tu nombre o número de cuenta?",
                    ttl=TemplateTier.QUESTION.value,
                    variables=[],
                    description="Pregunta de consulta de facturación"
                )
            },
            
            IntentType.EMERGENCY: {
                LanguageCode.ENGLISH: ResponseTemplate(
                    template="I understand this is an emergency. Please call 911 immediately for life-threatening situations. For urgent medical needs, I can help you find the nearest emergency room.",
                    ttl=TemplateTier.SPECIFIC.value,
                    variables=[],
                    description="Emergency response"
                ),
                LanguageCode.SPANISH: ResponseTemplate(
                    template="Entiendo que esto es una emergencia. Por favor llama al 911 inmediatamente para situaciones que amenacen la vida. Para necesidades médicas urgentes, puedo ayudarte a encontrar la sala de emergencias más cercana.",
                    ttl=TemplateTier.SPECIFIC.value,
                    variables=[],
                    description="Respuesta de emergencia"
                )
            },
            
            IntentType.GENERAL_INQUIRY: {
                LanguageCode.ENGLISH: ResponseTemplate(
                    template="I'm here to help with any questions you might have. What can I assist you with today?",
                    ttl=TemplateTier.QUESTION.value,
                    variables=[],
                    description="General inquiry response"
                ),
                LanguageCode.SPANISH: ResponseTemplate(
                    template="Estoy aquí para ayudar con cualquier pregunta que puedas tener. ¿Con qué puedo ayudarte hoy?",
                    ttl=TemplateTier.QUESTION.value,
                    variables=[],
                    description="Respuesta de consulta general"
                )
            },
            
            IntentType.GOODBYE: {
                LanguageCode.ENGLISH: ResponseTemplate(
                    template="Thank you for calling {clinic_name}! Have a great day!",
                    ttl=TemplateTier.GREETING.value,
                    variables=["clinic_name"],
                    description="Goodbye message"
                ),
                LanguageCode.SPANISH: ResponseTemplate(
                    template="¡Gracias por llamar a {clinic_name}! ¡Que tengas un gran día!",
                    ttl=TemplateTier.GREETING.value,
                    variables=["clinic_name"],
                    description="Mensaje de despedida"
                )
            }
        }
    
    def get_template(
        self, 
        intent: IntentType, 
        language: LanguageCode
    ) -> Optional[ResponseTemplate]:
        """
        Get template for given intent and language.
        
        Args:
            intent: Intent type
            language: Language code
            
        Returns:
            Optional[ResponseTemplate]: Template if found, None otherwise
        """
        return self.templates.get(intent, {}).get(language)
    
    def has_template(self, intent: IntentType, language: LanguageCode) -> bool:
        """
        Check if template exists for given intent and language.
        
        Args:
            intent: Intent type
            language: Language code
            
        Returns:
            bool: True if template exists, False otherwise
        """
        return intent in self.templates and language in self.templates[intent]
    
    def get_required_variables(self, intent: IntentType, language: LanguageCode) -> List[str]:
        """
        Get list of required variables for template.
        
        Args:
            intent: Intent type
            language: Language code
            
        Returns:
            List[str]: List of required variable names
        """
        template = self.get_template(intent, language)
        return template.variables if template else []
    
    def substitute_variables(
        self, 
        intent: IntentType, 
        language: LanguageCode, 
        variables: Dict[str, Any]
    ) -> Optional[str]:
        """
        Substitute variables in template and return final response.
        
        Args:
            intent: Intent type
            language: Language code
            variables: Variables to substitute
            
        Returns:
            Optional[str]: Substituted response if template exists, None otherwise
        """
        template = self.get_template(intent, language)
        if not template:
            return None
        
        try:
            # Validate required variables
            missing_vars = set(template.variables) - set(variables.keys())
            if missing_vars:
                raise ValueError(f"Missing required variables: {missing_vars}")
            
            # Substitute variables
            return template.template.format(**variables)
            
        except KeyError as e:
            raise ValueError(f"Missing variable in template: {e}")
        except Exception as e:
            raise ValueError(f"Error substituting template variables: {e}")
    
    def get_all_intents(self) -> List[IntentType]:
        """
        Get list of all intents that have templates.
        
        Returns:
            List[IntentType]: List of intents with templates
        """
        return list(self.templates.keys())
    
    def get_supported_languages(self, intent: IntentType) -> List[LanguageCode]:
        """
        Get list of supported languages for given intent.
        
        Args:
            intent: Intent type
            
        Returns:
            List[LanguageCode]: List of supported languages
        """
        return list(self.templates.get(intent, {}).keys())
    
    def get_template_statistics(self) -> Dict[str, Any]:
        """
        Get statistics about available templates.
        
        Returns:
            Dict[str, Any]: Template statistics
        """
        total_templates = 0
        intents_with_templates = 0
        language_coverage = {}
        
        for intent, languages in self.templates.items():
            intents_with_templates += 1
            total_templates += len(languages)
            
            for language in languages:
                if language not in language_coverage:
                    language_coverage[language] = 0
                language_coverage[language] += 1
        
        return {
            "total_templates": total_templates,
            "intents_with_templates": intents_with_templates,
            "language_coverage": language_coverage,
            "average_templates_per_intent": total_templates / max(intents_with_templates, 1)
        }
    
    def validate_template_variables(
        self, 
        intent: IntentType, 
        language: LanguageCode, 
        variables: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Validate variables against template requirements.
        
        Args:
            intent: Intent type
            language: Language code
            variables: Variables to validate
            
        Returns:
            Dict[str, Any]: Validation results
        """
        template = self.get_template(intent, language)
        if not template:
            return {
                "valid": False,
                "error": f"No template found for {intent.value}:{language.value}"
            }
        
        required_vars = set(template.variables)
        provided_vars = set(variables.keys())
        
        missing_vars = required_vars - provided_vars
        extra_vars = provided_vars - required_vars
        
        return {
            "valid": len(missing_vars) == 0,
            "missing_variables": list(missing_vars),
            "extra_variables": list(extra_vars),
            "required_variables": template.variables,
            "provided_variables": list(variables.keys())
        }


# Global instance
_response_templates: Optional[ResponseTemplates] = None


def get_response_templates() -> ResponseTemplates:
    """
    Get global response templates instance.
    
    Returns:
        ResponseTemplates: Global templates instance
    """
    global _response_templates
    if _response_templates is None:
        _response_templates = ResponseTemplates()
    return _response_templates
