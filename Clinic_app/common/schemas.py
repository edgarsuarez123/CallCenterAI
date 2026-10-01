"""
Shared Pydantic schemas used across multiple route modules.
"""

from typing import Optional, Any, Dict
from pydantic import BaseModel


class APIResponse(BaseModel):
    """Standardized API response wrapper used by admin and campaign routes."""

    success: bool
    data: Optional[Any] = None
    error: Optional[Dict[str, Any]] = None
    message: Optional[str] = None
