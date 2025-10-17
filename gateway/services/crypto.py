import base64
import hashlib
import hmac
import os
import secrets
from typing import Tuple

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# Load keys from env; in Azure Mode, load from Key Vault (CMK) or managed identity
_CLINIC_HMAC_KEY = base64.b64decode(os.getenv("CLINIC_TOKEN_HMAC_KEY_BASE64", ""))
_AES_KEY = base64.b64decode(os.getenv("AES_GCM_KEY_BASE64", ""))

if not _CLINIC_HMAC_KEY or not _AES_KEY:
    raise RuntimeError("Missing crypto keys. Set CLINIC_TOKEN_HMAC_KEY_BASE64 and AES_GCM_KEY_BASE64")

# ---------- Token classes ----------
def to_token_class_name(kind: str) -> str:
    # Examples: PATIENT, PHONE, EMAIL, INSPLAN, DATE, TIME, APPT, PROVIDER
    return kind.upper()

def make_hmac_token(kind: str, normalized_value: str) -> str:
    """Deterministic token for repeatable identifiers."""
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
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    return f"+{digits}"

def normalize_email(value: str) -> str:
    return value.strip().lower()

def normalize_generic(value: str) -> str:
    return " ".join(value.strip().split())

# ---------- AES-GCM encrypt/decrypt ----------
def aesgcm_encrypt(plaintext: bytes) -> Tuple[bytes, bytes]:
    """Returns (nonce, ciphertext_with_tag)."""
    aesgcm = AESGCM(_AES_KEY)
    nonce = os.urandom(12)
    ct = aesgcm.encrypt(nonce, plaintext, associated_data=None)
    return nonce, ct

def aesgcm_decrypt(nonce: bytes, ciphertext: bytes) -> bytes:
    aesgcm = AESGCM(_AES_KEY)
    return aesgcm.decrypt(nonce, ciphertext, associated_data=None)

def encrypt_str(value: str) -> Tuple[bytes, bytes]:
    return aesgcm_encrypt(value.encode("utf-8"))

def decrypt_str(nonce: bytes, ciphertext: bytes) -> str:
    return aesgcm_decrypt(nonce, ciphertext).decode("utf-8")
