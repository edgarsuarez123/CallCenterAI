"""
Clinic Management API Routes
REST endpoints for clinic operations including creation, updates, and configuration.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime

from services.database import get_db
from services.clinic_management import ClinicManagementService
from models.schemas import (
    ClinicCreateRequest, ClinicUpdateRequest, ClinicResponse,
    ClinicSearchRequest, SystemConfigCreateRequest, SystemConfigResponse,
    ClinicLicenseResponse, SuccessResponse, ErrorResponse
)
from models.models import Clinic

router = APIRouter(prefix="/v1/clinics", tags=["clinic-management"])


@router.post("/", response_model=ClinicResponse, status_code=status.HTTP_201_CREATED)
def create_clinic(
    clinic_data: ClinicCreateRequest,
    db: Session = Depends(get_db)
):
    """
    Create a new clinic with license and initial configuration.
    
    This endpoint creates a complete clinic setup including:
    - Clinic record with basic information
    - License with subscription tier limits
    - Initial system configurations
    - Audit trail for creation
    """
    try:
        service = ClinicManagementService(db)
        clinic = service.create_clinic(clinic_data)
        return ClinicResponse.from_orm(clinic)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create clinic: {str(e)}"
        )


@router.get("/", response_model=List[ClinicResponse])
def list_clinics(
    search: ClinicSearchRequest = Depends(),
    db: Session = Depends(get_db)
):
    """
    List clinics with optional filtering and pagination.
    
    Supports filtering by:
    - Clinic name (partial match)
    - Phone number (exact match)
    - Subscription tier
    - Active status
    
    Includes pagination with limit and offset.
    """
    try:
        service = ClinicManagementService(db)
        clinics = service.list_clinics(search)
        return [ClinicResponse.from_orm(clinic) for clinic in clinics]
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list clinics: {str(e)}"
        )


@router.get("/{clinic_id}", response_model=ClinicResponse)
def get_clinic(
    clinic_id: str,
    db: Session = Depends(get_db)
):
    """
    Get a specific clinic by ID.
    
    Returns complete clinic information including:
    - Basic clinic details
    - Subscription tier
    - Configuration settings
    - License information
    """
    try:
        service = ClinicManagementService(db)
        clinic = service.get_clinic(clinic_id)
        
        if not clinic:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Clinic {clinic_id} not found"
            )
        
        return ClinicResponse.from_orm(clinic)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get clinic: {str(e)}"
        )


@router.put("/{clinic_id}", response_model=ClinicResponse)
def update_clinic(
    clinic_id: str,
    updates: ClinicUpdateRequest,
    db: Session = Depends(get_db)
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
    """
    try:
        service = ClinicManagementService(db)
        clinic = service.update_clinic(clinic_id, updates)
        
        if not clinic:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Clinic {clinic_id} not found"
            )
        
        return ClinicResponse.from_orm(clinic)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update clinic: {str(e)}"
        )


@router.delete("/{clinic_id}", response_model=SuccessResponse)
def deactivate_clinic(
    clinic_id: str,
    db: Session = Depends(get_db)
):
    """
    Deactivate a clinic (soft delete).
    
    This operation:
    - Sets clinic status to inactive
    - Preserves all data for audit purposes
    - Logs the deactivation
    - Does not delete any records
    """
    try:
        service = ClinicManagementService(db)
        success = service.deactivate_clinic(clinic_id)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Clinic {clinic_id} not found"
            )
        
        return SuccessResponse(
            message=f"Clinic {clinic_id} deactivated successfully"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to deactivate clinic: {str(e)}"
        )


@router.get("/{clinic_id}/license", response_model=ClinicLicenseResponse)
def get_clinic_license(
    clinic_id: str,
    db: Session = Depends(get_db)
):
    """
    Get clinic license information.
    
    Returns license details including:
    - Subscription tier and limits
    - Current usage statistics
    - Billing information
    - License status
    """
    try:
        service = ClinicManagementService(db)
        license = service.get_clinic_license(clinic_id)
        
        if not license:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"License for clinic {clinic_id} not found"
            )
        
        return ClinicLicenseResponse.from_orm(license)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get clinic license: {str(e)}"
        )


@router.put("/{clinic_id}/license", response_model=SuccessResponse)
def update_clinic_license(
    clinic_id: str,
    tier: str,
    db: Session = Depends(get_db)
):
    """
    Update clinic subscription tier.
    
    This operation:
    - Updates the clinic's subscription tier
    - Adjusts license limits based on new tier
    - Updates billing information
    - Logs all changes
    """
    try:
        service = ClinicManagementService(db)
        success = service.update_clinic_license(clinic_id, tier)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Clinic {clinic_id} not found"
            )
        
        return SuccessResponse(
            message=f"Clinic {clinic_id} license updated to {tier} tier"
        )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update clinic license: {str(e)}"
        )


@router.get("/{clinic_id}/config/{config_key}", response_model=dict)
def get_clinic_config(
    clinic_id: str,
    config_key: str,
    db: Session = Depends(get_db)
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
    """
    try:
        service = ClinicManagementService(db)
        config_value = service.get_clinic_config(clinic_id, config_key)
        
        if config_value is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Configuration {config_key} not found for clinic {clinic_id}"
            )
        
        return {
            "clinic_id": clinic_id,
            "config_key": config_key,
            "config_value": config_value
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get clinic configuration: {str(e)}"
        )


@router.put("/{clinic_id}/config/{config_key}", response_model=SuccessResponse)
def set_clinic_config(
    clinic_id: str,
    config_key: str,
    config_data: SystemConfigCreateRequest,
    db: Session = Depends(get_db)
):
    """
    Set a configuration value for a clinic.
    
    Creates or updates a clinic-specific configuration.
    The configuration key will be prefixed with the clinic ID
    to ensure isolation between clinics.
    """
    try:
        service = ClinicManagementService(db)
        success = service.set_clinic_config(
            clinic_id, config_key, config_data.config_value, config_data.description
        )
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to set clinic configuration"
            )
        
        return SuccessResponse(
            message=f"Configuration {config_key} set for clinic {clinic_id}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to set clinic configuration: {str(e)}"
        )


@router.get("/{clinic_id}/stats", response_model=dict)
def get_clinic_stats(
    clinic_id: str,
    db: Session = Depends(get_db)
):
    """
    Get clinic statistics and usage information.
    
    Returns comprehensive statistics including:
    - Provider count
    - Appointment statistics
    - Call volume
    - License usage
    - Configuration summary
    """
    try:
        service = ClinicManagementService(db)
        clinic = service.get_clinic(clinic_id)
        
        if not clinic:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Clinic {clinic_id} not found"
            )
        
        # Get license information
        license = service.get_clinic_license(clinic_id)
        
        # Get common configurations
        emergency_keywords = service.get_clinic_config(clinic_id, "emergency_keywords")
        business_hours = service.get_clinic_config(clinic_id, "business_hours")
        google_calendar_enabled = service.get_clinic_config(clinic_id, "google_calendar_enabled")
        
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
            "created_at": clinic.created_at,
            "updated_at": clinic.updated_at
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get clinic statistics: {str(e)}"
        )
