"""
Admin routes for clinic management.

Handles clinic, integration, and license CRUD operations.
Routes handle database operations directly (no service layer).
"""

import json
import re
import logging
from typing import Optional, Dict, Any, List
from uuid import UUID
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from pydantic import BaseModel, field_validator

from Clinic_app.common.database import get_db
from Clinic_app.common.schemas import APIResponse
from Clinic_app.data.models.clinic import Clinic
from Clinic_app.data.models.clinic_integration import ClinicIntegration
from Clinic_app.data.models.license import License

logger = logging.getLogger(__name__)

# Router setup
admin_router = APIRouter(prefix="/admin", tags=["Clinic Admin"])

# Validation constants
VALID_CLINIC_TIERS = ["basic", "pro", "enterprise"]
VALID_CLINIC_STATUSES = ["active", "suspended"]
VALID_LICENSE_STATUSES = ["active", "suspended", "expired"]
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

class ClinicBase(BaseModel):
    """Base clinic model."""
    name: str
    tier: str
    status: str = "active"
    license_token: str
    license_expires_at: Optional[datetime] = None
    network_id: Optional[UUID] = None

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


class LicenseBase(BaseModel):
    """Base license model."""
    token: str
    tier: str
    status: str = "active"
    max_concurrency: int
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
        if v not in VALID_LICENSE_STATUSES:
            raise ValueError(f"status must be one of {VALID_LICENSE_STATUSES}")
        return v

    @field_validator('max_concurrency')
    @classmethod
    def validate_max_concurrency(cls, v):
        if v <= 0:
            raise ValueError("max_concurrency must be a positive integer")
        return v


class LicenseCreateRequest(LicenseBase):
    """Request model for creating/updating license."""
    pass


class ClinicSetupRequest(BaseModel):
    """Request model for clinic setup (creates clinic + integration + license)."""
    clinic: ClinicCreateRequest
    integration: IntegrationCreateRequest
    license: LicenseCreateRequest


class ClinicResponse(BaseModel):
    """Response model for clinic data."""
    id: UUID
    name: str
    tier: str
    status: str
    license_token: str
    license_expires_at: Optional[datetime]
    network_id: Optional[UUID]
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
    Create a new clinic with integration and license in a single transaction.
    
    This is a convenience endpoint for initial clinic onboarding. All three
    records (Clinic, ClinicIntegration, License) are created atomically.
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
        
        # Create Clinic
        clinic = Clinic(
            name=request.clinic.name,
            tier=request.clinic.tier,
            status=request.clinic.status,
            license_token=request.clinic.license_token,
            license_expires_at=request.clinic.license_expires_at,
            network_id=request.clinic.network_id
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
        
        # Create License
        license = License(
            clinic_id=clinic.id,
            token=request.license.token,
            tier=request.license.tier,
            status=request.license.status,
            max_concurrency=request.license.max_concurrency,
            features=request.license.features
        )
        db.add(license)
        
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
    """Create a clinic only (without integration/license)."""
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
            network_id=request.network_id
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


@admin_router.post("/clinics/{clinic_id}/license", response_model=APIResponse)
async def create_license(
    clinic_id: UUID,
    request: LicenseCreateRequest,
    db: AsyncSession = Depends(get_db)
) -> APIResponse:
    """Create or update clinic license."""
    # Check clinic exists
    clinic = await db.get(Clinic, clinic_id)
    if not clinic:
        raise_not_found("Clinic", clinic_id)
    
    try:
        logger.info(f"Creating/updating license: clinic_id={clinic_id}")
        
        # Check if license already exists
        license = await db.get(License, clinic_id)
        
        if license:
            # Update existing
            license.token = request.token
            license.tier = request.tier
            license.status = request.status
            license.max_concurrency = request.max_concurrency
            license.features = request.features
            license.updated_at = datetime.utcnow()
        else:
            # Check if token already exists
            stmt = select(License).where(License.token == request.token)
            result = await db.execute(stmt)
            existing = result.scalar_one_or_none()
            if existing:
                logger.warning(f"Duplicate license token attempted: {request.token}")
                raise_conflict_error(f"License token '{request.token}' already exists", "DUPLICATE_LICENSE_TOKEN")
            
            # Create new
            license = License(
                clinic_id=clinic_id,
                token=request.token,
                tier=request.tier,
                status=request.status,
                max_concurrency=request.max_concurrency,
                features=request.features
            )
            db.add(license)
        
        await db.commit()
        logger.info(f"License updated: clinic_id={clinic_id}")
        
        return APIResponse(
            success=True,
            data={
                "clinic_id": str(license.clinic_id),
                "token": license.token,
                "tier": license.tier,
                "status": license.status,
                "max_concurrency": license.max_concurrency,
                "features": license.features
            },
            message="License created/updated successfully"
        )
        
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError as e:
        await db.rollback()
        logger.error(f"Database integrity error creating license: {str(e)}", exc_info=True)
        if "token" in str(e.orig):
            raise_conflict_error("License token already exists", "DUPLICATE_LICENSE_TOKEN")
        raise_conflict_error("Database constraint violation", "CONSTRAINT_VIOLATION")
    except Exception as e:
        await db.rollback()
        logger.error(f"Unexpected error creating license: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "code": "INTERNAL_ERROR",
                "message": "Failed to create/update license"
            }
        )


@admin_router.get("/clinics/{clinic_id}/license", response_model=APIResponse)
async def get_license(
    clinic_id: UUID,
    db: AsyncSession = Depends(get_db)
) -> APIResponse:
    """Get clinic license."""
    license = await db.get(License, clinic_id)
    
    if not license:
        raise_not_found("License", clinic_id)
    
    return APIResponse(
        success=True,
        data={
            "clinic_id": str(license.clinic_id),
            "token": license.token,
            "tier": license.tier,
            "status": license.status,
            "max_concurrency": license.max_concurrency,
            "features": license.features,
            "issued_at": license.issued_at.isoformat(),
            "updated_at": license.updated_at.isoformat()
        }
    )


@admin_router.put("/clinics/{clinic_id}/license", response_model=APIResponse)
async def update_license(
    clinic_id: UUID,
    request: LicenseCreateRequest,
    db: AsyncSession = Depends(get_db)
) -> APIResponse:
    """Update clinic license."""
    license = await db.get(License, clinic_id)
    
    if not license:
        raise_not_found("License", clinic_id)
    
    try:
        logger.info(f"Updating license: clinic_id={clinic_id}")
        
        # Check token uniqueness if being updated
        if request.token != license.token:
            stmt = select(License).where(
                License.token == request.token,
                License.clinic_id != clinic_id
            )
            result = await db.execute(stmt)
            existing = result.scalar_one_or_none()
            if existing:
                logger.warning(f"Duplicate license token attempted: {request.token}")
                raise_conflict_error(f"License token '{request.token}' already exists", "DUPLICATE_LICENSE_TOKEN")
        
        license.token = request.token
        license.tier = request.tier
        license.status = request.status
        license.max_concurrency = request.max_concurrency
        license.features = request.features
        license.updated_at = datetime.utcnow()
        
        await db.commit()
        logger.info(f"License updated: clinic_id={clinic_id}")
        
        return APIResponse(
            success=True,
            data={
                "clinic_id": str(license.clinic_id),
                "token": license.token,
                "tier": license.tier,
                "status": license.status,
                "max_concurrency": license.max_concurrency,
                "features": license.features
            },
            message="License updated successfully"
        )
        
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError as e:
        await db.rollback()
        logger.error(f"Database integrity error updating license: {str(e)}", exc_info=True)
        raise_conflict_error("Database constraint violation", "CONSTRAINT_VIOLATION")
    except Exception as e:
        await db.rollback()
        logger.error(f"Unexpected error updating license: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "code": "INTERNAL_ERROR",
                "message": "Failed to update license"
            }
        )


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


# Note: Booking management endpoints (list/cancel) are part of the Phase 2
# GCal-based scheduling system. They are implemented in services/booking.py
# but not wired here to keep the MVP scope focused on outbound campaigns.

