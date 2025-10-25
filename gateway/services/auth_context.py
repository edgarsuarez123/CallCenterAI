"""Request context management for audit logging."""
from contextvars import ContextVar
from typing import Optional
from pydantic import BaseModel

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
