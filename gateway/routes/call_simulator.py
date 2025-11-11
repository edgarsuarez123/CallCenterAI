"""
Call Simulator API Routes

Provides endpoints for simulating phone calls and testing the call flow system.
This simulator uses CallOrchestrator to ensure the same code path as production,
but skips audio streaming and ACS registration for simulation purposes.

Critical for testing and development of call flow logic without requiring
actual phone calls or Azure Communication Services setup.
"""

from fastapi import APIRouter, HTTPException, Depends, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any
from pydantic import BaseModel

from services.database import get_async_db
from services.call_orchestrator import get_call_orchestrator
from services.call_flow_service import CallFlowService
from services.clinic_template_variables import get_clinic_template_variables
from services.nlp_service import get_nlp_service
from services.structured_logging import get_logger, LogCategory
from services.exceptions import (
    CallCenterAIException, ValidationError, ErrorCode, CallNotFoundError
)
from models.call_flow_models import (
    CallSimulationRequest, CallInputRequest, CallStatusResponse
)
from models.schemas import SuccessResponse

router = APIRouter(prefix="/call-simulator", tags=["Call Simulator"])
logger = get_logger("call_simulator")


class EndCallResponse(BaseModel):
    """Response model for ending a call simulation."""
    message: str
    call_sid: str


@router.post("/start-call", response_model=CallStatusResponse)
async def start_call_simulation(
    request: CallSimulationRequest,
    db: AsyncSession = Depends(get_async_db)
):
    """
    Start a new call simulation.
    
    This endpoint simulates an incoming phone call using CallOrchestrator
    to ensure the same code path as production, but skips audio streaming
    and ACS registration for simulation purposes.
    
    Args:
        request: Call simulation request with caller phone and clinic ID
        db: Database session
        
    Returns:
        CallStatusResponse with call SID, initial state, and greeting message
        
    Raises:
        HTTPException 400: Invalid request parameters
        HTTPException 500: Internal server error
    """
    try:
        logger.info(
            "Starting call simulation",
            LogCategory.API,
            extra_data={
                "caller_phone": request.caller_phone,
                "clinic_id": request.clinic_id
            }
        )
        
        orchestrator = get_call_orchestrator()
        
        # Generate a mock call SID for simulation
        # Use hash to ensure uniqueness while keeping it deterministic
        phone_clean = request.caller_phone.replace('+', '').replace('-', '').replace(' ', '')
        call_sid = f"SIM_{phone_clean}_{abs(hash(request.caller_phone)) % 10000:04d}"
        
        # Use CallOrchestrator to start the call (same as production)
        # This internally calls CallFlowService.initialize_call()
        call_context = await orchestrator.start_call(
            call_id=call_sid,
            caller_phone=request.caller_phone,
            clinic_id=request.clinic_id,
            call_type='inbound',
            call_metadata={'is_simulation': True}
        )
        
        # Get the call flow context from orchestrator metadata
        call_flow_context = call_context.metadata.get('call_flow_context')
        if not call_flow_context:
            # Fallback: get from CallFlowService directly
            call_flow_service = CallFlowService(db)
            call_flow_context = await call_flow_service.get_call_status(call_sid)
        
        # Get initial greeting message
        clinic_vars = await get_clinic_template_variables(request.clinic_id, db)
        message = f"Hello! Thank you for calling {clinic_vars.get('clinic_name', 'our clinic')}. How can I help you today?"
        
        logger.info(
            f"Call simulation started successfully: {call_sid}",
            LogCategory.API,
            extra_data={"call_sid": call_sid, "clinic_id": request.clinic_id}
        )
        
        return CallStatusResponse(
            call_sid=call_sid,
            current_state=call_flow_context.current_state if call_flow_context else None,
            message=message,
            options=[],
            requires_input=True,
            is_complete=False,
            context=call_flow_context
        )
        
    except HTTPException:
        raise
    except CallCenterAIException as e:
        http_status = e.http_status if hasattr(e, 'http_status') and e.http_status != 500 else (
            status.HTTP_400_BAD_REQUEST if e.error_code == ErrorCode.VALIDATION_ERROR
            else status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        logger.error(
            f"Service error starting call simulation: {e.user_message}",
            LogCategory.ERROR,
            extra_data={
                "caller_phone": request.caller_phone if hasattr(request, 'caller_phone') else None,
                "clinic_id": request.clinic_id if hasattr(request, 'clinic_id') else None
            }
        )
        raise HTTPException(
            status_code=http_status,
            detail=e.user_message
        )
    except Exception as e:
        logger.critical(
            f"Unexpected error starting call simulation: {e}",
            LogCategory.EXCEPTION,
            exception=e,
            extra_data={
                "caller_phone": request.caller_phone if hasattr(request, 'caller_phone') else None,
                "clinic_id": request.clinic_id if hasattr(request, 'clinic_id') else None
            }
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while starting the call simulation"
        )


@router.post("/call/{call_sid}/input", response_model=CallStatusResponse)
async def process_call_input(
    call_sid: str = Query(..., min_length=3, max_length=128, description="Call SID"),
    request: CallInputRequest = ...,
    db: AsyncSession = Depends(get_async_db)
):
    """
    Process user input during a call simulation.
    
    This endpoint simulates the user speaking or typing during a call
    and returns the AI's response. Uses CallOrchestrator's processing pipeline
    to ensure the same code path as production.
    
    Args:
        call_sid: Call SID to process input for
        request: Call input request with user input text
        db: Database session
        
    Returns:
        CallStatusResponse with updated state, message, and options
        
    Raises:
        HTTPException 404: Call not found
        HTTPException 400: Invalid input
        HTTPException 500: Internal server error
    """
    try:
        logger.info(
            f"Processing input for call {call_sid}",
            LogCategory.API,
            extra_data={
                "call_sid": call_sid,
                "input_length": len(request.user_input) if hasattr(request, 'user_input') else 0
            }
        )
        
        orchestrator = get_call_orchestrator()
        
        # Check if call exists in orchestrator
        # Note: Accessing _calls_lock for thread-safe access to active_calls
        # This is necessary for proper synchronization
        async with orchestrator._calls_lock:
            if call_sid not in orchestrator.active_calls:
                # Call not in orchestrator - fallback to CallFlowService
                call_flow_service = CallFlowService(db)
                response = await call_flow_service.process_user_input(
                    call_sid=call_sid,
                    user_input=request.user_input
                )
                context = await call_flow_service.get_call_status(call_sid)
                
                logger.info(
                    f"Processed input for call {call_sid} via CallFlowService",
                    LogCategory.API,
                    extra_data={"call_sid": call_sid, "next_state": response.next_state}
                )
                
                return CallStatusResponse(
                    call_sid=call_sid,
                    current_state=response.next_state,
                    message=response.message,
                    options=response.options,
                    requires_input=response.requires_input,
                    is_complete=response.is_complete,
                    context=context
                )
        
        # Use orchestrator's processing pipeline (same as production)
        # This handles STT → NLP → TTS pipeline
        call_context = orchestrator.active_calls[call_sid]
        
        # Process user input through orchestrator's NLP pipeline
        # For simulation, we skip STT and pass text directly
        # Note: Intent classification is done internally by CallFlowService
        nlp_service = get_nlp_service()
        
        # Classify intent (used internally by CallFlowService)
        await nlp_service.classify_intent(
            user_input=request.user_input,
            call_context=call_context
        )
        
        # Process through CallFlowService for appointment booking logic
        call_flow_service = CallFlowService(db)
        response = await call_flow_service.process_user_input(
            call_sid=call_sid,
            user_input=request.user_input
        )
        
        # Get the updated call context
        context = await call_flow_service.get_call_status(call_sid)
        
        logger.info(
            f"Processed input for call {call_sid}",
            LogCategory.API,
            extra_data={
                "call_sid": call_sid,
                "next_state": response.next_state,
                "is_complete": response.is_complete
            }
        )
        
        return CallStatusResponse(
            call_sid=call_sid,
            current_state=response.next_state,
            message=response.message,
            options=response.options,
            requires_input=response.requires_input,
            is_complete=response.is_complete,
            context=context
        )
        
    except HTTPException:
        raise
    except CallNotFoundError as e:
        logger.warning(
            f"Call {call_sid} not found for input processing",
            LogCategory.API,
            extra_data={"call_sid": call_sid}
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Call {call_sid} not found"
        )
    except CallCenterAIException as e:
        http_status = e.http_status if hasattr(e, 'http_status') and e.http_status != 500 else (
            status.HTTP_400_BAD_REQUEST if e.error_code == ErrorCode.VALIDATION_ERROR
            else status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        logger.error(
            f"Service error processing call input: {e.user_message}",
            LogCategory.ERROR,
            extra_data={"call_sid": call_sid}
        )
        raise HTTPException(
            status_code=http_status,
            detail=e.user_message
        )
    except Exception as e:
        logger.critical(
            f"Unexpected error processing call input: {e}",
            LogCategory.EXCEPTION,
            exception=e,
            extra_data={"call_sid": call_sid}
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while processing call input"
        )


@router.get("/call/{call_sid}/status", response_model=CallStatusResponse)
async def get_call_status(
    call_sid: str = Query(..., min_length=3, max_length=128, description="Call SID"),
    db: AsyncSession = Depends(get_async_db)
):
    """
    Get the current status of a call simulation.
    
    This endpoint returns the current state of the call conversation
    and any pending information.
    
    Args:
        call_sid: Call SID to get status for
        db: Database session
        
    Returns:
        CallStatusResponse with current call state and context
        
    Raises:
        HTTPException 404: Call not found
        HTTPException 500: Internal server error
    """
    try:
        logger.info(
            f"Getting status for call {call_sid}",
            LogCategory.API,
            extra_data={"call_sid": call_sid}
        )
        
        orchestrator = get_call_orchestrator()
        
        # Check if call exists in orchestrator
        # Note: Accessing _calls_lock for thread-safe access to active_calls
        async with orchestrator._calls_lock:
            if call_sid in orchestrator.active_calls:
                call_context = orchestrator.active_calls[call_sid]
                call_flow_context = call_context.metadata.get('call_flow_context')
                
                if call_flow_context:
                    logger.info(
                        f"Retrieved status for call {call_sid} from orchestrator",
                        LogCategory.API,
                        extra_data={"call_sid": call_sid}
                    )
                    return CallStatusResponse(
                        call_sid=call_sid,
                        current_state=call_flow_context.current_state,
                        message="Call is active",
                        options=[],
                        requires_input=True,
                        is_complete=False,
                        context=call_flow_context
                    )
        
        # Fallback to CallFlowService
        call_flow_service = CallFlowService(db)
        context = await call_flow_service.get_call_status(call_sid)
        
        if not context:
            logger.warning(
                f"Call {call_sid} not found",
                LogCategory.API,
                extra_data={"call_sid": call_sid}
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Call {call_sid} not found"
            )
        
        logger.info(
            f"Retrieved status for call {call_sid} from CallFlowService",
            LogCategory.API,
            extra_data={"call_sid": call_sid}
        )
        
        return CallStatusResponse(
            call_sid=call_sid,
            current_state=context.current_state,
            message="Call is active",
            options=[],
            requires_input=True,
            is_complete=False,
            context=context
        )
        
    except HTTPException:
        raise
    except CallNotFoundError as e:
        logger.warning(
            f"Call {call_sid} not found",
            LogCategory.API,
            extra_data={"call_sid": call_sid}
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Call {call_sid} not found"
        )
    except Exception as e:
        logger.critical(
            f"Unexpected error getting call status: {e}",
            LogCategory.EXCEPTION,
            exception=e,
            extra_data={"call_sid": call_sid}
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while retrieving call status"
        )


@router.post("/call/{call_sid}/end", response_model=EndCallResponse)
async def end_call_simulation(
    call_sid: str = Query(..., min_length=3, max_length=128, description="Call SID"),
    db: AsyncSession = Depends(get_async_db)
):
    """
    End a call simulation.
    
    This endpoint terminates the call simulation and cleans up resources.
    Uses CallOrchestrator to ensure proper cleanup (same as production).
    
    Args:
        call_sid: Call SID to end
        db: Database session
        
    Returns:
        EndCallResponse with confirmation message and call SID
        
    Raises:
        HTTPException 404: Call not found
        HTTPException 500: Internal server error
    """
    try:
        logger.info(
            f"Ending call simulation: {call_sid}",
            LogCategory.API,
            extra_data={"call_sid": call_sid}
        )
        
        orchestrator = get_call_orchestrator()
        
        # End call through orchestrator (same as production)
        # Note: Accessing _calls_lock for thread-safe access to active_calls
        async with orchestrator._calls_lock:
            if call_sid in orchestrator.active_calls:
                await orchestrator.end_call(call_sid, "simulation_ended")
        
        # Also end through CallFlowService for cleanup
        call_flow_service = CallFlowService(db)
        success = await call_flow_service.end_call(call_sid)
        
        if not success:
            logger.warning(
                f"CallFlowService.end_call returned False for {call_sid}",
                LogCategory.API,
                extra_data={"call_sid": call_sid}
            )
        
        logger.info(
            f"Call simulation ended successfully: {call_sid}",
            LogCategory.API,
            extra_data={"call_sid": call_sid}
        )
        
        return EndCallResponse(
            message="Call ended successfully",
            call_sid=call_sid
        )
        
    except HTTPException:
        raise
    except CallNotFoundError as e:
        logger.warning(
            f"Call {call_sid} not found for ending",
            LogCategory.API,
            extra_data={"call_sid": call_sid}
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Call {call_sid} not found"
        )
    except CallCenterAIException as e:
        http_status = e.http_status if hasattr(e, 'http_status') and e.http_status != 500 else (
            status.HTTP_400_BAD_REQUEST if e.error_code == ErrorCode.VALIDATION_ERROR
            else status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        logger.error(
            f"Service error ending call simulation: {e.user_message}",
            LogCategory.ERROR,
            extra_data={"call_sid": call_sid}
        )
        raise HTTPException(
            status_code=http_status,
            detail=e.user_message
        )
    except Exception as e:
        logger.critical(
            f"Unexpected error ending call simulation: {e}",
            LogCategory.EXCEPTION,
            exception=e,
            extra_data={"call_sid": call_sid}
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while ending the call simulation"
        )


@router.get("/active-calls", response_model=Dict[str, Any])
async def get_active_calls():
    """
    Get list of active call simulations.
    
    This endpoint returns all currently active call simulations
    from CallOrchestrator for monitoring and debugging purposes.
    
    Returns:
        Dictionary with active_calls list and total_count
        
    Raises:
        HTTPException 500: Internal server error
    """
    try:
        logger.info(
            "Getting active call simulations",
            LogCategory.API
        )
        
        orchestrator = get_call_orchestrator()
        
        # Get active calls from orchestrator (same as production)
        # Note: Accessing _calls_lock for thread-safe access to active_calls
        async with orchestrator._calls_lock:
            active_calls = []
            for call_id, call_context in orchestrator.active_calls.items():
                # Only include simulation calls
                if call_context.metadata.get('is_simulation'):
                    call_flow_context = call_context.metadata.get('call_flow_context')
                    active_calls.append({
                        "call_sid": call_id,
                        "caller_phone": call_context.caller_phone,
                        "clinic_id": call_context.clinic_id,
                        "state": call_context.state.value if hasattr(call_context.state, 'value') else str(call_context.state),
                        "flow_state": call_flow_context.current_state.value if call_flow_context and hasattr(call_flow_context.current_state, 'value') else None,
                        "start_time": call_context.start_time.isoformat() if call_context.start_time else None
                    })
        
        logger.info(
            f"Retrieved {len(active_calls)} active simulation calls",
            LogCategory.API,
            extra_data={"count": len(active_calls)}
        )
        
        return {
            "active_calls": active_calls,
            "total_count": len(active_calls)
        }
        
    except Exception as e:
        logger.critical(
            f"Unexpected error getting active calls: {e}",
            LogCategory.EXCEPTION,
            exception=e
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while retrieving active calls"
        )


@router.get("/demo-scenarios", response_model=Dict[str, Any])
async def get_demo_scenarios():
    """
    Get predefined demo scenarios for testing.
    
    This endpoint returns a list of predefined scenarios that can be used
    to test different call flow paths.
    
    Returns:
        Dictionary with demo_scenarios list containing scenario definitions
        
    Raises:
        HTTPException 500: Internal server error
    """
    try:
        logger.info(
            "Getting demo scenarios",
            LogCategory.API
        )
        
        scenarios = [
            {
                "id": "new_patient_booking",
                "name": "New Patient Appointment Booking",
                "description": "Simulate a new patient calling to book their first appointment",
                "steps": [
                    "Call comes in",
                    "AI: 'Hello! Thank you for calling [Clinic Name]. How can I help you today?'",
                    "User: 'I'd like to book an appointment'",
                    "AI: 'I'd be happy to help you book an appointment. What's your name?'",
                    "User: 'John Smith'",
                    "AI: 'Nice to meet you, John. Have you been to our clinic before?'",
                    "User: 'No'",
                    "AI: 'Welcome! Let me get some information to set up your appointment. What's your date of birth?'",
                    "User: 'January 15th, 1990'",
                    "AI: 'Thank you. What's your insurance provider?'",
                    "User: 'Blue Cross'",
                    "AI: 'Perfect! Now, which doctor would you like to see?'",
                    "... continue through provider, date, time selection and confirmation"
                ]
            },
            {
                "id": "returning_patient_booking",
                "name": "Returning Patient Appointment Booking",
                "description": "Simulate a returning patient calling to book an appointment",
                "steps": [
                    "Call comes in",
                    "AI: 'Hello! Thank you for calling [Clinic Name]. How can I help you today?'",
                    "User: 'I'd like to book an appointment'",
                    "AI: 'I'd be happy to help you book an appointment. What's your name?'",
                    "User: 'Jane Doe'",
                    "AI: 'Nice to meet you, Jane. Have you been to our clinic before?'",
                    "User: 'Yes'",
                    "AI: 'Great! I found you in our system. Which doctor would you like to see?'",
                    "... continue through provider, date, time selection and confirmation"
                ]
            },
            {
                "id": "appointment_cancellation",
                "name": "Appointment Cancellation",
                "description": "Simulate a patient calling to cancel an appointment",
                "steps": [
                    "Call comes in",
                    "AI: 'Hello! Thank you for calling [Clinic Name]. How can I help you today?'",
                    "User: 'I need to cancel my appointment'",
                    "AI: 'I can help you with appointment changes. Let me transfer you to our staff.'"
                ]
            }
        ]
        
        logger.info(
            f"Retrieved {len(scenarios)} demo scenarios",
            LogCategory.API,
            extra_data={"scenario_count": len(scenarios)}
        )
        
        return {"demo_scenarios": scenarios}
        
    except Exception as e:
        logger.critical(
            f"Unexpected error getting demo scenarios: {e}",
            LogCategory.EXCEPTION,
            exception=e
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while retrieving demo scenarios"
        )
