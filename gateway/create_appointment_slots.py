"""
Create Appointment Slots Script
Creates appointment slots for Monday-Friday 8AM-5PM in 30-minute chunks.
"""

from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import logging

from services.database import SessionLocal
from models.models import Provider, AppointmentSlot, Clinic
from services.crypto import make_ulid_token

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_appointment_slots():
    """Create appointment slots for all providers."""
    db = SessionLocal()
    
    try:
        # Get clinic
        clinic = db.query(Clinic).first()
        if not clinic:
            logger.error("No clinic found. Run demo_setup.py first.")
            return
        
        # Get all providers
        providers = db.query(Provider).all()
        if not providers:
            logger.error("No providers found. Run demo_setup.py first.")
            return
        
        logger.info(f"Found {len(providers)} providers for clinic {clinic.clinic_id}")
        
        # Create slots for the next 30 days
        start_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        end_date = start_date + timedelta(days=30)
        
        slots_created = 0
        
        for provider in providers:
            logger.info(f"Creating slots for {provider.name_token}")
            
            current_date = start_date
            while current_date < end_date:
                # Skip weekends (Saturday=5, Sunday=6)
                if current_date.weekday() < 5:  # Monday=0, Friday=4
                    # Create slots from 8 AM to 5 PM (30-minute slots)
                    for hour in range(8, 17):  # 8 AM to 4:30 PM
                        slot_time = current_date.replace(hour=hour, minute=0, second=0, microsecond=0)
                        
                        # Create 30-minute slot
                        slot = AppointmentSlot(
                            slot_id=f"SLOT_{make_ulid_token('SLOT')[:12]}",
                            provider_id=provider.provider_id,
                            clinic_id=clinic.clinic_id,
                            slot_datetime=slot_time,
                            duration_minutes=30,
                            is_booked="no"
                        )
                        
                        db.add(slot)
                        slots_created += 1
                        
                        # Create 30-minute slot (e.g., 8:30 AM)
                        slot_time_30 = slot_time + timedelta(minutes=30)
                        if slot_time_30.hour < 17:  # Don't go past 5 PM
                            slot_30 = AppointmentSlot(
                                slot_id=f"SLOT_{make_ulid_token('SLOT')[:12]}",
                                provider_id=provider.provider_id,
                                clinic_id=clinic.clinic_id,
                                slot_datetime=slot_time_30,
                                duration_minutes=30,
                                is_booked="no"
                            )
                            
                            db.add(slot_30)
                            slots_created += 1
                
                current_date += timedelta(days=1)
        
        db.commit()
        logger.info(f"Created {slots_created} appointment slots")
        
    except Exception as e:
        logger.error(f"Failed to create appointment slots: {str(e)}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    create_appointment_slots()
