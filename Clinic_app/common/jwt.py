"""
JWT utilities for clinic staff authentication.

Two token types share the same signing key (JWT_SECRET_KEY env var):
  - unscoped: issued after Google OAuth when staff belongs to >1 clinics.
              payload: { sub, email, type="unscoped", exp, iat }
  - scoped:   issued after clinic selection (or directly if 1 clinic).
              payload: { sub, email, clinic_id, role, type="scoped", exp, iat }

A third short-lived token type is used for OAuth CSRF protection:
  - state:    payload: { nonce, type="oauth_state", exp } — 5-minute expiry
"""

import os
import secrets
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
from uuid import UUID

import jwt
from fastapi import HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

logger = logging.getLogger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False)

# ── Constants ──────────────────────────────────────────────────────────────────

JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 8
STATE_EXPIRY_SECONDS = 300  # 5 minutes — OAuth CSRF state token


def _secret() -> str:
    key = os.environ.get("JWT_SECRET_KEY", "")
    if not key:
        raise RuntimeError("JWT_SECRET_KEY environment variable is not set")
    return key


# ── Payload model ──────────────────────────────────────────────────────────────

class StaffToken(BaseModel):
    """Decoded JWT payload for an authenticated clinic staff member."""
    google_sub: str
    email: str
    clinic_id: Optional[UUID] = None   # None in unscoped tokens
    role: Optional[str] = None          # None in unscoped tokens; "admin" | "viewer" in scoped
    token_type: str                     # "unscoped" | "scoped"


# ── Token creation ─────────────────────────────────────────────────────────────

def create_state_token() -> str:
    """
    Create a short-lived HMAC-signed state token for OAuth CSRF protection.
    The nonce is a cryptographically random 32-byte hex string.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "nonce": secrets.token_hex(32),
        "type": "oauth_state",
        "iat": now,
        "exp": now + timedelta(seconds=STATE_EXPIRY_SECONDS),
    }
    return jwt.encode(payload, _secret(), algorithm=JWT_ALGORITHM)


def verify_state_token(state: str) -> bool:
    """
    Verify an OAuth state token.
    Returns True if valid and unexpired, False otherwise.
    Does NOT raise — callers check the return value.
    """
    try:
        payload = jwt.decode(state, _secret(), algorithms=[JWT_ALGORITHM])
        return payload.get("type") == "oauth_state"
    except jwt.PyJWTError:
        return False


def create_unscoped_token(sub: str, email: str) -> str:
    """
    Issue an unscoped JWT after Google OAuth for staff with multiple clinics.
    The client must call /auth/select-clinic to upgrade to a scoped token.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": sub,
        "email": email,
        "type": "unscoped",
        "iat": now,
        "exp": now + timedelta(hours=JWT_EXPIRY_HOURS),
    }
    return jwt.encode(payload, _secret(), algorithm=JWT_ALGORITHM)


def create_scoped_token(sub: str, email: str, clinic_id: UUID, role: str) -> str:
    """
    Issue a scoped JWT bound to a specific clinic.
    Required by all campaign and dashboard routes.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": sub,
        "email": email,
        "clinic_id": str(clinic_id),
        "role": role,
        "type": "scoped",
        "iat": now,
        "exp": now + timedelta(hours=JWT_EXPIRY_HOURS),
    }
    return jwt.encode(payload, _secret(), algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> StaffToken:
    """
    Decode and validate a staff JWT.
    Raises HTTP 401 if the token is missing, invalid, or expired.
    """
    try:
        payload = jwt.decode(token, _secret(), algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail={"code": "TOKEN_EXPIRED", "message": "Token has expired"})
    except jwt.PyJWTError as exc:
        logger.warning(f"JWT decode failed: {exc}")
        raise HTTPException(status_code=401, detail={"code": "INVALID_TOKEN", "message": "Invalid token"})

    token_type = payload.get("type")
    if token_type not in ("unscoped", "scoped"):
        raise HTTPException(status_code=401, detail={"code": "INVALID_TOKEN", "message": "Invalid token type"})

    clinic_id_raw = payload.get("clinic_id")
    return StaffToken(
        google_sub=payload["sub"],
        email=payload.get("email", ""),
        clinic_id=UUID(clinic_id_raw) if clinic_id_raw else None,
        role=payload.get("role"),
        token_type=token_type,
    )


# ── FastAPI dependencies ───────────────────────────────────────────────────────

async def get_current_staff(
    credentials: HTTPAuthorizationCredentials = Security(_bearer_scheme),
) -> StaffToken:
    """
    FastAPI dependency: extract and validate Bearer token from Authorization header.
    Returns StaffToken (may be unscoped — clinic_id could be None).
    Raises HTTP 401 if token is missing or invalid.
    """
    if not credentials:
        raise HTTPException(
            status_code=401,
            detail={"code": "MISSING_TOKEN", "message": "Authorization header required"},
        )
    return decode_token(credentials.credentials)


async def require_scoped_staff(
    staff: StaffToken = Security(get_current_staff),
) -> StaffToken:
    """
    FastAPI dependency: same as get_current_staff but additionally requires a scoped token.
    Raises HTTP 403 if the token is unscoped (no clinic_id).
    Use this on all campaign and dashboard routes.
    """
    if not staff.clinic_id:
        raise HTTPException(
            status_code=403,
            detail={"code": "CLINIC_NOT_SELECTED", "message": "Please select a clinic first via /auth/select-clinic"},
        )
    return staff
