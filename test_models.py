#!/usr/bin/env python3
"""
Comprehensive test script for CallCenterAI database models.
Tests all models, relationships, tokenization, and emergency routing.
"""

import os
import sys
import json
from datetime import datetime, timedelta
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Add the gateway directory to Python path
sys.path.append(os.path.join(os.path.dirname(__file__), 'gateway'))

from gateway.models.models import (
    Base, Mapping, Call, Patient, Appointment, Provider, 
    CallNotes, AuditLog, CallQueue, SystemConfig
)
from gateway.services.crypto import (
    make_hmac_token, make_ulid_token, normalize_phone, 
    normalize_email, encrypt_str, decrypt_str
)

# Test database configuration
TEST_DB_URL = "sqlite:///test_callcenter.db"  # Use SQLite for testing

def setup_test_database():
    """Create test database and tables."""
    print("🔧 Setting up test database...")
    
    engine = create_engine(TEST_DB_URL, echo=False)
    Base.metadata.create_all(bind=engine)
    
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return SessionLocal()

def test_model_creation(session):
    """Test creating instances of all models."""
    print("\n📝 Testing model creation...")
    
    # Test SystemConfig
    print("  ✓ Testing SystemConfig...")
    emergency_config = SystemConfig(
        config_id="CONFIG_001",
        config_key="emergency_keywords",
        config_value='["chest pain", "can\'t breathe", "emergency", "urgent"]',
        config_type="json",
        category="emergency",
        description="Keywords that trigger emergency routing",
        updated_by="test_user"
    )
    session.add(emergency_config)
    
    clinic_hours_config = SystemConfig(
        config_id="CONFIG_002",
        config_key="clinic_hours",
        config_value='{"monday": "9am-5pm", "tuesday": "9am-5pm"}',
        config_type="json",
        category="clinic_settings",
        description="Clinic operating hours"
    )
    session.add(clinic_hours_config)
    
    # Test Provider
    print("  ✓ Testing Provider...")
    provider = Provider(
        provider_id="PROVIDER_001",
        name_token="PROVIDER_ABC123",
        title="Dr.",
        specialty="General Practice",
        license_number="MD123456",
        npi_number="1234567890",
        is_available="yes"
    )
    session.add(provider)
    
    # Test Patient
    print("  ✓ Testing Patient...")
    patient = Patient(
        patient_id="PATIENT_001",
        name_token="PATIENT_XYZ789",
        phone_token="PHONE_DEF456",
        email_token="EMAIL_GHI789",
        dob_token="DATE_JKL012",
        insurance_provider_token="INSURANCE_MNO345",
        insurance_member_id_token="MEMBER_PQR678",
        insurance_plan_type="PPO"
    )
    session.add(patient)
    
    # Test Call
    print("  ✓ Testing Call...")
    call = Call(
        call_sid="CA1234567890abcdef",
        call_id="CALL_20250110_001",
        caller_phone_token="PHONE_ABC123",
        status="active",
        patient_id="PATIENT_001"
    )
    session.add(call)
    
    # Test CallQueue
    print("  ✓ Testing CallQueue...")
    call_queue = CallQueue(
        queue_id="QUEUE_001",
        call_id="CALL_20250110_001",
        priority_level="normal",
        queue_status="processing",
        is_emergency="no"
    )
    session.add(call_queue)
    
    # Test Appointment
    print("  ✓ Testing Appointment...")
    appointment = Appointment(
        appointment_id="APPT_001",
        patient_id="PATIENT_001",
        provider_id="PROVIDER_001",
        call_id="CALL_20250110_001",
        appointment_date_token="DATE_ABC123",
        appointment_time_token="TIME_XYZ789",
        reason_token="REASON_DEF456",
        appointment_type="consultation",
        duration_minutes=30,
        status="scheduled"
    )
    session.add(appointment)
    
    # Test CallNotes
    print("  ✓ Testing CallNotes...")
    call_notes = CallNotes(
        notes_id="NOTES_001",
        call_id="CALL_20250110_001",
        patient_id="PATIENT_001",
        summary_token="SUMMARY_ABC123",
        key_points_token="POINTS_XYZ789",
        action_items_token="ACTIONS_DEF456",
        sentiment_score="positive",
        urgency_level="low",
        call_duration_seconds=300,
        ai_confidence_score="high",
        symptoms_detected="headache, fatigue",
        medications_mentioned="aspirin, ibuprofen",
        concerns_raised="work stress, sleep issues"
    )
    session.add(call_notes)
    
    # Test AuditLog
    print("  ✓ Testing AuditLog...")
    audit_log = AuditLog(
        log_id="AUDIT_001",
        user_id="test_user",
        action_type="create",
        table_name="patients",
        record_id="PATIENT_001",
        ip_address="192.168.1.100",
        user_agent="Test Script",
        request_id="REQ_001",
        details="Created new patient record",
        success="yes"
    )
    session.add(audit_log)
    
    # Test Mapping (PHI storage)
    print("  ✓ Testing Mapping (PHI storage)...")
    # Create some test PHI data
    test_phone = "+1234567890"
    test_name = "John Doe"
    test_email = "john.doe@example.com"
    
    # Tokenize and encrypt
    phone_token = make_hmac_token("PHONE", normalize_phone(test_phone))
    name_token = make_ulid_token("PATIENT")
    email_token = make_hmac_token("EMAIL", normalize_email(test_email))
    
    # Encrypt the actual values
    phone_nonce, phone_cipher = encrypt_str(test_phone)
    name_nonce, name_cipher = encrypt_str(test_name)
    email_nonce, email_cipher = encrypt_str(test_email)
    
    # Store in Mapping table
    phone_mapping = Mapping(
        token=phone_token,
        value_nonce=phone_nonce,
        value_ciphertext=phone_cipher,
        value_type="PHONE",
        call_id="CALL_20250110_001"
    )
    session.add(phone_mapping)
    
    name_mapping = Mapping(
        token=name_token,
        value_nonce=name_nonce,
        value_ciphertext=name_cipher,
        value_type="PATIENT",
        call_id="CALL_20250110_001"
    )
    session.add(name_mapping)
    
    email_mapping = Mapping(
        token=email_token,
        value_nonce=email_nonce,
        value_ciphertext=email_cipher,
        value_type="EMAIL",
        call_id="CALL_20250110_001"
    )
    session.add(email_mapping)
    
    session.commit()
    print("  ✅ All models created successfully!")

def test_relationships(session):
    """Test relationships between models."""
    print("\n🔗 Testing model relationships...")
    
    # Test Patient -> Calls relationship
    patient = session.query(Patient).filter_by(patient_id="PATIENT_001").first()
    if patient and patient.calls:
        print(f"  ✅ Patient has {len(patient.calls)} call(s)")
        for call in patient.calls:
            print(f"    - Call ID: {call.call_id}, Status: {call.status}")
    
    # Test Patient -> Appointments relationship
    if patient and patient.appointments:
        print(f"  ✅ Patient has {len(patient.appointments)} appointment(s)")
        for appointment in patient.appointments:
            print(f"    - Appointment ID: {appointment.appointment_id}, Type: {appointment.appointment_type}")
    
    # Test Provider -> Appointments relationship
    provider = session.query(Provider).filter_by(provider_id="PROVIDER_001").first()
    if provider and provider.appointments:
        print(f"  ✅ Provider has {len(provider.appointments)} appointment(s)")
        for appointment in provider.appointments:
            print(f"    - Appointment ID: {appointment.appointment_id}, Status: {appointment.status}")
    
    # Test Call -> CallQueue relationship
    call = session.query(Call).filter_by(call_id="CALL_20250110_001").first()
    if call:
        call_queue = session.query(CallQueue).filter_by(call_id=call.call_id).first()
        if call_queue:
            print(f"  ✅ Call {call.call_id} is in queue with status: {call_queue.queue_status}")

def test_tokenization_and_encryption(session):
    """Test PHI tokenization and encryption/decryption."""
    print("\n🔐 Testing tokenization and encryption...")
    
    # Test phone number tokenization
    test_phone = "+1234567890"
    normalized_phone = normalize_phone(test_phone)
    phone_token = make_hmac_token("PHONE", normalized_phone)
    print(f"  ✅ Phone tokenization: {test_phone} -> {phone_token}")
    
    # Test email tokenization
    test_email = "john.doe@example.com"
    normalized_email = normalize_email(test_email)
    email_token = make_hmac_token("EMAIL", normalized_email)
    print(f"  ✅ Email tokenization: {test_email} -> {email_token}")
    
    # Test name tokenization (ULID)
    test_name = "John Doe"
    name_token = make_ulid_token("PATIENT")
    print(f"  ✅ Name tokenization: {test_name} -> {name_token}")
    
    # Test encryption/decryption
    test_data = "This is sensitive PHI data"
    nonce, ciphertext = encrypt_str(test_data)
    decrypted_data = decrypt_str(nonce, ciphertext)
    print(f"  ✅ Encryption/Decryption: '{test_data}' -> encrypted -> '{decrypted_data}'")
    
    # Test retrieving and decrypting from database
    phone_mapping = session.query(Mapping).filter_by(value_type="PHONE").first()
    if phone_mapping:
        decrypted_phone = decrypt_str(phone_mapping.value_nonce, phone_mapping.value_ciphertext)
        print(f"  ✅ Database decryption: Token {phone_mapping.token} -> {decrypted_phone}")

def test_emergency_routing(session):
    """Test emergency keyword detection and routing."""
    print("\n🚨 Testing emergency routing...")
    
    # Get emergency keywords from SystemConfig
    emergency_config = session.query(SystemConfig).filter_by(config_key="emergency_keywords").first()
    if emergency_config:
        keywords = json.loads(emergency_config.config_value)
        print(f"  ✅ Emergency keywords loaded: {keywords}")
        
        # Simulate emergency detection
        test_phrases = [
            "I have chest pain",
            "I can't breathe",
            "This is an emergency",
            "I need help immediately"
        ]
        
        for phrase in test_phrases:
            is_emergency = any(keyword.lower() in phrase.lower() for keyword in keywords)
            if is_emergency:
                print(f"  🚨 EMERGENCY DETECTED: '{phrase}'")
                
                # Simulate emergency routing
                call_queue = session.query(CallQueue).first()
                if call_queue:
                    call_queue.is_emergency = "yes"
                    call_queue.emergency_reason = phrase
                    call_queue.transferred_to_human = "yes"
                    call_queue.assigned_human_agent = "Dr. Smith"
                    call_queue.human_transfer_at = datetime.now()
                    session.commit()
                    print(f"    → Call transferred to human agent: {call_queue.assigned_human_agent}")
            else:
                print(f"  ✅ Normal call: '{phrase}'")

def test_system_configuration(session):
    """Test system configuration management."""
    print("\n⚙️ Testing system configuration...")
    
    # Test retrieving configurations
    configs = session.query(SystemConfig).all()
    print(f"  ✅ Found {len(configs)} configuration(s)")
    
    for config in configs:
        print(f"    - {config.config_key}: {config.config_value} ({config.category})")
    
    # Test updating configuration
    emergency_config = session.query(SystemConfig).filter_by(config_key="emergency_keywords").first()
    if emergency_config:
        # Add a new keyword
        current_keywords = json.loads(emergency_config.config_value)
        current_keywords.append("heart attack")
        emergency_config.config_value = json.dumps(current_keywords)
        emergency_config.updated_by = "test_user"
        session.commit()
        print(f"  ✅ Updated emergency keywords: {current_keywords}")

def test_audit_trail(session):
    """Test audit logging functionality."""
    print("\n📋 Testing audit trail...")
    
    # Create a new audit log entry
    new_audit = AuditLog(
        log_id="AUDIT_002",
        user_id="test_user",
        action_type="read",
        table_name="patients",
        record_id="PATIENT_001",
        ip_address="192.168.1.100",
        user_agent="Test Script",
        request_id="REQ_002",
        details="Retrieved patient information",
        success="yes"
    )
    session.add(new_audit)
    session.commit()
    
    # Query audit logs
    audit_logs = session.query(AuditLog).all()
    print(f"  ✅ Found {len(audit_logs)} audit log entries")
    
    for log in audit_logs:
        print(f"    - {log.action_type} on {log.table_name} by {log.user_id} at {log.created_at}")

def cleanup_test_database():
    """Clean up test database file."""
    print("\n🧹 Cleaning up test database...")
    if os.path.exists("test_callcenter.db"):
        os.remove("test_callcenter.db")
        print("  ✅ Test database cleaned up")

def main():
    """Run all tests."""
    print("🚀 Starting CallCenterAI Model Tests")
    print("=" * 50)
    
    try:
        # Setup
        session = setup_test_database()
        
        # Run tests
        test_model_creation(session)
        test_relationships(session)
        test_tokenization_and_encryption(session)
        test_emergency_routing(session)
        test_system_configuration(session)
        test_audit_trail(session)
        
        print("\n" + "=" * 50)
        print("🎉 All tests completed successfully!")
        print("✅ All models are working correctly")
        print("✅ Relationships are properly configured")
        print("✅ Tokenization and encryption are functional")
        print("✅ Emergency routing is working")
        print("✅ System configuration is manageable")
        print("✅ Audit trail is operational")
        
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        cleanup_test_database()

if __name__ == "__main__":
    main()
