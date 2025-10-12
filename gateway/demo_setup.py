"""
Demo Setup Script
Creates demo data for the CallCenterAI system including clinic, providers, and appointment slots.
"""

from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import logging

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


def create_demo_clinic(db: Session) -> str:
    """Create demo clinic for St. Peters Medical."""
    clinic_service = ClinicManagementService(db)
    
    # Try to find existing clinic first
    from models.models import Clinic
    existing_clinic = db.query(Clinic).first()
    if existing_clinic:
        logger.info(f"Found existing clinic: {existing_clinic.clinic_id}")
        return existing_clinic.clinic_id
    
    clinic_data = ClinicCreateRequest(
        clinic_name="St. Peters Medical Center",
        address="123 Medical Drive, Orlando, FL 32801",
        phone_number="+14071234567",
        email="info@stpetersmedical.com",
        timezone="America/New_York",
        ehr_system="Google Calendar",
        business_hours={
            "monday": {"open": "08:00", "close": "17:00"},
            "tuesday": {"open": "08:00", "close": "17:00"},
            "wednesday": {"open": "08:00", "close": "17:00"},
            "thursday": {"open": "08:00", "close": "17:00"},
            "friday": {"open": "08:00", "close": "17:00"},
            "saturday": {"open": "09:00", "close": "13:00"},
            "sunday": {"open": "closed", "close": "closed"}
        },
        emergency_keywords=["emergency", "urgent", "chest pain", "can't breathe", "severe pain"],
        ai_model_settings={
            "model": "gpt-4",
            "temperature": 0.7,
            "max_tokens": 500
        },
        subscription_status="active"
    )
    
    try:
        clinic = clinic_service.create_clinic(clinic_data)
        logger.info(f"Created demo clinic: {clinic.clinic_id}")
        return clinic.clinic_id
    except Exception as e:
        logger.error(f"Failed to create clinic: {str(e)}")
        raise


def create_demo_providers(db: Session, clinic_id: str) -> list:
    """Create demo providers for the clinic."""
    provider_service = ProviderManagementService(db)
    
    providers_data = [
        {
            "name_token": "Dr. Sarah Johnson",
            "title": "Dr.",
            "specialty": "Family Medicine",
            "phone": "+14071234568",
            "email": "sarah.johnson@stpetersmedical.com",
            "is_available": "yes"
        },
        {
            "name_token": "Dr. Michael Smith",
            "title": "Dr.",
            "specialty": "Internal Medicine",
            "phone": "+14071234569",
            "email": "michael.smith@stpetersmedical.com",
            "is_available": "yes"
        },
        {
            "name_token": "Dr. Emily Davis",
            "title": "Dr.",
            "specialty": "Pediatrics",
            "phone": "+14071234570",
            "email": "emily.davis@stpetersmedical.com",
            "is_available": "yes"
        }
    ]
    
    created_providers = []
    
    for provider_data in providers_data:
        try:
            provider_request = ProviderCreateRequest(
                name_token=provider_data["name_token"],
                title=provider_data["title"],
                specialty=provider_data["specialty"]
            )
            
            provider = provider_service.add_provider(clinic_id, provider_request)
            created_providers.append(provider)
            logger.info(f"Created provider: {provider.provider_id} - {provider.name_token}")
            
        except Exception as e:
            logger.error(f"Failed to create provider {provider_data['name_token']}: {str(e)}")
    
    return created_providers


def create_demo_appointment_slots(db: Session, providers: list):
    """Create demo appointment slots for the next 14 days."""
    provider_service = ProviderManagementService(db)
    
    # Create slots for the next 14 days
    start_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    
    for provider in providers:
        logger.info(f"Creating appointment slots for {provider.name_token}")
        
        # Create slots for each day
        for day_offset in range(14):
            current_date = start_date + timedelta(days=day_offset)
            
            # Skip Sundays (day 6)
            if current_date.weekday() == 6:
                continue
            
            # Create slots from 9 AM to 4 PM (30-minute slots)
            for hour in range(9, 16):
                slot_time = current_date.replace(hour=hour, minute=0, second=0, microsecond=0)
                
                try:
                    slot_request = AppointmentSlotCreateRequest(
                        provider_id=provider.provider_id,
                        slot_datetime=slot_time,
                        duration_minutes=30,
                        is_booked="no"
                    )
                    
                    slot = provider_service.create_appointment_slot(slot_request)
                    logger.debug(f"Created slot: {slot.slot_id} at {slot_time}")
                    
                except Exception as e:
                    logger.error(f"Failed to create slot for {provider.name_token} at {slot_time}: {str(e)}")
    
    logger.info("Finished creating appointment slots")


def create_demo_patients(db: Session, clinic_id: str):
    """Create some demo patients for testing."""
    from models.models import Patient
    from services.crypto import make_ulid_token
    
    demo_patients = [
        {
            "name": "John Smith",
            "phone": "+14071234571",
            "email": "john.smith@email.com",
            "dob": "1985-03-15",
            "insurance_provider": "Blue Cross Blue Shield",
            "insurance_member_id": "BC123456789"
        },
        {
            "name": "Jane Doe",
            "phone": "+14071234572",
            "email": "jane.doe@email.com",
            "dob": "1990-07-22",
            "insurance_provider": "Aetna",
            "insurance_member_id": "AET987654321"
        }
    ]
    
    for patient_data in demo_patients:
        try:
            patient = Patient(
                patient_id=f"PATIENT_{make_ulid_token('PATIENT')[:12]}",
                name_token=patient_data["name"],
                phone_token=patient_data["phone"],
                email_token=patient_data["email"],
                dob_token=patient_data["dob"],
                insurance_provider_token=patient_data["insurance_provider"],
                insurance_member_id_token=patient_data["insurance_member_id"],
                insurance_plan_type="PPO"
            )
            
            db.add(patient)
            logger.info(f"Created demo patient: {patient.patient_id} - {patient.name_token}")
            
        except Exception as e:
            logger.error(f"Failed to create patient {patient_data['name']}: {str(e)}")
    
    db.commit()


def main():
    """Main setup function."""
    logger.info("Starting demo setup...")
    
    # Create database tables
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created/verified")
    
    # Create database session
    db = SessionLocal()
    
    try:
        # Create demo clinic
        logger.info("Creating demo clinic...")
        clinic_id = create_demo_clinic(db)
        
        # Create demo providers
        logger.info("Creating demo providers...")
        providers = create_demo_providers(db, clinic_id)
        
        # Create demo appointment slots
        logger.info("Creating demo appointment slots...")
        create_demo_appointment_slots(db, providers)
        
        # Create demo patients
        logger.info("Creating demo patients...")
        create_demo_patients(db, clinic_id)
        
        logger.info("Demo setup completed successfully!")
        logger.info(f"Clinic ID: {clinic_id}")
        logger.info(f"Created {len(providers)} providers")
        logger.info("Created appointment slots for the next 14 days")
        logger.info("Created 2 demo patients")
        
    except Exception as e:
        logger.error(f"Demo setup failed: {str(e)}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
