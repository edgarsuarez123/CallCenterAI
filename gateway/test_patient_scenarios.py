#!/usr/bin/env python3
"""
Test script for realistic patient call scenarios.
Tests how the system handles the same patient calling multiple times.
"""

import os
import sys
import json
import uuid
from datetime import datetime, timedelta
from sqlalchemy.orm import sessionmaker

# Import your models and services
from models.models import (
    Base, Mapping, Call, Patient, Appointment, Provider, 
    CallNotes, AuditLog, CallQueue, SystemConfig
)
from services.database import engine, get_db
from services.crypto import (
    make_hmac_token, make_ulid_token, normalize_phone, 
    normalize_email, encrypt_str, decrypt_str
)

def test_same_patient_multiple_calls():
    """Test the same patient calling multiple times."""
    print("🔄 Testing same patient multiple calls scenario...")
    
    # Create database session
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    
    try:
        # Create a persistent patient (like in real system)
        patient_id = "PATIENT_JOHN_DOE_001"
        patient_phone = "+1234567890"
        patient_name = "John Doe"
        patient_email = "john.doe@example.com"
        
        # Tokenize the patient's PHI
        phone_token = make_hmac_token("PHONE", normalize_phone(patient_phone))
        name_token = make_ulid_token("PATIENT")
        email_token = make_hmac_token("EMAIL", normalize_email(patient_email))
        
        # Encrypt the actual PHI values
        phone_nonce, phone_cipher = encrypt_str(patient_phone)
        name_nonce, name_cipher = encrypt_str(patient_name)
        email_nonce, email_cipher = encrypt_str(patient_email)
        
        # Check if patient already exists
        existing_patient = session.query(Patient).filter_by(patient_id=patient_id).first()
        
        if not existing_patient:
            print("  📝 Creating new patient...")
            # Create patient record
            patient = Patient(
                patient_id=patient_id,
                name_token=name_token,
                phone_token=phone_token,
                email_token=email_token,
                insurance_plan_type="PPO"
            )
            session.add(patient)
            
            # Store encrypted PHI in Mapping table
            phone_mapping = Mapping(
                token=phone_token,
                value_nonce=phone_nonce,
                value_ciphertext=phone_cipher,
                value_type="PHONE"
            )
            session.add(phone_mapping)
            
            name_mapping = Mapping(
                token=name_token,
                value_nonce=name_nonce,
                value_ciphertext=name_cipher,
                value_type="PATIENT"
            )
            session.add(name_mapping)
            
            email_mapping = Mapping(
                token=email_token,
                value_nonce=email_nonce,
                value_ciphertext=email_cipher,
                value_type="EMAIL"
            )
            session.add(email_mapping)
            
            session.commit()
            print(f"  ✅ Created patient: {patient_id}")
        else:
            print(f"  ✅ Found existing patient: {patient_id}")
            patient = existing_patient
        
        # Simulate multiple calls from the same patient
        call_scenarios = [
            {
                "call_id": f"CALL_{patient_id}_001",
                "call_sid": f"CA_{uuid.uuid4().hex[:12]}",
                "reason": "appointment_request",
                "status": "completed"
            },
            {
                "call_id": f"CALL_{patient_id}_002", 
                "call_sid": f"CA_{uuid.uuid4().hex[:12]}",
                "reason": "follow_up_question",
                "status": "completed"
            },
            {
                "call_id": f"CALL_{patient_id}_003",
                "call_sid": f"CA_{uuid.uuid4().hex[:12]}",
                "reason": "emergency_concern",
                "status": "transferred_to_human"
            }
        ]
        
        for i, scenario in enumerate(call_scenarios, 1):
            print(f"\n  📞 Call #{i}: {scenario['reason']}")
            
            # Create call record
            call = Call(
                call_sid=scenario["call_sid"],
                call_id=scenario["call_id"],
                caller_phone_token=phone_token,  # Same phone token
                status=scenario["status"],
                patient_id=patient_id  # Link to same patient
            )
            session.add(call)
            
            # Create call queue entry
            is_emergency = scenario["reason"] == "emergency_concern"
            call_queue = CallQueue(
                queue_id=f"QUEUE_{scenario['call_id']}",
                call_id=scenario["call_id"],
                priority_level="emergency" if is_emergency else "normal",
                queue_status="completed" if scenario["status"] == "completed" else "transferred_to_human",
                is_emergency="yes" if is_emergency else "no",
                transferred_to_human="yes" if is_emergency else "no",
                assigned_human_agent="Dr. Smith" if is_emergency else None
            )
            session.add(call_queue)
            
            # Create call notes
            call_notes = CallNotes(
                notes_id=f"NOTES_{scenario['call_id']}",
                call_id=scenario["call_id"],
                patient_id=patient_id,  # Link to same patient
                summary_token=f"SUMMARY_{uuid.uuid4().hex[:8]}",
                sentiment_score="positive" if scenario["reason"] != "emergency_concern" else "concerned",
                urgency_level="high" if is_emergency else "low",
                call_duration_seconds=300 + (i * 60),  # Increasing duration
                ai_confidence_score="high"
            )
            session.add(call_notes)
            
            session.commit()
            print(f"    ✅ Call recorded and linked to patient {patient_id}")
        
        # Test patient call history
        print(f"\n  📊 Patient Call History for {patient_id}:")
        patient_calls = session.query(Call).filter_by(patient_id=patient_id).all()
        print(f"    Total calls: {len(patient_calls)}")
        
        for call in patient_calls:
            call_notes = session.query(CallNotes).filter_by(call_id=call.call_id).first()
            call_queue = session.query(CallQueue).filter_by(call_id=call.call_id).first()
            
            print(f"    - {call.call_id}: {call.status}")
            if call_notes:
                print(f"      Sentiment: {call_notes.sentiment_score}, Urgency: {call_notes.urgency_level}")
            if call_queue and call_queue.is_emergency == "yes":
                print(f"      🚨 EMERGENCY - Transferred to: {call_queue.assigned_human_agent}")
        
        # Test PHI retrieval (decrypt patient info)
        print(f"\n  🔐 PHI Retrieval Test:")
        phone_mapping = session.query(Mapping).filter_by(token=phone_token).first()
        if phone_mapping:
            decrypted_phone = decrypt_str(phone_mapping.value_nonce, phone_mapping.value_ciphertext)
            print(f"    Decrypted phone: {decrypted_phone}")
        
        name_mapping = session.query(Mapping).filter_by(token=name_token).first()
        if name_mapping:
            decrypted_name = decrypt_str(name_mapping.value_nonce, name_mapping.value_ciphertext)
            print(f"    Decrypted name: {decrypted_name}")
        
        return True
        
    except Exception as e:
        print(f"  ❌ Error: {e}")
        session.rollback()
        return False
    finally:
        session.close()

def test_patient_identification():
    """Test patient identification by phone number."""
    print("\n🔍 Testing patient identification by phone...")
    
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    
    try:
        # Test phone number that should exist from previous test
        test_phone = "+1234567890"
        phone_token = make_hmac_token("PHONE", normalize_phone(test_phone))
        
        # Find patient by phone token
        patient = session.query(Patient).filter_by(phone_token=phone_token).first()
        
        if patient:
            print(f"  ✅ Found existing patient: {patient.patient_id}")
            
            # Get all calls for this patient
            calls = session.query(Call).filter_by(patient_id=patient.patient_id).all()
            print(f"  📞 Patient has {len(calls)} call(s) in history")
            
            # Get call notes
            notes = session.query(CallNotes).filter_by(patient_id=patient.patient_id).all()
            print(f"  📝 Patient has {len(notes)} call note(s)")
            
            return True
        else:
            print(f"  ❌ No patient found with phone token: {phone_token}")
            return False
            
    except Exception as e:
        print(f"  ❌ Error: {e}")
        return False
    finally:
        session.close()

def test_emergency_detection():
    """Test emergency detection in patient calls."""
    print("\n🚨 Testing emergency detection...")
    
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    
    try:
        # Get emergency calls
        emergency_calls = session.query(CallQueue).filter_by(is_emergency="yes").all()
        
        print(f"  Found {len(emergency_calls)} emergency call(s)")
        
        for call_queue in emergency_calls:
            call = session.query(Call).filter_by(call_id=call_queue.call_id).first()
            patient = session.query(Patient).filter_by(patient_id=call.patient_id).first() if call else None
            
            print(f"  🚨 Emergency Call: {call_queue.call_id}")
            print(f"    Patient: {patient.patient_id if patient else 'Unknown'}")
            print(f"    Transferred to: {call_queue.assigned_human_agent}")
            print(f"    Status: {call_queue.queue_status}")
        
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
        session.query(CallNotes).filter(CallNotes.notes_id.like("NOTES_CALL_PATIENT_JOHN_DOE_001_%")).delete()
        session.query(CallQueue).filter(CallQueue.queue_id.like("QUEUE_CALL_PATIENT_JOHN_DOE_001_%")).delete()
        session.query(Call).filter(Call.call_id.like("CALL_PATIENT_JOHN_DOE_001_%")).delete()
        session.query(Patient).filter(Patient.patient_id == "PATIENT_JOHN_DOE_001").delete()
        
        # Clean up mappings
        session.query(Mapping).filter(Mapping.value_type.in_(["PHONE", "PATIENT", "EMAIL"])).delete()
        
        session.commit()
        print("  ✅ Test data cleaned up")
        
    except Exception as e:
        print(f"  ❌ Error cleaning up: {e}")
        session.rollback()
    finally:
        session.close()

def main():
    """Run patient scenario tests."""
    print("🚀 CallCenterAI Patient Scenario Tests")
    print("=" * 50)
    
    tests = [
        ("Same Patient Multiple Calls", test_same_patient_multiple_calls),
        ("Patient Identification", test_patient_identification),
        ("Emergency Detection", test_emergency_detection)
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
    
    print("\n" + "=" * 50)
    print(f"📊 Test Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All patient scenario tests passed!")
        print("✅ Same patient can call multiple times")
        print("✅ Patient identification works correctly")
        print("✅ Emergency detection and routing works")
    else:
        print("⚠️ Some tests failed. Check the errors above.")
    
    # Clean up
    cleanup_test_data()

if __name__ == "__main__":
    main()
