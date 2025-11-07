from typing import Optional, Dict
from sqlalchemy.orm import Session
from models.models import Clinic
from services.structured_logging import get_logger, LogCategory

logger = get_logger("phone_routing")

class PhoneRoutingService:
    """Maps phone numbers to clinics."""
    
    def __init__(self, db: Session):
        self.db = db
        self._phone_to_clinic_cache: Dict[str, str] = {}
    
    def get_clinic_by_phone(self, phone_number: str) -> Optional[str]:
        """
        Get clinic ID from phone number.
        
        Args:
            phone_number: The called phone number
            
        Returns:
            Clinic ID or None if not found
        """
        # Validate input
        if not phone_number or not isinstance(phone_number, str) or not phone_number.strip():
            logger.warning(f"Invalid phone number provided: {phone_number}", LogCategory.ROUTING)
            return None
        
        # Normalize phone number (remove spaces, dashes, parentheses)
        normalized_phone = phone_number.strip().replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
        
        # Check cache first
        if normalized_phone in self._phone_to_clinic_cache:
            return self._phone_to_clinic_cache[normalized_phone]
        
        # Query database (with error handling)
        try:
            clinic = self.db.query(Clinic).filter(
                Clinic.phone_number == phone_number,
                Clinic.is_deleted == 'no'
            ).first()
            
            if clinic and clinic.clinic_id:
                self._phone_to_clinic_cache[normalized_phone] = clinic.clinic_id
                logger.info(f"Mapped phone {phone_number} to clinic {clinic.clinic_id}", LogCategory.ROUTING)
                return clinic.clinic_id
        except Exception as e:
            logger.error(f"Error querying clinic for phone {phone_number}: {e}", LogCategory.ROUTING, exception=e)
            return None
        
        logger.warning(f"No clinic found for phone {phone_number}", LogCategory.ROUTING)
        return None
    
    def clear_cache(self):
        """Clear the phone-to-clinic cache."""
        self._phone_to_clinic_cache.clear()

def get_phone_routing_service(db: Session) -> PhoneRoutingService:
    """Get phone routing service instance."""
    return PhoneRoutingService(db)
