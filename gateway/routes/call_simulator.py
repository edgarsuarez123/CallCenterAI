"""
Call Simulator API Routes
Provides endpoints for simulating phone calls and testing the call flow system.
"""

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from typing import Dict, Any
import logging

from services.database import get_db
from services.call_flow_service import CallFlowService
from services.call_store import list_calls
from models.call_flow_models import (
    CallSimulationRequest, CallInputRequest, CallStatusResponse,
    CallFlowResponse
)

router = APIRouter(prefix="/call-simulator", tags=["Call Simulator"])
logger = logging.getLogger(__name__)


@router.post("/start-call", response_model=CallStatusResponse)
async def start_call_simulation(
    request: CallSimulationRequest,
    db: Session = Depends(get_db)
):
    """
    Start a new call simulation.
    
    This endpoint simulates an incoming phone call and initializes
    the call flow conversation.
    """
    try:
        call_flow_service = CallFlowService(db)
        
        # Generate a mock call SID for simulation
        call_sid = f"SIM_{request.caller_phone.replace('+', '').replace('-', '')}_{hash(request.caller_phone) % 10000:04d}"
        
        # Initialize the call
        response = await call_flow_service.initialize_call(
            call_sid=call_sid,
            caller_phone=request.caller_phone,
            clinic_id=request.clinic_id
        )
        
        # Get the call context
        context = call_flow_service.get_call_status(call_sid)
        
        return CallStatusResponse(
            call_sid=call_sid,
            current_state=response.next_state,
            message=response.message,
            options=response.options,
            requires_input=response.requires_input,
            is_complete=response.is_complete,
            context=context
        )
        
    except Exception as e:
        logger.error(f"Failed to start call simulation: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to start call simulation: {str(e)}")


@router.post("/call/{call_sid}/input", response_model=CallStatusResponse)
async def process_call_input(
    call_sid: str,
    request: CallInputRequest,
    db: Session = Depends(get_db)
):
    """
    Process user input during a call simulation.
    
    This endpoint simulates the user speaking or typing during a call
    and returns the AI's response.
    """
    try:
        call_flow_service = CallFlowService(db)
        
        # Process the user input
        response = await call_flow_service.process_user_input(
            call_sid=call_sid,
            user_input=request.user_input
        )
        
        # Get the updated call context
        context = call_flow_service.get_call_status(call_sid)
        
        return CallStatusResponse(
            call_sid=call_sid,
            current_state=response.next_state,
            message=response.message,
            options=response.options,
            requires_input=response.requires_input,
            is_complete=response.is_complete,
            context=context
        )
        
    except Exception as e:
        logger.error(f"Failed to process call input: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to process call input: {str(e)}")


@router.get("/call/{call_sid}/status", response_model=CallStatusResponse)
def get_call_status(
    call_sid: str,
    db: Session = Depends(get_db)
):
    """
    Get the current status of a call simulation.
    
    This endpoint returns the current state of the call conversation
    and any pending information.
    """
    try:
        call_flow_service = CallFlowService(db)
        
        # Get the call context
        context = call_flow_service.get_call_status(call_sid)
        
        if not context:
            raise HTTPException(status_code=404, detail="Call not found")
        
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
    except Exception as e:
        logger.error(f"Failed to get call status: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get call status: {str(e)}")


@router.post("/call/{call_sid}/end")
def end_call_simulation(
    call_sid: str,
    db: Session = Depends(get_db)
):
    """
    End a call simulation.
    
    This endpoint terminates the call simulation and cleans up resources.
    """
    try:
        call_flow_service = CallFlowService(db)
        
        # End the call
        success = call_flow_service.end_call(call_sid)
        
        if not success:
            raise HTTPException(status_code=500, detail="Failed to end call")
        
        return {"message": "Call ended successfully", "call_sid": call_sid}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to end call simulation: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to end call simulation: {str(e)}")


@router.get("/active-calls")
def get_active_calls(db: Session = Depends(get_db)):
    """
    Get list of active call simulations.
    
    This endpoint returns all currently active call simulations
    for monitoring and debugging purposes.
    """
    try:
        call_flow_service = CallFlowService(db)
        
        # Get active calls (in production, this would query a database)
        active_calls = []
        for call_sid, context in list_calls().items():
            active_calls.append({
                "call_sid": call_sid,
                "current_state": context.current_state,
                "clinic_id": context.clinic_id,
                "patient_name": context.patient_name,
                "created_at": context.created_at.isoformat(),
                "updated_at": context.updated_at.isoformat()
            })
        
        return {
            "active_calls": active_calls,
            "total_count": len(active_calls)
        }
        
    except Exception as e:
        logger.error(f"Failed to get active calls: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get active calls: {str(e)}")


@router.get("/demo-scenarios")
def get_demo_scenarios():
    """
    Get predefined demo scenarios for testing.
    
    This endpoint returns a list of predefined scenarios that can be used
    to test different call flow paths.
    """
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
    
    return {"demo_scenarios": scenarios}
