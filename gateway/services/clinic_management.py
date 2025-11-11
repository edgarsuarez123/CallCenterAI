"""
Clinic Management Service
Handles all business logic for clinic operations including creation, updates, and configuration.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone, timedelta
import hashlib

# Atlantic Standard Time (UTC-4)
AST = timezone(timedelta(hours=-4))

from models.models import Clinic, ClinicLicense, SystemConfig
from models.schemas import (
    ClinicCreateRequest, ClinicUpdateRequest, ClinicSearchRequest
)
from services.crypto import make_ulid_token
from services.audit_utils import log_audit_trail


class ClinicManagementService:
    """Service for managing clinic operations and configuration."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create_clinic(self, clinic_data: ClinicCreateRequest, clinic_id: Optional[str] = None) -> Clinic:
        """
        Create a new clinic with license and initial configuration.
        
        Args:
            clinic_data: Clinic creation request data
            clinic_id: Optional clinic ID (if not provided, will be generated from phone number)
            
        Returns:
            Created clinic instance
            
        Raises:
            ValueError: If clinic data is invalid
            IntegrityError: If clinic already exists
        """
        try:
            # Use provided clinic_id or generate unique clinic ID
            if not clinic_id:
                clinic_id = self._generate_clinic_id(clinic_data.phone_number)
            
            # Create clinic record
            clinic = Clinic(
                clinic_id=clinic_id,
                clinic_name=clinic_data.clinic_name,
                phone_number=clinic_data.phone_number,
                timezone=clinic_data.timezone,
                default_language=clinic_data.default_language,
                supported_languages=clinic_data.supported_languages,
                ehr_system=clinic_data.ehr_system,
                ehr_api_endpoint=clinic_data.ehr_api_endpoint,
                ehr_credentials_vault_key=clinic_data.ehr_credentials_vault_key,
                max_concurrent_calls=clinic_data.max_concurrent_calls,
                queue_timeout_seconds=clinic_data.queue_timeout_seconds,
                subscription_tier=clinic_data.subscription_tier.value,
                is_active="yes"
            )
            
            self.db.add(clinic)
            await self.db.flush()  # Get the clinic_id for license creation
            
            # Create license
            license_data = self._get_license_config(clinic_data.subscription_tier.value)
            # Use same 'now' for all billing cycle calculations to avoid race conditions
            now = datetime.now(AST)
            license = ClinicLicense(
                license_id=f"LICENSE_{clinic_id}",
                clinic_id=clinic_id,
                tier=license_data['tier'],
                max_calls_per_month=license_data['max_calls_per_month'],
                max_concurrent_calls=license_data['max_concurrent_calls'],
                max_providers=license_data['max_providers'],
                monthly_fee_usd=license_data['monthly_fee_usd'],
                license_status="active",
                current_month_calls=0,
                billing_cycle_start=self._get_billing_cycle_start(now),
                billing_cycle_end=self._get_billing_cycle_end(now),
                next_billing_date=self._get_next_billing_date(now)
            )
            
            self.db.add(license)
            
            # Create initial system configurations
            await self._create_initial_configs(clinic_id, clinic_data)
            
            # Log the creation
            await self._log_audit("clinics", clinic_id, "CREATE", None, clinic_data.model_dump())
            
            # Commit with error handling
            try:
                await self.db.commit()
            except Exception as commit_error:
                await self.db.rollback()
                raise ValueError(f"Failed to commit clinic creation: {str(commit_error)}")
            
            return clinic
            
        except IntegrityError as e:
            await self.db.rollback()
            raise ValueError(f"Clinic with phone number {clinic_data.phone_number} already exists: {str(e)}")
        except ValueError:
            # Re-raise ValueError as-is
            raise
        except Exception as e:
            await self.db.rollback()
            raise ValueError(f"Failed to create clinic: {str(e)}")
    
    async def get_clinic(self, clinic_id: str) -> Optional[Clinic]:
        """Get clinic by ID."""
        result = await self.db.execute(select(Clinic).where(Clinic.clinic_id == clinic_id))
        return result.scalar_one_or_none()
    
    async def get_clinic_by_phone(self, phone_number: str) -> Optional[str]:
        """
        Get clinic ID from phone number.
        
        Args:
            phone_number: The called phone number
            
        Returns:
            Clinic ID or None if not found
        """
        from services.structured_logging import get_logger, LogCategory
        logger = get_logger("clinic_management")
        
        # Validate input
        if not phone_number or not isinstance(phone_number, str) or not phone_number.strip():
            logger.warning(f"Invalid phone number provided: {phone_number}", LogCategory.CLINIC_MANAGEMENT)
            return None
        
        # Normalize phone number (remove spaces, dashes, parentheses)
        normalized_phone = phone_number.strip().replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
        
        # Query database (with error handling)
        # Try both original and normalized phone number for matching
        try:
            clinic_result = await self.db.execute(select(Clinic).where(
                (Clinic.phone_number == phone_number) | (Clinic.phone_number == normalized_phone),
                Clinic.is_deleted == 'no'
            ))
            clinic = clinic_result.scalar_one_or_none()
            
            if clinic and clinic.clinic_id:
                logger.info(f"Mapped phone {phone_number} to clinic {clinic.clinic_id}", LogCategory.CLINIC_MANAGEMENT)
                return clinic.clinic_id
        except Exception as e:
            logger.error(f"Error querying clinic for phone {phone_number}: {e}", LogCategory.CLINIC_MANAGEMENT, exception=e)
            return None
        
        logger.warning(f"No clinic found for phone {phone_number}", LogCategory.CLINIC_MANAGEMENT)
        return None
    
    async def update_clinic(self, clinic_id: str, updates: ClinicUpdateRequest) -> Optional[Clinic]:
        """
        Update clinic information.
        
        Args:
            clinic_id: Clinic ID to update
            updates: Update request data
            
        Returns:
            Updated clinic instance or None if not found
        """
        clinic = await self.get_clinic(clinic_id)
        if not clinic:
            return None
        
        # Store old values for audit
        old_values = {
            "clinic_name": clinic.clinic_name,
            "phone_number": clinic.phone_number,
            "timezone": clinic.timezone,
            "subscription_tier": clinic.subscription_tier,
            "is_active": clinic.is_active
        }
        
        # Update fields
        update_data = updates.dict(exclude_unset=True)
        for field, value in update_data.items():
            if hasattr(clinic, field):
                setattr(clinic, field, value)
        
        clinic.updated_at = datetime.now(AST)
        
        # Log the update
        await self._log_audit("clinics", clinic_id, "UPDATE", old_values, update_data)
        
        # Commit with error handling
        try:
            await self.db.commit()
        except Exception as commit_error:
            await self.db.rollback()
            raise ValueError(f"Failed to commit clinic update: {str(commit_error)}")
        
        return clinic
    
    async def list_clinics(self, search: ClinicSearchRequest) -> List[Clinic]:
        """
        List clinics with optional filtering and pagination.
        
        Args:
            search: Search criteria and pagination
            
        Returns:
            List of matching clinics
        """
        stmt = select(Clinic).where(Clinic.is_deleted == 'no')
        
        # Apply filters
        if search.clinic_name:
            stmt = stmt.where(Clinic.clinic_name.ilike(f"%{search.clinic_name}%"))
        
        if search.phone_number:
            stmt = stmt.where(Clinic.phone_number == search.phone_number)
        
        if search.subscription_tier:
            stmt = stmt.where(Clinic.subscription_tier == search.subscription_tier.value)
        
        if search.is_active:
            stmt = stmt.where(Clinic.is_active == search.is_active.value)
        
        # Apply pagination
        stmt = stmt.offset(search.offset).limit(search.limit)
        
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
    
    async def deactivate_clinic(self, clinic_id: str) -> bool:
        """
        Deactivate a clinic (soft delete).
        
        Args:
            clinic_id: Clinic ID to deactivate
            
        Returns:
            True if successful, False if clinic not found
        """
        clinic = await self.get_clinic(clinic_id)
        if not clinic:
            return False
        
        old_values = {"is_active": clinic.is_active}
        clinic.is_active = "no"
        clinic.updated_at = datetime.now(AST)
        
        # Log the deactivation
        await self._log_audit("clinics", clinic_id, "DEACTIVATE", old_values, {"is_active": "no"})
        
        # Commit with error handling
        try:
            await self.db.commit()
        except Exception as commit_error:
            await self.db.rollback()
            raise ValueError(f"Failed to commit clinic deactivation: {str(commit_error)}")
        
        return True
    
    async def get_clinic_license(self, clinic_id: str) -> Optional[ClinicLicense]:
        """Get clinic license information."""
        result = await self.db.execute(select(ClinicLicense).where(ClinicLicense.clinic_id == clinic_id))
        return result.scalar_one_or_none()
    
    async def update_clinic_license(self, clinic_id: str, tier: str) -> bool:
        """
        Update clinic subscription tier and license.
        
        Args:
            clinic_id: Clinic ID
            tier: New subscription tier
            
        Returns:
            True if successful, False if clinic not found
        """
        try:
            # Use row-level locking to prevent race conditions
            clinic_stmt = select(Clinic).where(Clinic.clinic_id == clinic_id).with_for_update()
            clinic_result = await self.db.execute(clinic_stmt)
            clinic = clinic_result.scalar_one_or_none()
            
            license_stmt = select(ClinicLicense).where(ClinicLicense.clinic_id == clinic_id).with_for_update()
            license_result = await self.db.execute(license_stmt)
            license = license_result.scalar_one_or_none()
            
            if not clinic or not license:
                return False
            
            # Update clinic tier
            old_clinic_tier = clinic.subscription_tier
            clinic.subscription_tier = tier
            clinic.updated_at = datetime.now(AST)
            
            # Update license with new tier configuration
            license_data = self._get_license_config(tier)
            old_license_values = {
                "tier": license.tier,
                "max_calls_per_month": license.max_calls_per_month,
                "max_concurrent_calls": license.max_concurrent_calls,
                "max_providers": license.max_providers,
                "monthly_fee_usd": license.monthly_fee_usd
            }
            
            license.tier = license_data['tier']
            license.max_calls_per_month = license_data['max_calls_per_month']
            license.max_concurrent_calls = license_data['max_concurrent_calls']
            license.max_providers = license_data['max_providers']
            license.monthly_fee_usd = license_data['monthly_fee_usd']
            license.updated_at = datetime.now(AST)
            
            # Log the changes
            await self._log_audit("clinics", clinic_id, "UPDATE_TIER", 
                           {"subscription_tier": old_clinic_tier}, 
                           {"subscription_tier": tier})
            await self._log_audit("clinic_licenses", license.license_id, "UPDATE", 
                           old_license_values, license_data)
            
            # Commit with error handling
            try:
                await self.db.commit()
            except Exception as commit_error:
                await self.db.rollback()
                raise ValueError(f"Failed to commit license update: {str(commit_error)}")
            
            return True
        except ValueError:
            # Re-raise ValueError as-is
            raise
        except Exception as e:
            await self.db.rollback()
            from services.structured_logging import get_logger, LogCategory
            logger = get_logger("clinic_management")
            logger.error(
                f"Failed to update clinic license for {clinic_id}: {e}",
                LogCategory.CLINIC_MANAGEMENT,
                exception=e
            )
            raise ValueError(f"Failed to update clinic license: {str(e)}")
    
    async def get_clinic_config(self, clinic_id: str, config_key: str) -> Optional[str]:
        """Get a specific configuration value for a clinic."""
        full_key = f"{config_key}_{clinic_id}"
        result = await self.db.execute(select(SystemConfig).where(SystemConfig.config_key == full_key))
        config = result.scalar_one_or_none()
        return config.config_value if config is not None else None
    
    async def set_clinic_config(self, clinic_id: str, config_key: str, config_value: str, description: str = None) -> bool:
        """
        Set a configuration value for a clinic.
        
        Args:
            clinic_id: Clinic ID
            config_key: Configuration key
            config_value: Configuration value
            description: Optional description
            
        Returns:
            True if successful
        """
        full_config_key = f"{config_key}_{clinic_id}"
        
        # Check if config exists
        result = await self.db.execute(select(SystemConfig).where(SystemConfig.config_key == full_config_key))
        existing_config = result.scalar_one_or_none()
        
        if existing_config:
            # Update existing
            old_value = existing_config.config_value
            existing_config.config_value = config_value
            existing_config.description = description or existing_config.description
            existing_config.updated_at = datetime.now(AST)
            
            await self._log_audit("system_config", existing_config.config_id, "UPDATE",
                           {"config_value": old_value}, {"config_value": config_value})
        else:
            # Create new
            config = SystemConfig(
                config_id=f"CONFIG_{make_ulid_token('CONFIG')[:12]}",
                config_key=full_config_key,
                config_value=config_value,
                description=description or f"Configuration for {config_key}"
            )
            self.db.add(config)
            
            await self._log_audit("system_config", config.config_id, "CREATE", None, {
                "config_key": config.config_key,
                "config_value": config.config_value,
                "description": config.description
            })
        
        # Commit with error handling
        try:
            await self.db.commit()
        except Exception as commit_error:
            await self.db.rollback()
            raise ValueError(f"Failed to commit system config update: {str(commit_error)}")
        
        return True
    
    def _generate_clinic_id(self, phone_number: str) -> str:
        """Generate unique clinic ID from phone number."""
        # Use a hash of the phone number to ensure uniqueness
        phone_hash = hashlib.md5(phone_number.encode()).hexdigest()[:8]
        unique_token = make_ulid_token('CLINIC')[:8]
        return f"CLINIC_{phone_hash}_{unique_token}"
    
    def _get_license_config(self, tier: str) -> Dict[str, Any]:
        """Get license configuration based on tier."""
        # Import from centralized config
        try:
            from clinic_config import get_tier_limits
            return get_tier_limits(tier)
        except ImportError:
            # Fallback to hardcoded config if clinic_config not available
            configs = {
                'basic': {
                    'tier': 'basic',
                    'max_calls_per_month': 500,
                    'max_concurrent_calls': 5,
                    'max_providers': 5,
                    'monthly_fee_usd': 199.0
                },
                'professional': {
                    'tier': 'professional',
                    'max_calls_per_month': 2000,
                    'max_concurrent_calls': 15,
                    'max_providers': 20,
                    'monthly_fee_usd': 599.0
                },
                'enterprise': {
                    'tier': 'enterprise',
                    'max_calls_per_month': None,  # unlimited
                    'max_concurrent_calls': 50,
                    'max_providers': None,  # unlimited
                    'monthly_fee_usd': 1499.0
                }
            }
            return configs.get(tier, configs['basic'])
    
    def _get_billing_cycle_start(self, now: Optional[datetime] = None) -> datetime:
        """Get start of current billing cycle, optionally using a specific time to avoid race conditions."""
        if now is None:
            now = datetime.now(AST)
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    def _get_billing_cycle_end(self, now: Optional[datetime] = None) -> datetime:
        """Get end of current billing cycle, using same 'now' to avoid race conditions."""
        if now is None:
            now = datetime.now(AST)
        start = self._get_billing_cycle_start(now)
        if start.month == 12:
            return start.replace(year=start.year + 1, month=1) - timedelta(days=1)
        else:
            return start.replace(month=start.month + 1) - timedelta(days=1)
    
    def _get_next_billing_date(self, now: Optional[datetime] = None) -> datetime:
        """Get next billing date, optionally using a specific time to avoid race conditions."""
        start = self._get_billing_cycle_start(now)
        if start.month == 12:
            return start.replace(year=start.year + 1, month=1)
        else:
            return start.replace(month=start.month + 1)
    
    async def _create_initial_configs(self, clinic_id: str, clinic_data: ClinicCreateRequest):
        """Create initial system configurations for a new clinic."""
        initial_configs = [
            {
                "key": "emergency_keywords",
                "value": "emergency,urgent,chest pain,heart attack,stroke,bleeding,unconscious,can't breathe",
                "description": "Emergency detection keywords"
            },
            {
                "key": "business_hours",
                "value": "MON-FRI:08:00-17:00,SAT:09:00-13:00,SUN:CLOSED",
                "description": "Default business hours"
            },
            {
                "key": "ai_model",
                "value": "gpt-4",
                "description": "AI model configuration"
            },
            {
                "key": "voice_settings",
                "value": f"{clinic_data.default_language}-US-AriaNeural",
                "description": "Voice synthesis settings"
            },
            {
                "key": "google_calendar_enabled",
                "value": "yes",
                "description": "Enable Google Calendar integration"
            }
        ]
        
        for config in initial_configs:
            await self.set_clinic_config(
                clinic_id=clinic_id,
                config_key=config["key"],
                config_value=config["value"],
                description=config["description"]
            )
    
    async def _log_audit(self, table_name: str, record_id: str, action_type: str, 
                   old_values: Optional[Dict], new_values: Optional[Dict]):
        """Log audit trail for changes."""
        await log_audit_trail(
            self.db,
            table_name=table_name,
            record_id=record_id,
            action_type=action_type,
            old_values=old_values,
            new_values=new_values,
            service_name="ClinicManagementService"
        )
