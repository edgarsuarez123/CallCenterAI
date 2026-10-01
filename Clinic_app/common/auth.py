"""
Admin authentication dependency.

Provides API key-based authentication for all /admin routes.
Key is passed via X-API-Key header and compared against ADMIN_API_KEY env var.
"""

import os
import logging
from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

logger = logging.getLogger(__name__)

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_admin_api_key(api_key: str = Security(api_key_header)) -> str:
    """
    FastAPI dependency that validates the admin API key.

    Raises:
        HTTPException 401: If the X-API-Key header is missing.
        HTTPException 403: If the key is present but incorrect.
    """
    if not api_key:
        raise HTTPException(
            status_code=401,
            detail={
                "code": "MISSING_API_KEY",
                "message": "X-API-Key header is required for admin routes",
            },
        )

    expected_key = os.getenv("ADMIN_API_KEY")
    if not expected_key:
        logger.error("ADMIN_API_KEY environment variable is not set")
        raise HTTPException(
            status_code=500,
            detail={
                "code": "SERVER_MISCONFIGURATION",
                "message": "Admin authentication is not configured",
            },
        )

    if api_key != expected_key:
        logger.warning("Invalid admin API key attempt")
        raise HTTPException(
            status_code=403,
            detail={
                "code": "INVALID_API_KEY",
                "message": "The provided API key is invalid",
            },
        )

    return api_key
