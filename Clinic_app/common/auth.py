"""
Admin API key authentication dependency.

All /admin/* routes must use Depends(verify_admin_api_key).
The key is passed via the X-Admin-Key request header and compared
against the ADMIN_API_KEY environment variable.
"""

import os
import logging

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

logger = logging.getLogger(__name__)

_api_key_header = APIKeyHeader(name="X-Admin-Key", auto_error=False)


async def verify_admin_api_key(api_key: str = Security(_api_key_header)) -> None:
    """
    FastAPI dependency that validates the X-Admin-Key header.

    Raises HTTP 401 if the key is missing or does not match ADMIN_API_KEY.
    """
    expected = os.environ.get("ADMIN_API_KEY", "")
    if not expected:
        logger.error("ADMIN_API_KEY environment variable is not set")
        raise HTTPException(
            status_code=500,
            detail={"code": "CONFIGURATION_ERROR", "message": "Admin API key not configured"},
        )
    if not api_key or api_key != expected:
        logger.warning("Unauthorized admin request — invalid or missing X-Admin-Key")
        raise HTTPException(
            status_code=401,
            detail={"code": "UNAUTHORIZED", "message": "Invalid or missing admin API key"},
        )
