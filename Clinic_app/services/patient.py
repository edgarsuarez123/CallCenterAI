"""
Patient Service

Provides functions for finding and creating patients with encrypted PHI.
Uses hash-based lookup (name+DOB) for efficient patient identification.
"""

import hashlib
import logging
import re
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from Clinic_app.data.models.patient import Patient
from Clinic_app.data.models.clinic import Clinic
from Clinic_app.common.encryption import encrypt_phi, decrypt_phi, EncryptionError, DecryptionError
from Clinic_app.Routes.admin import validate_e164_phone

logger = logging.getLogger(__name__)

# Email validation pattern (simple regex)
EMAIL_PATTERN = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')

# DOB format (YYYY-MM-DD)
DOB_PATTERN = re.compile(r'^\d{4}-\d{2}-\d{2}$')

# Valid languages
VALID_LANGUAGES = ["en", "es"]


def _compute_name_dob_hash(name: str, dob: str) -> str:
    """
    Compute SHA-256 hash of normalized name and DOB for efficient lookup.
    
    Args:
        name: Patient name (will be normalized)
        dob: Date of birth (will be normalized)
        
    Returns:
        64-character hex string (SHA-256 hash)
    """
    # Normalize name: lowercase and strip whitespace
    normalized_name = name.lower().strip()
    
    # Normalize DOB: strip whitespace
    normalized_dob = dob.strip()
    
    # Combine with pipe separator
    combined = f"{normalized_name}|{normalized_dob}"
    
    # Compute SHA-256 hash
    hash_bytes = hashlib.sha256(combined.encode('utf-8')).digest()
    hash_hex = hash_bytes.hex()
    
    return hash_hex


async def _validate_patient_inputs(
    db: AsyncSession,
    clinic_id: UUID,
    name: str,
    dob: str,
    phone: str,
    email: Optional[str] = None,
    language: str = "en"
) -> None:
    """
    Validate patient input parameters.
    
    Args:
        db: Database session
        clinic_id: Clinic UUID
        name: Patient name
        dob: Date of birth (YYYY-MM-DD format)
        phone: Phone number (E.164 format)
        email: Email address (optional)
        language: Language code ("en" or "es")
        
    Raises:
        ValueError: If any validation fails
    """
    # Validate clinic_id exists
    clinic_result = await db.execute(select(Clinic).where(Clinic.id == clinic_id))
    clinic = clinic_result.scalar_one_or_none()
    if not clinic:
        raise ValueError(f"Clinic with id {clinic_id} not found")
    
    # Validate name
    if not name or not name.strip():
        raise ValueError("Patient name cannot be empty")
    
    # Validate DOB format
    if not DOB_PATTERN.match(dob.strip()):
        raise ValueError("Date of birth must be in YYYY-MM-DD format")
    
    # Validate phone
    if not validate_e164_phone(phone):
        raise ValueError("Phone number must be in E.164 format (e.g., +15551234567)")
    
    # Validate email if provided
    if email is not None and email.strip():
        if not EMAIL_PATTERN.match(email.strip()):
            raise ValueError("Invalid email format")
    
    # Validate language
    if language not in VALID_LANGUAGES:
        raise ValueError(f"Language must be one of: {', '.join(VALID_LANGUAGES)}")


async def find_patient(
    db: AsyncSession,
    clinic_id: UUID,
    name: str,
    dob: str
) -> Optional[Patient]:
    """
    Find existing patient by name + DOB within clinic scope.
    
    Uses hash-based lookup for efficiency. Decrypts name and DOB to verify match
    (defense against hash collisions).
    
    Args:
        db: Database session
        clinic_id: Clinic UUID
        name: Patient name
        dob: Date of birth (YYYY-MM-DD format)
        
    Returns:
        Patient if found, None otherwise
        
    Raises:
        ValueError: If inputs are invalid
        DecryptionError: If decryption fails
    """
    # Validate inputs
    if not name or not name.strip():
        raise ValueError("Patient name cannot be empty")
    
    if not DOB_PATTERN.match(dob.strip()):
        raise ValueError("Date of birth must be in YYYY-MM-DD format")
    
    # Compute hash
    name_dob_hash = _compute_name_dob_hash(name, dob)
    
    logger.info(f"Looking up patient by hash in clinic {clinic_id} (hash: {name_dob_hash[:8]}...)")
    
    # Query database
    result = await db.execute(
        select(Patient).where(
            Patient.clinic_id == clinic_id,
            Patient.name_dob_hash == name_dob_hash
        )
    )
    patient = result.scalar_one_or_none()
    
    if not patient:
        logger.info(f"Patient not found for hash in clinic {clinic_id}")
        return None
    
    # Decrypt and verify match (defense against hash collisions)
    try:
        decrypted_name = decrypt_phi(patient.name_token)
        decrypted_dob = decrypt_phi(patient.dob_token)
        
        # Compare (case-insensitive for name, exact match for DOB)
        normalized_input_name = name.lower().strip()
        normalized_decrypted_name = decrypted_name.lower().strip()
        normalized_input_dob = dob.strip()
        normalized_decrypted_dob = decrypted_dob.strip()
        
        if normalized_input_name == normalized_decrypted_name and normalized_input_dob == normalized_decrypted_dob:
            logger.info(f"Patient found and verified: {patient.id} in clinic {clinic_id}")
            return patient
        else:
            # Hash collision detected
            logger.warning(
                f"Hash collision detected for clinic {clinic_id} (hash: {name_dob_hash[:8]}...). "
                "Name/DOB mismatch after decryption."
            )
            return None
            
    except DecryptionError as e:
        logger.error(f"Failed to decrypt patient PHI for verification: {str(e)}")
        raise DecryptionError(f"Failed to decrypt patient data for verification: {str(e)}")


async def create_patient(
    db: AsyncSession,
    clinic_id: UUID,
    name: str,
    dob: str,
    phone: str,
    email: Optional[str] = None,
    language: str = "en",
    insurance_plan: Optional[str] = None
) -> Patient:
    """
    Create new patient with encrypted PHI.
    
    Args:
        db: Database session
        clinic_id: Clinic UUID
        name: Patient name
        dob: Date of birth (YYYY-MM-DD format)
        phone: Phone number (E.164 format)
        email: Email address (optional)
        language: Language code ("en" or "es", default: "en")
        insurance_plan: Insurance plan information (optional)
        
    Returns:
        Created Patient instance
        
    Raises:
        ValueError: If inputs are invalid or patient already exists
        EncryptionError: If encryption fails
    """
    # Validate all inputs
    await _validate_patient_inputs(db, clinic_id, name, dob, phone, email, language)
    
    # Compute hash
    name_dob_hash = _compute_name_dob_hash(name, dob)
    
    logger.info(f"Creating patient in clinic {clinic_id} (hash: {name_dob_hash[:8]}...)")
    
    # Check if patient already exists
    existing_patient = await find_patient(db, clinic_id, name, dob)
    if existing_patient:
        raise ValueError("Patient already exists with this name and DOB")
    
    # Encrypt PHI
    try:
        name_token = encrypt_phi(name)
        dob_token = encrypt_phi(dob)
        phone_token = encrypt_phi(phone)
        email_token = encrypt_phi(email) if email and email.strip() else None
    except EncryptionError as e:
        logger.error(f"Failed to encrypt patient PHI: {str(e)}")
        raise EncryptionError(f"Failed to encrypt patient data: {str(e)}")
    
    # Create new Patient record
    patient = Patient(
        clinic_id=clinic_id,
        name_token=name_token,
        dob_token=dob_token,
        phone_token=phone_token,
        email_token=email_token,
        name_dob_hash=name_dob_hash,
        language=language,
        insurance_plan=insurance_plan
    )
    
    # Add to session
    db.add(patient)
    await db.flush()
    
    logger.info(f"Patient created successfully: {patient.id} in clinic {clinic_id}")
    
    return patient

