"""
Clinic Template Variables Service
Loads clinic-specific template variables from multiple sources with priority:
1. Environment variables (primary - for containerized deployments)
2. Config file (if CLINIC_CONFIG_FILE env var is set)
3. SystemConfig table (fallback - for runtime customization via API)
4. Clinic model fields (fallback - only basic operational fields)
"""

import os
import json
from typing import Dict, Any, Optional, List
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

# Optional yaml support
try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False

from services.structured_logging import get_logger, LogCategory
from models.models import Clinic, Provider, SystemConfig

logger = get_logger("clinic_template_variables")


async def get_clinic_template_variables(clinic_id: Optional[str] = None, db: Optional[AsyncSession] = None) -> Dict[str, Any]:
    """
    Get clinic-specific template variables from multiple sources with priority order.
    
    Priority:
    1. Environment variables (CLINIC_NAME, CLINIC_ADDRESS, etc.)
    2. Config file (if CLINIC_CONFIG_FILE is set)
    3. SystemConfig table (for runtime customization)
    4. Clinic model basic fields (clinic_name, phone_number only)
    
    Args:
        clinic_id: Clinic ID (optional - if None, will check CLINIC_ID env var)
        db: Database session (optional)
        
    Returns:
        Dictionary with template variables: clinic_name, phone, address, hours, days,
        services, main_services, insurance_plans, pharmacy_phone, provider_names, provider_list
    """
    # If clinic_id not provided, try to get from CLINIC_ID env var
    if not clinic_id:
        clinic_id = os.getenv("CLINIC_ID")
        if clinic_id:
            logger.info(f"Using CLINIC_ID from environment: {clinic_id}", LogCategory.CONFIG)
    
    # If still no clinic_id, return defaults
    if not clinic_id:
        logger.warning("No clinic_id provided and CLINIC_ID env var not set, returning default variables", LogCategory.CONFIG)
        return _get_default_variables()
    
    variables = {}
    
    # Priority 1: Environment variables
    env_vars = _load_from_environment()
    if env_vars:
        logger.info(f"Loaded clinic template variables from environment for clinic {clinic_id}", LogCategory.CONFIG)
        variables.update(env_vars)
    
    # Priority 2: Config file (if CLINIC_CONFIG_FILE is set)
    config_file = os.getenv("CLINIC_CONFIG_FILE")
    if config_file and Path(config_file).exists():
        file_vars = _load_from_config_file(config_file)
        if file_vars:
            logger.info(f"Loaded clinic template variables from config file {config_file} for clinic {clinic_id}", LogCategory.CONFIG)
            # Merge file vars, but don't override env vars
            for key, value in file_vars.items():
                if key not in variables:
                    variables[key] = value
    
    # Priority 3: SystemConfig table (fallback)
    if db:
        db_vars = await _load_from_system_config(clinic_id, db)
        if db_vars:
            logger.info(f"Loaded clinic template variables from SystemConfig for clinic {clinic_id}", LogCategory.CONFIG)
            # Merge DB vars, but don't override env vars or file vars
            for key, value in db_vars.items():
                if key not in variables:
                    variables[key] = value
    
    # Priority 4: Clinic model basic fields (operational data)
    if db:
        clinic_vars = await _load_from_clinic_model(clinic_id, db)
        if clinic_vars:
            # Merge clinic model vars, but don't override existing
            for key, value in clinic_vars.items():
                if key not in variables:
                    variables[key] = value
    
    # Always load provider names from database (operational data)
    if db:
        provider_vars = await _load_provider_names(clinic_id, db)
        variables.update(provider_vars)
    
    # Set defaults for missing required variables
    _set_defaults(variables)
    
    # Validate required variables
    _validate_variables(variables, clinic_id)
    
    return variables


def _load_from_environment() -> Dict[str, Any]:
    """Load clinic template variables from environment variables."""
    vars = {}
    
    if os.getenv("CLINIC_NAME"):
        vars["clinic_name"] = os.getenv("CLINIC_NAME")
    
    if os.getenv("CLINIC_ADDRESS"):
        vars["address"] = os.getenv("CLINIC_ADDRESS")
    
    if os.getenv("CLINIC_EMAIL"):
        vars["email"] = os.getenv("CLINIC_EMAIL")
    
    if os.getenv("CLINIC_BUSINESS_HOURS"):
        hours_str = os.getenv("CLINIC_BUSINESS_HOURS")
        vars["hours"] = hours_str
        # Parse hours to extract days
        vars["days"] = _parse_days_from_hours(hours_str)
    
    if os.getenv("CLINIC_SERVICES"):
        services = os.getenv("CLINIC_SERVICES")
        vars["services"] = services
        # Use first few services as main_services
        services_list = [s.strip() for s in services.split(",")]
        vars["main_services"] = ", ".join(services_list[:3]) if len(services_list) > 3 else services
    
    if os.getenv("CLINIC_INSURANCE_PLANS"):
        vars["insurance_plans"] = os.getenv("CLINIC_INSURANCE_PLANS")
    
    if os.getenv("CLINIC_PHARMACY_PHONE"):
        vars["pharmacy_phone"] = os.getenv("CLINIC_PHARMACY_PHONE")
    
    return vars


def _load_from_config_file(config_file_path: str) -> Dict[str, Any]:
    """Load clinic template variables from JSON or YAML config file."""
    try:
        path = Path(config_file_path)
        if not path.exists():
            logger.warning(f"Config file not found: {config_file_path}", LogCategory.CONFIG)
            return {}
        
        with open(path, 'r') as f:
            if path.suffix.lower() in ['.yaml', '.yml']:
                if not YAML_AVAILABLE:
                    logger.warning(f"YAML support not available. Install pyyaml to use YAML config files.", LogCategory.CONFIG)
                    return {}
                config = yaml.safe_load(f)
            else:
                config = json.load(f)
        
        # Extract clinic template variables from config
        vars = {}
        clinic_config = config.get("clinic", {})
        
        if clinic_config.get("clinic_name"):
            vars["clinic_name"] = clinic_config["clinic_name"]
        
        if clinic_config.get("address"):
            vars["address"] = clinic_config["address"]
        
        if clinic_config.get("email"):
            vars["email"] = clinic_config["email"]
        
        if clinic_config.get("business_hours"):
            hours_str = clinic_config["business_hours"]
            vars["hours"] = hours_str
            vars["days"] = _parse_days_from_hours(hours_str)
        
        if clinic_config.get("services"):
            services = clinic_config["services"]
            vars["services"] = services if isinstance(services, str) else ", ".join(services)
            services_list = services if isinstance(services, list) else [s.strip() for s in services.split(",")]
            vars["main_services"] = ", ".join(services_list[:3]) if len(services_list) > 3 else vars["services"]
        
        if clinic_config.get("insurance_plans"):
            insurance = clinic_config["insurance_plans"]
            vars["insurance_plans"] = insurance if isinstance(insurance, str) else ", ".join(insurance)
        
        if clinic_config.get("pharmacy_phone"):
            vars["pharmacy_phone"] = clinic_config["pharmacy_phone"]
        
        return vars
        
    except Exception as e:
        logger.error(f"Error loading config file {config_file_path}: {e}", LogCategory.CONFIG)
        return {}


async def _load_from_system_config(clinic_id: str, db: AsyncSession) -> Dict[str, Any]:
    """Load clinic template variables from SystemConfig table."""
    vars = {}
    
    try:
        # SystemConfig uses pattern: {config_key}_{clinic_id}
        config_keys = [
            "clinic_name", "clinic_address", "clinic_email", "business_hours",
            "clinic_services", "insurance_plans", "pharmacy_phone"
        ]
        
        for key in config_keys:
            full_key = f"{key}_{clinic_id}"
            # Check if is_deleted attribute exists (for backward compatibility)
            filter_conditions = [SystemConfig.config_key == full_key]
            if hasattr(SystemConfig, 'is_deleted'):
                filter_conditions.append(SystemConfig.is_deleted == 'no')
            
            config_result = await db.execute(select(SystemConfig).where(*filter_conditions))
            config = config_result.scalar_one_or_none()
            
            if config:
                if key == "clinic_name":
                    vars["clinic_name"] = config.config_value
                elif key == "clinic_address":
                    vars["address"] = config.config_value
                elif key == "clinic_email":
                    vars["email"] = config.config_value
                elif key == "business_hours":
                    vars["hours"] = config.config_value
                    vars["days"] = _parse_days_from_hours(config.config_value)
                elif key == "clinic_services":
                    vars["services"] = config.config_value
                    services_list = [s.strip() for s in config.config_value.split(",")]
                    vars["main_services"] = ", ".join(services_list[:3]) if len(services_list) > 3 else config.config_value
                elif key == "insurance_plans":
                    vars["insurance_plans"] = config.config_value
                elif key == "pharmacy_phone":
                    vars["pharmacy_phone"] = config.config_value
        
        # Also check for legacy keys without clinic_id suffix
        # Check if is_deleted attribute exists (for backward compatibility)
        filter_conditions = [
            SystemConfig.config_key.in_(["office_hours", "days_open", "main_services", "insurance_plans", "pharmacy_phone"])
        ]
        if hasattr(SystemConfig, 'is_deleted'):
            filter_conditions.append(SystemConfig.is_deleted == 'no')
        
        legacy_configs_result = await db.execute(select(SystemConfig).where(*filter_conditions))
        legacy_configs = list(legacy_configs_result.scalars().all())
        
        for config in legacy_configs:
            if config.config_key == "office_hours" and "hours" not in vars:
                vars["hours"] = config.config_value
                vars["days"] = _parse_days_from_hours(config.config_value)
            elif config.config_key == "days_open" and "days" not in vars:
                vars["days"] = config.config_value
            elif config.config_key == "main_services" and "main_services" not in vars:
                vars["main_services"] = config.config_value
            elif config.config_key == "insurance_plans" and "insurance_plans" not in vars:
                vars["insurance_plans"] = config.config_value
            elif config.config_key == "pharmacy_phone" and "pharmacy_phone" not in vars:
                vars["pharmacy_phone"] = config.config_value
                
    except Exception as e:
        logger.error(f"Error loading from SystemConfig for clinic {clinic_id}: {e}", LogCategory.CONFIG)
    
    return vars


async def _load_from_clinic_model(clinic_id: str, db: AsyncSession) -> Dict[str, Any]:
    """Load basic clinic fields from Clinic model (operational data only)."""
    vars = {}
    
    try:
        clinic_result = await db.execute(select(Clinic).where(Clinic.clinic_id == clinic_id))
        clinic = clinic_result.scalar_one_or_none()
        if clinic:
            vars["clinic_name"] = clinic.clinic_name
            vars["phone"] = clinic.phone_number
    except Exception as e:
        logger.error(f"Error loading from Clinic model for clinic {clinic_id}: {e}", LogCategory.CONFIG)
    
    return vars


async def _load_provider_names(clinic_id: str, db: AsyncSession) -> Dict[str, Any]:
    """Load provider names from Provider model (operational data)."""
    vars = {}
    
    try:
        # Get providers associated with this clinic
        # Providers can be associated via clinic_id or through many-to-many relationship
        # Check if is_deleted attribute exists (for backward compatibility)
        filter_conditions = [
            Provider.clinic_id == clinic_id,
            Provider.is_available == 'yes'
        ]
        if hasattr(Provider, 'is_deleted'):
            filter_conditions.append(Provider.is_deleted == 'no')
        
        providers_result = await db.execute(select(Provider).where(*filter_conditions))
        providers = list(providers_result.scalars().all())
        
        # Also check many-to-many relationship and combine results
        from models.models import provider_clinics
        many_to_many_conditions = [
            provider_clinics.c.clinic_id == clinic_id,
            Provider.is_available == 'yes'
        ]
        if hasattr(Provider, 'is_deleted'):
            many_to_many_conditions.append(Provider.is_deleted == 'no')
        
        many_to_many_result = await db.execute(
            select(Provider).join(provider_clinics).where(*many_to_many_conditions)
        )
        many_to_many_providers = list(many_to_many_result.scalars().all())
        
        # Combine results and remove duplicates (by provider_id)
        provider_dict = {p.provider_id: p for p in providers}
        for p in many_to_many_providers:
            if p.provider_id not in provider_dict:
                provider_dict[p.provider_id] = p
        
        providers = list(provider_dict.values())
        
        if providers:
            # Build provider names using title and specialty (non-PHI fields)
            provider_names = []
            for provider in providers:
                # Use title and specialty for display (non-PHI)
                if provider.title and provider.specialty:
                    provider_names.append(f"{provider.title} ({provider.specialty})")
                elif provider.title:
                    provider_names.append(provider.title)
                elif provider.specialty:
                    provider_names.append(provider.specialty)
                else:
                    # Fallback to provider ID if no title/specialty
                    provider_names.append(f"Provider {provider.provider_id[-4:]}")
            
            vars["provider_names"] = ", ".join(provider_names)
            vars["provider_list"] = provider_names
        else:
            vars["provider_names"] = "our providers"
            vars["provider_list"] = []
            
    except Exception as e:
        logger.error(f"Error loading provider names for clinic {clinic_id}: {e}", LogCategory.CONFIG)
        vars["provider_names"] = "our providers"
        vars["provider_list"] = []
    
    return vars


def _parse_days_from_hours(hours_str: str) -> str:
    """Parse days from business hours string."""
    if not hours_str:
        return "Monday through Friday"
    
    # Try to extract days from common formats
    hours_lower = hours_str.lower()
    
    if "monday" in hours_lower or "mon" in hours_lower:
        if "saturday" in hours_lower or "sat" in hours_lower:
            return "Monday through Saturday"
        return "Monday through Friday"
    elif "tuesday" in hours_lower or "tue" in hours_lower:
        return "Tuesday through Friday"
    elif "wednesday" in hours_lower or "wed" in hours_lower:
        return "Wednesday through Friday"
    
    return "Monday through Friday"  # Default


def _get_default_variables() -> Dict[str, Any]:
    """Get default template variables when clinic_id is not available."""
    return {
        "clinic_name": "our clinic",
        "phone": "our main number",
        "address": "our main location",
        "hours": "Monday-Friday 9AM-5PM",
        "days": "Monday through Friday",
        "services": "comprehensive healthcare services",
        "main_services": "general medicine, preventive care, and specialized treatments",
        "insurance_plans": "Blue Cross, Aetna, Cigna, and Medicare",
        "pharmacy_phone": "our pharmacy",
        "provider_names": "our providers",
        "provider_list": []
    }


def _set_defaults(variables: Dict[str, Any]) -> None:
    """Set default values for missing variables."""
    if "clinic_name" not in variables:
        variables["clinic_name"] = "our clinic"
    if "phone" not in variables:
        variables["phone"] = "our main number"
    if "address" not in variables:
        variables["address"] = "our main location"
    if "hours" not in variables:
        variables["hours"] = "Monday-Friday 9AM-5PM"
    if "days" not in variables:
        variables["days"] = "Monday through Friday"
    if "services" not in variables:
        variables["services"] = "comprehensive healthcare services"
    if "main_services" not in variables:
        variables["main_services"] = "general medicine, preventive care, and specialized treatments"
    if "insurance_plans" not in variables:
        variables["insurance_plans"] = "Blue Cross, Aetna, Cigna, and Medicare"
    if "pharmacy_phone" not in variables:
        variables["pharmacy_phone"] = "our pharmacy"
    if "provider_names" not in variables:
        variables["provider_names"] = "our providers"
    if "provider_list" not in variables:
        variables["provider_list"] = []


def _validate_variables(variables: Dict[str, Any], clinic_id: Optional[str] = None) -> None:
    """Validate that required variables exist and are valid."""
    clinic_id_str = clinic_id or "unknown"
    required = ["clinic_name", "phone"]
    
    for key in required:
        if not variables.get(key):
            logger.warning(f"Missing required template variable '{key}' for clinic {clinic_id_str}", LogCategory.CONFIG)
    
    # Validate phone format (basic check)
    phone = variables.get("phone", "")
    if phone and not phone.startswith("+") and not phone.startswith("("):
        logger.warning(f"Phone number format may be invalid for clinic {clinic_id_str}: {phone}", LogCategory.CONFIG)

