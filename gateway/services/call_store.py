"""
Simple in-memory call store for development.
In production, this should be replaced with Redis or database storage.
"""

from typing import Dict, Optional
from models.call_flow_models import CallFlowContext

# Global store for active calls
_active_calls: Dict[str, CallFlowContext] = {}

def store_call(call_sid: str, context: CallFlowContext) -> None:
    """Store a call context."""
    _active_calls[call_sid] = context

def get_call(call_sid: str) -> Optional[CallFlowContext]:
    """Get a call context."""
    return _active_calls.get(call_sid)

def remove_call(call_sid: str) -> bool:
    """Remove a call context."""
    if call_sid in _active_calls:
        del _active_calls[call_sid]
        return True
    return False

def list_calls() -> Dict[str, CallFlowContext]:
    """List all active calls."""
    return _active_calls.copy()

def clear_all_calls() -> None:
    """Clear all active calls."""
    _active_calls.clear()
