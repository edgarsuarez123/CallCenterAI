"""
Azure Communication Services integration for telephony and call management.

This service provides:
- Call initiation and management
- Webhook handling for ACS events
- Audio streaming coordination
- Integration with existing call flow system
"""

import asyncio
import hashlib
import hmac
import json
import logging
import uuid
from datetime import datetime, timezone, timezone
from typing import Dict, List, Optional, Any, Tuple
from urllib.parse import urlencode

import httpx
from fastapi import Request, HTTPException, status
from sqlalchemy.orm import Session

from services.configuration import get_settings
from services.structured_logging import get_logger, LogCategory, log_performance
from services.exceptions import (
    AzureCommunicationError,
    CallNotFoundError,
    ValidationError,
    ExternalServiceUnavailableError
)
from models.models import Call, Clinic, ClinicLicense, Mapping
from models.enums import CallStatus
from services.database import get_db_session
from services.crypto import make_hmac_token, normalize_phone, encrypt_str
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import func


logger = get_logger("azure_communication_service")


class CallState:
    """Represents the state of an active call."""
    
    def __init__(self, call_id: str, clinic_id: str, caller_phone: str):
        self.call_id = call_id
        self.clinic_id = clinic_id
        self.caller_phone = caller_phone
        self.acs_call_id: Optional[str] = None
        self.status = CallStatus.INITIATED.value
        self.start_time = datetime.now(timezone.utc)
        self.end_time: Optional[datetime] = None
        self.websocket_connected = False
        self.audio_stream_active = False
        self.language_detected: Optional[str] = None
        self.language_locked = False
        self.conversation_history: List[Dict[str, str]] = []
        self.metadata: Dict[str, Any] = {}


class AzureCommunicationService:
    """
    Service for managing Azure Communication Services integration.
    
    Provides call management, webhook handling, and audio streaming coordination.
    """
    
    def __init__(self):
        self.settings = get_settings()
        self.logger = logger
        self.active_calls: Dict[str, CallState] = {}
        self._calls_lock = asyncio.Lock()  # ADD LOCK FOR THREAD SAFETY
        self.http_client = httpx.AsyncClient(timeout=30.0)
        self._closed = False
        
        # ACS configuration
        self.connection_string = self.settings.azure.communication.connection_string.get_secret_value()
        self.phone_number = self.settings.azure.communication.phone_number
        self.callback_url = self.settings.azure.communication.callback_url
        self.webhook_secret = self.settings.azure.communication.webhook_secret.get_secret_value()
        
        # Extract endpoint and access key from connection string
        self._parse_connection_string()
    
    def _parse_connection_string(self):
        """Parse ACS connection string to extract endpoint and access key."""
        try:
            parts = self.connection_string.split(';')
            self.endpoint = None
            self.access_key = None
            
            for part in parts:
                if part.startswith('endpoint='):
                    self.endpoint = part.split('=', 1)[1]
                elif part.startswith('accesskey='):
                    self.access_key = part.split('=', 1)[1]
            
            if not self.endpoint or not self.access_key:
                raise ValueError("Invalid ACS connection string format")
                
            # Ensure endpoint ends with /
            if not self.endpoint.endswith('/'):
                self.endpoint += '/'
                
        except Exception as e:
            self.logger.error(f"Failed to parse ACS connection string: {e}")
            raise AzureCommunicationError("connection_parsing", str(e))
    
    def _get_auth_headers(self) -> Dict[str, str]:
        """Generate authentication headers for ACS API calls."""
        return {
            "Authorization": f"Bearer {self.access_key}",
            "Content-Type": "application/json",
            "User-Agent": "CallCenterAI/1.0"
        }
    
    @log_performance("acs_call_initiation")
    async def initialize_call(self, phone_number: str, clinic_id: str, 
                            call_type: str = "inbound") -> Tuple[str, str]:
        """
        Initialize a new call with Azure Communication Services.
        
        Args:
            phone_number: Phone number to call (for outbound) or caller's number (for inbound)
            clinic_id: ID of the clinic handling the call
            call_type: Type of call ("inbound" or "outbound")
            
        Returns:
            Tuple of (call_id, acs_call_id)
            
        Raises:
            AzureCommunicationError: If call initialization fails
            ValidationError: If input validation fails
        """
        try:
            # Validate inputs
            if not phone_number or not phone_number.startswith('+'):
                raise ValidationError("phone_number", phone_number, "Phone number must include country code")
            
            if not clinic_id:
                raise ValidationError("clinic_id", clinic_id, "Clinic ID is required")
            
            # Generate unique call ID
            call_id = f"CALL_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8].upper()}"
            
            # Check clinic capacity
            await self._check_clinic_capacity(clinic_id)
            
            # Create call state
            call_state = CallState(call_id, clinic_id, phone_number)
            call_state.status = "initiating"
            async with self._calls_lock:
                self.active_calls[call_id] = call_state
            
            # Prepare ACS call request
            if call_type == "outbound":
                acs_call_id = await self._initiate_outbound_call(phone_number, call_id)
            else:
                # For inbound calls, ACS will provide the call ID via webhook
                acs_call_id = None
            
            call_state.acs_call_id = acs_call_id
            call_state.status = CallStatus.ACTIVE.value
            
            # Store call in database
            await self._store_call_record(call_id, phone_number, clinic_id, call_type)
            
            self.logger.info(
                f"Call initialized successfully: {call_id}",
                LogCategory.AZURE_COMMUNICATION,
                extra_data={
                    "call_id": call_id,
                    "acs_call_id": acs_call_id,
                    "clinic_id": clinic_id,
                    "call_type": call_type,
                    "phone_number": phone_number[:3] + "***" + phone_number[-4:]  # Masked for privacy
                }
            )
            
            return call_id, acs_call_id or "pending"
            
        except Exception as e:
            self.logger.error(
                f"Failed to initialize call: {e}",
                LogCategory.AZURE_COMMUNICATION,
                exception=e,
                extra_data={
                    "phone_number": phone_number[:3] + "***" + phone_number[-4:] if phone_number else None,
                    "clinic_id": clinic_id,
                    "call_type": call_type
                }
            )
            
            if isinstance(e, (ValidationError, AzureCommunicationError)):
                raise
            else:
                raise AzureCommunicationError("call_initialization", str(e))
    
    async def _initiate_outbound_call(self, phone_number: str, call_id: str) -> str:
        """Initiate an outbound call via ACS."""
        try:
            # Prepare call request payload
            payload = {
                "source": {
                    "phoneNumber": self.phone_number
                },
                "target": {
                    "phoneNumber": phone_number
                },
                "callbackUri": f"{self.callback_url}?call_id={call_id}",
                "mediaStreamingConfiguration": {
                    "transportUrl": f"{self.callback_url.replace('/webhooks/events', '/ws/audio')}/{call_id}",
                    "transportType": "websocket",
                    "audioChannelType": "mixed"
                }
            }
            
            # Make API call to ACS
            url = f"{self.endpoint}calling/callConnections"
            headers = self._get_auth_headers()
            
            async with self.http_client.post(url, json=payload, headers=headers) as response:
                if response.status_code not in [200, 201]:
                    error_text = await response.aread()
                    raise AzureCommunicationError(
                        "outbound_call_failed",
                        f"ACS API returned {response.status_code}: {error_text.decode()}"
                    )
                
                result = response.json()
                acs_call_id = result.get("callConnectionId")
                
                if not acs_call_id:
                    raise AzureCommunicationError("outbound_call_failed", "No call ID returned from ACS")
                
                return acs_call_id
                
        except httpx.RequestError as e:
            raise ExternalServiceUnavailableError("Azure Communication Services", str(e))
        except Exception as e:
            if isinstance(e, AzureCommunicationError):
                raise
            raise AzureCommunicationError("outbound_call_failed", str(e))
    
    async def _check_clinic_capacity(self, clinic_id: str):
        """Check if clinic has capacity for new calls."""
        try:
            with get_db_session() as db:
                # Get clinic license
                license_record = db.query(ClinicLicense).filter_by(clinic_id=clinic_id).first()
                if not license_record:
                    raise AzureCommunicationError("clinic_not_found", f"Clinic {clinic_id} not found")
                
                # Check if license is active
                if license_record.license_status != "active":
                    raise AzureCommunicationError(
                        "license_suspended",
                        f"Clinic {clinic_id} license is {license_record.license_status}"
                    )
                
                # Check concurrent call limit
                if license_record.current_concurrent_calls >= license_record.max_concurrent_calls:
                    raise AzureCommunicationError(
                        "capacity_exceeded",
                        f"Clinic {clinic_id} at capacity ({license_record.current_concurrent_calls}/{license_record.max_concurrent_calls})"
                    )
                
                # Increment concurrent call count
                license_record.current_concurrent_calls += 1
                db.commit()
                
        except Exception as e:
            if isinstance(e, AzureCommunicationError):
                raise
            raise AzureCommunicationError("capacity_check_failed", str(e))
    
    async def _store_call_record(self, call_id: str, phone_number: str, clinic_id: str, call_type: str):
        """Store call record in database with tokenized phone number."""
        try:
            with get_db_session() as db:
                # Tokenize phone number for HIPAA compliance
                normalized_phone = normalize_phone(phone_number)
                phone_token = make_hmac_token("PHONE", normalized_phone)
                
                # Store encrypted phone in mappings table
                nonce, ct = encrypt_str(normalized_phone)
                
                stmt = insert(Mapping).values({
                    'token': phone_token,
                    'value_nonce': nonce,
                    'value_ciphertext': ct,
                    'value_type': 'PHONE',
                    'call_id': call_id
                })
                stmt = stmt.on_conflict_do_update(
                    index_elements=['token'],
                    set_={'last_used_at': func.now()}
                )
                db.execute(stmt)
                
                # Create call record with tokenized phone
                call_record = Call(
                    call_sid=call_id,  # Using our call_id as call_sid for now
                    call_id=call_id,
                    caller_phone_token=phone_token,  # Now properly tokenized
                    status=CallStatus.ACTIVE.value,
                    started_at=datetime.now(timezone.utc)
                )
                
                db.add(call_record)
                db.commit()
                
        except Exception as e:
            self.logger.error(f"Failed to store call record: {e}")
            # Don't raise here as the call is already active
    
    async def answer_call(self, call_id: str) -> bool:
        """
        Answer an inbound call.
        
        Args:
            call_id: ID of the call to answer
            
        Returns:
            True if call was answered successfully
            
        Raises:
            CallNotFoundError: If call is not found
            AzureCommunicationError: If answering fails
        """
        try:
            async with self._calls_lock:
                call_state = self.active_calls.get(call_id)
            if not call_state:
                raise CallNotFoundError(call_id)
            
            if not call_state.acs_call_id:
                raise AzureCommunicationError("no_acs_call_id", "ACS call ID not available")
            
            # Answer the call via ACS API
            url = f"{self.endpoint}calling/callConnections/{call_state.acs_call_id}:answer"
            headers = self._get_auth_headers()
            
            payload = {
                "callbackUri": f"{self.callback_url}?call_id={call_id}",
                "mediaStreamingConfiguration": {
                    "transportUrl": f"{self.callback_url.replace('/webhooks/events', '/ws/audio')}/{call_id}",
                    "transportType": "websocket",
                    "audioChannelType": "mixed"
                }
            }
            
            async with self.http_client.post(url, json=payload, headers=headers) as response:
                if response.status_code not in [200, 202]:
                    error_text = await response.aread()
                    raise AzureCommunicationError(
                        "answer_call_failed",
                        f"ACS API returned {response.status_code}: {error_text.decode()}"
                    )
            
            call_state.status = CallStatus.ANSWERED.value
            
            self.logger.info(
                f"Call answered successfully: {call_id}",
                LogCategory.AZURE_COMMUNICATION,
                extra_data={"call_id": call_id, "acs_call_id": call_state.acs_call_id}
            )
            
            return True
            
        except Exception as e:
            self.logger.error(
                f"Failed to answer call {call_id}: {e}",
                LogCategory.AZURE_COMMUNICATION,
                exception=e
            )
            
            if isinstance(e, (CallNotFoundError, AzureCommunicationError)):
                raise
            else:
                raise AzureCommunicationError("answer_call_failed", str(e))
    
    async def end_call(self, call_id: str, reason: str = "completed") -> bool:
        """
        End a call.
        
        Args:
            call_id: ID of the call to end
            reason: Reason for ending the call
            
        Returns:
            True if call was ended successfully
        """
        try:
            call_state = self.active_calls.get(call_id)
            if not call_state:
                self.logger.warning(f"Attempted to end non-existent call: {call_id}")
                return False
            
            if call_state.acs_call_id:
                # End call via ACS API
                url = f"{self.endpoint}calling/callConnections/{call_state.acs_call_id}:hangup"
                headers = self._get_auth_headers()
                
                async with self.http_client.post(url, json={}, headers=headers) as response:
                    if response.status_code not in [200, 202]:
                        error_text = await response.aread()
                        self.logger.warning(
                            f"ACS hangup API returned {response.status_code}: {error_text.decode()}"
                        )
            
            # Update call state
            call_state.status = "ended"
            call_state.end_time = datetime.now(timezone.utc)
            
            # Update database
            await self._update_call_record(call_id, "completed", call_state.end_time)
            
            # Decrement clinic capacity
            await self._decrement_clinic_capacity(call_state.clinic_id)
            
            # Remove from active calls
            async with self._calls_lock:
                del self.active_calls[call_id]
            
            self.logger.info(
                f"Call ended successfully: {call_id}",
                LogCategory.AZURE_COMMUNICATION,
                extra_data={
                    "call_id": call_id,
                    "reason": reason,
                    "duration_seconds": (call_state.end_time - call_state.start_time).total_seconds()
                }
            )
            
            return True
            
        except Exception as e:
            self.logger.error(
                f"Failed to end call {call_id}: {e}",
                LogCategory.AZURE_COMMUNICATION,
                exception=e
            )
            return False
    
    async def _update_call_record(self, call_id: str, status: str, end_time: datetime):
        """Update call record in database."""
        try:
            with get_db_session() as db:
                call_record = db.query(Call).filter_by(call_id=call_id).first()
                if call_record:
                    call_record.status = status
                    call_record.ended_at = end_time
                    db.commit()
        except Exception as e:
            self.logger.error(f"Failed to update call record: {e}")
    
    async def _decrement_clinic_capacity(self, clinic_id: str):
        """Decrement clinic's concurrent call count."""
        try:
            with get_db_session() as db:
                license_record = db.query(ClinicLicense).filter_by(clinic_id=clinic_id).first()
                if license_record and license_record.current_concurrent_calls > 0:
                    license_record.current_concurrent_calls -= 1
                    db.commit()
        except Exception as e:
            self.logger.error(f"Failed to decrement clinic capacity: {e}")
    
    async def start_audio_stream(self, call_id: str) -> bool:
        """
        Start audio streaming for a call.
        
        Args:
            call_id: ID of the call
            
        Returns:
            True if audio streaming started successfully
        """
        try:
            call_state = self.active_calls.get(call_id)
            if not call_state:
                raise CallNotFoundError(call_id)
            
            call_state.audio_stream_active = True
            
            self.logger.info(
                f"Audio streaming started for call: {call_id}",
                LogCategory.AZURE_COMMUNICATION,
                extra_data={"call_id": call_id}
            )
            
            return True
            
        except Exception as e:
            self.logger.error(
                f"Failed to start audio stream for call {call_id}: {e}",
                LogCategory.AZURE_COMMUNICATION,
                exception=e
            )
            return False
    
    async def send_audio_chunk(self, call_id: str, audio_data: bytes) -> bool:
        """
        Send audio chunk to ACS for TTS playback.
        
        Args:
            call_id: ID of the call
            audio_data: Audio data to send
            
        Returns:
            True if audio was sent successfully
        """
        try:
            call_state = self.active_calls.get(call_id)
            if not call_state or not call_state.acs_call_id:
                return False
            
            # In a real implementation, this would send audio via WebSocket
            # For now, we'll just log the action
            self.logger.debug(
                f"Audio chunk sent for call: {call_id}",
                LogCategory.AZURE_COMMUNICATION,
                extra_data={
                    "call_id": call_id,
                    "audio_size_bytes": len(audio_data)
                }
            )
            
            return True
            
        except Exception as e:
            self.logger.error(
                f"Failed to send audio chunk for call {call_id}: {e}",
                LogCategory.AZURE_COMMUNICATION,
                exception=e
            )
            return False
    
    def verify_webhook_signature(self, request: Request, payload: bytes) -> bool:
        """
        Verify webhook signature from ACS.
        
        Args:
            request: FastAPI request object
            payload: Raw request payload
            
        Returns:
            True if signature is valid
        """
        try:
            # Get signature from headers
            signature = request.headers.get("x-ms-signature")
            if not signature:
                self.logger.warning("No signature found in webhook request")
                return False
            
            # Calculate expected signature
            expected_signature = hmac.new(
                self.webhook_secret.encode(),
                payload,
                hashlib.sha256
            ).hexdigest()
            
            # Compare signatures
            is_valid = hmac.compare_digest(signature, expected_signature)
            
            if not is_valid:
                self.logger.warning("Invalid webhook signature")
            
            return is_valid
            
        except Exception as e:
            self.logger.error(f"Failed to verify webhook signature: {e}")
            return False
    
    async def handle_webhook_event(self, request: Request, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle webhook events from ACS.
        
        Args:
            request: FastAPI request object
            payload: Parsed webhook payload
            
        Returns:
            Response data
        """
        try:
            event_type = payload.get("eventType")
            call_connection_id = payload.get("callConnectionId")
            
            self.logger.info(
                f"Received ACS webhook event: {event_type}",
                LogCategory.AZURE_COMMUNICATION,
                extra_data={
                    "event_type": event_type,
                    "call_connection_id": call_connection_id
                }
            )
            
            # Find call by ACS call ID
            call_state = None
            for state in self.active_calls.values():
                if state.acs_call_id == call_connection_id:
                    call_state = state
                    break
            
            if not call_state:
                self.logger.warning(f"No active call found for ACS call ID: {call_connection_id}")
                return {"status": "ignored", "reason": "call_not_found"}
            
            # Handle different event types
            if event_type == "CallConnectionStateChanged":
                await self._handle_call_state_change(call_state, payload)
            elif event_type == "MediaStreamingStarted":
                await self._handle_media_streaming_started(call_state, payload)
            elif event_type == "MediaStreamingStopped":
                await self._handle_media_streaming_stopped(call_state, payload)
            else:
                self.logger.info(f"Unhandled webhook event type: {event_type}")
            
            return {"status": "processed", "call_id": call_state.call_id}
            
        except Exception as e:
            self.logger.error(
                f"Failed to handle webhook event: {e}",
                LogCategory.AZURE_COMMUNICATION,
                exception=e
            )
            return {"status": "error", "message": str(e)}
    
    async def _handle_call_state_change(self, call_state: CallState, payload: Dict[str, Any]):
        """Handle call state change events."""
        new_state = payload.get("state")
        call_state.status = new_state.lower()
        
        if new_state == "Disconnected":
            await self.end_call(call_state.call_id, "disconnected")
    
    async def _handle_media_streaming_started(self, call_state: CallState, payload: Dict[str, Any]):
        """Handle media streaming started events."""
        call_state.websocket_connected = True
        call_state.audio_stream_active = True
    
    async def _handle_media_streaming_stopped(self, call_state: CallState, payload: Dict[str, Any]):
        """Handle media streaming stopped events."""
        call_state.websocket_connected = False
        call_state.audio_stream_active = False
    
    def get_call_status(self, call_id: str) -> Optional[Dict[str, Any]]:
        """
        Get status of a call.
        
        Args:
            call_id: ID of the call
            
        Returns:
            Call status information or None if not found
        """
        call_state = self.active_calls.get(call_id)
        if not call_state:
            return None
        
        return {
            "call_id": call_state.call_id,
            "acs_call_id": call_state.acs_call_id,
            "clinic_id": call_state.clinic_id,
            "status": call_state.status,
            "start_time": call_state.start_time.isoformat(),
            "end_time": call_state.end_time.isoformat() if call_state.end_time else None,
            "websocket_connected": call_state.websocket_connected,
            "audio_stream_active": call_state.audio_stream_active,
            "language_detected": call_state.language_detected,
            "language_locked": call_state.language_locked
        }
    
    def get_active_calls_count(self) -> int:
        """Get count of active calls."""
        return len(self.active_calls)
    
    def get_clinic_active_calls_count(self, clinic_id: str) -> int:
        """Get count of active calls for a specific clinic."""
        return sum(1 for call_state in self.active_calls.values() 
                  if call_state.clinic_id == clinic_id and call_state.status == CallStatus.ACTIVE.value)
    
    async def cleanup_expired_calls(self):
        """Clean up calls that have exceeded maximum duration."""
        try:
            max_duration = timedelta(minutes=self.settings.azure.communication.max_call_duration_minutes)
            current_time = datetime.now(timezone.utc)
            
            expired_calls = []
            for call_id, call_state in self.active_calls.items():
                if current_time - call_state.start_time > max_duration:
                    expired_calls.append(call_id)
            
            for call_id in expired_calls:
                await self.end_call(call_id, "timeout")
                self.logger.info(f"Cleaned up expired call: {call_id}")
                
        except Exception as e:
            self.logger.error(f"Failed to cleanup expired calls: {e}")


    async def close(self):
        """Clean up resources."""
        if not self._closed and self.http_client:
            await self.http_client.aclose()
            self._closed = True
            self.logger.info("Azure Communication Service HTTP client closed")


# Global service instance
_azure_communication_service: Optional[AzureCommunicationService] = None


def get_azure_communication_service() -> AzureCommunicationService:
    """Get the global Azure Communication Service instance."""
    global _azure_communication_service
    if _azure_communication_service is None:
        _azure_communication_service = AzureCommunicationService()
    return _azure_communication_service
