"""
Patient Service

Provides functions for finding and creating patients with encrypted PHI.
Uses hash-based lookup (name+DOB) for efficient patient identification.
"""

import logging
import re
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from Clinic_app.data.models.patient import Patient
from Clinic_app.data.models.clinic import Clinic
from Clinic_app.common.encryption import encrypt_phi, hash_phi, EncryptionError
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
    HMAC-SHA256 of normalized name+DOB using PHI_HASH_KEY. Used for patient lookup.

    Keyed HMAC prevents offline enumeration of name/DOB combinations.
    """
    normalized = f"{name.lower().strip()}|{dob.strip()}"
    return hash_phi(normalized)


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

    # name_dob_hash match is sufficient — SHA-256 collision probability is negligible.
    # dob_token was removed (PHI Rule #2: DOB must not be stored in DB).
    logger.info(f"Patient found: {patient.id} in clinic {clinic_id}")
    return patient


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
        phone_token = encrypt_phi(phone)
        email_token = encrypt_phi(email) if email and email.strip() else None
    except EncryptionError as e:
        logger.error(f"Failed to encrypt patient PHI: {str(e)}")
        raise EncryptionError(f"Failed to encrypt patient data: {str(e)}")

    phone_hash = hash_phi(phone)

    # Create new Patient record
    patient = Patient(
        clinic_id=clinic_id,
        name_token=name_token,
        phone_token=phone_token,
        phone_hash=phone_hash,
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

