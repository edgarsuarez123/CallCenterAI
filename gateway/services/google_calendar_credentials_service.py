"""
Google Calendar Credentials Service
Manages secure storage and retrieval of Google Calendar OAuth credentials.
"""

import logging
from typing import Optional, Dict, Any
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from google.oauth2.credentials import Credentials

from models.models import GoogleCalendarCredentials
from services.crypto import aesgcm_encrypt, aesgcm_decrypt, make_ulid_token

logger = logging.getLogger(__name__)


class GoogleCalendarCredentialsService:
    """Service for managing Google Calendar OAuth credentials in the database."""
    
    def __init__(self, db: Session):
        self.db = db
        self.logger = logging.getLogger(__name__)
    
    def store_credentials(self, provider_id: str, credentials: Credentials) -> bool:
        """
        Store Google Calendar credentials for a provider.
        
        Args:
            provider_id: Provider ID
            credentials: Google OAuth credentials object
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Check if credentials already exist
            existing = self.db.query(GoogleCalendarCredentials).filter(
                GoogleCalendarCredentials.provider_id == provider_id
            ).first()
            
            if existing:
                # Update existing credentials
                credential_record = existing
                credential_record.updated_at = datetime.now(timezone.utc)
            else:
                # Create new credentials record
                credential_id = f"GCC_{make_ulid_token('GCC')[:12]}"
                credential_record = GoogleCalendarCredentials(
                    credential_id=credential_id,
                    provider_id=provider_id,
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc)
                )
                self.db.add(credential_record)
            
            # Encrypt and store access token
            if credentials.token:
                access_token_nonce, access_token_ciphertext = aesgcm_encrypt(credentials.token.encode('utf-8'))
                credential_record.access_token_nonce = access_token_nonce
                credential_record.access_token_ciphertext = access_token_ciphertext
            
            # Encrypt and store refresh token
            if credentials.refresh_token:
                refresh_token_nonce, refresh_token_ciphertext = aesgcm_encrypt(credentials.refresh_token.encode('utf-8'))
                credential_record.refresh_token_nonce = refresh_token_nonce
                credential_record.refresh_token_ciphertext = refresh_token_ciphertext
            
            # Store metadata - ensure expiry is timezone-aware
            if credentials.expiry:
                if credentials.expiry.tzinfo is None:
                    credential_record.token_expires_at = credentials.expiry.replace(tzinfo=timezone.utc)
                else:
                    credential_record.token_expires_at = credentials.expiry
            else:
                credential_record.token_expires_at = None
            credential_record.scope = ' '.join(credentials.scopes) if credentials.scopes else ''
            credential_record.is_active = True
            credential_record.last_used_at = datetime.now(timezone.utc)
            
            self.db.commit()
            self.logger.info(f"Successfully stored Google Calendar credentials for provider {provider_id}")
            return True
            
        except Exception as e:
            self.db.rollback()
            self.logger.error(f"Failed to store credentials for provider {provider_id}: {e}")
            return False
    
    def get_credentials(self, provider_id: str) -> Optional[Credentials]:
        """
        Retrieve Google Calendar credentials for a provider.
        
        Args:
            provider_id: Provider ID
            
        Returns:
            Google OAuth credentials object or None if not found/expired
        """
        try:
            credential_record = self.db.query(GoogleCalendarCredentials).filter(
                GoogleCalendarCredentials.provider_id == provider_id,
                GoogleCalendarCredentials.is_active == True
            ).first()
            
            if not credential_record:
                self.logger.warning(f"No active credentials found for provider {provider_id}")
                return None
            
            # Check if token is expired
            if credential_record.token_expires_at:
                # Ensure both datetimes are timezone-aware for comparison
                expires_at = credential_record.token_expires_at
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)
                if expires_at < datetime.now(timezone.utc):
                    self.logger.warning(f"Credentials expired for provider {provider_id}")
                    # Mark as inactive
                    credential_record.is_active = False
                    self.db.commit()
                    return None
            
            # Decrypt access token
            access_token = None
            if credential_record.access_token_nonce and credential_record.access_token_ciphertext:
                access_token = aesgcm_decrypt(
                    credential_record.access_token_nonce,
                    credential_record.access_token_ciphertext
                ).decode('utf-8')
            
            # Decrypt refresh token
            refresh_token = None
            if credential_record.refresh_token_nonce and credential_record.refresh_token_ciphertext:
                refresh_token = aesgcm_decrypt(
                    credential_record.refresh_token_nonce,
                    credential_record.refresh_token_ciphertext
                ).decode('utf-8')
            
            # Create credentials object - ensure expiry is timezone-naive for Google auth library
            expiry_time = None
            if credential_record.token_expires_at:
                if credential_record.token_expires_at.tzinfo is not None:
                    expiry_time = credential_record.token_expires_at.replace(tzinfo=None)
                else:
                    expiry_time = credential_record.token_expires_at
            
            credentials = Credentials(
                token=access_token,
                refresh_token=refresh_token,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=None,  # Will be set by the calling service
                client_secret=None,  # Will be set by the calling service
                scopes=credential_record.scope.split() if credential_record.scope else [],
                expiry=expiry_time
            )
            
            # Update last used timestamp
            credential_record.last_used_at = datetime.now(timezone.utc)
            self.db.commit()
            
            self.logger.info(f"Successfully retrieved credentials for provider {provider_id}")
            return credentials
            
        except Exception as e:
            self.logger.error(f"Failed to retrieve credentials for provider {provider_id}: {e}")
            return None
    
    def revoke_credentials(self, provider_id: str) -> bool:
        """
        Revoke/deactivate Google Calendar credentials for a provider.
        
        Args:
            provider_id: Provider ID
            
        Returns:
            True if successful, False otherwise
        """
        try:
            credential_record = self.db.query(GoogleCalendarCredentials).filter(
                GoogleCalendarCredentials.provider_id == provider_id
            ).first()
            
            if credential_record:
                credential_record.is_active = False
                credential_record.updated_at = datetime.now(timezone.utc)
                self.db.commit()
                self.logger.info(f"Successfully revoked credentials for provider {provider_id}")
                return True
            else:
                self.logger.warning(f"No credentials found to revoke for provider {provider_id}")
                return False
                
        except Exception as e:
            self.db.rollback()
            self.logger.error(f"Failed to revoke credentials for provider {provider_id}: {e}")
            return False
    
    def get_credentials_status(self, provider_id: str) -> Dict[str, Any]:
        """
        Get the status of Google Calendar credentials for a provider.
        
        Args:
            provider_id: Provider ID
            
        Returns:
            Dictionary with credential status information
        """
        try:
            credential_record = self.db.query(GoogleCalendarCredentials).filter(
                GoogleCalendarCredentials.provider_id == provider_id
            ).first()
            
            if not credential_record:
                return {
                    "has_credentials": False,
                    "is_active": False,
                    "is_expired": False,
                    "last_used": None,
                    "created_at": None
                }
            
            is_expired = False
            if credential_record.token_expires_at:
                # Ensure both datetimes are timezone-aware for comparison
                expires_at = credential_record.token_expires_at
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)
                is_expired = expires_at < datetime.now(timezone.utc)
            
            return {
                "has_credentials": True,
                "is_active": credential_record.is_active and not is_expired,
                "is_expired": is_expired,
                "last_used": credential_record.last_used_at,
                "created_at": credential_record.created_at,
                "expires_at": credential_record.token_expires_at,
                "scope": credential_record.scope
            }
            
        except Exception as e:
            self.logger.error(f"Failed to get credentials status for provider {provider_id}: {e}")
            return {
                "has_credentials": False,
                "is_active": False,
                "is_expired": False,
                "last_used": None,
                "created_at": None,
                "error": str(e)
            }
