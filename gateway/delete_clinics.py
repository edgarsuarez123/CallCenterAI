"""
Script to delete clinics from the database
"""
from sqlalchemy.orm import Session
import logging

from services.database import SessionLocal
from models.models import Clinic, ClinicLicense, SystemConfig, AppointmentSlot, Provider, provider_clinics

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
        # Find the clinic
        clinic = db.query(Clinic).filter(Clinic.clinic_id == clinic_id).first()
        if not clinic:
            logger.error(f"Clinic {clinic_id} not found")
            return False
        
        logger.info(f"Deleting clinic: {clinic.clinic_id} - {clinic.clinic_name}")
        
        # Delete related records first (foreign key constraints)
        # Delete appointment slots
        db.query(AppointmentSlot).filter(AppointmentSlot.clinic_id == clinic_id).delete()
        logger.info(f"Deleted appointment slots for clinic {clinic_id}")
        
        # Delete provider-clinic associations
        db.query(provider_clinics).filter(provider_clinics.c.clinic_id == clinic_id).delete()
        logger.info(f"Deleted provider-clinic associations for clinic {clinic_id}")
        
        # Delete system configs (they have clinic_id in the config_key)
        db.query(SystemConfig).filter(SystemConfig.config_key.like(f"%{clinic_id}%")).delete()
        logger.info(f"Deleted system configs for clinic {clinic_id}")
        
        # Delete clinic license
        db.query(ClinicLicense).filter(ClinicLicense.clinic_id == clinic_id).delete()
        logger.info(f"Deleted license for clinic {clinic_id}")
        
        # Delete the clinic
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
            
            # Delete related records first
            db.query(AppointmentSlot).filter(AppointmentSlot.clinic_id == clinic.clinic_id).delete()
            db.query(provider_clinics).filter(provider_clinics.c.clinic_id == clinic.clinic_id).delete()
            db.query(SystemConfig).filter(SystemConfig.config_key.like(f"%{clinic.clinic_id}%")).delete()
            db.query(ClinicLicense).filter(ClinicLicense.clinic_id == clinic.clinic_id).delete()
            
            # Delete the clinic
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
            
            # Delete related records first
            db.query(AppointmentSlot).filter(AppointmentSlot.clinic_id == clinic.clinic_id).delete()
            db.query(provider_clinics).filter(provider_clinics.c.clinic_id == clinic.clinic_id).delete()
            db.query(SystemConfig).filter(SystemConfig.config_key.like(f"%{clinic.clinic_id}%")).delete()
            db.query(ClinicLicense).filter(ClinicLicense.clinic_id == clinic.clinic_id).delete()
            
            # Delete the clinic
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

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python delete_clinics.py list                    # List all clinics")
        print("  python delete_clinics.py delete <clinic_id>      # Delete specific clinic")
        print("  python delete_clinics.py delete-all              # Delete all clinics")
        print("  python delete_clinics.py delete-by-name <name>   # Delete clinics by name")
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command == "list":
        list_clinics()
    elif command == "delete" and len(sys.argv) > 2:
        clinic_id = sys.argv[2]
        delete_clinic_by_id(clinic_id)
    elif command == "delete-all":
        confirm = input("Are you sure you want to delete ALL clinics? (yes/no): ")
        if confirm.lower() == "yes":
            delete_all_clinics()
        else:
            print("Operation cancelled.")
    elif command == "delete-by-name" and len(sys.argv) > 2:
        clinic_name = sys.argv[2]
        delete_clinics_by_name(clinic_name)
    else:
        print("Invalid command. Use 'python delete_clinics.py' for usage information.")
