"""
PHI Encryption Utilities

Provides AES-256-GCM encryption for Protected Health Information (PHI).
Used to encrypt patient names and dates of birth before storing in database.

Phase 1: Uses environment variable for encryption key
Phase 2: Will migrate to Azure Key Vault
"""

import os
import base64
import logging
from typing import Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger(__name__)

# Module-level key cache for performance
_encryption_key: Optional[bytes] = None

# Constants
KEY_SIZE_BYTES = 32
IV_SIZE_BYTES = 12
AUTH_TAG_SIZE_BYTES = 16


# Custom Exceptions

class EncryptionError(Exception):
    """Base exception for encryption operations."""
    pass


class EncryptionKeyError(EncryptionError):
    """Encryption key is missing or invalid."""
    pass


class DecryptionError(EncryptionError):
    """Decryption failed."""
    pass


class AuthenticationError(DecryptionError):
    """Authentication tag verification failed (possible tampering)."""
    pass


# Key Management

def get_encryption_key() -> bytes:
    """
    Get encryption key from environment variable.
    
    Supports both Base64 and hex encoding. Key is cached after first access.
    
    Returns:
        32-byte encryption key
        
    Raises:
        EncryptionKeyError: If key is missing or invalid
    """
    global _encryption_key
    
    # Return cached key if available
    if _encryption_key is not None:
        return _encryption_key
    
    # Read from environment
    key_str = os.getenv("PHI_ENCRYPTION_KEY")
    if not key_str:
        logger.error("PHI_ENCRYPTION_KEY environment variable is not set")
        raise EncryptionKeyError(
            "PHI_ENCRYPTION_KEY environment variable is required. "
            "Set it to a 32-byte key encoded in Base64 or hex format."
        )
    
    # Try to decode as Base64 first
    try:
        key_bytes = base64.b64decode(key_str, validate=True)
        logger.debug("Encryption key decoded from Base64 format")
    except Exception:
        # Try hex encoding
        try:
            key_bytes = bytes.fromhex(key_str)
            logger.debug("Encryption key decoded from hex format")
        except Exception as e:
            logger.error(f"Failed to decode encryption key: {str(e)}")
            raise EncryptionKeyError(
                "PHI_ENCRYPTION_KEY must be a 32-byte key encoded in Base64 or hex format. "
                f"Failed to decode: {str(e)}"
            )
    
    # Validate key size
    if len(key_bytes) != KEY_SIZE_BYTES:
        logger.error(f"Encryption key has invalid size: {len(key_bytes)} bytes (expected {KEY_SIZE_BYTES})")
        raise EncryptionKeyError(
            f"Encryption key must be exactly {KEY_SIZE_BYTES} bytes. "
            f"Received {len(key_bytes)} bytes."
        )
    
    # Cache the key
    _encryption_key = key_bytes
    logger.info("Encryption key loaded and validated successfully")
    
    return _encryption_key


# Encryption Functions

def encrypt_phi(plaintext: str) -> bytes:
    """
    Encrypt PHI data using AES-256-GCM.
    
    Args:
        plaintext: Plain text string to encrypt (patient name or DOB)
        
    Returns:
        Encrypted bytes in format: IV (12 bytes) + ciphertext + auth_tag (16 bytes)
        
    Raises:
        EncryptionError: If encryption fails
        EncryptionKeyError: If encryption key is invalid
    """
    try:
        # Get encryption key
        key = get_encryption_key()
        
        # Generate random IV/nonce (12 bytes for GCM)
        iv = os.urandom(IV_SIZE_BYTES)
        
        # Create AESGCM cipher
        aesgcm = AESGCM(key)
        
        # Encrypt (GCM mode automatically generates and appends auth tag)
        # Associated data is empty (can add metadata in Phase 2 if needed)
        ciphertext_with_tag = aesgcm.encrypt(iv, plaintext.encode('utf-8'), None)
        
        # Combine: IV + ciphertext + auth_tag
        # GCM returns ciphertext + tag together, so: IV + (ciphertext + tag)
        encrypted = iv + ciphertext_with_tag
        
        logger.debug("PHI encrypted successfully")
        return encrypted
        
    except EncryptionKeyError:
        # Re-raise key errors as-is
        raise
    except Exception as e:
        logger.error(f"Encryption failed: {str(e)}", exc_info=True)
        raise EncryptionError(f"Failed to encrypt PHI: {str(e)}")


def decrypt_phi(encrypted: bytes) -> str:
    """
    Decrypt PHI data using AES-256-GCM.
    
    Args:
        encrypted: Encrypted bytes from database (format: IV + ciphertext + auth_tag)
        
    Returns:
        Decrypted plain text string
        
    Raises:
        DecryptionError: If decryption fails
        AuthenticationError: If authentication tag verification fails (tampering detected)
        EncryptionKeyError: If encryption key is invalid
    """
    try:
        # Validate minimum size (IV + at least 1 byte ciphertext + auth tag)
        min_size = IV_SIZE_BYTES + 1 + AUTH_TAG_SIZE_BYTES
        if len(encrypted) < min_size:
            logger.error(f"Encrypted data too short: {len(encrypted)} bytes (minimum {min_size})")
            raise DecryptionError(
                f"Encrypted data is too short: {len(encrypted)} bytes. "
                f"Expected at least {min_size} bytes."
            )
        
        # Get encryption key
        key = get_encryption_key()
        
        # Extract components
        iv = encrypted[:IV_SIZE_BYTES]
        ciphertext_with_tag = encrypted[IV_SIZE_BYTES:]
        
        # Create AESGCM cipher
        aesgcm = AESGCM(key)
        
        # Decrypt (GCM automatically verifies auth tag)
        # Associated data is empty (must match encryption)
        try:
            plaintext_bytes = aesgcm.decrypt(iv, ciphertext_with_tag, None)
        except Exception as e:
            # GCM will raise exception if auth tag verification fails
            logger.warning("Authentication tag verification failed - possible tampering detected")
            raise AuthenticationError(
                "Authentication tag verification failed. "
                "The encrypted data may have been tampered with."
            )
        
        # Decode to string
        plaintext = plaintext_bytes.decode('utf-8')
        
        logger.debug("PHI decrypted successfully")
        return plaintext
        
    except (AuthenticationError, EncryptionKeyError):
        # Re-raise specific errors as-is
        raise
    except DecryptionError:
        # Re-raise decryption errors as-is
        raise
    except Exception as e:
        logger.error(f"Decryption failed: {str(e)}", exc_info=True)
        raise DecryptionError(f"Failed to decrypt PHI: {str(e)}")

