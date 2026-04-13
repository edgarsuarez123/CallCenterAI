"""
Admin routes for clinic management.

Handles clinic, integration, staff, booking, and EHR CRUD operations.
Routes handle database operations directly (no service layer).
"""

import json
import re
import logging
from typing import Optional, Dict, Any, List
from uuid import UUID
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from pydantic import BaseModel, field_validator

from Clinic_app.common.database import get_db
from Clinic_app.data.models.clinic import Clinic
from Clinic_app.data.models.clinic_integration import ClinicIntegration
from Clinic_app.data.models.clinic_staff import ClinicStaff
from Clinic_app.data.models.booking import Booking
from Clinic_app.data.models.clinic_ehr_config import ClinicEHRConfig
from Clinic_app.data.enums import BookingStatus, GapType
from Clinic_app.common.encryption import encrypt_phi
from Clinic_app.services.booking import list_bookings, cancel_booking, get_booking_by_id
from Clinic_app.services.playbook_cache import invalidate_clinic_ehr_cache
from Clinic_app.services.playwright_ehr import playwright_ehr_service
from Clinic_app.services.auth_service import create_staff

logger = logging.getLogger(__name__)

# Router setup
admin_router = APIRouter(prefix="/admin", tags=["admin"])

# Validation constants
VALID_CLINIC_TIERS = ["basic", "pro", "enterprise"]
VALID_CLINIC_STATUSES = ["active", "suspended"]
DEFAULT_APPOINTMENT_LENGTH = 15
DEFAULT_CAPACITY = 1
E164_PATTERN = re.compile(r'^\+[1-9]\d{1,14}$')

# Validation helper functions
def validate_service_account_json(json_str: str) -> bool:
    """
    Validate Google service account JSON structure.
    
    Args:
        json_str: JSON string to validate
        
    Returns:
        True if valid, False otherwise
    """
    try:
        data = json.loads(json_str)
        required_fields = ["type", "project_id", "private_key_id", "private_key", "client_email"]
        return all(key in data for key in required_fields)
    except (json.JSONDecodeError, TypeError):
        return False


def validate_e164_phone(phone: str) -> bool:
    """
    Validate E.164 phone format.
    
    Args:
        phone: Phone number to validate
        
    Returns:
        True if valid E.164 format, False otherwise
    """
    return bool(E164_PATTERN.match(phone))


# Error helper functions
def raise_not_found(resource: str, id: UUID):
    """Raise 404 with standardized format."""
    raise HTTPException(
        status_code=404,
        detail={
            "code": "NOT_FOUND",
            "message": f"{resource} not found",
            "resource": resource,
            "id": str(id)
        }
    )


def raise_validation_error(message: str, field: str = None):
    """Raise 400 with validation error format."""
    detail = {
        "code": "VALIDATION_ERROR",
        "message": message
    }
    if field:
        detail["field"] = field
    raise HTTPException(status_code=400, detail=detail)


def raise_conflict_error(message: str, code: str = "CONFLICT"):
    """Raise 409 for unique constraint violations."""
    raise HTTPException(
        status_code=409,
        detail={
            "code": code,
            "message": message
        }
    )


# Pydantic Models

class APIResponse(BaseModel):
    """Standardized API response wrapper."""
    success: bool
    data: Optional[Any] = None
    error: Optional[Dict[str, Any]] = None
    message: Optional[str] = None


class ClinicBase(BaseModel):
    """Base clinic model."""
    name: str
    tier: str
    status: str = "active"
    license_token: str
    license_expires_at: Optional[datetime] = None
    network_id: Optional[UUID] = None
    max_concurrency: int = 3
    features: Dict[str, Any] = {}

    @field_validator('tier')
    @classmethod
    def validate_tier(cls, v):
        if v not in VALID_CLINIC_TIERS:
            raise ValueError(f"tier must be one of {VALID_CLINIC_TIERS}")
        return v

    @field_validator('status')
    @classmethod
    def validate_status(cls, v):
        if v not in VALID_CLINIC_STATUSES:
            raise ValueError(f"status must be one of {VALID_CLINIC_STATUSES}")
        return v

    @field_validator('max_concurrency')
    @classmethod
    def validate_max_concurrency(cls, v):
        if v < 1:
            raise ValueError("max_concurrency must be a positive integer")
        return v


class ClinicCreateRequest(ClinicBase):
    """Request model for creating a clinic."""
    pass


class ClinicUpdateRequest(BaseModel):
    """Request model for updating a clinic."""
    name: Optional[str] = None
    tier: Optional[str] = None
    status: Optional[str] = None
    license_token: Optional[str] = None
    license_expires_at: Optional[datetime] = None
    network_id: Optional[UUID] = None
    max_concurrency: Optional[int] = None
    features: Optional[Dict[str, Any]] = None

    @field_validator('tier')
    @classmethod
    def validate_tier(cls, v):
        if v is not None and v not in VALID_CLINIC_TIERS:
            raise ValueError(f"tier must be one of {VALID_CLINIC_TIERS}")
        return v

    @field_validator('status')
    @classmethod
    def validate_status(cls, v):
        if v is not None and v not in VALID_CLINIC_STATUSES:
            raise ValueError(f"status must be one of {VALID_CLINIC_STATUSES}")
        return v

    @field_validator('max_concurrency')
    @classmethod
    def validate_max_concurrency(cls, v):
        if v is not None and v < 1:
            raise ValueError("max_concurrency must be a positive integer")
        return v


class IntegrationBase(BaseModel):
    """Base integration model."""
    retell_agent_id: str
    retell_did: str
    google_service_account_json: str
    default_appointment_length_minutes: int = DEFAULT_APPOINTMENT_LENGTH
    default_capacity: int = DEFAULT_CAPACITY

    @field_validator('retell_did')
    @classmethod
    def validate_retell_did(cls, v):
        if not validate_e164_phone(v):
            raise ValueError("retell_did must be in E.164 format (e.g., +1234567890)")
        return v

    @field_validator('google_service_account_json')
    @classmethod
    def validate_service_account_json(cls, v):
        if not validate_service_account_json(v):
            raise ValueError("google_service_account_json must be valid JSON with required fields: type, project_id, private_key_id, private_key, client_email")
        return v


class IntegrationCreateRequest(IntegrationBase):
    """Request model for creating/updating integration."""
    pass


class EhrConfigUpsertRequest(BaseModel):
    """NextGen URL and credentials. Password and username are encrypted at rest."""

    nextgen_url: str
    nextgen_username: str
    nextgen_password: str


class ApptTypesPutRequest(BaseModel):
    """Maps GapType string values to clinic-specific NextGen appointment type codes."""

    mapping: Dict[str, str]

    @field_validator("mapping")
    @classmethod
    def validate_gap_keys(cls, v: Dict[str, str]) -> Dict[str, str]:
        allowed = {g.value for g in GapType}
        for k in v:
            if k not in allowed:
                raise ValueError(f"Invalid gap_type key: {k}")
        return v


class ClinicSetupRequest(BaseModel):
    """Request model for clinic setup (creates clinic + integration atomically)."""
    clinic: ClinicCreateRequest
    integration: IntegrationCreateRequest


class ClinicResponse(BaseModel):
    """Response model for clinic data."""
    id: UUID
    name: str
    tier: str
    status: str
    license_token: str
    license_expires_at: Optional[datetime]
    network_id: Optional[UUID]
    max_concurrency: int
    features: Dict[str, Any]
    created_at: datetime

    class Config:
        from_attributes = True


# Route Handlers

@admin_router.post("/clinics/setup", response_model=APIResponse)
async def setup_clinic(
    request: ClinicSetupRequest,
    db: AsyncSession = Depends(get_db)
) -> APIResponse:
    """
    Create a new clinic with integration in a single transaction.
    
    This is a convenience endpoint for initial clinic onboarding. Both
    records (Clinic, ClinicIntegration) are created atomically.
    """
    try:
        logger.info(f"Creating clinic setup: name={request.clinic.name}, tier={request.clinic.tier}")
        
        # Check if license_token already exists
        stmt = select(Clinic).where(Clinic.license_token == request.clinic.license_token)
        result = await db.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing:
            logger.warning(f"Duplicate license_token attempted: {request.clinic.license_token}")
            raise_conflict_error(f"License token '{request.clinic.license_token}' already exists", "DUPLICATE_LICENSE_TOKEN")
        
        # Create Clinic (includes subscription fields: tier, max_concurrency, features)
        clinic = Clinic(
            name=request.clinic.name,
            tier=request.clinic.tier,
            status=request.clinic.status,
            license_token=request.clinic.license_token,
            license_expires_at=request.clinic.license_expires_at,
            network_id=request.clinic.network_id,
            max_concurrency=request.clinic.max_concurrency,
            features=request.clinic.features,
        )
        db.add(clinic)
        await db.flush()  # Get clinic.id
        
        # Create ClinicIntegration
        integration = ClinicIntegration(
            clinic_id=clinic.id,
            retell_agent_id=request.integration.retell_agent_id,
            retell_did=request.integration.retell_did,
            google_service_account_json=request.integration.google_service_account_json,
            default_appointment_length_minutes=request.integration.default_appointment_length_minutes,
            default_capacity=request.integration.default_capacity
        )
        db.add(integration)
        
        await db.commit()
        logger.info(f"Clinic created successfully: clinic_id={clinic.id}, name={clinic.name}")
        
        return APIResponse(
            success=True,
            data=ClinicResponse.model_validate(clinic),
            message="Clinic setup completed successfully"
        )
        
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError as e:
        await db.rollback()
        logger.error(f"Database integrity error creating clinic: {str(e)}", exc_info=True)
        if "license_token" in str(e.orig):
            raise_conflict_error("License token already exists", "DUPLICATE_LICENSE_TOKEN")
        raise_conflict_error("Database constraint violation", "CONSTRAINT_VIOLATION")
    except Exception as e:
        await db.rollback()
        logger.error(f"Unexpected error in setup_clinic: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "code": "INTERNAL_ERROR",
                "message": "Failed to create clinic setup"
            }
        )


@admin_router.post("/clinics", response_model=APIResponse)
async def create_clinic(
    request: ClinicCreateRequest,
    db: AsyncSession = Depends(get_db)
) -> APIResponse:
    """Create a clinic only (without integration)."""
    try:
        logger.info(f"Creating clinic: name={request.name}, tier={request.tier}")
        
        # Check if license_token already exists
        stmt = select(Clinic).where(Clinic.license_token == request.license_token)
        result = await db.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing:
            logger.warning(f"Duplicate license_token attempted: {request.license_token}")
            raise_conflict_error(f"License token '{request.license_token}' already exists", "DUPLICATE_LICENSE_TOKEN")
        
        clinic = Clinic(
            name=request.name,
            tier=request.tier,
            status=request.status,
            license_token=request.license_token,
            license_expires_at=request.license_expires_at,
            network_id=request.network_id,
            max_concurrency=request.max_concurrency,
            features=request.features,
        )
        db.add(clinic)
        await db.commit()
        
        logger.info(f"Clinic created: clinic_id={clinic.id}, name={clinic.name}")
        
        return APIResponse(
            success=True,
            data=ClinicResponse.model_validate(clinic),
            message="Clinic created successfully"
        )
        
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError as e:
        await db.rollback()
        logger.error(f"Database integrity error creating clinic: {str(e)}", exc_info=True)
        if "license_token" in str(e.orig):
            raise_conflict_error("License token already exists", "DUPLICATE_LICENSE_TOKEN")
        raise_conflict_error("Database constraint violation", "CONSTRAINT_VIOLATION")
    except Exception as e:
        await db.rollback()
        logger.error(f"Unexpected error creating clinic: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "code": "INTERNAL_ERROR",
                "message": "Failed to create clinic"
            }
        )


@admin_router.get("/clinics/{clinic_id}", response_model=APIResponse)
async def get_clinic(
    clinic_id: UUID,
    db: AsyncSession = Depends(get_db)
) -> APIResponse:
    """Get clinic by ID."""
    clinic = await db.get(Clinic, clinic_id)
    if not clinic:
        raise_not_found("Clinic", clinic_id)
    
    return APIResponse(
        success=True,
        data=ClinicResponse.model_validate(clinic)
    )


@admin_router.put("/clinics/{clinic_id}", response_model=APIResponse)
async def update_clinic(
    clinic_id: UUID,
    request: ClinicUpdateRequest,
    db: AsyncSession = Depends(get_db)
) -> APIResponse:
    """Update clinic."""
    clinic = await db.get(Clinic, clinic_id)
    if not clinic:
        raise_not_found("Clinic", clinic_id)
    
    try:
        logger.info(f"Updating clinic: clinic_id={clinic_id}")
        
        # Update fields if provided
        update_data = request.model_dump(exclude_unset=True)
        
        # Check license_token uniqueness if being updated
        if "license_token" in update_data:
            stmt = select(Clinic).where(
                Clinic.license_token == update_data["license_token"],
                Clinic.id != clinic_id
            )
            result = await db.execute(stmt)
            existing = result.scalar_one_or_none()
            if existing:
                logger.warning(f"Duplicate license_token attempted: {update_data['license_token']}")
                raise_conflict_error(f"License token '{update_data['license_token']}' already exists", "DUPLICATE_LICENSE_TOKEN")
        
        for field, value in update_data.items():
            setattr(clinic, field, value)
        
        await db.commit()
        logger.info(f"Clinic updated: clinic_id={clinic_id}")
        
        return APIResponse(
            success=True,
            data=ClinicResponse.model_validate(clinic),
            message="Clinic updated successfully"
        )
        
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError as e:
        await db.rollback()
        logger.error(f"Database integrity error updating clinic: {str(e)}", exc_info=True)
        raise_conflict_error("Database constraint violation", "CONSTRAINT_VIOLATION")
    except Exception as e:
        await db.rollback()
        logger.error(f"Unexpected error updating clinic: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "code": "INTERNAL_ERROR",
                "message": "Failed to update clinic"
            }
        )


@admin_router.get("/clinics", response_model=APIResponse)
async def list_clinics(
    db: AsyncSession = Depends(get_db)
) -> APIResponse:
    """List all clinics."""
    stmt = select(Clinic)
    result = await db.execute(stmt)
    clinics = result.scalars().all()
    
    return APIResponse(
        success=True,
        data=[ClinicResponse.model_validate(clinic) for clinic in clinics]
    )


@admin_router.post("/clinics/{clinic_id}/integration", response_model=APIResponse)
async def create_integration(
    clinic_id: UUID,
    request: IntegrationCreateRequest,
    db: AsyncSession = Depends(get_db)
) -> APIResponse:
    """Create or update clinic integration."""
    # Check clinic exists
    clinic = await db.get(Clinic, clinic_id)
    if not clinic:
        raise_not_found("Clinic", clinic_id)
    
    try:
        logger.info(f"Creating/updating integration: clinic_id={clinic_id}")
        
        # Check if integration already exists
        stmt = select(ClinicIntegration).where(ClinicIntegration.clinic_id == clinic_id)
        result = await db.execute(stmt)
        existing = result.scalar_one_or_none()
        
        if existing:
            # Update existing
            existing.retell_agent_id = request.retell_agent_id
            existing.retell_did = request.retell_did
            existing.google_service_account_json = request.google_service_account_json
            existing.default_appointment_length_minutes = request.default_appointment_length_minutes
            existing.default_capacity = request.default_capacity
            existing.updated_at = datetime.utcnow()
            integration = existing
        else:
            # Create new
            integration = ClinicIntegration(
                clinic_id=clinic_id,
                retell_agent_id=request.retell_agent_id,
                retell_did=request.retell_did,
                google_service_account_json=request.google_service_account_json,
                default_appointment_length_minutes=request.default_appointment_length_minutes,
                default_capacity=request.default_capacity
            )
            db.add(integration)
        
        await db.commit()
        logger.info(f"Integration updated: clinic_id={clinic_id}")
        
        return APIResponse(
            success=True,
            data={
                "id": str(integration.id),
                "clinic_id": str(integration.clinic_id),
                "retell_agent_id": integration.retell_agent_id,
                "retell_did": integration.retell_did,
                "default_appointment_length_minutes": integration.default_appointment_length_minutes,
                "default_capacity": integration.default_capacity
            },
            message="Integration created/updated successfully"
        )
        
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError as e:
        await db.rollback()
        logger.error(f"Database integrity error creating integration: {str(e)}", exc_info=True)
        raise_conflict_error("Database constraint violation", "CONSTRAINT_VIOLATION")
    except Exception as e:
        await db.rollback()
        logger.error(f"Unexpected error creating integration: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "code": "INTERNAL_ERROR",
                "message": "Failed to create/update integration"
            }
        )


@admin_router.get("/clinics/{clinic_id}/integration", response_model=APIResponse)
async def get_integration(
    clinic_id: UUID,
    db: AsyncSession = Depends(get_db)
) -> APIResponse:
    """Get clinic integration."""
    stmt = select(ClinicIntegration).where(ClinicIntegration.clinic_id == clinic_id)
    result = await db.execute(stmt)
    integration = result.scalar_one_or_none()
    
    if not integration:
        raise_not_found("Integration", clinic_id)
    
    return APIResponse(
        success=True,
        data={
            "id": str(integration.id),
            "clinic_id": str(integration.clinic_id),
            "retell_agent_id": integration.retell_agent_id,
            "retell_did": integration.retell_did,
            "default_appointment_length_minutes": integration.default_appointment_length_minutes,
            "default_capacity": integration.default_capacity,
            "created_at": integration.created_at.isoformat(),
            "updated_at": integration.updated_at.isoformat()
        }
    )


@admin_router.put("/clinics/{clinic_id}/integration", response_model=APIResponse)
async def update_integration(
    clinic_id: UUID,
    request: IntegrationCreateRequest,
    db: AsyncSession = Depends(get_db)
) -> APIResponse:
    """Update clinic integration."""
    stmt = select(ClinicIntegration).where(ClinicIntegration.clinic_id == clinic_id)
    result = await db.execute(stmt)
    integration = result.scalar_one_or_none()
    
    if not integration:
        raise_not_found("Integration", clinic_id)
    
    try:
        logger.info(f"Updating integration: clinic_id={clinic_id}")
        
        integration.retell_agent_id = request.retell_agent_id
        integration.retell_did = request.retell_did
        integration.google_service_account_json = request.google_service_account_json
        integration.default_appointment_length_minutes = request.default_appointment_length_minutes
        integration.default_capacity = request.default_capacity
        integration.updated_at = datetime.utcnow()
        
        await db.commit()
        logger.info(f"Integration updated: clinic_id={clinic_id}")
        
        return APIResponse(
            success=True,
            data={
                "id": str(integration.id),
                "clinic_id": str(integration.clinic_id),
                "retell_agent_id": integration.retell_agent_id,
                "retell_did": integration.retell_did,
                "default_appointment_length_minutes": integration.default_appointment_length_minutes,
                "default_capacity": integration.default_capacity
            },
            message="Integration updated successfully"
        )
        
    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Unexpected error updating integration: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "code": "INTERNAL_ERROR",
                "message": "Failed to update integration"
            }
        )


# ============================================================================
# STAFF MANAGEMENT ENDPOINTS
# ============================================================================

class StaffCreateRequest(BaseModel):
    """Request model for provisioning a staff member to a clinic."""
    google_sub: str
    email: str
    role: str = "viewer"  # "admin" | "viewer"


class StaffResponse(BaseModel):
    """Response model for a clinic staff record."""
    id: UUID
    clinic_id: UUID
    google_sub: str
    email: str
    role: str
    created_at: datetime

    class Config:
        from_attributes = True


@admin_router.post("/clinics/{clinic_id}/staff", response_model=APIResponse, status_code=201)
async def provision_staff(
    clinic_id: UUID,
    request: StaffCreateRequest,
    db: AsyncSession = Depends(get_db),
) -> APIResponse:
    """
    Provision a Google account as a staff member for a clinic.

    This is the admin-only endpoint Edgar uses to grant clinic dashboard access
    to staff before they can log in via Google OAuth.

    Raises 404 if the clinic does not exist.
    Raises 409 if the google_sub is already provisioned for this clinic.
    """
    try:
        staff = await create_staff(
            db=db,
            clinic_id=clinic_id,
            google_sub=request.google_sub,
            email=request.email,
            role=request.role,
        )
        await db.commit()
        logger.info(f"Staff provisioned: clinic_id={clinic_id}, sub={request.google_sub[:8]}..., role={request.role}")
        return APIResponse(
            success=True,
            data=StaffResponse.model_validate(staff),
            message="Staff member provisioned successfully",
        )
    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error provisioning staff: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"code": "INTERNAL_ERROR", "message": "Failed to provision staff member"},
        )


@admin_router.get("/clinics/{clinic_id}/staff", response_model=APIResponse)
async def list_clinic_staff(
    clinic_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> APIResponse:
    """List all provisioned staff members for a clinic."""
    clinic = await db.get(Clinic, clinic_id)
    if not clinic:
        raise_not_found("Clinic", clinic_id)

    stmt = select(ClinicStaff).where(ClinicStaff.clinic_id == clinic_id).order_by(ClinicStaff.created_at)
    result = await db.execute(stmt)
    staff_list = result.scalars().all()

    return APIResponse(
        success=True,
        data=[StaffResponse.model_validate(s) for s in staff_list],
    )


@admin_router.delete("/clinics/{clinic_id}/staff/{staff_id}", response_model=APIResponse)
async def remove_staff(
    clinic_id: UUID,
    staff_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> APIResponse:
    """Remove a staff member's access to a clinic."""
    staff = await db.get(ClinicStaff, staff_id)
    if not staff or staff.clinic_id != clinic_id:
        raise_not_found("Staff member", staff_id)

    await db.delete(staff)
    await db.commit()
    logger.info(f"Staff removed: staff_id={staff_id}, clinic_id={clinic_id}")
    return APIResponse(success=True, message="Staff member removed successfully")


# ============================================================================
# BUSINESS HOURS ENDPOINTS
# ============================================================================

# Time format validation pattern (HH:MM)
TIME_FORMAT_PATTERN = re.compile(r'^([01]\d|2[0-3]):([0-5]\d)$')


def validate_time_format(time_str: str) -> bool:
    """Validate HH:MM time format (00:00 - 23:59)."""
    return bool(TIME_FORMAT_PATTERN.match(time_str))


class BusinessHoursRequest(BaseModel):
    """Request model for updating business hours."""
    start: str
    end: str
    
    @field_validator('start', 'end')
    @classmethod
    def validate_time(cls, v: str) -> str:
        if not validate_time_format(v):
            raise ValueError("Time must be in HH:MM format (00:00 - 23:59)")
        return v


class BusinessHoursResponse(BaseModel):
    """Response model for business hours."""
    start: str
    end: str


@admin_router.get("/clinics/{clinic_id}/business-hours", response_model=APIResponse)
async def get_business_hours(
    clinic_id: UUID,
    db: AsyncSession = Depends(get_db)
) -> APIResponse:
    """Get business hours for a clinic."""
    clinic = await db.get(Clinic, clinic_id)
    if not clinic:
        raise_not_found("Clinic", clinic_id)
    
    logger.info(f"Retrieved business hours for clinic {clinic_id}")
    
    return APIResponse(
        success=True,
        data={
            "clinic_id": str(clinic_id),
            "start": clinic.business_hours_start,
            "end": clinic.business_hours_end
        },
        message="Business hours retrieved successfully"
    )


@admin_router.put("/clinics/{clinic_id}/business-hours", response_model=APIResponse)
async def update_business_hours(
    clinic_id: UUID,
    request: BusinessHoursRequest,
    db: AsyncSession = Depends(get_db)
) -> APIResponse:
    """Update business hours for a clinic."""
    clinic = await db.get(Clinic, clinic_id)
    if not clinic:
        raise_not_found("Clinic", clinic_id)
    
    # Validate start is before end
    start_parts = request.start.split(':')
    end_parts = request.end.split(':')
    start_minutes = int(start_parts[0]) * 60 + int(start_parts[1])
    end_minutes = int(end_parts[0]) * 60 + int(end_parts[1])
    
    if start_minutes >= end_minutes:
        raise_validation_error("Business hours start must be before end", "start")
    
    try:
        clinic.business_hours_start = request.start
        clinic.business_hours_end = request.end
        await db.commit()
        
        logger.info(f"Updated business hours for clinic {clinic_id}: {request.start} - {request.end}")
        
        return APIResponse(
            success=True,
            data={
                "clinic_id": str(clinic_id),
                "start": clinic.business_hours_start,
                "end": clinic.business_hours_end
            },
            message="Business hours updated successfully"
        )
        
    except Exception as e:
        await db.rollback()
        logger.error(f"Error updating business hours: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "code": "INTERNAL_ERROR",
                "message": "Failed to update business hours"
            }
        )


# Booking Models

class BookingResponse(BaseModel):
    """Response model for booking data."""
    id: UUID
    clinic_id: UUID
    provider_id: UUID
    patient_id: UUID
    slot_start: datetime
    slot_end: datetime
    status: str
    source: Optional[str]
    google_event_id: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class CancelBookingsRequest(BaseModel):
    """Request model for bulk booking cancellation."""
    booking_ids: List[UUID]
    
    @field_validator('booking_ids')
    @classmethod
    def validate_booking_ids(cls, v):
        if not v:
            raise ValueError("booking_ids cannot be empty")
        if len(v) > 100:
            raise ValueError("Cannot cancel more than 100 bookings at once")
        return v


# Booking Endpoints

@admin_router.get("/clinics/{clinic_id}/bookings", response_model=APIResponse)
async def list_clinic_bookings(
    clinic_id: UUID,
    provider_id: Optional[UUID] = None,
    patient_id: Optional[UUID] = None,
    status: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    limit: int = 100,
    offset: int = 0,
    db: AsyncSession = Depends(get_db)
) -> APIResponse:
    """
    List bookings for a clinic with optional filters.
    
    Query parameters:
    - provider_id: Filter by provider
    - patient_id: Filter by patient
    - status: Filter by status (tentative/confirmed/canceled)
    - start_date: Bookings on or after this date
    - end_date: Bookings on or before this date
    - limit: Maximum results (default 100, max 1000)
    - offset: Pagination offset (default 0)
    """
    # Check clinic exists
    clinic = await db.get(Clinic, clinic_id)
    if not clinic:
        raise_not_found("Clinic", clinic_id)
    
    # Validate limit
    if limit > 1000:
        limit = 1000
    if limit < 1:
        limit = 100
    
    # Parse status filter
    status_filter = None
    if status:
        try:
            booking_status = BookingStatus(status)
            status_filter = [booking_status]
        except ValueError:
            raise_validation_error(
                f"Invalid status: {status}. Must be one of: tentative, confirmed, canceled",
                "status"
            )
    
    try:
        bookings, total = await list_bookings(
            db=db,
            clinic_id=clinic_id,
            provider_id=provider_id,
            patient_id=patient_id,
            status_filter=status_filter,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            offset=offset
        )
        
        return APIResponse(
            success=True,
            data={
                "bookings": [BookingResponse.model_validate(b) for b in bookings],
                "total": total,
                "limit": limit,
                "offset": offset
            }
        )
        
    except Exception as e:
        logger.error(f"Error listing bookings: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "code": "INTERNAL_ERROR",
                "message": "Failed to list bookings"
            }
        )


@admin_router.delete("/clinics/{clinic_id}/bookings/{booking_id}", response_model=APIResponse)
async def cancel_clinic_booking(
    clinic_id: UUID,
    booking_id: UUID,
    db: AsyncSession = Depends(get_db)
) -> APIResponse:
    """
    Cancel a single booking.
    
    This will:
    - Delete the Google Calendar event (if exists)
    - Set booking status to CANCELED
    - Create audit entry
    - Free up the time slot for new appointments
    """
    # Check clinic exists
    clinic = await db.get(Clinic, clinic_id)
    if not clinic:
        raise_not_found("Clinic", clinic_id)
    
    # Check booking exists and belongs to clinic
    booking = await get_booking_by_id(db, booking_id, clinic_id)
    if not booking:
        raise_not_found("Booking", booking_id)
    
    try:
        canceled_booking = await cancel_booking(
            db=db,
            booking_id=booking_id,
            clinic_id=clinic_id,
            actor="admin"
        )
        
        await db.commit()
        logger.info(f"Booking canceled: booking_id={booking_id}, clinic_id={clinic_id}")
        return APIResponse(
            success=True,
            message=f"Booking {booking_id} canceled successfully"
        )
            
    except ValueError as e:
        await db.rollback()
        raise HTTPException(
            status_code=400,
            detail={
                "code": "VALIDATION_ERROR",
                "message": str(e)
            }
        )
    except Exception as e:
        await db.rollback()
        logger.error(f"Error canceling booking: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "code": "INTERNAL_ERROR",
                "message": "Failed to cancel booking"
            }
        )


@admin_router.delete("/clinics/{clinic_id}/bookings", response_model=APIResponse)
async def cancel_clinic_bookings(
    clinic_id: UUID,
    request: CancelBookingsRequest,
    db: AsyncSession = Depends(get_db)
) -> APIResponse:
    """
    Cancel multiple bookings.
    
    This will:
    - Delete Google Calendar events (if exist)
    - Set booking status to CANCELED
    - Create audit entries
    - Free up time slots for new appointments
    
    Returns count of successfully canceled bookings.
    """
    # Check clinic exists
    clinic = await db.get(Clinic, clinic_id)
    if not clinic:
        raise_not_found("Clinic", clinic_id)
    
    canceled_count = 0
    failed_count = 0
    errors = []
    
    try:
        for booking_id in request.booking_ids:
            try:
                # Check booking exists and belongs to clinic
                booking = await get_booking_by_id(db, booking_id, clinic_id)
                if not booking:
                    errors.append(f"Booking {booking_id} not found")
                    failed_count += 1
                    continue
                
                await cancel_booking(
                    db=db,
                    booking_id=booking_id,
                    clinic_id=clinic_id,
                    actor="admin"
                )
                
                canceled_count += 1
                    
            except ValueError as e:
                # Handle validation errors (e.g., already canceled)
                failed_count += 1
                errors.append(f"Booking {booking_id}: {str(e)}")
            except Exception as e:
                failed_count += 1
                errors.append(f"Booking {booking_id}: {str(e)}")
                logger.error(f"Error canceling booking {booking_id}: {str(e)}")
        
        await db.commit()
        
        logger.info(
            f"Bulk booking cancellation completed: "
            f"clinic_id={clinic_id}, canceled={canceled_count}, failed={failed_count}"
        )
        
        return APIResponse(
            success=True,
            data={
                "canceled_count": canceled_count,
                "failed_count": failed_count,
                "total_requested": len(request.booking_ids),
                "errors": errors[:10]  # Limit errors in response
            },
            message=f"Canceled {canceled_count} booking(s), {failed_count} failed"
        )
        
    except Exception as e:
        await db.rollback()
        logger.error(f"Error in bulk booking cancellation: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "code": "INTERNAL_ERROR",
                "message": "Failed to cancel bookings"
            }
        )


# ── NextGen EHR (Playwright + AgentQL) — super-admin API key only ─────────────


@admin_router.post("/clinics/{clinic_id}/ehr-config", response_model=APIResponse)
async def upsert_ehr_config(
    clinic_id: UUID,
    request: EhrConfigUpsertRequest,
    db: AsyncSession = Depends(get_db),
) -> APIResponse:
    """Create or update encrypted NextGen credentials for a clinic."""
    clinic = await db.get(Clinic, clinic_id)
    if not clinic:
        raise_not_found("Clinic", clinic_id)

    stmt = select(ClinicEHRConfig).where(ClinicEHRConfig.clinic_id == clinic_id)
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()

    enc_user = encrypt_phi(request.nextgen_username)
    enc_pass = encrypt_phi(request.nextgen_password)

    if existing:
        existing.nextgen_url = request.nextgen_url
        existing.nextgen_username_encrypted = enc_user
        existing.nextgen_password_encrypted = enc_pass
        existing.updated_at = datetime.now(timezone.utc)
        row = existing
    else:
        row = ClinicEHRConfig(
            clinic_id=clinic_id,
            nextgen_url=request.nextgen_url,
            nextgen_username_encrypted=enc_user,
            nextgen_password_encrypted=enc_pass,
            appt_type_mapping={},
        )
        db.add(row)

    await invalidate_clinic_ehr_cache(clinic_id)
    await db.commit()
    await db.refresh(row)

    return APIResponse(
        success=True,
        data={
            "clinic_id": str(clinic_id),
            "nextgen_url": row.nextgen_url,
            "appt_type_mapping": row.appt_type_mapping or {},
            "connection_verified_at": (
                row.connection_verified_at.isoformat() if row.connection_verified_at else None
            ),
        },
        message="EHR configuration saved",
    )


@admin_router.get("/clinics/{clinic_id}/ehr-config", response_model=APIResponse)
async def get_ehr_config(
    clinic_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> APIResponse:
    """Return NextGen config without secrets."""
    stmt = select(ClinicEHRConfig).where(ClinicEHRConfig.clinic_id == clinic_id)
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if not row:
        raise_not_found("ClinicEHRConfig", clinic_id)

    return APIResponse(
        success=True,
        data={
            "clinic_id": str(clinic_id),
            "nextgen_url": row.nextgen_url,
            "appt_type_mapping": row.appt_type_mapping or {},
            "connection_verified_at": (
                row.connection_verified_at.isoformat() if row.connection_verified_at else None
            ),
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        },
    )


@admin_router.post("/clinics/{clinic_id}/ehr-test", response_model=APIResponse)
async def ehr_test_credentials(
    clinic_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> APIResponse:
    """Run a one-off Playwright login against NextGen; updates connection_verified_at on success."""
    stmt = select(ClinicEHRConfig).where(ClinicEHRConfig.clinic_id == clinic_id)
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if not row:
        raise_not_found("ClinicEHRConfig", clinic_id)

    test_result = await playwright_ehr_service.test_credentials(db, clinic_id)
    if test_result.get("success"):
        row.connection_verified_at = datetime.now(timezone.utc)
        row.updated_at = datetime.now(timezone.utc)
        await db.commit()

    return APIResponse(success=True, data=test_result, message="EHR credential test complete")


@admin_router.put("/clinics/{clinic_id}/appt-types", response_model=APIResponse)
async def put_appt_type_mapping(
    clinic_id: UUID,
    request: ApptTypesPutRequest,
    db: AsyncSession = Depends(get_db),
) -> APIResponse:
    """Update gap_type → NextGen appointment type code mapping (JSONB)."""
    stmt = select(ClinicEHRConfig).where(ClinicEHRConfig.clinic_id == clinic_id)
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if not row:
        raise_not_found("ClinicEHRConfig", clinic_id)

    row.appt_type_mapping = request.mapping
    row.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(row)

    return APIResponse(
        success=True,
        data={"clinic_id": str(clinic_id), "appt_type_mapping": row.appt_type_mapping},
        message="Appointment type mapping updated",
    )


# ── EHR MFA / two-factor authentication handoff ───────────────────────────────


@admin_router.get("/clinics/{clinic_id}/ehr-status", response_model=APIResponse)
async def get_ehr_status(
    clinic_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> APIResponse:
    """
    Return current EHR login status for a clinic.
    Dashboard polls this to detect when MFA is required.

    Response: {"logged_in": bool, "mfa_required": bool}
    """
    from Clinic_app.common.redis import get_redis
    from Clinic_app.services.playwright_ehr import playwright_ehr_service, MFA_REDIS_PREFIX

    r = await get_redis()
    mfa_key = f"{MFA_REDIS_PREFIX}:{clinic_id}"
    mfa_val = await r.get(mfa_key)
    mfa_val_str = mfa_val.decode() if isinstance(mfa_val, bytes) else (mfa_val or "")
    mfa_required = mfa_val_str == "pending"

    # Check if an active session exists (non-None entry in service's internal dict)
    # Browser-Use doesn't keep persistent sessions — use MFA key as proxy for active state
    return APIResponse(
        success=True,
        data={
            "clinic_id": str(clinic_id),
            "mfa_required": mfa_required,
        },
        message="EHR status retrieved",
    )


class EhrMfaCodeRequest(BaseModel):
    code: str

    @field_validator("code")
    @classmethod
    def code_must_be_nonempty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("MFA code cannot be empty")
        return v


@admin_router.post("/clinics/{clinic_id}/ehr-mfa-code", response_model=APIResponse)
async def submit_ehr_mfa_code(
    clinic_id: UUID,
    request: EhrMfaCodeRequest,
    db: AsyncSession = Depends(get_db),
) -> APIResponse:
    """
    Submit the MFA / verification code for an EHR login that is waiting for 2FA.
    The Browser-Use automation polls Redis every 5s for this code.

    Steps:
      1. Dashboard shows MFA banner (GET /ehr-status → mfa_required: true)
      2. Clinic admin enters code from their email/phone
      3. Admin submits POST /ehr-mfa-code with the code
      4. This endpoint writes the code to Redis
      5. Browser-Use automation picks it up and continues login
    """
    from Clinic_app.common.redis import get_redis
    from Clinic_app.services.playwright_ehr import MFA_REDIS_PREFIX, MFA_TIMEOUT_SECONDS

    r = await get_redis()
    mfa_key = f"{MFA_REDIS_PREFIX}:{clinic_id}"

    # Check that MFA is actually pending before accepting a code
    mfa_val = await r.get(mfa_key)
    mfa_val_str = mfa_val.decode() if isinstance(mfa_val, bytes) else (mfa_val or "")
    if not mfa_val_str:
        return APIResponse(
            success=False,
            data={"clinic_id": str(clinic_id)},
            message="No MFA challenge is pending for this clinic",
        )

    # Write the code — the playwright_ehr.py polling loop will pick it up
    await r.set(mfa_key, request.code, ex=MFA_TIMEOUT_SECONDS)
    return APIResponse(
        success=True,
        data={"clinic_id": str(clinic_id), "accepted": True},
        message="MFA code accepted — EHR automation will resume within 5 seconds",
    )

