"""
Demo Setup Script
Creates demo data for the CallCenterAI system including clinic, providers, and appointment slots.
"""

from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import logging
import random

from services.database import SessionLocal, engine
from services.clinic_management import ClinicManagementService
from services.provider_management import ProviderManagementService
from models.models import Base
from models.schemas import (
    ClinicCreateRequest, ProviderCreateRequest, 
    AppointmentSlotCreateRequest
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_custom_clinic(db: Session) -> str:
    """Create a new clinic with unique clinic_id. Each run creates a new clinic."""
    clinic_service = ClinicManagementService(db)
    
    # Always create a new clinic (removed existing clinic check)
    # Each run will create a new clinic with a unique clinic_id
    
    # ============================================================================
    # CUSTOMIZE YOUR CLINIC INFORMATION HERE
    # ============================================================================
    # Generate unique phone number for each clinic using UUID
    import uuid
    uuid_suffix = str(uuid.uuid4()).replace('-', '')[:10]  # First 10 chars of UUID
    unique_phone = f"+1{uuid_suffix}"
    
    clinic_data = ClinicCreateRequest(
        clinic_name="St Peters Medical",  # Change this to your clinic name
        phone_number=unique_phone,  # Unique phone number for each clinic
        timezone="America/New_York",  # Change this to your timezone
        default_language="en",  # Change this to your default language
        supported_languages="en,es",  # Change this to your supported languages
        ehr_system="Google Calendar",  # Keep this for Google Calendar integration
        ehr_api_endpoint=None,  # Optional: your EHR API endpoint
        ehr_credentials_vault_key=None,  # Optional: your EHR credentials vault key
        max_concurrent_calls=10,  # Change this to your max concurrent calls
        queue_timeout_seconds=45,  # Change this to your queue timeout
        subscription_tier="professional"  # Change this to your subscription tier
    )
    
    try:
        clinic = clinic_service.create_clinic(clinic_data)
        logger.info(f"Created new clinic: {clinic.clinic_id} with phone: {unique_phone}")
        return clinic.clinic_id
    except Exception as e:
        logger.error(f"Failed to create clinic: {str(e)}")
        raise


def create_custom_providers(db: Session, clinic_id: str) -> list:
    """Create your custom providers. Modify the providers_data below to match your providers."""
    provider_service = ProviderManagementService(db)
    
    # ============================================================================
    # CUSTOMIZE YOUR PROVIDERS HERE
    # Add, remove, or modify providers as needed
    # ============================================================================
    providers_data = [
        {
            "name_token": "Dr. Miriam Rivera",  # Change this to your provider's name
            "title": "Dr.",  # Dr., Mr., Ms., etc.
            "specialty": "Family Medicine",  # Change this to their specialty
            "email": "dr.smith@yourclinic.com"  # Change this to their email
        },
        {
            "name_token": "Dr. Jane Doe",  # Add more providers as needed
            "title": "Dr.",
            "specialty": "Cardiology",
            "email": "dr.doe@yourclinic.com"
        },
        {
            "name_token": "Dr. Robert Johnson",  # Add more providers as needed
            "title": "Dr.",
            "specialty": "Pediatrics",
            "email": "dr.johnson@yourclinic.com"
        }
        # Add more providers here if needed
        # {
        #     "name_token": "Dr. Another Provider",
        #     "title": "Dr.",
        #     "specialty": "Dermatology",
        #     "email": "dr.another@yourclinic.com"
        # }
    ]
    
    created_providers = []
    
    for provider_data in providers_data:
        try:
            provider_request = ProviderCreateRequest(
                name_token=provider_data["name_token"],
                title=provider_data["title"],
                specialty=provider_data["specialty"],
                email=provider_data["email"]
            )
            
            provider = provider_service.add_provider(clinic_id, provider_request)
            created_providers.append(provider)
            logger.info(f"Created provider: {provider.provider_id} - {provider.name_token}")
            
        except Exception as e:
            logger.error(f"Failed to create provider {provider_data['name_token']}: {str(e)}")
    
    return created_providers


def create_demo_appointment_slots(db: Session, providers: list, clinic_id: str):
    """Create demo appointment slots for business hours (9 AM to 5 PM, Monday to Friday) for the entire year."""
    provider_service = ProviderManagementService(db)
    
    # Create slots for the entire year (365 days)
    start_date = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    end_date = start_date + timedelta(days=365)  # One year from tomorrow
    
    total_slots_created = 0
    
    for provider in providers:
        logger.info(f"Creating appointment slots for {provider.name_token} for the entire year")
        provider_slots = 0
        
        # Create slots for each day
        current_date = start_date
        while current_date < end_date:
            # Skip weekends (Saturday=5, Sunday=6)
            if current_date.weekday() < 5:  # Monday=0, Friday=4
                # Create slots from 9 AM to 5 PM (Monday to Friday)
                # 9:00, 9:30, 10:00, 10:30, 11:00, 11:30, 12:00, 12:30, 1:00, 1:30, 2:00, 2:30, 3:00, 3:30, 4:00, 4:30
                for hour in range(9, 17):  # 9 AM to 5 PM (17:00)
                    for minute in [0, 30]:  # Every 30 minutes
                        slot_time = current_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
                        
                        try:
                            slot_request = AppointmentSlotCreateRequest(
                                provider_id=provider.provider_id,
                                slot_datetime=slot_time,
                                duration_minutes=30,
                                clinic_id=clinic_id
                            )
                            
                            slot = provider_service.create_appointment_slot(slot_request)
                            provider_slots += 1
                            total_slots_created += 1
                            
                            # Log progress every 100 slots
                            if provider_slots % 100 == 0:
                                logger.info(f"Created {provider_slots} slots for {provider.name_token} up to {current_date.strftime('%Y-%m-%d')}")
                            
                        except Exception as e:
                            logger.error(f"Failed to create slot for {provider.name_token} at {slot_time}: {str(e)}")
            
            # Move to next day
            current_date += timedelta(days=1)
        
        logger.info(f"Finished creating {provider_slots} slots for {provider.name_token}")
    
    logger.info(f"Finished creating {total_slots_created} total appointment slots for the year")


# Note: Patients are created dynamically when they call the system
# The AI will collect their information and create patient records automatically


def main():
    """Main setup function."""
    logger.info("Starting custom clinic setup...")
    
    # Create database tables
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created/verified")
    
    # Create database session
    db = SessionLocal()
    
    try:
        # Create custom clinic
        logger.info("Creating custom clinic...")
        clinic_id = create_custom_clinic(db)
        
        # Create custom providers
        logger.info("Creating custom providers...")
        providers = create_custom_providers(db, clinic_id)
        
        # Create appointment slots for the entire year
        logger.info("Creating appointment slots for the entire year...")
        create_demo_appointment_slots(db, providers, clinic_id)
        
        logger.info("Custom clinic setup completed successfully!")
        logger.info(f"Clinic ID: {clinic_id}")
        logger.info(f"Created {len(providers)} providers")
        logger.info("Created appointment slots for the entire year")
        logger.info("Patients will be created automatically when they call")
        
    except Exception as e:
        logger.error(f"Clinic setup failed: {str(e)}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
