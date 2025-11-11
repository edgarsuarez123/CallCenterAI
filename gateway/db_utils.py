#!/usr/bin/env python3
"""
Database Utilities Tool
Consolidated tool for database operations including clinic management,
demo setup, and data migrations.

Usage:
    python db_utils.py list-clinics
    python db_utils.py delete-clinic <clinic_id>
    python db_utils.py delete-all-clinics
    python db_utils.py delete-clinics-by-name <name>
    python db_utils.py setup-demo
    python db_utils.py migrate-provider-email
"""

import argparse
import sys
import os
import logging
import uuid
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from sqlalchemy import inspect, text

# Add the current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services.database import SessionLocal, engine
from services.clinic_management import ClinicManagementService
from services.provider_management import ProviderManagementService
from models.models import (
    Base, Clinic, ClinicLicense, SystemConfig, AppointmentSlot, 
    Provider, provider_clinics
)
from models.schemas import (
    ClinicCreateRequest, ProviderCreateRequest, AppointmentSlotCreateRequest
)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')
logger = logging.getLogger(__name__)


# ============================================================================
# Clinic Management Functions
# ============================================================================

def list_clinics():
    """List all clinics in the database."""
    db = SessionLocal()
    try:
        clinics = db.query(Clinic).all()
        logger.info(f"Found {len(clinics)} clinics:")
        for clinic in clinics:
            logger.info(f"  - {clinic.clinic_id}: {clinic.clinic_name} (phone: {clinic.phone_number})")
        return clinics
    finally:
        db.close()


def delete_clinic_by_id(clinic_id: str):
    """Delete a specific clinic by ID."""
    db = SessionLocal()
    try:
        clinic = db.query(Clinic).filter(Clinic.clinic_id == clinic_id).first()
        if not clinic:
            logger.error(f"Clinic {clinic_id} not found")
            return False
        
        logger.info(f"Deleting clinic: {clinic.clinic_id} - {clinic.clinic_name}")
        
        # Delete related records first (foreign key constraints)
        db.query(AppointmentSlot).filter(AppointmentSlot.clinic_id == clinic_id).delete()
        logger.info(f"Deleted appointment slots for clinic {clinic_id}")
        
        db.query(provider_clinics).filter(provider_clinics.c.clinic_id == clinic_id).delete()
        logger.info(f"Deleted provider-clinic associations for clinic {clinic_id}")
        
        db.query(SystemConfig).filter(SystemConfig.config_key.like(f"%{clinic_id}%")).delete()
        logger.info(f"Deleted system configs for clinic {clinic_id}")
        
        db.query(ClinicLicense).filter(ClinicLicense.clinic_id == clinic_id).delete()
        logger.info(f"Deleted license for clinic {clinic_id}")
        
        db.delete(clinic)
        db.commit()
        
        logger.info(f"✅ Successfully deleted clinic {clinic_id}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to delete clinic {clinic_id}: {str(e)}")
        db.rollback()
        return False
    finally:
        db.close()


def delete_all_clinics():
    """Delete all clinics (use with caution!)."""
    db = SessionLocal()
    try:
        clinics = db.query(Clinic).all()
        logger.info(f"Deleting {len(clinics)} clinics...")
        
        for clinic in clinics:
            logger.info(f"Deleting clinic: {clinic.clinic_id} - {clinic.clinic_name}")
            
            db.query(AppointmentSlot).filter(AppointmentSlot.clinic_id == clinic.clinic_id).delete()
            db.query(provider_clinics).filter(provider_clinics.c.clinic_id == clinic.clinic_id).delete()
            db.query(SystemConfig).filter(SystemConfig.config_key.like(f"%{clinic.clinic_id}%")).delete()
            db.query(ClinicLicense).filter(ClinicLicense.clinic_id == clinic.clinic_id).delete()
            db.delete(clinic)
        
        db.commit()
        logger.info(f"✅ Successfully deleted all {len(clinics)} clinics")
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to delete clinics: {str(e)}")
        db.rollback()
        return False
    finally:
        db.close()


def delete_clinics_by_name(clinic_name: str):
    """Delete all clinics with a specific name."""
    db = SessionLocal()
    try:
        clinics = db.query(Clinic).filter(Clinic.clinic_name == clinic_name).all()
        logger.info(f"Found {len(clinics)} clinics with name '{clinic_name}'")
        
        for clinic in clinics:
            logger.info(f"Deleting clinic: {clinic.clinic_id} - {clinic.clinic_name}")
            
            db.query(AppointmentSlot).filter(AppointmentSlot.clinic_id == clinic.clinic_id).delete()
            db.query(provider_clinics).filter(provider_clinics.c.clinic_id == clinic.clinic_id).delete()
            db.query(SystemConfig).filter(SystemConfig.config_key.like(f"%{clinic.clinic_id}%")).delete()
            db.query(ClinicLicense).filter(ClinicLicense.clinic_id == clinic.clinic_id).delete()
            db.delete(clinic)
        
        db.commit()
        logger.info(f"✅ Successfully deleted {len(clinics)} clinics with name '{clinic_name}'")
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to delete clinics: {str(e)}")
        db.rollback()
        return False
    finally:
        db.close()


# ============================================================================
# Demo Setup Functions
# ============================================================================

def create_custom_clinic(db: Session) -> str:
    """Create a new clinic with unique clinic_id."""
    clinic_service = ClinicManagementService(db)
    
    uuid_suffix = str(uuid.uuid4()).replace('-', '')[:10]
    unique_phone = f"+1{uuid_suffix}"
    
    clinic_data = ClinicCreateRequest(
        clinic_name="St Peters Medical",
        phone_number=unique_phone,
        timezone="America/New_York",
        default_language="en",
        supported_languages="en,es",
        ehr_system="Google Calendar",
        ehr_api_endpoint=None,
        ehr_credentials_vault_key=None,
        max_concurrent_calls=10,
        queue_timeout_seconds=45,
        subscription_tier="professional"
    )
    
    try:
        clinic = clinic_service.create_clinic(clinic_data)
        logger.info(f"Created new clinic: {clinic.clinic_id} with phone: {unique_phone}")
        return clinic.clinic_id
    except Exception as e:
        logger.error(f"Failed to create clinic: {str(e)}")
        raise


def create_custom_providers(db: Session, clinic_id: str) -> list:
    """Create custom providers."""
    provider_service = ProviderManagementService(db)
    
    providers_data = [
        {
            "name_token": "Dr. Miriam Rivera",
            "title": "Dr.",
            "specialty": "Family Medicine",
            "email": "dr.rivera@yourclinic.com"
        },
        {
            "name_token": "Dr. Jane Doe",
            "title": "Dr.",
            "specialty": "Cardiology",
            "email": "dr.doe@yourclinic.com"
        },
        {
            "name_token": "Dr. Robert Johnson",
            "title": "Dr.",
            "specialty": "Pediatrics",
            "email": "dr.johnson@yourclinic.com"
        }
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
    
    start_date = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    end_date = start_date + timedelta(days=365)
    
    total_slots_created = 0
    
    for provider in providers:
        logger.info(f"Creating appointment slots for {provider.name_token} for the entire year")
        provider_slots = 0
        
        current_date = start_date
        while current_date < end_date:
            if current_date.weekday() < 5:  # Monday to Friday
                for hour in range(9, 17):  # 9 AM to 5 PM
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
                            
                            if provider_slots % 100 == 0:
                                logger.info(f"Created {provider_slots} slots for {provider.name_token} up to {current_date.strftime('%Y-%m-%d')}")
                            
                        except Exception as e:
                            logger.error(f"Failed to create slot for {provider.name_token} at {slot_time}: {str(e)}")
            
            current_date += timedelta(days=1)
        
        logger.info(f"Finished creating {provider_slots} slots for {provider.name_token}")
    
    logger.info(f"Finished creating {total_slots_created} total appointment slots for the year")


def setup_demo():
    """Setup demo data for the CallCenterAI system."""
    logger.info("Starting custom clinic setup...")
    
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created/verified")
    
    db = SessionLocal()
    
    try:
        logger.info("Creating custom clinic...")
        clinic_id = create_custom_clinic(db)
        
        logger.info("Creating custom providers...")
        providers = create_custom_providers(db, clinic_id)
        
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


# ============================================================================
# Migration Functions
# ============================================================================

def migrate_provider_email():
    """Add email field to Provider model and update existing providers."""
    logger.info("Starting Provider email column migration...")
    
    try:
        # Check if column already exists
        inspector = inspect(engine)
        columns = inspector.get_columns('providers')
        column_names = [col['name'] for col in columns]
        
        if 'email' in column_names:
            logger.info("✅ Email column already exists in providers table")
        else:
            # Add the email column
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE providers ADD COLUMN email VARCHAR(255)"))
                conn.commit()
            
            logger.info("✅ Email column added successfully to providers table")
            
            # Verify the column was added
            inspector = inspect(engine)
            columns = inspector.get_columns('providers')
            column_names = [col['name'] for col in columns]
            
            if 'email' in column_names:
                logger.info("✅ Column verification successful - email column exists")
            else:
                logger.error("❌ Column verification failed - email column not found")
                return False
        
        # Update existing providers
        logger.info("Updating existing providers with email addresses...")
        
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT provider_id, name_token, title 
                FROM providers 
                WHERE email IS NULL OR email = ''
            """))
            
            providers = result.fetchall()
            logger.info(f"Found {len(providers)} providers without email addresses")
            
            for provider in providers:
                provider_id = provider[0]
                name_token = provider[1]
                title = provider[2]
                
                # Generate clinic-specific email
                parts = provider_id.split('_')
                if len(parts) >= 3:
                    clinic_id = parts[1]
                    email = f"{title.lower().replace('.', '')}.{name_token.lower()}@{clinic_id.lower()}.com"
                else:
                    email = f"provider.{provider_id.lower()}@clinic.com"
                
                conn.execute(text("""
                    UPDATE providers 
                    SET email = :email 
                    WHERE provider_id = :provider_id
                """), {"email": email, "provider_id": provider_id})
                
                logger.info(f"Updated provider {provider_id} with email: {email}")
            
            conn.commit()
            logger.info("✅ All providers updated with email addresses")
        
        logger.info("🎉 Provider email migration completed successfully!")
        return True
        
    except Exception as e:
        logger.error(f"🚨 Migration failed: {e}")
        return False


# ============================================================================
# Main Entry Point
# ============================================================================

def main():
    """Main function."""
    parser = argparse.ArgumentParser(description="CallCenterAI Database Utilities")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # List clinics command
    list_parser = subparsers.add_parser("list-clinics", help="List all clinics")
    
    # Delete clinic command
    delete_parser = subparsers.add_parser("delete-clinic", help="Delete a specific clinic")
    delete_parser.add_argument("clinic_id", help="Clinic ID to delete")
    
    # Delete all clinics command
    delete_all_parser = subparsers.add_parser("delete-all-clinics", help="Delete all clinics (DANGEROUS)")
    
    # Delete clinics by name command
    delete_by_name_parser = subparsers.add_parser("delete-clinics-by-name", help="Delete clinics by name")
    delete_by_name_parser.add_argument("name", help="Clinic name to delete")
    
    # Setup demo command
    setup_parser = subparsers.add_parser("setup-demo", help="Setup demo data (clinic, providers, appointment slots)")
    
    # Migrate provider email command
    migrate_parser = subparsers.add_parser("migrate-provider-email", help="Add email column to providers table and update existing providers")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    if args.command == "list-clinics":
        list_clinics()
        return 0
    
    elif args.command == "delete-clinic":
        if delete_clinic_by_id(args.clinic_id):
            return 0
        else:
            return 1
    
    elif args.command == "delete-all-clinics":
        confirm = input("Are you sure you want to delete ALL clinics? (yes/no): ")
        if confirm.lower() == "yes":
            if delete_all_clinics():
                return 0
            else:
                return 1
        else:
            print("Operation cancelled.")
            return 0
    
    elif args.command == "delete-clinics-by-name":
        if delete_clinics_by_name(args.name):
            return 0
        else:
            return 1
    
    elif args.command == "setup-demo":
        try:
            setup_demo()
            return 0
        except Exception as e:
            logger.error(f"Demo setup failed: {e}")
            return 1
    
    elif args.command == "migrate-provider-email":
        if migrate_provider_email():
            return 0
        else:
            return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

