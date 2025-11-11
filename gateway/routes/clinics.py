"""
Clinic Management API Routes

REST endpoints for clinic operations including creation, updates, and configuration.
Provides comprehensive clinic management including licenses, configurations, and template variables.
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional, Dict, Any
from pydantic import BaseModel

from services.database import get_async_db
from services.clinic_management import ClinicManagementService
from services.clinic_template_variables import get_clinic_template_variables
from services.response_service import get_response_templates
from services.nlp_service import IntentType
from services.structured_logging import get_logger, LogCategory
from services.exceptions import (
    CallCenterAIException, ValidationError, ErrorCode
)
from models.enums import LanguageCode
from models.schemas import (
    ClinicCreateRequest, ClinicUpdateRequest, ClinicResponse,
    ClinicSearchRequest, SystemConfigCreateRequest,
    ClinicLicenseResponse, SuccessResponse
)

# Initialize logger
logger = get_logger("clinic_routes")

router = APIRouter(prefix="/clinics", tags=["clinic-management"])

# Allowed subscription tiers for validation
ALLOWED_TIERS = {"free", "basic", "professional", "enterprise"}


@router.post("/", response_model=ClinicResponse, status_code=status.HTTP_201_CREATED)
async def create_clinic(
    clinic_data: ClinicCreateRequest,
    db: AsyncSession = Depends(get_async_db)
):
    """
    Create a new clinic with license and initial configuration.
    
    This endpoint creates a complete clinic setup including:
    - Clinic record with basic information
    - License with subscription tier limits
    - Initial system configurations
    - Audit trail for creation
    
    Args:
        clinic_data: Clinic creation request with all required information
        db: Database session
        
    Returns:
        ClinicResponse with created clinic information
        
    Raises:
        HTTPException 400: Invalid clinic data or clinic already exists
        HTTPException 500: Internal server error
    """
    try:
        logger.info(
            "Creating new clinic",
            LogCategory.CLINIC_MANAGEMENT,
            extra_data={
                "clinic_name": clinic_data.clinic_name,
                "subscription_tier": clinic_data.subscription_tier.value if hasattr(clinic_data.subscription_tier, 'value') else str(clinic_data.subscription_tier)
            }
        )
        
        service = ClinicManagementService(db)
        clinic = await service.create_clinic(clinic_data)
        
        logger.info(
            f"Clinic created successfully: {clinic.clinic_id}",
            LogCategory.CLINIC_MANAGEMENT,
            extra_data={"clinic_id": clinic.clinic_id}
        )
        
        return ClinicResponse.model_validate(clinic)
        
    except HTTPException:
        raise
    except ValueError as e:
        logger.warning(
            f"Validation error creating clinic: {str(e)}",
            LogCategory.VALIDATION,
            extra_data={"clinic_name": clinic_data.clinic_name if hasattr(clinic_data, 'clinic_name') else None}
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except CallCenterAIException as e:
        http_status = e.http_status if hasattr(e, 'http_status') and e.http_status != 500 else (
            status.HTTP_400_BAD_REQUEST if e.error_code == ErrorCode.VALIDATION_ERROR
            else status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        logger.error(
            f"Service error creating clinic: {e.user_message}",
            LogCategory.ERROR,
            extra_data={"error_code": e.error_code.value if hasattr(e.error_code, 'value') else str(e.error_code)}
        )
        raise HTTPException(
            status_code=http_status,
            detail=e.user_message
        )
    except Exception as e:
        logger.critical(
            f"Unexpected error creating clinic: {e}",
            LogCategory.EXCEPTION,
            exception=e
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while creating the clinic"
        )


@router.get("/", response_model=List[ClinicResponse])
async def list_clinics(
    search: ClinicSearchRequest = Depends(),
    db: AsyncSession = Depends(get_async_db)
):
    """
    List clinics with optional filtering and pagination.
    
    Supports filtering by:
    - Clinic name (partial match)
    - Phone number (exact match)
    - Subscription tier
    - Active status
    
    Includes pagination with limit and offset.
    
    Args:
        search: Search request with optional filters and pagination
        db: Database session
        
    Returns:
        List of ClinicResponse objects matching the search criteria
        
    Raises:
        HTTPException 500: Internal server error
    """
    try:
        logger.info(
            "Listing clinics",
            LogCategory.CLINIC_MANAGEMENT,
            extra_data={
                "has_name_filter": bool(search.clinic_name) if hasattr(search, 'clinic_name') else False,
                "has_phone_filter": bool(search.phone_number) if hasattr(search, 'phone_number') else False,
                "limit": search.limit if hasattr(search, 'limit') else None,
                "offset": search.offset if hasattr(search, 'offset') else None
            }
        )
        
        service = ClinicManagementService(db)
        clinics = await service.list_clinics(search)
        
        logger.info(
            f"Retrieved {len(clinics)} clinics",
            LogCategory.CLINIC_MANAGEMENT,
            extra_data={"count": len(clinics)}
        )
        
        return [ClinicResponse.model_validate(clinic) for clinic in clinics]
        
    except Exception as e:
        logger.critical(
            f"Unexpected error listing clinics: {e}",
            LogCategory.EXCEPTION,
            exception=e
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while listing clinics"
        )


@router.get("/{clinic_id}", response_model=ClinicResponse)
async def get_clinic(
    clinic_id: str = Query(..., min_length=3, max_length=64, description="Clinic ID"),
    db: AsyncSession = Depends(get_async_db)
):
    """
    Get a specific clinic by ID.
    
    Returns complete clinic information including:
    - Basic clinic details
    - Subscription tier
    - Configuration settings
    - License information
    
    Args:
        clinic_id: Clinic ID to retrieve
        db: Database session
        
    Returns:
        ClinicResponse with complete clinic information
        
    Raises:
        HTTPException 404: Clinic not found
        HTTPException 500: Internal server error
    """
    try:
        logger.info(
            f"Getting clinic {clinic_id}",
            LogCategory.CLINIC_MANAGEMENT,
            extra_data={"clinic_id": clinic_id}
        )
        
        service = ClinicManagementService(db)
        clinic = await service.get_clinic(clinic_id)
        
        if not clinic:
            logger.warning(
                f"Clinic {clinic_id} not found",
                LogCategory.CLINIC_MANAGEMENT,
                extra_data={"clinic_id": clinic_id}
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Clinic {clinic_id} not found"
            )
        
        logger.info(
            f"Retrieved clinic {clinic_id}",
            LogCategory.CLINIC_MANAGEMENT,
            extra_data={"clinic_id": clinic_id, "clinic_name": clinic.clinic_name}
        )
        
        return ClinicResponse.model_validate(clinic)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.critical(
            f"Unexpected error getting clinic: {e}",
            LogCategory.EXCEPTION,
            exception=e,
            extra_data={"clinic_id": clinic_id}
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while retrieving the clinic"
        )


@router.put("/{clinic_id}", response_model=ClinicResponse)
async def update_clinic(
    clinic_id: str = Query(..., min_length=3, max_length=64, description="Clinic ID"),
    updates: ClinicUpdateRequest = ...,
    db: AsyncSession = Depends(get_async_db)
):
    """
    Update clinic information.
    
    Supports updating:
    - Basic clinic information
    - Contact details
    - System settings
    - Subscription tier
    - Active status
    
    All changes are logged in the audit trail.
    
    Args:
        clinic_id: Clinic ID to update
        updates: Clinic update request with fields to update
        db: Database session
        
    Returns:
        ClinicResponse with updated clinic information
        
    Raises:
        HTTPException 404: Clinic not found
        HTTPException 400: Invalid update data
        HTTPException 500: Internal server error
    """
    try:
        logger.info(
            f"Updating clinic {clinic_id}",
            LogCategory.CLINIC_MANAGEMENT,
            extra_data={"clinic_id": clinic_id}
        )
        
        service = ClinicManagementService(db)
        clinic = await service.update_clinic(clinic_id, updates)
        
        if not clinic:
            logger.warning(
                f"Clinic {clinic_id} not found for update",
                LogCategory.CLINIC_MANAGEMENT,
                extra_data={"clinic_id": clinic_id}
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Clinic {clinic_id} not found"
            )
        
        logger.info(
            f"Clinic {clinic_id} updated successfully",
            LogCategory.CLINIC_MANAGEMENT,
            extra_data={"clinic_id": clinic_id}
        )
        
        return ClinicResponse.model_validate(clinic)
        
    except HTTPException:
        raise
    except ValueError as e:
        logger.warning(
            f"Validation error updating clinic: {str(e)}",
            LogCategory.VALIDATION,
            extra_data={"clinic_id": clinic_id}
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except CallCenterAIException as e:
        http_status = e.http_status if hasattr(e, 'http_status') and e.http_status != 500 else (
            status.HTTP_400_BAD_REQUEST if e.error_code == ErrorCode.VALIDATION_ERROR
            else status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        logger.error(
            f"Service error updating clinic: {e.user_message}",
            LogCategory.ERROR,
            extra_data={"clinic_id": clinic_id}
        )
        raise HTTPException(
            status_code=http_status,
            detail=e.user_message
        )
    except Exception as e:
        logger.critical(
            f"Unexpected error updating clinic: {e}",
            LogCategory.EXCEPTION,
            exception=e,
            extra_data={"clinic_id": clinic_id}
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while updating the clinic"
        )


@router.delete("/{clinic_id}", response_model=SuccessResponse)
async def deactivate_clinic(
    clinic_id: str = Query(..., min_length=3, max_length=64, description="Clinic ID"),
    db: AsyncSession = Depends(get_async_db)
):
    """
    Deactivate a clinic (soft delete).
    
    This operation:
    - Sets clinic status to inactive
    - Preserves all data for audit purposes
    - Logs the deactivation
    - Does not delete any records
    
    Args:
        clinic_id: Clinic ID to deactivate
        db: Database session
        
    Returns:
        SuccessResponse with confirmation message
        
    Raises:
        HTTPException 404: Clinic not found
        HTTPException 500: Internal server error
    """
    try:
        logger.info(
            f"Deactivating clinic {clinic_id}",
            LogCategory.CLINIC_MANAGEMENT,
            extra_data={"clinic_id": clinic_id}
        )
        
        service = ClinicManagementService(db)
        success = await service.deactivate_clinic(clinic_id)
        
        if not success:
            logger.warning(
                f"Clinic {clinic_id} not found for deactivation",
                LogCategory.CLINIC_MANAGEMENT,
                extra_data={"clinic_id": clinic_id}
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Clinic {clinic_id} not found"
            )
        
        logger.info(
            f"Clinic {clinic_id} deactivated successfully",
            LogCategory.CLINIC_MANAGEMENT,
            extra_data={"clinic_id": clinic_id}
        )
        
        return SuccessResponse(
            message=f"Clinic {clinic_id} deactivated successfully"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.critical(
            f"Unexpected error deactivating clinic: {e}",
            LogCategory.EXCEPTION,
            exception=e,
            extra_data={"clinic_id": clinic_id}
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while deactivating the clinic"
        )


@router.get("/{clinic_id}/license", response_model=ClinicLicenseResponse)
async def get_clinic_license(
    clinic_id: str = Query(..., min_length=3, max_length=64, description="Clinic ID"),
    db: AsyncSession = Depends(get_async_db)
):
    """
    Get clinic license information.
    
    Returns license details including:
    - Subscription tier and limits
    - Current usage statistics
    - Billing information
    - License status
    
    Args:
        clinic_id: Clinic ID to get license for
        db: Database session
        
    Returns:
        ClinicLicenseResponse with license information
        
    Raises:
        HTTPException 404: License not found
        HTTPException 500: Internal server error
    """
    try:
        logger.info(
            f"Getting license for clinic {clinic_id}",
            LogCategory.CLINIC_MANAGEMENT,
            extra_data={"clinic_id": clinic_id}
        )
        
        service = ClinicManagementService(db)
        license = await service.get_clinic_license(clinic_id)
        
        if not license:
            logger.warning(
                f"License for clinic {clinic_id} not found",
                LogCategory.CLINIC_MANAGEMENT,
                extra_data={"clinic_id": clinic_id}
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"License for clinic {clinic_id} not found"
            )
        
        logger.info(
            f"Retrieved license for clinic {clinic_id}",
            LogCategory.CLINIC_MANAGEMENT,
            extra_data={"clinic_id": clinic_id, "tier": license.tier if license else None}
        )
        
        return ClinicLicenseResponse.model_validate(license)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.critical(
            f"Unexpected error getting clinic license: {e}",
            LogCategory.EXCEPTION,
            exception=e,
            extra_data={"clinic_id": clinic_id}
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while retrieving the clinic license"
        )


@router.put("/{clinic_id}/license", response_model=SuccessResponse)
async def update_clinic_license(
    clinic_id: str = Query(..., min_length=3, max_length=64, description="Clinic ID"),
    tier: str = Query(..., min_length=3, max_length=20, description="Subscription tier"),
    db: AsyncSession = Depends(get_async_db)
):
    """
    Update clinic subscription tier.
    
    This operation:
    - Updates the clinic's subscription tier
    - Adjusts license limits based on new tier
    - Updates billing information
    - Logs all changes
    
    Args:
        clinic_id: Clinic ID to update license for
        tier: New subscription tier (free, basic, professional, enterprise)
        db: Database session
        
    Returns:
        SuccessResponse with confirmation message
        
    Raises:
        HTTPException 404: Clinic not found
        HTTPException 400: Invalid tier value
        HTTPException 500: Internal server error
    """
    try:
        # Validate tier
        if tier.lower() not in ALLOWED_TIERS:
            logger.warning(
                f"Invalid tier value: {tier}",
                LogCategory.VALIDATION,
                extra_data={"clinic_id": clinic_id, "tier": tier, "allowed_tiers": list(ALLOWED_TIERS)}
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid tier '{tier}'. Allowed tiers: {', '.join(ALLOWED_TIERS)}"
            )
        
        logger.info(
            f"Updating license for clinic {clinic_id} to tier {tier}",
            LogCategory.CLINIC_MANAGEMENT,
            extra_data={"clinic_id": clinic_id, "tier": tier}
        )
        
        service = ClinicManagementService(db)
        success = await service.update_clinic_license(clinic_id, tier.lower())
        
        if not success:
            logger.warning(
                f"Clinic {clinic_id} not found for license update",
                LogCategory.CLINIC_MANAGEMENT,
                extra_data={"clinic_id": clinic_id}
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Clinic {clinic_id} not found"
            )
        
        logger.info(
            f"Clinic {clinic_id} license updated to {tier} tier",
            LogCategory.CLINIC_MANAGEMENT,
            extra_data={"clinic_id": clinic_id, "tier": tier}
        )
        
        return SuccessResponse(
            message=f"Clinic {clinic_id} license updated to {tier} tier"
        )
        
    except HTTPException:
        raise
    except ValueError as e:
        logger.warning(
            f"Validation error updating clinic license: {str(e)}",
            LogCategory.VALIDATION,
            extra_data={"clinic_id": clinic_id, "tier": tier}
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except CallCenterAIException as e:
        http_status = e.http_status if hasattr(e, 'http_status') and e.http_status != 500 else (
            status.HTTP_400_BAD_REQUEST if e.error_code == ErrorCode.VALIDATION_ERROR
            else status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        logger.error(
            f"Service error updating clinic license: {e.user_message}",
            LogCategory.ERROR,
            extra_data={"clinic_id": clinic_id, "tier": tier}
        )
        raise HTTPException(
            status_code=http_status,
            detail=e.user_message
        )
    except Exception as e:
        logger.critical(
            f"Unexpected error updating clinic license: {e}",
            LogCategory.EXCEPTION,
            exception=e,
            extra_data={"clinic_id": clinic_id, "tier": tier}
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while updating the clinic license"
        )


@router.get("/{clinic_id}/config/{config_key}", response_model=dict)
async def get_clinic_config(
    clinic_id: str = Query(..., min_length=3, max_length=64, description="Clinic ID"),
    config_key: str = Query(..., min_length=1, max_length=100, description="Configuration key"),
    db: AsyncSession = Depends(get_async_db)
):
    """
    Get a specific configuration value for a clinic.
    
    Returns the configuration value for the specified key.
    Common configuration keys:
    - emergency_keywords
    - business_hours
    - ai_model
    - voice_settings
    - google_calendar_enabled
    
    Args:
        clinic_id: Clinic ID
        config_key: Configuration key to retrieve
        db: Database session
        
    Returns:
        Dictionary with clinic_id, config_key, and config_value
        
    Raises:
        HTTPException 404: Configuration not found
        HTTPException 500: Internal server error
    """
    try:
        logger.info(
            f"Getting configuration {config_key} for clinic {clinic_id}",
            LogCategory.CLINIC_MANAGEMENT,
            extra_data={"clinic_id": clinic_id, "config_key": config_key}
        )
        
        service = ClinicManagementService(db)
        config_value = await service.get_clinic_config(clinic_id, config_key)
        
        if config_value is None:
            logger.warning(
                f"Configuration {config_key} not found for clinic {clinic_id}",
                LogCategory.CLINIC_MANAGEMENT,
                extra_data={"clinic_id": clinic_id, "config_key": config_key}
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Configuration {config_key} not found for clinic {clinic_id}"
            )
        
        logger.info(
            f"Retrieved configuration {config_key} for clinic {clinic_id}",
            LogCategory.CLINIC_MANAGEMENT,
            extra_data={"clinic_id": clinic_id, "config_key": config_key}
        )
        
        return {
            "clinic_id": clinic_id,
            "config_key": config_key,
            "config_value": config_value
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.critical(
            f"Unexpected error getting clinic configuration: {e}",
            LogCategory.EXCEPTION,
            exception=e,
            extra_data={"clinic_id": clinic_id, "config_key": config_key}
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while retrieving the clinic configuration"
        )


@router.put("/{clinic_id}/config/{config_key}", response_model=SuccessResponse)
async def set_clinic_config(
    clinic_id: str = Query(..., min_length=3, max_length=64, description="Clinic ID"),
    config_key: str = Query(..., min_length=1, max_length=100, description="Configuration key"),
    config_data: SystemConfigCreateRequest = ...,
    db: AsyncSession = Depends(get_async_db)
):
    """
    Set a configuration value for a clinic.
    
    Creates or updates a clinic-specific configuration.
    The configuration key will be prefixed with the clinic ID
    to ensure isolation between clinics.
    
    Args:
        clinic_id: Clinic ID
        config_key: Configuration key to set
        config_data: Configuration data with value and description
        db: Database session
        
    Returns:
        SuccessResponse with confirmation message
        
    Raises:
        HTTPException 500: Internal server error or failed to set configuration
    """
    try:
        logger.info(
            f"Setting configuration {config_key} for clinic {clinic_id}",
            LogCategory.CLINIC_MANAGEMENT,
            extra_data={"clinic_id": clinic_id, "config_key": config_key}
        )
        
        service = ClinicManagementService(db)
        success = await service.set_clinic_config(
            clinic_id, config_key, config_data.config_value, config_data.description
        )
        
        if not success:
            logger.error(
                f"Failed to set configuration {config_key} for clinic {clinic_id}",
                LogCategory.ERROR,
                extra_data={"clinic_id": clinic_id, "config_key": config_key}
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to set clinic configuration"
            )
        
        logger.info(
            f"Configuration {config_key} set successfully for clinic {clinic_id}",
            LogCategory.CLINIC_MANAGEMENT,
            extra_data={"clinic_id": clinic_id, "config_key": config_key}
        )
        
        return SuccessResponse(
            message=f"Configuration {config_key} set for clinic {clinic_id}"
        )
        
    except HTTPException:
        raise
    except CallCenterAIException as e:
        http_status = e.http_status if hasattr(e, 'http_status') and e.http_status != 500 else (
            status.HTTP_400_BAD_REQUEST if e.error_code == ErrorCode.VALIDATION_ERROR
            else status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        logger.error(
            f"Service error setting clinic configuration: {e.user_message}",
            LogCategory.ERROR,
            extra_data={"clinic_id": clinic_id, "config_key": config_key}
        )
        raise HTTPException(
            status_code=http_status,
            detail=e.user_message
        )
    except Exception as e:
        logger.critical(
            f"Unexpected error setting clinic configuration: {e}",
            LogCategory.EXCEPTION,
            exception=e,
            extra_data={"clinic_id": clinic_id, "config_key": config_key}
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while setting the clinic configuration"
        )


@router.get("/{clinic_id}/stats", response_model=dict)
async def get_clinic_stats(
    clinic_id: str = Query(..., min_length=3, max_length=64, description="Clinic ID"),
    db: AsyncSession = Depends(get_async_db)
):
    """
    Get clinic statistics and usage information.
    
    Returns comprehensive statistics including:
    - Provider count
    - Appointment statistics
    - Call volume
    - License usage
    - Configuration summary
    
    Args:
        clinic_id: Clinic ID to get statistics for
        db: Database session
        
    Returns:
        Dictionary with clinic statistics and information
        
    Raises:
        HTTPException 404: Clinic not found
        HTTPException 500: Internal server error
    """
    try:
        logger.info(
            f"Getting statistics for clinic {clinic_id}",
            LogCategory.CLINIC_MANAGEMENT,
            extra_data={"clinic_id": clinic_id}
        )
        
        service = ClinicManagementService(db)
        clinic = await service.get_clinic(clinic_id)
        
        if not clinic:
            logger.warning(
                f"Clinic {clinic_id} not found for statistics",
                LogCategory.CLINIC_MANAGEMENT,
                extra_data={"clinic_id": clinic_id}
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Clinic {clinic_id} not found"
            )
        
        # Get license information
        license = await service.get_clinic_license(clinic_id)
        
        # Get common configurations
        emergency_keywords = await service.get_clinic_config(clinic_id, "emergency_keywords")
        business_hours = await service.get_clinic_config(clinic_id, "business_hours")
        google_calendar_enabled = await service.get_clinic_config(clinic_id, "google_calendar_enabled")
        
        logger.info(
            f"Retrieved statistics for clinic {clinic_id}",
            LogCategory.CLINIC_MANAGEMENT,
            extra_data={"clinic_id": clinic_id}
        )
        
        return {
            "clinic_id": clinic_id,
            "clinic_name": clinic.clinic_name,
            "subscription_tier": clinic.subscription_tier,
            "is_active": clinic.is_active,
            "license": {
                "tier": license.tier if license else None,
                "max_calls_per_month": license.max_calls_per_month if license else None,
                "current_month_calls": license.current_month_calls if license else 0,
                "max_providers": license.max_providers if license else None,
                "monthly_fee_usd": license.monthly_fee_usd if license else None
            },
            "configuration": {
                "emergency_keywords": emergency_keywords,
                "business_hours": business_hours,
                "google_calendar_enabled": google_calendar_enabled
            },
            "created_at": clinic.created_at.isoformat() if clinic.created_at else None,
            "updated_at": clinic.updated_at.isoformat() if clinic.updated_at else None
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.critical(
            f"Unexpected error getting clinic statistics: {e}",
            LogCategory.EXCEPTION,
            exception=e,
            extra_data={"clinic_id": clinic_id}
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while retrieving clinic statistics"
        )


class ClinicTemplateVariablesRequest(BaseModel):
    """Request to update clinic template variables."""
    clinic_name: Optional[str] = None
    clinic_address: Optional[str] = None
    clinic_email: Optional[str] = None
    clinic_business_hours: Optional[str] = None
    clinic_services: Optional[str] = None
    clinic_insurance_plans: Optional[str] = None
    clinic_pharmacy_phone: Optional[str] = None


@router.get("/{clinic_id}/template-variables", response_model=Dict[str, Any])
async def get_clinic_template_variables_endpoint(
    clinic_id: str = Query(..., min_length=3, max_length=64, description="Clinic ID"),
    db: AsyncSession = Depends(get_async_db)
):
    """
    Get current clinic template variables.
    
    Returns template variables from all sources (env vars, config file, SystemConfig, Clinic model)
    in priority order.
    
    Args:
        clinic_id: Clinic ID to get template variables for
        db: Database session
        
    Returns:
        Dictionary with clinic_id, template_variables, and source information
        
    Raises:
        HTTPException 404: Clinic not found
        HTTPException 500: Internal server error
    """
    try:
        logger.info(
            f"Getting template variables for clinic {clinic_id}",
            LogCategory.CLINIC_MANAGEMENT,
            extra_data={"clinic_id": clinic_id}
        )
        
        service = ClinicManagementService(db)
        clinic = await service.get_clinic(clinic_id)
        
        if not clinic:
            logger.warning(
                f"Clinic {clinic_id} not found for template variables",
                LogCategory.CLINIC_MANAGEMENT,
                extra_data={"clinic_id": clinic_id}
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Clinic {clinic_id} not found"
            )
        
        # Get template variables from all sources
        template_vars = await get_clinic_template_variables(clinic_id, db)
        
        logger.info(
            f"Retrieved template variables for clinic {clinic_id}",
            LogCategory.CLINIC_MANAGEMENT,
            extra_data={"clinic_id": clinic_id, "variable_count": len(template_vars)}
        )
        
        return {
            "clinic_id": clinic_id,
            "template_variables": template_vars,
            "source": "environment_variables"  # Could be enhanced to show actual source
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.critical(
            f"Unexpected error getting clinic template variables: {e}",
            LogCategory.EXCEPTION,
            exception=e,
            extra_data={"clinic_id": clinic_id}
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while retrieving clinic template variables"
        )


@router.put("/{clinic_id}/template-variables", response_model=SuccessResponse)
async def update_clinic_template_variables(
    clinic_id: str = Query(..., min_length=3, max_length=64, description="Clinic ID"),
    variables: ClinicTemplateVariablesRequest = ...,
    db: AsyncSession = Depends(get_async_db)
):
    """
    Update clinic template variables in SystemConfig table.
    
    Note: Environment variables take precedence over SystemConfig values.
    This endpoint stores values in SystemConfig as a fallback.
    
    Args:
        clinic_id: Clinic ID to update template variables for
        variables: Template variables request with optional fields to update
        db: Database session
        
    Returns:
        SuccessResponse with number of variables updated
        
    Raises:
        HTTPException 404: Clinic not found
        HTTPException 500: Internal server error
    """
    try:
        logger.info(
            f"Updating template variables for clinic {clinic_id}",
            LogCategory.CLINIC_MANAGEMENT,
            extra_data={"clinic_id": clinic_id}
        )
        
        service = ClinicManagementService(db)
        clinic = await service.get_clinic(clinic_id)
        
        if not clinic:
            logger.warning(
                f"Clinic {clinic_id} not found for template variable update",
                LogCategory.CLINIC_MANAGEMENT,
                extra_data={"clinic_id": clinic_id}
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Clinic {clinic_id} not found"
            )
        
        # Update each variable in SystemConfig
        updated_count = 0
        if variables.clinic_name:
            await service.set_clinic_config(clinic_id, "clinic_name", variables.clinic_name, "Clinic name for templates")
            updated_count += 1
        if variables.clinic_address:
            await service.set_clinic_config(clinic_id, "clinic_address", variables.clinic_address, "Clinic address for templates")
            updated_count += 1
        if variables.clinic_email:
            await service.set_clinic_config(clinic_id, "clinic_email", variables.clinic_email, "Clinic email for templates")
            updated_count += 1
        if variables.clinic_business_hours:
            await service.set_clinic_config(clinic_id, "business_hours", variables.clinic_business_hours, "Business hours for templates")
            updated_count += 1
        if variables.clinic_services:
            await service.set_clinic_config(clinic_id, "clinic_services", variables.clinic_services, "Services offered for templates")
            updated_count += 1
        if variables.clinic_insurance_plans:
            await service.set_clinic_config(clinic_id, "insurance_plans", variables.clinic_insurance_plans, "Insurance plans for templates")
            updated_count += 1
        if variables.clinic_pharmacy_phone:
            await service.set_clinic_config(clinic_id, "pharmacy_phone", variables.clinic_pharmacy_phone, "Pharmacy phone for templates")
            updated_count += 1
        
        logger.info(
            f"Updated {updated_count} template variable(s) for clinic {clinic_id}",
            LogCategory.CLINIC_MANAGEMENT,
            extra_data={"clinic_id": clinic_id, "updated_count": updated_count}
        )
        
        return SuccessResponse(
            success=True,
            message=f"Updated {updated_count} template variable(s) for clinic {clinic_id}"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.critical(
            f"Unexpected error updating clinic template variables: {e}",
            LogCategory.EXCEPTION,
            exception=e,
            extra_data={"clinic_id": clinic_id}
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while updating clinic template variables"
        )


@router.get("/{clinic_id}/template-preview", response_model=Dict[str, Any])
async def preview_clinic_templates(
    clinic_id: str = Query(..., min_length=3, max_length=64, description="Clinic ID"),
    db: AsyncSession = Depends(get_async_db)
):
    """
    Preview how templates look with clinic-specific data.
    
    Returns preview of common templates (greeting, goodbye) with clinic variables substituted.
    
    Args:
        clinic_id: Clinic ID to preview templates for
        db: Database session
        
    Returns:
        Dictionary with clinic_id, template_variables, and template previews
        
    Raises:
        HTTPException 404: Clinic not found
        HTTPException 500: Internal server error
    """
    try:
        logger.info(
            f"Previewing templates for clinic {clinic_id}",
            LogCategory.CLINIC_MANAGEMENT,
            extra_data={"clinic_id": clinic_id}
        )
        
        service = ClinicManagementService(db)
        clinic = await service.get_clinic(clinic_id)
        
        if not clinic:
            logger.warning(
                f"Clinic {clinic_id} not found for template preview",
                LogCategory.CLINIC_MANAGEMENT,
                extra_data={"clinic_id": clinic_id}
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Clinic {clinic_id} not found"
            )
        
        # Get template variables
        template_vars = await get_clinic_template_variables(clinic_id, db)
        
        # Get response templates service
        response_templates = get_response_templates()
        
        # Greeting template
        greeting_en = await response_templates.substitute_variables(
            IntentType.GREETING,
            LanguageCode.ENGLISH,
            {},
            clinic_id=clinic_id,
            db=db
        )
        greeting_es = await response_templates.substitute_variables(
            IntentType.GREETING,
            LanguageCode.SPANISH,
            {},
            clinic_id=clinic_id,
            db=db
        )
        
        # Goodbye template
        goodbye_en = await response_templates.substitute_variables(
            IntentType.GOODBYE,
            LanguageCode.ENGLISH,
            {},
            clinic_id=clinic_id,
            db=db
        )
        goodbye_es = await response_templates.substitute_variables(
            IntentType.GOODBYE,
            LanguageCode.SPANISH,
            {},
            clinic_id=clinic_id,
            db=db
        )
        
        logger.info(
            f"Generated template preview for clinic {clinic_id}",
            LogCategory.CLINIC_MANAGEMENT,
            extra_data={"clinic_id": clinic_id}
        )
        
        return {
            "clinic_id": clinic_id,
            "template_variables": template_vars,
            "previews": {
                "greeting": {
                    "en": greeting_en,
                    "es": greeting_es
                },
                "goodbye": {
                    "en": goodbye_en,
                    "es": goodbye_es
                }
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.critical(
            f"Unexpected error previewing clinic templates: {e}",
            LogCategory.EXCEPTION,
            exception=e,
            extra_data={"clinic_id": clinic_id}
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while previewing clinic templates"
        )
