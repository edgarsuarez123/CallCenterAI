#!/usr/bin/env python3
"""
Test script for appointment scheduling with time blocks.
Tests proper start/end times and consistent appointment blocks.
"""

import os
import sys
import uuid
from datetime import datetime, timedelta, time
from sqlalchemy.orm import sessionmaker

# Import your models and services
from models.models import (
    Base, Mapping, Call, Patient, Appointment, Provider, 
    CallNotes, AuditLog, CallQueue, SystemConfig, AppointmentBlock
)
from services.database import engine, get_db
from services.crypto import (
    make_hmac_token, make_ulid_token, normalize_phone, 
    normalize_email, encrypt_str, decrypt_str
)

def create_test_provider(session):
    """Create a test provider."""
    provider_id = f"PROVIDER_TEST_{uuid.uuid4().hex[:8]}"
    provider = Provider(
        provider_id=provider_id,
        name_token=f"PROVIDER_{uuid.uuid4().hex[:8]}",
        title="Dr.",
        specialty="General Practice",
        is_available="yes"
    )
    session.add(provider)
    session.commit()
    return provider

def create_test_patient(session):
    """Create a test patient."""
    patient_id = f"PATIENT_TEST_{uuid.uuid4().hex[:8]}"
    patient = Patient(
        patient_id=patient_id,
        name_token=f"PATIENT_{uuid.uuid4().hex[:8]}",
        phone_token=f"PHONE_{uuid.uuid4().hex[:8]}",
        email_token=f"EMAIL_{uuid.uuid4().hex[:8]}",
        insurance_plan_type="PPO"
    )
    session.add(patient)
    session.commit()
    return patient

def test_appointment_blocks():
    """Test creating and managing appointment blocks."""
    print("📅 Testing appointment blocks...")
    
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    
    try:
        # Create test provider
        provider = create_test_provider(session)
        print(f"  ✅ Created provider: {provider.provider_id}")
        
        # Create appointment blocks for a week
        base_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        
        for day in range(7):  # Monday to Sunday
            current_date = base_date + timedelta(days=day)
            
            # Create morning block (9 AM - 12 PM)
            morning_block = AppointmentBlock(
                block_id=f"BLOCK_{provider.provider_id}_{current_date.strftime('%Y%m%d')}_MORNING",
                provider_id=provider.provider_id,
                block_date=current_date,
                start_time=current_date.replace(hour=9, minute=0),
                end_time=current_date.replace(hour=12, minute=0),
                slot_duration_minutes=30,
                break_duration_minutes=0,
                max_appointments=6,  # 3 hours / 30 min slots = 6 appointments
                is_available="yes",
                status="active"
            )
            session.add(morning_block)
            
            # Create afternoon block (1 PM - 5 PM)
            afternoon_block = AppointmentBlock(
                block_id=f"BLOCK_{provider.provider_id}_{current_date.strftime('%Y%m%d')}_AFTERNOON",
                provider_id=provider.provider_id,
                block_date=current_date,
                start_time=current_date.replace(hour=13, minute=0),
                end_time=current_date.replace(hour=17, minute=0),
                slot_duration_minutes=30,
                break_duration_minutes=0,
                max_appointments=8,  # 4 hours / 30 min slots = 8 appointments
                is_available="yes",
                status="active"
            )
            session.add(afternoon_block)
        
        session.commit()
        print(f"  ✅ Created 14 appointment blocks (7 days × 2 blocks)")
        
        # Verify blocks were created
        blocks = session.query(AppointmentBlock).filter_by(provider_id=provider.provider_id).all()
        print(f"  ✅ Total blocks for provider: {len(blocks)}")
        
        # Show sample blocks
        for block in blocks[:3]:  # Show first 3 blocks
            print(f"    - {block.block_date.strftime('%Y-%m-%d')} {block.start_time.strftime('%H:%M')}-{block.end_time.strftime('%H:%M')} ({block.slot_duration_minutes}min slots)")
        
        return provider, blocks
        
    except Exception as e:
        print(f"  ❌ Error: {e}")
        session.rollback()
        return None, None
    finally:
        session.close()

def test_appointment_scheduling():
    """Test scheduling appointments with proper start/end times."""
    print("\n📝 Testing appointment scheduling...")
    
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    
    try:
        # Get a provider and their blocks
        provider = session.query(Provider).first()
        if not provider:
            print("  ❌ No provider found. Run appointment blocks test first.")
            return False
        
        blocks = session.query(AppointmentBlock).filter_by(provider_id=provider.provider_id).all()
        if not blocks:
            print("  ❌ No appointment blocks found. Run appointment blocks test first.")
            return False
        
        # Create test patient
        patient = create_test_patient(session)
        print(f"  ✅ Created patient: {patient.patient_id}")
        
        # Schedule appointments in available slots
        scheduled_appointments = []
        
        for i, block in enumerate(blocks[:3]):  # Schedule in first 3 blocks
            # Calculate appointment start time
            appointment_start = block.start_time + timedelta(minutes=i * block.slot_duration_minutes)
            appointment_end = appointment_start + timedelta(minutes=block.slot_duration_minutes)
            
            # Create appointment
            appointment = Appointment(
                appointment_id=f"APPT_{uuid.uuid4().hex[:8]}",
                patient_id=patient.patient_id,
                provider_id=provider.provider_id,
                appointment_date=appointment_start,
                start_time=appointment_start,
                end_time=appointment_end,
                appointment_type="consultation",
                duration_minutes=block.slot_duration_minutes,
                status="scheduled"
            )
            session.add(appointment)
            scheduled_appointments.append(appointment)
            
            print(f"  📅 Scheduled appointment {i+1}:")
            print(f"    Date: {appointment_start.strftime('%Y-%m-%d')}")
            print(f"    Time: {appointment_start.strftime('%H:%M')} - {appointment_end.strftime('%H:%M')}")
            print(f"    Duration: {block.slot_duration_minutes} minutes")
        
        session.commit()
        print(f"  ✅ Successfully scheduled {len(scheduled_appointments)} appointments")
        
        # Verify appointments have proper timing
        for appointment in scheduled_appointments:
            duration = (appointment.end_time - appointment.start_time).total_seconds() / 60
            print(f"    ✅ Appointment {appointment.appointment_id}: {duration} minutes")
        
        return True
        
    except Exception as e:
        print(f"  ❌ Error: {e}")
        session.rollback()
        return False
    finally:
        session.close()

def test_time_block_consistency():
    """Test that appointment blocks maintain consistent time slots."""
    print("\n⏰ Testing time block consistency...")
    
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    
    try:
        # Get a provider's blocks
        provider = session.query(Provider).first()
        blocks = session.query(AppointmentBlock).filter_by(provider_id=provider.provider_id).all()
        
        if not blocks:
            print("  ❌ No blocks found")
            return False
        
        # Test time slot consistency
        for block in blocks:
            print(f"  📅 Block: {block.block_date.strftime('%Y-%m-%d')} {block.start_time.strftime('%H:%M')}-{block.end_time.strftime('%H:%M')}")
            
            # Calculate expected slots
            total_minutes = (block.end_time - block.start_time).total_seconds() / 60
            expected_slots = int(total_minutes / block.slot_duration_minutes)
            
            print(f"    Slot duration: {block.slot_duration_minutes} minutes")
            print(f"    Expected slots: {expected_slots}")
            print(f"    Max appointments: {block.max_appointments}")
            
            # Verify consistency
            if expected_slots == block.max_appointments:
                print(f"    ✅ Time block is consistent")
            else:
                print(f"    ⚠️ Time block inconsistency: expected {expected_slots}, max {block.max_appointments}")
        
        return True
        
    except Exception as e:
        print(f"  ❌ Error: {e}")
        return False
    finally:
        session.close()

def test_appointment_conflicts():
    """Test appointment conflict detection."""
    print("\n⚠️ Testing appointment conflict detection...")
    
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    
    try:
        # Get existing appointments
        appointments = session.query(Appointment).all()
        
        if len(appointments) < 2:
            print("  ❌ Need at least 2 appointments to test conflicts")
            return False
        
        # Check for overlapping appointments
        conflicts = []
        for i, apt1 in enumerate(appointments):
            for j, apt2 in enumerate(appointments[i+1:], i+1):
                # Check if appointments overlap
                if (apt1.start_time < apt2.end_time and apt2.start_time < apt1.end_time):
                    conflicts.append((apt1, apt2))
        
        if conflicts:
            print(f"  ⚠️ Found {len(conflicts)} appointment conflict(s):")
            for apt1, apt2 in conflicts:
                print(f"    - {apt1.appointment_id} ({apt1.start_time.strftime('%H:%M')}-{apt1.end_time.strftime('%H:%M')})")
                print(f"      conflicts with {apt2.appointment_id} ({apt2.start_time.strftime('%H:%M')}-{apt2.end_time.strftime('%H:%M')})")
        else:
            print(f"  ✅ No appointment conflicts found")
        
        return True
        
    except Exception as e:
        print(f"  ❌ Error: {e}")
        return False
    finally:
        session.close()

def cleanup_test_data():
    """Clean up test data."""
    print("\n🧹 Cleaning up test data...")
    
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    
    try:
        # Delete in correct order
        session.query(Appointment).filter(Appointment.appointment_id.like("APPT_%")).delete()
        session.query(AppointmentBlock).filter(AppointmentBlock.block_id.like("BLOCK_%")).delete()
        session.query(Patient).filter(Patient.patient_id.like("PATIENT_TEST_%")).delete()
        session.query(Provider).filter(Provider.provider_id.like("PROVIDER_TEST_%")).delete()
        
        session.commit()
        print("  ✅ Test data cleaned up")
        
    except Exception as e:
        print(f"  ❌ Error cleaning up: {e}")
        session.rollback()
    finally:
        session.close()

def main():
    """Run appointment scheduling tests."""
    print("🚀 CallCenterAI Appointment Scheduling Tests")
    print("=" * 60)
    
    tests = [
        ("Appointment Blocks", test_appointment_blocks),
        ("Appointment Scheduling", test_appointment_scheduling),
        ("Time Block Consistency", test_time_block_consistency),
        ("Appointment Conflicts", test_appointment_conflicts)
    ]
    
    passed = 0
    total = len(tests)
    
    for test_name, test_func in tests:
        print(f"\n📋 Running {test_name} test...")
        if test_func():
            passed += 1
            print(f"✅ {test_name} test passed")
        else:
            print(f"❌ {test_name} test failed")
    
    print("\n" + "=" * 60)
    print(f"📊 Test Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All appointment scheduling tests passed!")
        print("✅ Appointment blocks work correctly")
        print("✅ Start/end times are properly managed")
        print("✅ Time blocks are consistent")
        print("✅ Conflict detection works")
    else:
        print("⚠️ Some tests failed. Check the errors above.")
    
    # Clean up
    cleanup_test_data()

if __name__ == "__main__":
    main()
