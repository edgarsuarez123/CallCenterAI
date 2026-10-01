"""
Auth routes — Google OAuth 2.0 flow and JWT issuance for clinic staff.

Flow:
  1. GET /auth/google              → redirect to Google consent screen
  2. GET /auth/google/callback     → exchange code, issue JWT (scoped or unscoped)
  3. GET /auth/me                  → list clinic memberships (any valid JWT)
  4. POST /auth/select-clinic      → upgrade unscoped JWT to scoped JWT

All routes are stateless. CSRF protection uses a signed state token (see common/jwt.py).
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from Clinic_app.common.database import get_db
from Clinic_app.common.rate_limit import auth_rate_limit
from Clinic_app.common.jwt import (
    StaffToken,
    create_state_token,
    verify_state_token,
    create_scoped_token,
    create_unscoped_token,
    get_current_staff,
)
from Clinic_app.services.auth_service import (
    build_google_auth_url,
    exchange_code_for_tokens,
    extract_google_user,
    get_staff_clinics,
    get_staff_for_clinic,
    upsert_staff_email,
)

logger = logging.getLogger(__name__)

auth_router = APIRouter(prefix="/auth", tags=["auth"])


# ── Request / Response models ──────────────────────────────────────────────────


class SelectClinicRequest(BaseModel):
    clinic_id: UUID


class TokenResponse(BaseModel):
    token: str
    token_type: str  # "scoped" | "unscoped"
    requires_clinic_selection: bool = False  # True when multiple clinics


class ClinicMembership(BaseModel):
    clinic_id: UUID
    clinic_name: str
    role: str


class MeResponse(BaseModel):
    google_sub: str
    email: str
    clinics: list[ClinicMembership]


# ── Endpoints ──────────────────────────────────────────────────────────────────


@auth_router.get("/google", summary="Initiate Google OAuth login")
async def google_login(
    _rl: None = Depends(auth_rate_limit()),
) -> RedirectResponse:
    """
    Redirect the user to Google's OAuth consent screen.
    A signed state token is embedded in the URL for CSRF protection.
    """
    state = create_state_token()
    url = build_google_auth_url(state)
    return RedirectResponse(url=url, status_code=302)


@auth_router.get("/google/callback", response_model=TokenResponse, summary="Google OAuth callback")
async def google_callback(
    code: str,
    state: str,
    db: AsyncSession = Depends(get_db),
    _rl: None = Depends(auth_rate_limit()),
) -> TokenResponse:
    """
    Handle the Google OAuth callback.

    - Verifies CSRF state token
    - Exchanges authorization code for Google tokens
    - Looks up clinic memberships by google_sub
    - Issues a scoped JWT (1 clinic) or unscoped JWT (>1 clinics, requires selection)
    - Returns 403 NOT_PROVISIONED if the Google account has no clinic memberships
    """
    # 1. Verify CSRF state
    if not verify_state_token(state):
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_STATE", "message": "Invalid or expired OAuth state token"},
        )

    # 2. Exchange code for Google tokens
    token_response = await exchange_code_for_tokens(code)

    # 3. Extract identity from ID token
    google_sub, email = extract_google_user(token_response)
    logger.info(f"Google OAuth callback for sub={google_sub[:8]}...")

    # 4. Keep email current (Google users may change their email)
    await upsert_staff_email(db, google_sub, email)
    await db.commit()

    # 5. Look up clinic memberships
    memberships = await get_staff_clinics(db, google_sub)

    if not memberships:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "NOT_PROVISIONED",
                "message": "This Google account has not been provisioned for any clinic. Contact your administrator.",
            },
        )

    # 6. Single clinic → scoped JWT directly (skip selector screen)
    if len(memberships) == 1:
        m = memberships[0]
        token = create_scoped_token(google_sub, email, m.clinic_id, m.role)
        return TokenResponse(token=token, token_type="scoped")

    # 7. Multiple clinics → unscoped JWT, client must call /auth/select-clinic
    token = create_unscoped_token(google_sub, email)
    return TokenResponse(
        token=token,
        token_type="unscoped",
        requires_clinic_selection=True,
    )


@auth_router.get("/me", response_model=MeResponse, summary="Get current staff clinic memberships")
async def get_me(
    staff: StaffToken = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
    _rl: None = Depends(auth_rate_limit()),
) -> MeResponse:
    """
    Return all clinic memberships for the authenticated staff member.
    Accepts both scoped and unscoped tokens — used by the clinic selector screen.
    """
    memberships = await get_staff_clinics(db, staff.google_sub)

    clinic_list = []
    for m in memberships:
        # Load clinic name — clinic is accessible via FK relationship
        from Clinic_app.data.models.clinic import Clinic

        clinic = await db.get(Clinic, m.clinic_id)
        clinic_name = clinic.name if clinic else "Unknown"
        clinic_list.append(
            ClinicMembership(
                clinic_id=m.clinic_id,
                clinic_name=clinic_name,
                role=m.role,
            )
        )

    return MeResponse(
        google_sub=staff.google_sub,
        email=staff.email,
        clinics=clinic_list,
    )


@auth_router.post(
    "/select-clinic", response_model=TokenResponse, summary="Select a clinic and get scoped JWT"
)
async def select_clinic(
    request: SelectClinicRequest,
    staff: StaffToken = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
    _rl: None = Depends(auth_rate_limit()),
) -> TokenResponse:
    """
    Upgrade an unscoped token to a scoped token for a specific clinic.
    The staff member must have a provisioned membership for the requested clinic.
    Returns a new scoped JWT with clinic_id and role embedded.
    """
    membership = await get_staff_for_clinic(db, staff.google_sub, request.clinic_id)
    if not membership:
        raise HTTPException(
            status_code=403,
            detail={"code": "ACCESS_DENIED", "message": "You do not have access to this clinic"},
        )

    token = create_scoped_token(
        staff.google_sub, staff.email, membership.clinic_id, membership.role
    )
    return TokenResponse(token=token, token_type="scoped")
