"""
Auth service — Google OAuth token exchange and ClinicStaff database operations.

Keeps Routes/auth.py thin by centralising all external API calls and DB queries here.
All Google API calls use httpx.AsyncClient with a tenacity retry wrapper.
"""

import os
import logging
from typing import Optional
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from Clinic_app.data.models.clinic_staff import ClinicStaff
from Clinic_app.data.models.clinic import Clinic

logger = logging.getLogger(__name__)

# ── Google OAuth constants ─────────────────────────────────────────────────────

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_SCOPES = "openid email profile"


# ── Google OAuth helpers ───────────────────────────────────────────────────────


def build_google_auth_url(state: str) -> str:
    """
    Build the Google OAuth 2.0 authorization URL.
    The client is redirected here to begin the login flow.
    """
    client_id = os.environ.get("GOOGLE_CLIENT_ID", "")
    redirect_uri = os.environ.get("GOOGLE_REDIRECT_URI", "")
    if not client_id or not redirect_uri:
        raise RuntimeError("GOOGLE_CLIENT_ID and GOOGLE_REDIRECT_URI must be set")

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": GOOGLE_SCOPES,
        "access_type": "online",
        "state": state,
        "prompt": "select_account",
    }
    query_string = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{GOOGLE_AUTH_URL}?{query_string}"


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    retry=retry_if_exception_type(httpx.TransportError),
    reraise=True,
)
async def exchange_code_for_tokens(code: str) -> dict:
    """
    Exchange an authorization code for Google OAuth tokens.
    Returns the full token response dict including id_token.
    Retries up to 3 times on network errors.
    Raises HTTP 400 on invalid code or Google API error.
    """
    client_id = os.environ.get("GOOGLE_CLIENT_ID", "")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    redirect_uri = os.environ.get("GOOGLE_REDIRECT_URI", "")

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )

    if response.status_code != 200:
        logger.warning(f"Google token exchange failed: status={response.status_code}")
        raise HTTPException(
            status_code=400,
            detail={
                "code": "OAUTH_EXCHANGE_FAILED",
                "message": "Failed to exchange authorization code",
            },
        )

    return response.json()


def extract_google_user(token_response: dict) -> tuple[str, str]:
    """
    Extract (sub, email) from a Google token response.
    Decodes the ID token without signature verification — Google already validated it.
    Raises HTTP 400 if the ID token is missing or malformed.
    """
    import jwt as pyjwt

    id_token = token_response.get("id_token")
    if not id_token:
        raise HTTPException(
            status_code=400,
            detail={"code": "MISSING_ID_TOKEN", "message": "Google response missing id_token"},
        )

    try:
        # Decode without verification — trust Google's server-to-server delivery
        payload = pyjwt.decode(id_token, options={"verify_signature": False})
    except pyjwt.PyJWTError as exc:
        logger.warning(f"Failed to decode Google ID token: {exc}")
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_ID_TOKEN", "message": "Could not parse Google ID token"},
        )

    sub = payload.get("sub")
    email = payload.get("email", "")
    if not sub:
        raise HTTPException(
            status_code=400,
            detail={"code": "MISSING_SUB", "message": "Google ID token missing sub claim"},
        )

    return sub, email


# ── ClinicStaff database operations ───────────────────────────────────────────


async def get_staff_clinics(db: AsyncSession, google_sub: str) -> list[ClinicStaff]:
    """
    Return all ClinicStaff rows for this google_sub, with their Clinic eagerly joined.
    Returns an empty list if the sub has no provisioned clinic memberships.
    """
    stmt = (
        select(ClinicStaff)
        .where(ClinicStaff.google_sub == google_sub)
        .order_by(ClinicStaff.created_at)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def upsert_staff_email(db: AsyncSession, google_sub: str, email: str) -> None:
    """
    Update the display email on all ClinicStaff rows for this google_sub.
    Google users can change their email — sub is the stable identity, email is display only.
    """
    stmt = select(ClinicStaff).where(ClinicStaff.google_sub == google_sub)
    result = await db.execute(stmt)
    rows = result.scalars().all()
    for row in rows:
        if row.email != email:
            row.email = email
    # Caller commits


async def create_staff(
    db: AsyncSession,
    clinic_id: UUID,
    google_sub: str,
    email: str,
    role: str,
) -> ClinicStaff:
    """
    Create a new ClinicStaff row linking a Google account to a clinic.
    Raises HTTP 404 if the clinic does not exist.
    Raises HTTP 409 if the staff member is already provisioned for this clinic.
    """
    clinic = await db.get(Clinic, clinic_id)
    if not clinic:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "Clinic not found"},
        )

    if role not in ("admin", "viewer"):
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_ROLE", "message": "role must be 'admin' or 'viewer'"},
        )

    staff = ClinicStaff(
        clinic_id=clinic_id,
        google_sub=google_sub,
        email=email,
        role=role,
    )
    db.add(staff)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail={
                "code": "ALREADY_PROVISIONED",
                "message": "Staff member already provisioned for this clinic",
            },
        )
    return staff


async def get_staff_for_clinic(
    db: AsyncSession,
    google_sub: str,
    clinic_id: UUID,
) -> Optional[ClinicStaff]:
    """
    Return the ClinicStaff row for a specific (google_sub, clinic_id) pair.
    Returns None if not found.
    """
    stmt = select(ClinicStaff).where(
        ClinicStaff.google_sub == google_sub,
        ClinicStaff.clinic_id == clinic_id,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()
