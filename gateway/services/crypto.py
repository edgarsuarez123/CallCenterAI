import base64
import hashlib
import hmac
import os
import secrets
from typing import Tuple

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# Load keys from configuration system
from services.configuration import get_settings
settings = get_settings()
_CLINIC_HMAC_KEY = base64.b64decode(settings.crypto.clinic_token_hmac_key_base64.get_secret_value())
_AES_KEY = base64.b64decode(settings.crypto.aes_gcm_key_base64.get_secret_value())

# ---------- Token classes ----------
def to_token_class_name(kind: str) -> str:
    # Examples: PATIENT, PHONE, EMAIL, INSPLAN, DATE, TIME, APPT, PROVIDER
    return kind.upper()

def make_hmac_token(kind: str, normalized_value: str) -> str:
    """Deterministic token for repeatable identifiers."""
    if not kind:
        raise ValueError("Token kind cannot be empty")
    if not normalized_value:
        raise ValueError("Normalized value cannot be empty")
    digest = hmac.new(_CLINIC_HMAC_KEY, normalized_value.encode("utf-8"), hashlib.sha256).hexdigest()[:12].upper()
    return f"{to_token_class_name(kind)}_{digest}"

def make_ulid_token(kind: str) -> str:
    """ULID-like sortable token for one-off items (names, appointment instances)."""
    # Lightweight ULID: 26 base32 chars � here we�ll approximate with 20 hex chars for demo simplicity
    rnd = secrets.token_hex(10).upper()
    return f"{to_token_class_name(kind)}_{rnd}"

def make_unique_audit_log_id() -> str:
    """Generate a truly unique audit log ID using timestamp + random."""
    import time
    import uuid
    
    # Use timestamp for uniqueness and UUID for additional randomness
    timestamp = str(int(time.time() * 1000))  # milliseconds for better uniqueness
    uuid_part = str(uuid.uuid4()).replace('-', '')[:8]  # First 8 chars of UUID
    
    return f"LOG_AUDIT_{timestamp}_{uuid_part}"

# ---------- Normalizers ----------
def normalize_phone(value: str) -> str:
    """Normalize phone number to international format."""
    if not value:
        raise ValueError("Phone number cannot be empty")
    digits = "".join(ch for ch in value if ch.isdigit())
    if not digits:
        raise ValueError("Phone number must contain at least one digit")
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    return f"+{digits}"

def normalize_email(value: str) -> str:
    """Normalize email address to lowercase."""
    if not value:
        raise ValueError("Email cannot be empty")
    normalized = value.strip().lower()
    if not normalized:
        raise ValueError("Email cannot be empty after normalization")
    return normalized

def normalize_generic(value: str) -> str:
    """Normalize generic text value."""
    if not value:
        raise ValueError("Value cannot be empty")
    normalized = " ".join(value.strip().split())
    if not normalized:
        raise ValueError("Value cannot be empty after normalization")
    return normalized

# ---------- AES-GCM encrypt/decrypt ----------
def aesgcm_encrypt(plaintext: bytes) -> Tuple[bytes, bytes]:
    """Returns (nonce, ciphertext_with_tag)."""
    aesgcm = AESGCM(_AES_KEY)
    nonce = os.urandom(12)
    ct = aesgcm.encrypt(nonce, plaintext, associated_data=None)
    return nonce, ct

def aesgcm_decrypt(nonce: bytes, ciphertext: bytes) -> bytes:
    """Decrypt ciphertext using AES-GCM."""
    if not nonce:
        raise ValueError("Nonce cannot be empty")
    if not ciphertext:
        raise ValueError("Ciphertext cannot be empty")
    try:
        aesgcm = AESGCM(_AES_KEY)
        return aesgcm.decrypt(nonce, ciphertext, associated_data=None)
    except Exception as e:
        raise ValueError(f"Decryption failed: {str(e)}")

def encrypt_str(value: str) -> Tuple[bytes, bytes]:
    """Encrypt a string value."""
    if value is None:
        raise ValueError("Value cannot be None")
    try:
        return aesgcm_encrypt(value.encode("utf-8"))
    except Exception as e:
        raise ValueError(f"Encryption failed: {str(e)}")

def decrypt_str(nonce: bytes, ciphertext: bytes) -> str:
    """Decrypt a string value."""
    try:
        return aesgcm_decrypt(nonce, ciphertext).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as e:
        raise ValueError(f"Decryption failed: {str(e)}")
