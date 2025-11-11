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
from datetime import datetime, timezone, timedelta

# Atlantic Standard Time (UTC-4)
AST = timezone(timedelta(hours=-4))
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
from services.database import get_async_db_session
from services.crypto import make_hmac_token, normalize_phone, encrypt_str
# Import call_orchestrator inside __init__ to avoid circular import
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import func, select


logger = get_logger("azure_communication_service")


class AzureCommunicationService:
    """
    Service for managing Azure Communication Services integration.
    
    Provides call management, webhook handling, and audio streaming coordination.
    """
    
    def __init__(self):
        self.settings = get_settings()
        self.logger = logger
        # Import here to avoid circular import with call_orchestrator
        from services.call_orchestrator import get_call_orchestrator
        self.call_orchestrator = get_call_orchestrator()
        self.http_client = httpx.AsyncClient(timeout=30.0)
        self._closed = False
        
        # ACS configuration
        self.connection_string = self.settings.azure.communication.connection_string.get_secret_value()
        self.phone_number = self.settings.azure.communication.phone_number
        self.callback_url = self.settings.azure.communication.callback_url
        self.webhook_secret = self.settings.azure.communication.webhook_secret.get_secret_value()
        
        # Extract endpoint and access key from connection string
        self._parse_connection_string()
        
        # Note: _pending_call_metadata removed - use orchestrator metadata instead
    
    async def _get_acs_metadata(self, call_id: str) -> Dict[str, Any]:
        """Get ACS-specific metadata from CallContext (thread-safe async version)."""
        # Use atomic method from orchestrator that holds lock
        return await self.call_orchestrator.get_call_metadata(call_id)
    
    async def _set_acs_metadata(self, call_id: str, key: str, value: Any):
        """Set ACS-specific metadata in CallContext (thread-safe async version)."""
        # Use atomic method from orchestrator that holds lock during update
        await self.call_orchestrator.update_call_metadata(call_id, key, value)
    
    async def _get_acs_call_id(self, call_id: str) -> Optional[str]:
        """Get ACS call ID from CallContext metadata (thread-safe async version)."""
        metadata = await self._get_acs_metadata(call_id)
        return metadata.get('acs_call_id')
    
    async def _set_acs_call_id(self, call_id: str, acs_call_id: str):
        """Set ACS call ID in CallContext metadata (thread-safe async version)."""
        await self._set_acs_metadata(call_id, 'acs_call_id', acs_call_id)
    
    def _parse_connection_string(self):
        """Parse ACS connection string to extract endpoint and access key."""
        # Issue 6.1: Validate connection string format on initialization
        if not self.connection_string:
            raise ValidationError(
                "connection_string",
                None,
                "Azure Communication Services connection string is required"
            )
        
        try:
            parts = self.connection_string.split(';')
            self.endpoint = None
            self.access_key = None
            
            for part in parts:
                if part.startswith('endpoint='):
                    self.endpoint = part.split('=', 1)[1]
                elif part.startswith('accesskey='):
                    self.access_key = part.split('=', 1)[1]
            
            # Issue 6.1: Validate connection string format
            if not self.endpoint or not self.access_key:
                raise ValidationError(
                    "connection_string",
                    self.connection_string[:50] + "..." if len(self.connection_string) > 50 else self.connection_string,
                    "Invalid connection string format: missing endpoint or access key. "
                    "Expected format: 'endpoint=https://...;accesskey=...'"
                )
            
            # Issue 6.1: Validate endpoint URL format
            if not self.endpoint.startswith('https://'):
                raise ValidationError(
                    "connection_string",
                    self.endpoint,
                    f"Invalid endpoint URL format: must start with 'https://'. Got: {self.endpoint}"
                )
            
            # Ensure endpoint ends with /
            if not self.endpoint.endswith('/'):
                self.endpoint += '/'
            
            self.logger.info("Successfully parsed and validated ACS connection string")
                
        except ValidationError:
            raise
        except Exception as e:
            # Don't log the full exception (may contain connection string)
            self.logger.error("Failed to parse ACS connection string: Invalid format")
            raise ValidationError(
                "connection_string",
                None,
                f"Failed to parse connection string: {str(e)}"
            ) from e
    
    def _get_auth_headers(self) -> Dict[str, str]:
        """Generate authentication headers for ACS API calls."""
        return {
            "Authorization": f"Bearer {self.access_key}",
            "Content-Type": "application/json",
            "User-Agent": "CallCenterAI/1.0"
        }
    
    async def answer_incoming_call(
        self, 
        incoming_call_context: str, 
        callback_url: str,
        cognitive_services_endpoint: Optional[str] = None
    ) -> Dict[str, Any]:
        
        try:
            from azure.communication.callautomation import CallAutomationClient
            
            # Get cognitive services endpoint from settings if not provided
            if not cognitive_services_endpoint:
                # Construct from Azure Speech Service region
                # Format: https://{region}.cognitiveservices.azure.com
                speech_region = self.settings.azure.speech.speech_region
                if speech_region:
                    cognitive_services_endpoint = f"https://{speech_region}.cognitiveservices.azure.com"
                    self.logger.info(
                        f"Constructed cognitive services endpoint from region: {cognitive_services_endpoint}",
                        LogCategory.AZURE_COMMUNICATION
                    )
                else:
                    self.logger.warning(
                        "Azure Speech region not configured, cognitive services endpoint not set",
                        LogCategory.AZURE_COMMUNICATION
                    )
            
            # Create Call Automation client
            call_automation_client = CallAutomationClient.from_connection_string(
                self.connection_string
            )
            
            # Answer the call using proper SDK method
            # Try AnswerCallOptions first, then fallback to keyword arguments
            answer_call_result = None
            try:
                # Try using AnswerCallOptions if available in SDK
                from azure.communication.callautomation import AnswerCallOptions
                
                answer_options = AnswerCallOptions(
                    incoming_call_context=incoming_call_context,
                    callback_uri=callback_url
                )
                # Add cognitive_services_endpoint if available and supported
                if cognitive_services_endpoint and hasattr(answer_options, 'cognitive_services_endpoint'):
                    answer_options.cognitive_services_endpoint = cognitive_services_endpoint
                
                answer_call_result = call_automation_client.answer_call(answer_options)
                self.logger.info(
                    "Call answered successfully using AnswerCallOptions",
                    LogCategory.AZURE_COMMUNICATION,
                    extra_data={"callback_url": callback_url}
                )
            except (ImportError, Exception) as e:
                # AnswerCallOptions not available or failed, try keyword arguments
                self.logger.info(f"AnswerCallOptions not available or failed: {e}, trying keyword arguments", LogCategory.AZURE_COMMUNICATION)
                try:
                    # Try keyword arguments with cognitive_services_endpoint if provided
                    if cognitive_services_endpoint:
                        answer_call_result = call_automation_client.answer_call(
                            incoming_call_context=incoming_call_context,
                            cognitive_services_endpoint=cognitive_services_endpoint,
                            callback_url=callback_url
                        )
                    else:
                        answer_call_result = call_automation_client.answer_call(
                            incoming_call_context=incoming_call_context,
                            callback_url=callback_url
                        )
                    self.logger.info("Call answered successfully with keyword arguments", LogCategory.AZURE_COMMUNICATION)
                except Exception as e2:
                    # Final fallback: try positional arguments
                    self.logger.warning(f"Keyword arguments failed: {e2}, trying positional arguments", LogCategory.AZURE_COMMUNICATION)
                    try:
                        answer_call_result = call_automation_client.answer_call(
                            incoming_call_context,
                            callback_url
                        )
                        self.logger.info("Call answered successfully with positional arguments", LogCategory.AZURE_COMMUNICATION)
                    except Exception as e3:
                        self.logger.error(f"All answer_call attempts failed: {e}, {e2}, {e3}", LogCategory.AZURE_COMMUNICATION)
                        raise AzureCommunicationError(
                            "answer_failed", 
                            f"Failed to answer incoming call: {str(e)}"
                        )
            
            self.logger.info(
                f"Call answered successfully via Call Automation SDK",
                LogCategory.AZURE_COMMUNICATION,
                extra_data={
                    "call_connection_id": answer_call_result.call_connection_id,
                    "callback_url": callback_url
                }
            )
            
            # Start media streaming for real-time audio
            try:
                # Check if SDK supports start_media_streaming
                if hasattr(answer_call_result.call_connection, 'start_media_streaming'):
                    # Configure WebSocket URL for media streaming
                    ws_url = f"{callback_url.replace('https://', 'wss://')}/ws/audio/{answer_call_result.call_connection_id}"
                    
                    # Start streaming (method signature may vary)
                    answer_call_result.call_connection.start_media_streaming(
                        transport_url=ws_url,
                        transport_type="websocket"
                    )
                    
                    self.logger.info(f"Media streaming started for call {answer_call_result.call_connection_id}")
                else:
                    self.logger.warning("Media streaming not supported, will use Play API fallback")
                    
            except Exception as e:
                self.logger.warning(f"Failed to start media streaming: {e}")
                # Continue without media streaming - will use Play API instead
            
            # Get call connection using the client
            call_connection = call_automation_client.get_call_connection(
                answer_call_result.call_connection_id
            )
            
            return {
                "call_connection_id": answer_call_result.call_connection_id,
                "call_connection": call_connection,
                "status": "answered"
            }
            
        except Exception as e:
            self.logger.error(
                f"Error answering incoming call: {e}",
                LogCategory.AZURE_COMMUNICATION,
                exception=e
            )
            raise AzureCommunicationError("answer_failed", f"Failed to answer incoming call: {str(e)}")

    # Note: register_incoming_call() removed - logic moved to orchestrator.start_call()
    # Note: store_call_id_mapping() / get_call_id_from_mapping() removed - use orchestrator metadata directly
    
    # Note: store_pending_call_metadata() / get_pending_call_metadata() / remove_pending_call_metadata() removed
    # Use orchestrator metadata directly - metadata is stored in CallContext.metadata when start_call() is called

    async def hangup_call(self, acs_call_id: str) -> bool:
        """
        Hang up a call via ACS API.
        
        Args:
            acs_call_id: ACS call connection ID
            
        Returns:
            True if hangup succeeded
        """
        try:
            url = f"{self.endpoint}calling/callConnections/{acs_call_id}:hangup"
            headers = self._get_auth_headers()
            
            async with self.http_client.post(url, json={}, headers=headers) as response:
                if response.status_code not in [200, 202]:
                    error_text = await response.aread()
                    self.logger.warning(
                        f"ACS hangup API returned {response.status_code}: {error_text.decode()}",
                        LogCategory.AZURE_COMMUNICATION,
                        extra_data={"acs_call_id": acs_call_id}
                    )
                    return False
                return True
        except Exception as e:
            self.logger.error(
                f"Failed to hangup ACS call {acs_call_id}: {e}",
                LogCategory.AZURE_COMMUNICATION,
                exception=e
            )
            return False

    async def end_call(self, call_id: str, reason: str = "completed") -> bool:
        """
        End a call (delegates to orchestrator).
        
        Args:
            call_id: ID of the call to end
            reason: Reason for ending the call
            
        Returns:
            True if call was ended successfully
        """
        try:
            # Delegate to orchestrator (handles ACS hangup, DB update, capacity release)
            await self.call_orchestrator.end_call(call_id, reason)
            return True
        except Exception as e:
            self.logger.error(
                f"Failed to end call {call_id}: {e}",
                LogCategory.AZURE_COMMUNICATION,
                exception=e
            )
            return False
    
    # Note: start_audio_stream() removed - handled by orchestrator.connect_audio_stream()
    
    async def play_scripted_text(self, call_connection_id: str, text: str, language: str = "en-US") -> bool:
        """Play text using ACS TextSource (fast, no TTS processing)."""
        try:
            from azure.communication.callautomation import CallAutomationClient
            from azure.communication.callautomation import TextSource
            
            # Create client
            client = CallAutomationClient.from_connection_string(self.connection_string)
            call_connection = client.get_call_connection(call_connection_id)
            
            # Create TextSource
            text_source = TextSource(text=text, voice_name=self._get_voice_name(language))
            
            # Play text
            call_connection.play_media(play_source=text_source)
            
            self.logger.info(f"Text played via TextSource for {call_connection_id}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to play text via TextSource for {call_connection_id}: {e}")
            return False
    
    def _get_voice_name(self, language: str) -> str:
        """Get appropriate voice name for language."""
        voice_mapping = {
            "en-US": "en-US-AriaNeural",
            "es-ES": "es-ES-ElviraNeural",
            "es-MX": "es-MX-DaliaNeural"
        }
        return voice_mapping.get(language, "en-US-AriaNeural")
    
    async def play_audio_to_call(self, call_connection_id: str, audio_data: bytes) -> bool:
        """Play audio to call using Call Automation Play API."""
        try:
            from azure.communication.callautomation import CallAutomationClient
            
            # Create client
            client = CallAutomationClient.from_connection_string(self.connection_string)
            call_connection = client.get_call_connection(call_connection_id)
            
            # Option 1: Try FileSource with data URI
            try:
                from azure.communication.callautomation import FileSource
                import base64
                
                audio_base64 = base64.b64encode(audio_data).decode('utf-8')
                audio_uri = f"data:audio/wav;base64,{audio_base64}"
                
                play_source = FileSource(url=audio_uri)
                call_connection.play_media(play_source=play_source)
                
                self.logger.info(f"Audio played via FileSource for {call_connection_id}")
                return True
                
            except Exception as e1:
                self.logger.warning(f"FileSource failed: {e1}")
                
                # Option 2: Try TextSource with SSML
                try:
                    from azure.communication.callautomation import TextSource
                    
                    # Convert audio back to text if possible, or use placeholder
                    text_source = TextSource(text="Response audio playback")
                    call_connection.play_media(play_source=text_source)
                    
                    self.logger.info(f"Audio played via TextSource for {call_connection_id}")
                    return True
                    
                except Exception as e2:
                    self.logger.error(f"All play methods failed: {e1}, {e2}")
                    return False
            
        except Exception as e:
            self.logger.error(f"Failed to play audio to call {call_connection_id}: {e}")
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
        Handle webhook events from ACS (delegates to orchestrator).
        
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
            
            # Delegate to orchestrator
            return await self.call_orchestrator.handle_acs_event(event_type, payload)
            
        except Exception as e:
            self.logger.error(
                f"Failed to handle webhook event: {e}",
                LogCategory.AZURE_COMMUNICATION,
                exception=e
            )
            return {"status": "error", "message": str(e)}
    
    async def make_outbound_call(
        self,
        to_phone: str,
        from_phone: Optional[str] = None,
        audio_content: Optional[bytes] = None,
        call_context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Make an outbound call using Azure Communication Services.
        
        Args:
            to_phone: Phone number to call (E.164 format, e.g., +1234567890)
            from_phone: Phone number to call from (defaults to configured phone number)
            audio_content: Optional audio bytes to play when call connects
            call_context: Optional context data to attach to the call
            
        Returns:
            Dict with call result: {'success': bool, 'call_id': str, 'error_code': str, 'error_message': str}
        """
        try:
            from azure.communication.callautomation import CallAutomationClient, PhoneNumberIdentifier
            from azure.communication.callautomation.models import CallInvite, FileSource
            
            # Validate inputs
            if not to_phone:
                raise ValidationError("to_phone", to_phone, "Phone number cannot be empty")
            
            # Normalize phone number
            to_phone = normalize_phone(to_phone)
            from_phone = from_phone or self.phone_number
            from_phone = normalize_phone(from_phone)
            
            # Create Call Automation client
            call_automation_client = CallAutomationClient.from_connection_string(
                self.connection_string
            )
            
            # Create call invite
            target = PhoneNumberIdentifier(phone_number=to_phone)
            call_invite = CallInvite(target=target, source_caller_id_number=PhoneNumberIdentifier(phone_number=from_phone))
            
            # Prepare callback URL with context if provided
            callback_url = self.callback_url
            if call_context:
                # Encode context in callback URL
                context_str = json.dumps(call_context)
                callback_url = f"{self.callback_url}?context={context_str}"
            
            # Make the outbound call
            call_connection_properties = call_automation_client.create_call(
                call_invite=call_invite,
                callback_url=callback_url
            )
            
            call_connection_id = call_connection_properties.call_connection_id
            
            self.logger.info(
                f"Outbound call initiated: {call_connection_id} from {from_phone} to {to_phone}",
                LogCategory.AZURE_COMMUNICATION,
                extra_data={
                    "call_connection_id": call_connection_id,
                    "from_phone": from_phone,
                    "to_phone": to_phone,
                    "call_context": call_context
                }
            )
            
            # If audio content provided, play it when call connects
            if audio_content:
                try:
                    # Convert audio to base64 data URI
                    import base64
                    audio_base64 = base64.b64encode(audio_content).decode('utf-8')
                    audio_uri = f"data:audio/wav;base64,{audio_base64}"
                    
                    # Play audio using FileSource
                    play_source = FileSource(url=audio_uri)
                    call_connection = call_automation_client.get_call_connection(call_connection_id)
                    call_connection.play_media(play_source=play_source)
                    
                    self.logger.info(
                        f"Audio playback started for outbound call {call_connection_id}",
                        LogCategory.AZURE_COMMUNICATION
                    )
                except Exception as audio_error:
                    self.logger.warning(
                        f"Failed to play audio for outbound call {call_connection_id}: {audio_error}",
                        LogCategory.AZURE_COMMUNICATION,
                        exception=audio_error
                    )
                    # Continue - audio failure shouldn't fail the call
            
            return {
                "success": True,
                "call_id": call_connection_id,
                "call_connection_id": call_connection_id,
                "from_phone": from_phone,
                "to_phone": to_phone
            }
            
        except Exception as e:
            self.logger.error(
                f"Failed to make outbound call to {to_phone}: {e}",
                LogCategory.AZURE_COMMUNICATION,
                exception=e
            )
            return {
                "success": False,
                "call_id": None,
                "error_code": "call_failed",
                "error_message": str(e),
                "to_phone": to_phone
            }
    
    async def get_call_status(self, call_id: str) -> Optional[Dict[str, Any]]:
        """
        Get status of a call (queries orchestrator).
        
        Args:
            call_id: ID of the call
            
        Returns:
            Call status information or None if not found
        """
        call_context = await self.call_orchestrator.get_call_context(call_id)
        if not call_context:
            return None
        
        metadata = await self.call_orchestrator.get_call_metadata(call_id)
        
        return {
            "call_id": call_context.call_id,
            "acs_call_id": metadata.get('acs_call_id'),
            "clinic_id": call_context.clinic_id,
            "status": metadata.get('acs_status', 'unknown'),
            "start_time": call_context.start_time.isoformat() if call_context.start_time else None,
            "end_time": metadata.get('end_time').isoformat() if metadata.get('end_time') else None,
            "websocket_connected": metadata.get('websocket_connected', False),
            "audio_stream_active": metadata.get('audio_stream_active', False),
            "language_detected": call_context.language.value if call_context.language else None,
            "language_locked": metadata.get('language_locked', False)
        }
    
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
