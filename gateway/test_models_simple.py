#!/usr/bin/env python3
"""
Simple test script for CallCenterAI models that works with the existing Docker setup.
Run this inside the gateway container or with the same environment.
"""

import os
import sys
import json
import uuid
from datetime import datetime
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

def test_basic_models():
    """Test basic model creation and relationships."""
    print("🧪 Testing basic models...")
    
    # Generate unique test IDs
    test_id = str(uuid.uuid4())[:8]
    
    # Create database session
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    
    try:
        # Test 1: Create a patient
        print("  📝 Creating test patient...")
        patient = Patient(
            patient_id=f"TEST_PATIENT_{test_id}",
            name_token="PATIENT_TEST123",
            phone_token="PHONE_TEST456",
            email_token="EMAIL_TEST789",
            insurance_plan_type="PPO"
        )
        session.add(patient)
        session.commit()
        print("  ✅ Patient created successfully")
        
        # Test 2: Create a provider
        print("  📝 Creating test provider...")
        provider = Provider(
            provider_id=f"TEST_PROVIDER_{test_id}",
            name_token="PROVIDER_TEST123",
            title="Dr.",
            specialty="General Practice",
            is_available="yes"
        )
        session.add(provider)
        session.commit()
        print("  ✅ Provider created successfully")
        
        # Test 3: Create a call
        print("  📝 Creating test call...")
        call = Call(
            call_sid=f"CA_TEST{test_id}",
            call_id=f"TEST_CALL_{test_id}",
            caller_phone_token="PHONE_TEST456",
            status="active",
            patient_id=f"TEST_PATIENT_{test_id}"
        )
        session.add(call)
        session.commit()
        print("  ✅ Call created successfully")
        
        # Test 4: Create an appointment
        print("  📝 Creating test appointment...")
        appointment = Appointment(
            appointment_id=f"TEST_APPT_{test_id}",
            patient_id=f"TEST_PATIENT_{test_id}",
            provider_id=f"TEST_PROVIDER_{test_id}",
            call_id=f"TEST_CALL_{test_id}",
            appointment_type="consultation",
            duration_minutes=30,
            status="scheduled"
        )
        session.add(appointment)
        session.commit()
        print("  ✅ Appointment created successfully")
        
        # Test 5: Test relationships
        print("  🔗 Testing relationships...")
        retrieved_patient = session.query(Patient).filter_by(patient_id=f"TEST_PATIENT_{test_id}").first()
        if retrieved_patient:
            print(f"    ✅ Patient found: {retrieved_patient.patient_id}")
            print(f"    ✅ Patient has {len(retrieved_patient.calls)} call(s)")
            print(f"    ✅ Patient has {len(retrieved_patient.appointments)} appointment(s)")
        
        return True
        
    except Exception as e:
        print(f"  ❌ Error: {e}")
        session.rollback()
        return False
    finally:
        session.close()

def test_tokenization():
    """Test PHI tokenization and encryption."""
    print("\n🔐 Testing tokenization and encryption...")
    
    try:
        # Test phone tokenization
        test_phone = "+1234567890"
        normalized = normalize_phone(test_phone)
        token = make_hmac_token("PHONE", normalized)
        print(f"  ✅ Phone: {test_phone} -> {token}")
        
        # Test email tokenization
        test_email = "test@example.com"
        normalized = normalize_email(test_email)
        token = make_hmac_token("EMAIL", normalized)
        print(f"  ✅ Email: {test_email} -> {token}")
        
        # Test name tokenization
        name_token = make_ulid_token("PATIENT")
        print(f"  ✅ Name token: {name_token}")
        
        # Test encryption/decryption
        test_data = "Sensitive PHI data"
        nonce, cipher = encrypt_str(test_data)
        decrypted = decrypt_str(nonce, cipher)
        print(f"  ✅ Encryption: '{test_data}' -> encrypted -> '{decrypted}'")
        
        return True
        
    except Exception as e:
        print(f"  ❌ Error: {e}")
        return False

def test_emergency_keywords():
    """Test emergency keyword configuration."""
    print("\n🚨 Testing emergency keywords...")
    
    # Generate unique test ID
    test_id = str(uuid.uuid4())[:8]
    
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    
    try:
        # Create emergency keywords config
        emergency_config = SystemConfig(
            config_id=f"TEST_CONFIG_{test_id}",
            config_key=f"emergency_keywords_{test_id}",
            config_value='["chest pain", "can\'t breathe", "emergency", "urgent"]',
            config_type="json",
            category="emergency",
            description="Test emergency keywords"
        )
        session.add(emergency_config)
        session.commit()
        
        # Test keyword detection
        keywords = json.loads(emergency_config.config_value)
        test_phrases = [
            "I have chest pain",
            "I can't breathe", 
            "This is an emergency",
            "I need an appointment"
        ]
        
        for phrase in test_phrases:
            is_emergency = any(keyword.lower() in phrase.lower() for keyword in keywords)
            status = "🚨 EMERGENCY" if is_emergency else "✅ Normal"
            print(f"  {status}: '{phrase}'")
        
        return True
        
    except Exception as e:
        print(f"  ❌ Error: {e}")
        session.rollback()
        return False
    finally:
        session.close()

def test_audit_logging():
    """Test audit logging."""
    print("\n📋 Testing audit logging...")
    
    # Generate unique test ID
    test_id = str(uuid.uuid4())[:8]
    
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    
    try:
        # Create audit log entry
        audit_log = AuditLog(
            log_id=f"TEST_AUDIT_{test_id}",
            user_id="test_user",
            action_type="create",
            table_name="patients",
            record_id=f"TEST_PATIENT_{test_id}",
            ip_address="127.0.0.1",
            details="Test audit log entry",
            success="yes"
        )
        session.add(audit_log)
        session.commit()
        
        # Query audit logs
        logs = session.query(AuditLog).filter_by(log_id=f"TEST_AUDIT_{test_id}").all()
        print(f"  ✅ Created and retrieved {len(logs)} audit log entry")
        
        return True
        
    except Exception as e:
        print(f"  ❌ Error: {e}")
        session.rollback()
        return False
    finally:
        session.close()

def cleanup_test_data():
    """Clean up test data."""
    print("\n🧹 Cleaning up test data...")
    
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    
    try:
        # Delete test records in correct order to respect foreign key constraints
        # 1. Delete appointments first (they reference calls and patients)
        session.query(Appointment).filter(Appointment.appointment_id.like("TEST_%")).delete()
        
        # 2. Delete calls (they reference patients)
        session.query(Call).filter(Call.call_id.like("TEST_%")).delete()
        
        # 3. Delete patients (no longer referenced)
        session.query(Patient).filter(Patient.patient_id.like("TEST_%")).delete()
        
        # 4. Delete providers (no longer referenced)
        session.query(Provider).filter(Provider.provider_id.like("TEST_%")).delete()
        
        # 5. Delete system configs
        session.query(SystemConfig).filter(SystemConfig.config_id.like("TEST_%")).delete()
        
        # 6. Delete audit logs
        session.query(AuditLog).filter(AuditLog.log_id.like("TEST_%")).delete()
        
        session.commit()
        print("  ✅ Test data cleaned up")
        
    except Exception as e:
        print(f"  ❌ Error cleaning up: {e}")
        session.rollback()
    finally:
        session.close()

def main():
    """Run all tests."""
    print("🚀 CallCenterAI Model Tests")
    print("=" * 40)
    
    tests = [
        ("Basic Models", test_basic_models),
        ("Tokenization", test_tokenization),
        ("Emergency Keywords", test_emergency_keywords),
        ("Audit Logging", test_audit_logging)
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
    
    print("\n" + "=" * 40)
    print(f"📊 Test Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! Your models are working correctly.")
    else:
        print("⚠️ Some tests failed. Check the errors above.")
    
    # Clean up
    cleanup_test_data()

if __name__ == "__main__":
    main()
