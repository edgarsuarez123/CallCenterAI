import base64
import hashlib
import hmac
import os
import secrets
import re
import logging
from typing import Tuple, List, Dict
from contextvars import ContextVar
from typing import Optional
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import func, select

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


# ---------- Request Context Management ----------
class RequestContext(BaseModel):
    """Request context for audit logging."""
    user_id: str = "system"
    ip_address: str = "127.0.0.1"
    request_id: Optional[str] = None

_request_context: ContextVar[RequestContext] = ContextVar(
    'request_context', 
    default=RequestContext()
)

def set_request_context(user_id: str, ip_address: str, request_id: Optional[str] = None):
    """Set the current request context."""
    _request_context.set(RequestContext(
        user_id=user_id, 
        ip_address=ip_address, 
        request_id=request_id
    ))

def get_request_context() -> RequestContext:
    """Get the current request context."""
    return _request_context.get()


# ---------- Text Tokenization (PHI Protection) ----------
PHONE_RE = re.compile(r"(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# Super simple "name" heuristic for demo (capitalized words). Replace later with better NER.
NAME_RE = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b")

async def tokenize_text(db: AsyncSession, call_id: str, text: str) -> Tuple[str, List[str], bool]:
    """
    Tokenize text by replacing PHI (phone numbers, emails, names) with tokens.
    
    Args:
        db: Database session
        call_id: ID of the call
        text: Text to tokenize
        
    Returns:
        Tuple of (tokenized_text, list_of_tokens, has_residual_phi)
    """
    tokens: List[str] = []
    residual_phi = False
    token_map: Dict[str, str] = {}

    # Phones (deterministic)
    for m in set(PHONE_RE.findall(text)):
        norm = normalize_phone(m)
        token = make_hmac_token("PHONE", norm)
        text = text.replace(m, token)
        token_map[token] = norm

    # Emails (deterministic)
    for m in set(EMAIL_RE.findall(text)):
        norm = normalize_email(m)
        token = make_hmac_token("EMAIL", norm)
        text = text.replace(m, token)
        token_map[token] = norm

    # Names (one-off): use ULID token
    for m in set(NAME_RE.findall(text)):
        norm = normalize_generic(m)
        token = make_ulid_token("PATIENT")
        text = text.replace(m, token)
        token_map[token] = norm

    # Store encrypted mappings using upsert pattern
    if token_map:
        # Prepare batch insert data
        insert_data = []
        for token, value in token_map.items():
            nonce, ct = encrypt_str(value)
            insert_data.append({
                'token': token,
                'value_nonce': nonce,
                'value_ciphertext': ct,
                'value_type': token.split("_", 1)[0],
                'call_id': call_id
            })
            tokens.append(token)
        
        # Batch upsert: insert new tokens or update last_used_at for existing ones
        try:
            from models.models import Mapping
            stmt = insert(Mapping).values(insert_data)
            stmt = stmt.on_conflict_do_update(
                index_elements=['token'],
                set_={
                    'last_used_at': func.now()
                    # Note: We DO NOT update call_id to preserve original for audit trail
                    # Note: We DO NOT update encrypted values (they should be identical anyway)
                }
            )
            await db.execute(stmt)
            
            # Commit with error handling
            try:
                await db.commit()
            except Exception as commit_error:
                await db.rollback()
                logging.error(f"Failed to commit token mappings: {commit_error}")
                # Continue execution - tokens are not critical for call flow
        except Exception as e:
            await db.rollback()
            logging.error(f"Failed to store token mappings: {e}")
            # Continue execution - tokens are not critical for call flow

    # Basic residual check: check tokenized text for any remaining PHI patterns
    if PHONE_RE.search(text) or EMAIL_RE.search(text) or NAME_RE.search(text):
        residual_phi = True

    return text, tokens, residual_phi

async def hydrate_text(db: AsyncSession, text_tokenized: str) -> Tuple[str, List[str]]:
    """
    Replace tokens with original values from DB.
    
    Args:
        db: Database session
        text_tokenized: Text with tokens
        
    Returns:
        Tuple of (hydrated_text, list_of_missing_tokens)
    """
    missing: List[str] = []
    # Find tokens by pattern KIND_HEX (we use 6+ uppercase hex chars)
    token_candidates = set(re.findall(r"\b([A-Z]+_[A-F0-9]{6,})\b", text_tokenized))
    if not token_candidates:
        return text_tokenized, missing

    from models.models import Mapping
    mappings_result = await db.execute(
        select(Mapping).where(Mapping.token.in_(list(token_candidates)))
    )
    mappings = {m.token: m for m in mappings_result.scalars().all()}

    result = text_tokenized
    for tok in token_candidates:
        m = mappings.get(tok)
        if not m:
            missing.append(tok)
            continue
        try:
            original = decrypt_str(m.value_nonce, m.value_ciphertext)
            result = result.replace(tok, original)
        except Exception as e:
            logging.warning(f"Failed to decrypt token {tok}: {e}")
            missing.append(tok)

    return result, missing
