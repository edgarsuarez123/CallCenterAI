"""
Azure Communication Services API routes.

Provides REST endpoints for:
- Call initiation and management
- Webhook handling for ACS events
- Call status and monitoring
- WebSocket endpoint for audio streaming
"""

import json
import base64
import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Request, HTTPException, status, Depends, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

# Atlantic Standard Time (UTC-4)
AST = timezone(timedelta(hours=-4))

from services.azure_communication_service import get_azure_communication_service
from services.audio_stream_handler import get_audio_stream_handler
from services.database import get_async_db
from services.structured_logging import get_logger, LogCategory
from services.configuration import get_settings

# Initialize router
router = APIRouter(prefix="/acs", tags=["Azure Communication Services"])

# Get logger
logger = get_logger("azure_communication_routes")


async def get_clinic_id_from_env_or_phone(to_number: Optional[str], db: AsyncSession) -> str:
    """
    Get clinic_id from CLINIC_ID env var (single-tenant) or phone lookup (multi-tenant).
    
    Args:
        to_number: Phone number that was called (for multi-tenant lookup)
        db: Database session
        
    Returns:
        Clinic ID
    """
    import os
    
    # Single-tenant mode: use CLINIC_ID env var directly
    clinic_id = os.getenv("CLINIC_ID")
    if clinic_id:
        logger.info(f"Using CLINIC_ID from environment: {clinic_id} (single-tenant mode)", LogCategory.API)
        return clinic_id
    
    # Multi-tenant mode: lookup by phone number (backward compatibility)
    clinic_id = 'default-clinic'  # Default fallback
    try:
        if to_number:
            from services.clinic_management import ClinicManagementService
            clinic_service = ClinicManagementService(db)
            clinic_id = await clinic_service.get_clinic_by_phone(to_number) or 'default-clinic'
    except Exception as e:
        logger.warning(f"Failed to get clinic_id for {to_number}, using default: {e}", LogCategory.API)
        clinic_id = 'default-clinic'
    
    return clinic_id


# Pydantic models for request/response validation

class AzureCallStatusResponse(BaseModel):
    """Response model for call status."""
    call_id: str
    status: str
    duration_seconds: Optional[float] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    caller_phone: Optional[str] = None
    callee_phone: Optional[str] = None


# REST API endpoints
# Note: Call initiation is handled via Event Grid IncomingCall events, not REST API

@router.get("/calls/{call_id}/status", response_model=AzureCallStatusResponse)
async def get_call_status(
    call_id: str,
    db: AsyncSession = Depends(get_async_db)
) -> AzureCallStatusResponse:
    """
    Get the status of a call.
    
    Args:
        call_id: ID of the call
        db: Database session
        
    Returns:
        AzureCallStatusResponse: Call status information
    """
    try:
        acs_service = get_azure_communication_service()
        
        # Get call status
        status_info = await acs_service.get_call_status(call_id)
        
        return AzureCallStatusResponse(
            call_id=call_id,
            status=status_info.get('status', 'unknown'),
            duration_seconds=status_info.get('duration_seconds'),
            start_time=status_info.get('start_time'),
            end_time=status_info.get('end_time'),
            caller_phone=status_info.get('caller_phone'),
            callee_phone=status_info.get('callee_phone')
        )
        
    except Exception as e:
        logger.error(
            f"Failed to get call status for {call_id}: {e}",
            LogCategory.API,
            exception=e,
            extra_data={"call_id": call_id}
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get call status: {e}"
        )


@router.get("/calls/active", response_model=Dict[str, Any])
async def get_active_calls(
    db: AsyncSession = Depends(get_async_db)
) -> Dict[str, Any]:
    """
    Get all active calls.
    
    Args:
        db: Database session
        
    Returns:
        Dict[str, Any]: Active calls information
    """
    try:
        acs_service = get_azure_communication_service()
        
        # Get active calls
        active_calls = await acs_service.get_active_calls()
        
        return {
            "active_calls": active_calls,
            "count": len(active_calls),
            "timestamp": datetime.now(AST).isoformat()
        }
        
    except Exception as e:
        logger.error(
            f"Failed to get active calls: {e}",
            LogCategory.API,
            exception=e
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get active calls: {e}"
        )


# Event handlers
async def handle_call_connected_event(acs_service, payload: Dict[str, Any], db: AsyncSession) -> Dict[str, Any]:
    """
    Handle CallConnected event from Call Automation.
    
    This event is sent after successfully answering an incoming call.
    According to Azure Communication Services Call Automation documentation:
    - CallConnected is sent when a call is successfully answered
    - This confirms the call connection is established
    - After this event, we can start playing audio, capturing speech, etc.
    
    Event Flow:
    1. Event Grid IncomingCall → Answer call → CallConnected (this event)
    2. OR: IncomingCallReceived → Answer call → CallConnected (this event)
    3. After CallConnected, we initialize call flow and play greeting
    
    Args:
        acs_service: Azure Communication Service instance
        payload: Event payload containing callConnectionId
        db: Database session
        
    Returns:
        Dict[str, Any]: Event handling result with status and call details
    """
    try:
        call_connection_id = payload.get('callConnectionId')
        if not call_connection_id:
            logger.error("Missing callConnectionId in CallConnected event payload", LogCategory.API)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing callConnectionId in payload"
            )
        
        logger.info(
            f"CallConnected event: {call_connection_id}",
            LogCategory.API,
            extra_data={"call_connection_id": call_connection_id, "payload": payload}
        )
        
        # Get call info from payload
        from_number = payload.get('from', {}).get('phoneNumber', {}).get('value') if isinstance(payload.get('from'), dict) else None
        to_number = payload.get('to', {}).get('phoneNumber', {}).get('value') if isinstance(payload.get('to'), dict) else None
        
        # Get clinic_id from phone number if not in payload
        clinic_id = 'default-clinic'
        try:
            if to_number:
                from services.clinic_management import ClinicManagementService
                clinic_service = ClinicManagementService(db)
                clinic_id = await clinic_service.get_clinic_by_phone(to_number) or 'default-clinic'
        except Exception as e:
            logger.warning(f"Failed to get clinic_id for {to_number}, using default: {e}", LogCategory.API)
        
        # Use call_connection_id as call_id (or generate one)
        call_id = call_connection_id
        
        # Delegate to orchestrator to start call (handles CallFlow init, DB record, ACS registration)
        from services.call_orchestrator import get_call_orchestrator
        from models.enums import CallType, CallState
        orchestrator = get_call_orchestrator()
        
        try:
            # Check if call already exists
            async with orchestrator._calls_lock:
                if call_id not in orchestrator.active_calls:
                    # Call doesn't exist - initialize it via orchestrator
                    await orchestrator.start_call(
                        call_id=call_id,
                        caller_phone=from_number or 'unknown',
                        clinic_id=clinic_id,
                        call_type=CallType.INBOUND,
                        call_metadata={'acs_call_id': call_connection_id}
                    )
                    logger.info(f"Call started via orchestrator for {call_id}", LogCategory.API)
                else:
                    # Call already exists - update state to CONNECTED
                    call_context = orchestrator.active_calls[call_id]
                    if call_context.state not in [CallState.ENDING, CallState.ENDED, CallState.ERROR]:
                        call_context.state = CallState.CONNECTED
                        call_context.last_activity = datetime.now(AST)
                    else:
                        logger.info(f"Call {call_id} already in state {call_context.state.value}, skipping", LogCategory.API)
                        return {
                            "status": "call_already_ended",
                            "message": f"Call {call_id} already ended",
                            "call_id": call_id,
                            "timestamp": datetime.now(AST).isoformat()
                        }
        except Exception as e:
            logger.error(f"Failed to start call via orchestrator: {e}", LogCategory.API, exception=e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to start call: {e}"
            )
        
        # Play greeting (with error handling)
        # According to Microsoft documentation: "After CallConnected, we initialize call flow and play greeting"
        try:
            await orchestrator.play_greeting(call_id)
            logger.info(f"Greeting played for call {call_id} in CallConnected handler", LogCategory.API)
        except Exception as e:
            logger.error(f"Failed to play greeting for call {call_id}: {e}", LogCategory.API, exception=e)
            # Continue - greeting failure shouldn't stop the call
        
        return {
            "status": "call_connected",
            "message": f"Call {call_connection_id} connected",
            "call_connection_id": call_connection_id,
            "timestamp": datetime.now(AST).isoformat()
        }
        
    except Exception as e:
        logger.error(
            f"Error handling CallConnected event: {e}",
            LogCategory.API,
            exception=e,
            extra_data={"call_connection_id": payload.get('callConnectionId') if isinstance(payload, dict) else None}
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error handling CallConnected event: {e}"
        )


async def handle_call_disconnected_event(acs_service, payload: Dict[str, Any], db: AsyncSession) -> Dict[str, Any]:
    """
    Handle CallDisconnected event from Call Automation.
    
    Args:
        acs_service: Azure Communication Service instance
        payload: Event payload
        db: Database session
        
    Returns:
        Dict[str, Any]: Event handling result
    """
    try:
        call_connection_id = payload.get('callConnectionId')
        if not call_connection_id:
            logger.error("Missing callConnectionId in CallDisconnected event payload", LogCategory.API)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing callConnectionId in payload"
            )
        
        logger.info(
            f"CallDisconnected event: {call_connection_id}",
            LogCategory.API,
            extra_data={"call_connection_id": call_connection_id, "payload": payload}
        )
        
        # Get call_id from orchestrator metadata (search by acs_call_id)
        from services.call_orchestrator import get_call_orchestrator
        from models.enums import CallState
        from services.admission_controller import get_admission_controller
        orchestrator = get_call_orchestrator()
        admission_controller = get_admission_controller()
        call_id = None
        async with orchestrator._calls_lock:
            for cid, context in orchestrator.active_calls.items():
                if context.metadata.get('acs_call_id') == call_connection_id:
                    call_id = cid
                    break
        if not call_id:
            call_id = call_connection_id  # Fallback to using call_connection_id as call_id
        
        async with orchestrator._calls_lock:
            if call_id not in orchestrator.active_calls:
                # Call might be in queue - try to remove it
                logger.info(f"Call {call_id} not found in orchestrator, checking queue", LogCategory.API)
                removed = await admission_controller.remove_from_queue(call_id)
                if removed:
                    logger.info(f"Call {call_id} removed from queue (caller hung up)", LogCategory.API)
                    return {
                        "status": "removed_from_queue",
                        "message": f"Call {call_id} was in queue and has been removed",
                        "call_id": call_id,
                        "timestamp": datetime.now(AST).isoformat()
                    }
                else:
                    logger.warning(f"Call {call_id} not found in orchestrator or queue for disconnected event", LogCategory.API)
                    return {
                        "status": "call_not_found",
                        "message": f"Call {call_id} not found",
                        "call_id": call_id,
                        "timestamp": datetime.now(AST).isoformat()
                    }
            
            call_context = orchestrator.active_calls[call_id]
            # Issue 142: Check if call is already ended
            if call_context.state in [CallState.ENDING, CallState.ENDED]:
                logger.info(f"Call {call_id} already in state {call_context.state.value}, skipping disconnect", LogCategory.API)
                return {
                    "status": "call_already_ended",
                    "message": f"Call {call_id} already ended",
                    "call_id": call_id,
                    "timestamp": datetime.now(AST).isoformat()
                }
        
        # End AI call handling (with error handling)
        try:
            await orchestrator.end_call(call_id)
        except Exception as e:
            logger.error(f"Failed to end call {call_id}: {e}", LogCategory.API, exception=e)
            # Continue - end call failure shouldn't raise exception
        
        return {
            "status": "call_disconnected",
            "message": f"Call {call_connection_id} disconnected",
            "call_connection_id": call_connection_id,
            "timestamp": datetime.now(AST).isoformat()
        }
        
    except Exception as e:
        logger.error(
            f"Error handling CallDisconnected event: {e}",
            LogCategory.API,
            exception=e,
            extra_data={"call_connection_id": payload.get('callConnectionId') if isinstance(payload, dict) else None}
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error handling CallDisconnected event: {e}"
        )


async def handle_event_grid_call_ended(acs_service, payload: Dict[str, Any], db: AsyncSession) -> Dict[str, Any]:
    """
    Handle CallEnded event from Event Grid.
    
    Args:
        acs_service: Azure Communication Service instance
        payload: Event payload
        db: Database session
        
    Returns:
        Dict[str, Any]: Event handling result
    """
    try:
        call_id = payload.get('data', {}).get('callId')
        if not call_id:
            logger.warning("Missing callId in Event Grid CallEnded event payload", LogCategory.API)
            call_id = payload.get('id', 'unknown')
        
        # Validate call_id
        if not call_id or call_id == 'unknown':
            logger.warning("Invalid call_id in Event Grid CallEnded event", LogCategory.API)
            # Continue with processing even if call_id is invalid
        
        logger.info(
            f"Event Grid CallEnded event: {call_id}",
            LogCategory.API,
            extra_data={"call_id": call_id, "payload": payload}
        )
        
        # Note: call_id is already the internal call_id from Event Grid payload
        # No need to map - Event Grid provides the call_id directly
        
        # End AI call handling (with error handling)
        try:
            from services.call_orchestrator import get_call_orchestrator
            orchestrator = get_call_orchestrator()
            await orchestrator.end_call(call_id)
        except Exception as e:
            logger.error(f"Failed to end call {call_id}: {e}", LogCategory.API, exception=e)
            # Continue - end call failure shouldn't raise exception
        
        return {
            "status": "call_ended",
            "message": f"Event Grid call {call_id} ended",
            "call_id": call_id,
            "timestamp": datetime.now(AST).isoformat()
        }
        
    except Exception as e:
        logger.error(
            f"Error handling Event Grid CallEnded event: {e}",
            LogCategory.API,
            exception=e,
            extra_data={"call_id": call_id, "payload": payload}
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error handling Event Grid CallEnded event: {e}"
        )


async def handle_event_grid_incoming_call(acs_service, payload: Dict[str, Any], db: AsyncSession) -> Dict[str, Any]:
    """
    Handle IncomingCall event from Event Grid.
    This event comes when someone calls the phone number.
    We need to answer the call to establish the connection.
    
    Event Flow:
    1. Event Grid sends IncomingCall event when someone calls the phone number
    2. We extract incomingCallContext from the payload
    3. We answer the call using Call Automation SDK with the incomingCallContext
    4. Call Automation sends CallConnected event to the callback URL after answering
    5. CallConnected event triggers call initialization and greeting
    
    Important Notes:
    - Event Grid requires HTTPS for webhook subscriptions (container uses HTTP)
    - Azure Container Instances with public IP use HTTP by default
    - For Event Grid integration, use Azure Application Gateway or Azure Container Apps for HTTPS
    - Call Automation webhooks can use HTTP for development/testing
    - For production, configure HTTPS endpoint (e.g., via Application Gateway or Container Apps)
    - If Event Grid events are not received, phone number must be configured in Azure Portal
    - The incomingCallContext is required to answer the call
    - After answering, Call Automation sends CallConnected event to callback_url
    
    HTTP vs HTTPS Limitation:
    - Event Grid subscriptions require HTTPS endpoints for security
    - Azure Container Instances (ACI) with public IP don't provide HTTPS/TLS termination by default
    - Solutions:
      1. Use Azure Container Apps (built-in HTTPS support with automatic certificates)
      2. Use Azure Application Gateway in front of ACI (provides TLS termination)
      3. Use reverse proxy (nginx/Traefik) with certificate management
      4. Use ngrok or similar for development/testing
    """
    try:
        # Validate payload structure first
        if not isinstance(payload, dict):
            logger.error(
                f"Invalid payload type for Event Grid IncomingCall event: {type(payload).__name__}",
                LogCategory.API,
                extra_data={"payload": payload}
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid payload type: expected dict, got {type(payload).__name__}"
            )
        
        # Validate data field exists and is a dict
        if 'data' not in payload:
            logger.error(
                "Missing 'data' field in Event Grid IncomingCall payload",
                LogCategory.API,
                extra_data={"payload_keys": list(payload.keys()), "full_payload": payload}
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing 'data' field in Event Grid IncomingCall payload"
            )
        
        if not isinstance(payload.get('data'), dict):
            logger.error(
                f"Invalid 'data' field type in Event Grid IncomingCall payload: {type(payload.get('data')).__name__}",
                LogCategory.API,
                extra_data={"payload": payload}
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid 'data' field type: expected dict, got {type(payload.get('data')).__name__}"
            )
        
        # Extract call details from Event Grid payload
        data = payload.get('data', {})
        from_number = data.get('from', {}).get('phoneNumber', {}).get('value') if isinstance(data.get('from'), dict) else None
        to_number = data.get('to', {}).get('phoneNumber', {}).get('value') if isinstance(data.get('to'), dict) else None
        server_call_id = data.get('serverCallId')
        
        # Validate phone numbers
        if not from_number or not isinstance(from_number, str) or len(from_number.strip()) == 0:
            logger.error(
                f"Invalid from_number in Event Grid payload: {from_number}",
                LogCategory.API,
                extra_data={"from_number": from_number, "to_number": to_number, "payload": payload}
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid from_number in Event Grid payload"
            )
        
        if not to_number or not isinstance(to_number, str) or len(to_number.strip()) == 0:
            logger.error(
                f"Invalid to_number in Event Grid payload: {to_number}",
                LogCategory.API,
                extra_data={"from_number": from_number, "to_number": to_number, "payload": payload}
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid to_number in Event Grid payload"
            )
        
        # Use serverCallId as the call_id (it's base64 encoded)
        if server_call_id:
            try:
                # Decode the base64 serverCallId to get a readable call ID
                decoded_id = base64.b64decode(server_call_id).decode('utf-8')
                # Extract a shorter ID from the decoded string (with bounds check)
                parts = decoded_id.split('/')
                if parts and len(parts) > 0:
                    last_part = parts[-1].split('?')[0]
                    call_id = f"EVENT_GRID_{last_part[:12] if len(last_part) > 12 else last_part}"
                else:
                    call_id = f"EVENT_GRID_{decoded_id[:12] if len(decoded_id) > 12 else decoded_id}"
            except Exception as e:
                logger.warning(f"Failed to decode serverCallId {server_call_id}: {e}", LogCategory.API)
                # Fallback to using the base64 string directly (with bounds check)
                call_id = f"EVENT_GRID_{server_call_id[:12] if len(server_call_id) > 12 else server_call_id}"
        else:
            # Generate a fallback call ID (with bounds check)
            payload_id = payload.get('id', 'unknown')
            call_id = f"EVENT_GRID_{payload_id[:12] if len(payload_id) > 12 else payload_id}"

        logger.info(
            f"Event Grid IncomingCall event from {from_number} to {to_number}",
            LogCategory.API,
            extra_data={
                "from_number": from_number,
                "to_number": to_number,
                "call_id": call_id,
                "server_call_id": server_call_id,
                "payload_structure": {
                    "has_data": "data" in payload,
                    "data_type": type(payload.get("data")).__name__ if "data" in payload else None,
                    "data_keys": list(payload.get("data", {}).keys()) if isinstance(payload.get("data"), dict) else None,
                    "has_from": "from" in payload.get("data", {}) if isinstance(payload.get("data"), dict) else False,
                    "has_to": "to" in payload.get("data", {}) if isinstance(payload.get("data"), dict) else False,
                    "has_incomingCallContext": "incomingCallContext" in payload.get("data", {}) if isinstance(payload.get("data"), dict) else False
                },
                "full_payload": payload  # Log full payload for debugging
            }
        )

        # Get the base callback URL from environment variables
        settings = get_settings()
        base_callback_url = settings.azure.communication.callback_url

        if not base_callback_url:
            logger.error(
                "ACS_CALLBACK_URL is not configured. Cannot answer call.",
                LogCategory.API,
                extra_data={"call_id": call_id, "from_number": from_number, "to_number": to_number}
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="ACS_CALLBACK_URL is not configured"
            )

        # Generate unique callback URL per call (similar to sample implementation)
        # This allows tracking individual calls through webhook events
        guid = uuid.uuid4()
        query_parameters = urlencode({
            "callerId": from_number,
            "callId": call_id
        })
        # Construct callback URL with context ID and query parameters
        # Format: {base_url}/{guid}?callerId={from_number}&callId={call_id}
        # Remove trailing slash from base URL and append context ID
        base_url_clean = base_callback_url.rstrip('/')
        callback_uri = f"{base_url_clean}/{guid}?{query_parameters}"
        
        logger.info(
            f"Generated unique callback URL for call {call_id}",
            LogCategory.API,
            extra_data={
                "call_id": call_id,
                "callback_uri": callback_uri,
                "context_id": str(guid)
            }
        )

        # Extract incomingCallContext from Event Grid payload
        # Try multiple payload paths as the structure may vary
        incoming_call_context = None
        attempted_paths = []
        
        # Try path 1: data.incomingCallContext (most common)
        if isinstance(payload.get('data'), dict):
            incoming_call_context = payload.get('data', {}).get('incomingCallContext')
            attempted_paths.append("data.incomingCallContext")
        
        # Try path 2: incomingCallContext at root level
        if not incoming_call_context:
            incoming_call_context = payload.get('incomingCallContext')
            attempted_paths.append("incomingCallContext")
        
        # Try path 3: data.incomingCall.context
        if not incoming_call_context and isinstance(payload.get('data'), dict):
            incoming_call_data = payload.get('data', {}).get('incomingCall')
            if isinstance(incoming_call_data, dict):
                incoming_call_context = incoming_call_data.get('context')
                attempted_paths.append("data.incomingCall.context")
        
        # Log extraction attempts
        logger.info(
            f"Extracting incomingCallContext for call {call_id}",
            LogCategory.API,
            extra_data={
                "call_id": call_id,
                "attempted_paths": attempted_paths,
                "found": incoming_call_context is not None,
                "payload_data_keys": list(payload.get("data", {}).keys()) if isinstance(payload.get("data"), dict) else None
            }
        )
        
        if not incoming_call_context:
            logger.error(
                f"No incomingCallContext found in Event Grid payload for call {call_id}",
                LogCategory.API,
                extra_data={
                    "call_id": call_id,
                    "attempted_paths": attempted_paths,
                    "payload_structure": {
                        "has_data": "data" in payload,
                        "data_keys": list(payload.get("data", {}).keys()) if isinstance(payload.get("data"), dict) else None,
                        "root_keys": list(payload.keys()) if isinstance(payload, dict) else None
                    },
                    "full_payload": payload  # Log full payload for debugging
                }
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Missing incomingCallContext in Event Grid payload. Attempted paths: {', '.join(attempted_paths)}. Payload structure: {json.dumps(payload, default=str)}"
            )

        # Answer the call using Call Automation SDK with unique callback URL
        answer_result = await acs_service.answer_incoming_call(
            incoming_call_context=incoming_call_context,
            callback_url=callback_uri
        )

        if not answer_result or not answer_result.get('call_connection_id'):
            logger.error(
                f"Failed to answer incoming call {call_id}: {answer_result}",
                LogCategory.API,
                extra_data={"call_id": call_id, "answer_result": answer_result}
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to answer incoming call"
            )
        
        call_connection_id = answer_result.get('call_connection_id')
        if not call_connection_id:
            logger.error(
                f"Missing call_connection_id in answer_result for {call_id}",
                LogCategory.API,
                extra_data={"call_id": call_id, "answer_result": answer_result}
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Missing call_connection_id in answer result"
            )
        
        logger.info(
            f"Call answered with connection ID: {call_connection_id}",
            LogCategory.API,
            extra_data={"call_id": call_id, "call_connection_id": call_connection_id}
        )
        
        # Determine clinic from phone number mapping (with proper database session management)
        # This is needed for CallConnected handler to initialize the call
        clinic_id = 'default-clinic'  # Default fallback
        try:
            if to_number:
                from services.clinic_management import ClinicManagementService
                clinic_service = ClinicManagementService(db)
                clinic_id = await clinic_service.get_clinic_by_phone(to_number) or 'default-clinic'
        except Exception as e:
            logger.warning(f"Failed to get clinic_id for {to_number}, using default: {e}", LogCategory.API)
            clinic_id = 'default-clinic'

        # Note: No need to store pending metadata - CallConnected handler gets info from payload
        # Orchestrator.start_call() handles all initialization when CallConnected event arrives

        # According to Microsoft documentation:
        # - "When an incoming call event is received, if your application fails to respond back with a 200Ok status code to Event Grid within the required time frame, Event Grid utilizes exponential backoff retry"
        # - "However, an incoming call only rings for 30 seconds, and responding to a call after that time won't be effective"
        # - Best practice: Return 200 OK immediately after answering the call
        # - Heavy initialization work (orchestrator.start_call, greeting) should be done in CallConnected handler
        
        logger.info(
            f"Event Grid IncomingCall answered, returning 200 OK immediately. Call will be initialized in CallConnected handler.",
            LogCategory.API,
            extra_data={
                "call_id": call_id,
                "call_connection_id": call_connection_id,
                "from_number": from_number,
                "to_number": to_number,
                "clinic_id": clinic_id
            }
        )

        return {
            "status": "call_received",
            "message": f"Event Grid call received and answered. Call will be initialized when CallConnected event arrives.",
            "call_id": call_id,
            "call_connection_id": call_connection_id,
            "timestamp": datetime.now(AST).isoformat(),
            "note": "Heavy initialization work (orchestrator start, greeting) will be done in CallConnected handler per Microsoft best practices"
        }

    except Exception as e:
        logger.error(
            f"Error handling Event Grid IncomingCall event: {e}",
            LogCategory.API,
            exception=e,
            extra_data={"from_number": from_number if 'from_number' in locals() else None, "to_number": to_number if 'to_number' in locals() else None}
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error handling Event Grid IncomingCall event: {e}"
        )


# Webhook endpoints
MAX_WEBHOOK_BODY_SIZE = 1_048_576  # 1MB

async def validate_request_size(request: Request):
    """Validate webhook request body size to prevent DoS attacks."""
    content_length = request.headers.get('content-length')
    if content_length and int(content_length) > MAX_WEBHOOK_BODY_SIZE:
        raise RequestValidationError("Request body too large")

@router.get("/webhooks/health", response_model=Dict[str, Any])
async def webhook_health_check() -> Dict[str, Any]:
    """
    Health check endpoint for webhook diagnostics.
    
    Returns:
        Dict[str, Any]: Webhook endpoint status and configuration
    """
    from services.configuration import get_settings
    settings = get_settings()
    
    return {
        "status": "healthy",
        "endpoint": "/api/v1/acs/webhooks/events",
        "methods": ["POST", "GET", "OPTIONS"],
        "event_grid_configured": bool(settings.azure.communication.callback_url),
        "callback_url": str(settings.azure.communication.callback_url) if settings.azure.communication.callback_url else None,
        "phone_number": settings.azure.communication.phone_number,
        "note": "This endpoint receives webhook events from Azure Communication Services and Event Grid"
    }


@router.get("/webhooks/events/test", response_model=Dict[str, Any])
async def webhook_test_endpoint(
    request: Request
) -> Dict[str, Any]:
    """
    Test endpoint that logs all incoming requests for debugging.
    
    Args:
        request: FastAPI request object
        
    Returns:
        Dict[str, Any]: Request details for debugging
    """
    all_headers = dict(request.headers)
    query_params = dict(request.query_params)
    
    logger.info(
        "Test endpoint accessed",
        LogCategory.API,
        extra_data={
            "method": request.method,
            "path": request.url.path,
            "full_url": str(request.url),
            "client_ip": request.client.host if request.client else "unknown",
            "user_agent": request.headers.get("user-agent", "unknown"),
            "all_headers": all_headers,
            "query_params": query_params
        }
    )
    
    return {
        "message": "Test endpoint accessed",
        "method": request.method,
        "path": request.url.path,
        "full_url": str(request.url),
        "client_ip": request.client.host if request.client else "unknown",
        "user_agent": request.headers.get("user-agent", "unknown"),
        "headers": all_headers,
        "query_params": query_params,
        "timestamp": datetime.now(AST).isoformat()
    }


@router.post("/webhooks/events", response_model=Dict[str, Any], dependencies=[Depends(validate_request_size)])
@router.post("/webhooks/events/{contextId}", response_model=Dict[str, Any], dependencies=[Depends(validate_request_size)])
@router.get("/webhooks/events", response_model=Dict[str, Any])
@router.get("/webhooks/events/{contextId}", response_model=Dict[str, Any])
@router.options("/webhooks/events", response_model=Dict[str, Any])
@router.options("/webhooks/events/{contextId}", response_model=Dict[str, Any])
async def handle_webhook_events(
    request: Request,
    contextId: Optional[str] = None,
    db: AsyncSession = Depends(get_async_db)
) -> Dict[str, Any]:
    """
    Handle Azure Communication Services webhook events.
    
    Supports both with and without context ID:
    - /webhooks/events - Standard webhook endpoint (backward compatible)
    - /webhooks/events/{contextId} - Unique callback URL per call (for tracking individual calls)
    
    The contextId is a GUID generated per call, and query parameters (callerId, callId) 
    are used to track individual calls through webhook events.
    
    Args:
        request: FastAPI request object
        contextId: Optional context ID (GUID) for tracking individual calls
        db: Database session
        
    Returns:
        Dict[str, Any]: Webhook handling result
    """
    return await _handle_webhook_events_internal(contextId, request, db)


async def _handle_webhook_events_internal(
    contextId: Optional[str],
    request: Request,
    db: AsyncSession
) -> Dict[str, Any]:
    """
    Internal webhook event handler that supports both with and without context ID.
    
    Args:
        contextId: Optional context ID (GUID) for tracking individual calls
        request: FastAPI request object
        db: Database session
        
    Returns:
        Dict[str, Any]: Webhook handling result
    """
    try:
        # Extract query parameters (callerId, callId) from callback URL if context ID is provided
        caller_id = None
        call_id = None
        if contextId:
            caller_id = request.query_params.get("callerId")
            call_id = request.query_params.get("callId")
            
            logger.info(
                f"Webhook event received with context ID: {contextId}",
                LogCategory.API,
                extra_data={
                    "context_id": contextId,
                    "caller_id": caller_id,
                    "call_id": call_id,
                    "query_params": dict(request.query_params)
                }
            )
        
        # Handle OPTIONS request for CORS preflight
        if request.method == "OPTIONS":
            # Check if this is a CloudEvents v1.0 validation request
            webhook_request_origin = request.headers.get("WebHook-Request-Origin")
            webhook_request_callback = request.headers.get("WebHook-Request-Callback")
            
            if webhook_request_origin and webhook_request_callback:
                logger.info(
                    f"CloudEvents v1.0 validation request from {webhook_request_origin}",
                    LogCategory.API,
                    extra_data={
                        "webhook_request_origin": webhook_request_origin,
                        "webhook_request_callback": webhook_request_callback,
                        "client_ip": request.client.host if request.client else "unknown"
                    }
                )
                
                # Return required headers for CloudEvents v1.0 validation
                return JSONResponse(
                    content={"message": "CloudEvents v1.0 validation successful"},
                    headers={
                        "WebHook-Allowed-Origin": webhook_request_origin,
                        "WebHook-Allowed-Rate": "120"
                    }
                )
            else:
                # Regular CORS preflight
                return JSONResponse(
                    content={"message": "CORS preflight request handled"},
                    headers={
                        "Access-Control-Allow-Origin": "*",
                        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                        "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Request-ID, WebHook-Request-Origin, WebHook-Request-Callback"
                    }
                )
        
        # Handle GET requests (browser access, validation, etc.)
        if request.method == "GET":
            logger.info(
                "GET request to webhook endpoint (likely browser access or validation)",
                LogCategory.API,
                extra_data={
                    "client_ip": request.client.host if request.client else "unknown",
                    "user_agent": request.headers.get("user-agent", "unknown")
                }
            )
            return {
                "message": "Webhook endpoint is active",
                "endpoint": "/api/v1/acs/webhooks/events",
                "methods": ["POST", "GET", "OPTIONS"],
                "note": "This endpoint receives webhook events from Azure Communication Services. Use POST to send events."
            }
        
        # Handle ACS webhook events (POST requests)
        acs_service = get_azure_communication_service()
        
        # Log comprehensive webhook request details for debugging
        all_headers = dict(request.headers)
        query_params = dict(request.query_params)
        
        logger.info(
            f"Webhook POST request received",
            LogCategory.API,
            extra_data={
                "method": request.method,
                "path": request.url.path,
                "full_url": str(request.url),
                "client_ip": request.client.host if request.client else "unknown",
                "user_agent": request.headers.get("user-agent", "unknown"),
                "content_type": request.headers.get("content-type", "unknown"),
                "content_length": request.headers.get("content-length", "unknown"),
                "all_headers": all_headers,  # Log all headers for debugging
                "query_params": query_params,  # Log query parameters
                "has_body": request.headers.get("content-length") is not None
            }
        )
        
        # Parse payload first to check if it's an Event Grid validation event
        # IMPORTANT: Handle validation events BEFORE rate limiting to allow handshake
        try:
            payload_bytes = await request.body()
            if not payload_bytes:
                logger.warning(
                    "Empty payload received in POST request",
                    LogCategory.API,
                    extra_data={
                        "client_ip": request.client.host if request.client else "unknown",
                        "path": request.url.path
                    }
                )
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Empty payload"
                )
            payload = json.loads(payload_bytes.decode('utf-8'))
            
            # Log comprehensive payload structure for debugging
            # Determine if this is an Event Grid event or Call Automation event
            is_event_grid = False
            is_call_automation = False
            event_type_hint = None
            
            if isinstance(payload, list) and len(payload) > 0:
                first_event = payload[0]
                if isinstance(first_event, dict):
                    event_type_hint = first_event.get('type') or first_event.get('eventType')
                    is_event_grid = event_type_hint and event_type_hint.startswith('Microsoft.Communication.') and not event_type_hint.startswith('Microsoft.Communication.CallAutomation.')
                    is_call_automation = event_type_hint and event_type_hint.startswith('Microsoft.Communication.CallAutomation.')
            elif isinstance(payload, dict):
                event_type_hint = payload.get('type') or payload.get('eventType')
                is_event_grid = event_type_hint and event_type_hint.startswith('Microsoft.Communication.') and not event_type_hint.startswith('Microsoft.Communication.CallAutomation.')
                is_call_automation = event_type_hint and event_type_hint.startswith('Microsoft.Communication.CallAutomation.')
            
            logger.info(
                f"Webhook payload parsed successfully",
                LogCategory.API,
                extra_data={
                    "payload_type": type(payload).__name__,
                    "is_list": isinstance(payload, list),
                    "is_dict": isinstance(payload, dict),
                    "payload_keys": list(payload.keys()) if isinstance(payload, dict) else None,
                    "payload_length": len(payload) if isinstance(payload, (list, dict)) else None,
                    "event_type_hint": event_type_hint,
                    "is_event_grid": is_event_grid,
                    "is_call_automation": is_call_automation,
                    "full_payload": payload  # Log full payload for debugging
                }
            )
        except json.JSONDecodeError as e:
            logger.error(
                f"Invalid JSON in webhook payload: {e}",
                LogCategory.API,
                exception=e,
                extra_data={
                    "client_ip": request.client.host if request.client else "unknown",
                    "path": request.url.path,
                    "content_length": request.headers.get("content-length", "unknown")
                }
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid JSON payload"
            )
        
        # Handle Event Grid validation handshake (SubscriptionValidationEvent)
        # MUST be checked BEFORE rate limiting to allow Event Grid handshake
        # Event Grid sends an array of events, so we need to check each one
        # According to Azure Event Grid documentation:
        # - Synchronous validation: Event Grid sends validationCode, we return {"validationResponse": code}
        # - Asynchronous validation: Event Grid sends validationUrl, we must GET that URL within 10 minutes
        # - Response must be 200 OK with Content-Type: application/json
        # - Response body must be exactly: {"validationResponse": "<code>"}
        if isinstance(payload, list) and len(payload) > 0:
            # Check if any event in the array is a validation event
            for event in payload:
                # Check both 'eventType' (Event Grid) and 'type' (CloudEvents) fields
                event_type = event.get('eventType') or event.get('type')
                if event_type == 'Microsoft.EventGrid.SubscriptionValidationEvent':
                    event_data = event.get('data', {})
                    validation_code = event_data.get('validationCode')
                    validation_url = event_data.get('validationUrl')
                    
                    if validation_code:
                        logger.info(
                            f"Event Grid synchronous validation handshake received: {validation_code}",
                            LogCategory.API,
                            extra_data={
                                "validation_code": validation_code,
                                "client_ip": request.client.host if request.client else "unknown",
                                "event_type": event_type,
                                "validation_method": "synchronous"
                            }
                        )
                        # Return validation response immediately (before rate limiting)
                        # Response must be exactly: {"validationResponse": "<code>"} with 200 OK
                        # JSONResponse automatically sets Content-Type: application/json
                        return JSONResponse(
                            content={"validationResponse": validation_code},
                            status_code=status.HTTP_200_OK,
                            headers={"Content-Type": "application/json"}
                        )
                    elif validation_url:
                        # Asynchronous validation: Event Grid provides a validationUrl
                        # We need to perform a GET request to this URL within 10 minutes
                        logger.info(
                            f"Event Grid asynchronous validation received: {validation_url}",
                            LogCategory.API,
                            extra_data={
                                "validation_url": validation_url,
                                "client_ip": request.client.host if request.client else "unknown",
                                "event_type": event_type,
                                "validation_method": "asynchronous"
                            }
                        )
                        # Perform GET request to validationUrl asynchronously
                        try:
                            async with httpx.AsyncClient(timeout=30.0) as client:
                                validation_response = await client.get(validation_url)
                                if validation_response.status_code == 200:
                                    logger.info(
                                        f"Asynchronous validation completed successfully: {validation_url}",
                                        LogCategory.API
                                    )
                                    # Return 200 OK to acknowledge receipt
                                    return JSONResponse(
                                        content={"status": "validation_url_received", "message": "Asynchronous validation initiated"},
                                        status_code=status.HTTP_200_OK,
                                        headers={"Content-Type": "application/json"}
                                    )
                                else:
                                    logger.warning(
                                        f"Asynchronous validation URL returned {validation_response.status_code}: {validation_url}",
                                        LogCategory.API
                                    )
                                    # Still return 200 OK to acknowledge receipt
                                    return JSONResponse(
                                        content={"status": "validation_url_received", "message": "Asynchronous validation initiated"},
                                        status_code=status.HTTP_200_OK,
                                        headers={"Content-Type": "application/json"}
                                    )
                        except Exception as e:
                            logger.error(
                                f"Failed to perform asynchronous validation GET request: {e}",
                                LogCategory.API,
                                exception=e
                            )
                            # Still return 200 OK to acknowledge receipt
                            return JSONResponse(
                                content={"status": "validation_url_received", "message": "Asynchronous validation initiated"},
                                status_code=status.HTTP_200_OK,
                                headers={"Content-Type": "application/json"}
                            )
                    else:
                        logger.warning(
                            "Event Grid validation event missing both validationCode and validationUrl",
                            LogCategory.API,
                            extra_data={"event": event}
                        )
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Missing validationCode or validationUrl in Event Grid validation event"
                        )
        elif isinstance(payload, dict):
            # Check both 'eventType' (Event Grid) and 'type' (CloudEvents) fields
            event_type = payload.get('eventType') or payload.get('type')
            if event_type == 'Microsoft.EventGrid.SubscriptionValidationEvent':
                event_data = payload.get('data', {})
                validation_code = event_data.get('validationCode')
                validation_url = event_data.get('validationUrl')
                
                if validation_code:
                    logger.info(
                        f"Event Grid synchronous validation handshake received: {validation_code}",
                        LogCategory.API,
                        extra_data={
                            "validation_code": validation_code,
                            "client_ip": request.client.host if request.client else "unknown",
                            "event_type": event_type,
                            "validation_method": "synchronous"
                        }
                    )
                    # Return validation response immediately (before rate limiting)
                    # Response must be exactly: {"validationResponse": "<code>"} with 200 OK
                    # JSONResponse automatically sets Content-Type: application/json
                    return JSONResponse(
                        content={"validationResponse": validation_code},
                        status_code=status.HTTP_200_OK,
                        headers={"Content-Type": "application/json"}
                    )
                elif validation_url:
                    # Asynchronous validation: Event Grid provides a validationUrl
                    # We need to perform a GET request to this URL within 10 minutes
                    logger.info(
                        f"Event Grid asynchronous validation received: {validation_url}",
                        LogCategory.API,
                        extra_data={
                            "validation_url": validation_url,
                            "client_ip": request.client.host if request.client else "unknown",
                            "event_type": event_type,
                            "validation_method": "asynchronous"
                        }
                    )
                    # Perform GET request to validationUrl asynchronously
                    try:
                        async with httpx.AsyncClient(timeout=30.0) as client:
                            validation_response = await client.get(validation_url)
                            if validation_response.status_code == 200:
                                logger.info(
                                    f"Asynchronous validation completed successfully: {validation_url}",
                                    LogCategory.API
                                )
                                # Return 200 OK to acknowledge receipt
                                return JSONResponse(
                                    content={"status": "validation_url_received", "message": "Asynchronous validation initiated"},
                                    status_code=status.HTTP_200_OK,
                                    headers={"Content-Type": "application/json"}
                                )
                            else:
                                logger.warning(
                                    f"Asynchronous validation URL returned {validation_response.status_code}: {validation_url}",
                                    LogCategory.API
                                )
                                # Still return 200 OK to acknowledge receipt
                                return JSONResponse(
                                    content={"status": "validation_url_received", "message": "Asynchronous validation initiated"},
                                    status_code=status.HTTP_200_OK,
                                    headers={"Content-Type": "application/json"}
                                )
                    except Exception as e:
                        logger.error(
                            f"Failed to perform asynchronous validation GET request: {e}",
                            LogCategory.API,
                            exception=e
                        )
                        # Still return 200 OK to acknowledge receipt
                        return JSONResponse(
                            content={"status": "validation_url_received", "message": "Asynchronous validation initiated"},
                            status_code=status.HTTP_200_OK,
                            headers={"Content-Type": "application/json"}
                        )
                else:
                    logger.warning(
                        "Event Grid validation event missing both validationCode and validationUrl",
                        LogCategory.API,
                        extra_data={"payload": payload}
                    )
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Missing validationCode or validationUrl in Event Grid validation event"
                    )
        
        # Extract clinic_id for rate limiting: Single-tenant mode (CLINIC_ID env var) or multi-tenant mode (phone lookup)
        # Only do this AFTER validation check to avoid blocking validation handshake
        to_number = None
        try:
            # Try to extract phone number from payload
            if isinstance(payload, list) and len(payload) > 0:
                # For Event Grid events, look in the first event
                first_event = payload[0]
                to_number = first_event.get('data', {}).get('to', {}).get('phoneNumber', {}).get('value')
            elif isinstance(payload, dict):
                to_number = payload.get('data', {}).get('to', {}).get('phoneNumber', {}).get('value')
        except Exception as e:
            logger.warning(
                f"Could not extract phone number from payload: {e}",
                LogCategory.API,
                exception=e
            )
        
        clinic_id = await get_clinic_id_from_env_or_phone(to_number, db)
        
        # Check webhook rate limit (DoS protection)
        # Rate limiting removed - concurrent calls are handled by admission_controller.py

        # Process events - handle both single event and array of events
        events_to_process = payload if isinstance(payload, list) else [payload]
        
        results = []
        for event_payload in events_to_process:
            if not isinstance(event_payload, dict):
                logger.warning(
                    f"Skipping non-dict event: {event_payload}",
                    LogCategory.API,
                    extra_data={"event_payload_type": type(event_payload).__name__}
                )
                continue
                
            # Event Grid uses 'type' field, Call Automation uses 'eventType' field
            # Check both fields to handle all event formats
            event_type_checks = {
                "type": event_payload.get('type'),
                "eventType": event_payload.get('eventType'),
                "data.type": None,
                "data.eventType": None
            }
            
            event_type = event_payload.get('type') or event_payload.get('eventType') or 'unknown'
            call_connection_id = event_payload.get('callConnectionId')
            
            # For Event Grid events, also check in 'data' field
            if event_type == 'unknown' and 'data' in event_payload:
                data = event_payload.get('data', {})
                if isinstance(data, dict):
                    data_type = data.get('type')
                    data_event_type = data.get('eventType')
                    event_type_checks["data.type"] = data_type
                    event_type_checks["data.eventType"] = data_event_type
                    event_type = data_type or data_event_type or event_type
            
            logger.info(
                f"Processing webhook event: {event_type}",
                LogCategory.API,
                extra_data={
                    "event_type": event_type,
                    "event_type_checks": event_type_checks,
                    "call_connection_id": call_connection_id,
                    "event_payload_keys": list(event_payload.keys()) if isinstance(event_payload, dict) else None,
                    "event_payload_structure": event_payload if event_type == 'unknown' else None  # Log full structure for unknown events
                }
            )

            # Check if this is a Call Automation event (signed with ACS webhook secret)
            is_call_automation_event = event_type.startswith('Microsoft.Communication.CallAutomation.')
            
            # Check if this is an Event Grid event (not signed with ACS webhook secret)
            is_event_grid_event = (
                event_type.startswith('Microsoft.Communication.') and
                not event_type.startswith('Microsoft.Communication.CallAutomation.')
            )

            # Only verify ACS webhook signature for Call Automation events
            if is_call_automation_event:
                if not acs_service.verify_webhook_signature(request, payload_bytes):
                    logger.warning(
                        "Invalid webhook signature received for Call Automation event",
                        LogCategory.API,
                        extra_data={
                            "client_ip": request.client.host if request.client else "unknown",
                            "user_agent": request.headers.get("user-agent", "unknown"),
                            "event_type": event_type
                        }
                    )
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Invalid webhook signature"
                    )
            elif is_event_grid_event:
                # Issue 6.4: Event Grid events do not need signature verification
                # Event Grid uses Azure AD authentication and HTTPS transport security
                # The events are sent over HTTPS from Azure's infrastructure, which provides
                # transport-level security. Event Grid also supports validation handshakes
                # (SubscriptionValidationEvent) which we handle separately.
                # Unlike Call Automation webhooks which use HMAC signatures, Event Grid
                # relies on Azure AD authentication and HTTPS for security.
                logger.info(
                    "Event Grid event received, skipping ACS signature verification",
                    LogCategory.API,
                    extra_data={
                        "event_type": event_type,
                        "reason": "Event Grid uses Azure AD authentication and HTTPS transport security"
                    }
                )
            else:
                logger.info(
                    "Non-Call Automation event received, skipping ACS signature verification",
                    LogCategory.API,
                    extra_data={"event_type": event_type}
                )

            # Handle different types of call events
            # According to Azure Communication Services Call Automation documentation:
            # - Call Automation events: IncomingCallReceived, CallConnected, CallDisconnected, PlayCompleted, etc.
            # - Event Grid events: IncomingCall, CallStarted, CallEnded (requires HTTPS subscription)
            # 
            # Event Flow:
            # 1. Event Grid IncomingCall → Answer call → CallConnected → Initialize call
            # 
            # Note: Event Grid requires HTTPS for webhook subscriptions (container uses HTTP)
            # If Event Grid events are not received, phone number must be configured in Azure Portal
            # Note: IncomingCallReceived handler removed - only using Event Grid IncomingCall flow

            # Handle CallConnected event from Call Automation (when call is answered)
            # This is sent after successfully answering an incoming call
            # This confirms the call connection is established
            # After this event, we can start playing audio, capturing speech, etc.
            if event_type == 'Microsoft.Communication.CallAutomation.CallConnected':
                result = await handle_call_connected_event(acs_service, event_payload, db)

            # Handle CallDisconnected event from Call Automation (when call ends)
            # This is sent when a call ends or is disconnected
            elif event_type == 'Microsoft.Communication.CallAutomation.CallDisconnected':
                result = await handle_call_disconnected_event(acs_service, event_payload, db)

            # Handle Event Grid IncomingCall event (when someone calls via Event Grid)
            # This is sent when someone calls the phone number (requires HTTPS subscription)
            # Contains incomingCallContext which is required to answer the call
            # Check multiple possible event type formats
            elif (event_type == 'Microsoft.Communication.IncomingCall' or 
                  event_type.startswith('Microsoft.Communication.IncomingCall') or
                  'IncomingCall' in event_type):
                result = await handle_event_grid_incoming_call(acs_service, event_payload, db)

            # Handle Event Grid CallStarted event (when call starts via Event Grid)
            # This is sent when a call starts (requires HTTPS subscription)
            # Just log it - no action needed as call is already handled by IncomingCall event
            elif event_type == 'Microsoft.Communication.CallStarted':
                call_id = event_payload.get('data', {}).get('callId') or event_payload.get('id', 'unknown')
                logger.info(
                    f"Event Grid CallStarted event: {call_id}",
                    LogCategory.API,
                    extra_data={"call_id": call_id, "payload": event_payload}
                )
                result = {
                    "status": "call_started",
                    "message": f"Event Grid call {call_id} started",
                    "call_id": call_id,
                    "timestamp": datetime.now(AST).isoformat()
                }

            # Handle Event Grid CallEnded event (when call ends via Event Grid)
            # This is sent when a call ends (requires HTTPS subscription)
            elif event_type == 'Microsoft.Communication.CallEnded':
                result = await handle_event_grid_call_ended(acs_service, event_payload, db)

            # Handle other Call Automation events
            else:
                result = await acs_service.handle_webhook_event(request, event_payload)
            
            results.append(result)
        
        # Return results - single result if single event, array if multiple events
        return results[0] if len(results) == 1 else {"results": results}

    except Exception as e:
        logger.error(
            f"Error processing webhook event: {e}",
            LogCategory.API,
            exception=e,
            extra_data={
                "context_id": contextId,
                "client_ip": request.client.host if request.client else "unknown",
                "path": request.url.path
            }
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing webhook event: {e}"
        )


# WebSocket endpoint for audio streaming
@router.websocket("/ws/audio/{call_id}")
async def websocket_audio_stream(
    websocket: WebSocket,
    call_id: str,
    db: AsyncSession = Depends(get_async_db)
):
    """
    WebSocket endpoint for real-time audio streaming.
    
    Args:
        websocket: WebSocket connection
        call_id: ID of the call
        db: Database session
    """
    connection_id = None
    
    try:
        # Issue 111: Verify call exists in orchestrator before connecting audio stream
        from services.call_orchestrator import get_call_orchestrator
        orchestrator = get_call_orchestrator()
        
        # Issue 111: Check if call exists before connecting
        async with orchestrator._calls_lock:
            if call_id not in orchestrator.active_calls:
                logger.warning(f"Call {call_id} not found in orchestrator, closing WebSocket", LogCategory.API)
                await websocket.close(code=1008, reason="Call not found")
                return
        
        audio_handler = get_audio_stream_handler()
        
        # Issue 137: Check if connection already exists for this call
        # Check for existing connections before creating new ones
        async with audio_handler._connections_lock:
            existing_connections = [
                conn_id for conn_id, conn in audio_handler.active_connections.items()
                if conn.call_id == call_id and conn.is_active
            ]
            if existing_connections:
                logger.warning(
                    f"Existing audio connection(s) found for call {call_id}: {existing_connections}",
                    LogCategory.API
                )
                # Issue 137: Close existing connections or handle multiple connections gracefully
                # For now, close existing connections to prevent conflicts
                for existing_conn_id in existing_connections:
                    try:
                        await audio_handler.disconnect_audio_stream(existing_conn_id)
                    except Exception as e:
                        logger.warning(
                            f"Failed to close existing connection {existing_conn_id}: {e}",
                            LogCategory.API,
                            exception=e,
                            extra_data={"call_id": call_id, "existing_conn_id": existing_conn_id}
                        )
        
        # Issue 132: Verify connection succeeds before continuing
        connection_id = await audio_handler.connect_audio_stream(websocket, call_id)
        if not connection_id:
            logger.error(f"Failed to connect audio stream for call {call_id}", LogCategory.API)
            await websocket.close(code=1011, reason="Failed to connect audio stream")
            return
        
        logger.info(
            f"Audio stream connected for call {call_id}",
            LogCategory.API,
            extra_data={"call_id": call_id, "connection_id": connection_id}
        )
        
        # Delegate to orchestrator to connect audio stream (handles STT initialization)
        success = await orchestrator.connect_audio_stream(call_id, connection_id)
        if not success:
            logger.warning(f"Failed to connect audio stream via orchestrator for call {call_id}", LogCategory.API)
            # Continue - audio stream connection failure shouldn't stop the call
        
        # Keep connection alive
        while True:
            try:
                # Issue 6: Receive bytes instead of text for audio data
                data = await websocket.receive_bytes()
                
                # Issue 16: Pass received data to audio handler
                await audio_handler.handle_incoming_audio(connection_id, data)
                
            except WebSocketDisconnect:
                logger.info(
                    f"WebSocket disconnected for call {call_id}",
                    LogCategory.API,
                    extra_data={"call_id": call_id, "connection_id": connection_id}
                )
                break
            except Exception as e:
                logger.error(
                    f"Error in WebSocket for call {call_id}: {e}",
                    LogCategory.API,
                    exception=e,
                    extra_data={"call_id": call_id, "connection_id": connection_id}
                )
                break
                
    except Exception as e:
        logger.error(
            f"Failed to establish audio stream for call {call_id}: {e}",
            LogCategory.API,
            exception=e,
            extra_data={"call_id": call_id}
        )
        try:
            await websocket.close(code=1011, reason="Internal server error")
        except Exception as close_error:
            logger.warning(
                f"Failed to close WebSocket after error: {close_error}",
                LogCategory.API,
                exception=close_error,
                extra_data={"call_id": call_id}
            )
    finally:
        # Issue 4.5: Ensure WebSocket and connection are cleaned up in finally block
        try:
            # Clean up audio stream connection
            if connection_id:
                try:
                    audio_handler = get_audio_stream_handler()
                    await audio_handler.disconnect_audio_stream(connection_id)
                except Exception as disconnect_error:
                    logger.error(
                        f"Error disconnecting audio stream for call {call_id}: {disconnect_error}",
                        LogCategory.API,
                        exception=disconnect_error,
                        extra_data={"call_id": call_id, "connection_id": connection_id}
                    )
            
            # Issue 4.5: Ensure WebSocket is closed
            try:
                if websocket.client_state.name != "DISCONNECTED":
                    await websocket.close(code=1000, reason="Connection cleanup")
            except Exception as close_error:
                # WebSocket may already be closed, ignore
                logger.debug(
                    f"WebSocket already closed or close failed: {close_error}",
                    LogCategory.API,
                    exception=close_error,
                    extra_data={"call_id": call_id}
                )
        except Exception as cleanup_error:
            logger.error(
                f"Error in finally block cleanup for call {call_id}: {cleanup_error}",
                LogCategory.API,
                exception=cleanup_error,
                extra_data={"call_id": call_id, "connection_id": connection_id}
            )


# Health and monitoring endpoints
@router.get("/health", response_model=Dict[str, Any])
async def get_acs_health():
    """
    Get Azure Communication Services health status.
    
    Returns:
        Dict[str, Any]: Health status information
    """
    try:
        acs_service = get_azure_communication_service()
        
        # Check ACS service health
        health_status = await acs_service.get_health_status()
        
        return {
            "status": "healthy",
            "acs_service": health_status,
            "timestamp": datetime.now(AST).isoformat()
        }
        
    except Exception as e:
        logger.error(
            f"ACS health check failed: {e}",
            LogCategory.API,
            exception=e
        )
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.now(AST).isoformat()
        }

