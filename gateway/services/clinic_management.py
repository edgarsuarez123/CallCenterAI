"""
Clinic Management Service
Handles all business logic for clinic operations including creation, updates, and configuration.
"""

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
import uuid

from models.models import Clinic, ClinicLicense, SystemConfig, AuditLog
from models.schemas import (
    ClinicCreateRequest, ClinicUpdateRequest, ClinicSearchRequest,
    ClinicResponse, SystemConfigCreateRequest
)
from services.crypto import make_ulid_token


class ClinicManagementService:
    """Service for managing clinic operations and configuration."""
    
    def __init__(self, db: Session):
        self.db = db
    
    def create_clinic(self, clinic_data: ClinicCreateRequest) -> Clinic:
        """
        Create a new clinic with license and initial configuration.
        
        Args:
            clinic_data: Clinic creation request data
            
        Returns:
            Created clinic instance
            
        Raises:
            ValueError: If clinic data is invalid
            IntegrityError: If clinic already exists
        """
        try:
            # Generate unique clinic ID
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
            self.db.flush()  # Get the clinic_id for license creation
            
            # Create license
            license_data = self._get_license_config(clinic_data.subscription_tier.value)
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
                billing_cycle_start=self._get_billing_cycle_start(),
                billing_cycle_end=self._get_billing_cycle_end(),
                next_billing_date=self._get_next_billing_date()
            )
            
            self.db.add(license)
            
            # Create initial system configurations
            self._create_initial_configs(clinic_id, clinic_data)
            
            # Log the creation
            self._log_audit("clinics", clinic_id, "CREATE", None, clinic_data.dict())
            
            self.db.commit()
            return clinic
            
        except IntegrityError as e:
            self.db.rollback()
            raise ValueError(f"Clinic with phone number {clinic_data.phone_number} already exists")
        except Exception as e:
            self.db.rollback()
            raise ValueError(f"Failed to create clinic: {str(e)}")
    
    def get_clinic(self, clinic_id: str) -> Optional[Clinic]:
        """Get clinic by ID."""
        return self.db.query(Clinic).filter_by(clinic_id=clinic_id).first()
    
    def update_clinic(self, clinic_id: str, updates: ClinicUpdateRequest) -> Optional[Clinic]:
        """
        Update clinic information.
        
        Args:
            clinic_id: Clinic ID to update
            updates: Update request data
            
        Returns:
            Updated clinic instance or None if not found
        """
        clinic = self.get_clinic(clinic_id)
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
        
        clinic.updated_at = datetime.utcnow()
        
        # Log the update
        self._log_audit("clinics", clinic_id, "UPDATE", old_values, update_data)
        
        self.db.commit()
        return clinic
    
    def list_clinics(self, search: ClinicSearchRequest) -> List[Clinic]:
        """
        List clinics with optional filtering and pagination.
        
        Args:
            search: Search criteria and pagination
            
        Returns:
            List of matching clinics
        """
        query = self.db.query(Clinic)
        
        # Apply filters
        if search.clinic_name:
            query = query.filter(Clinic.clinic_name.ilike(f"%{search.clinic_name}%"))
        
        if search.phone_number:
            query = query.filter(Clinic.phone_number == search.phone_number)
        
        if search.subscription_tier:
            query = query.filter(Clinic.subscription_tier == search.subscription_tier.value)
        
        if search.is_active:
            query = query.filter(Clinic.is_active == search.is_active.value)
        
        # Apply pagination
        query = query.offset(search.offset).limit(search.limit)
        
        return query.all()
    
    def deactivate_clinic(self, clinic_id: str) -> bool:
        """
        Deactivate a clinic (soft delete).
        
        Args:
            clinic_id: Clinic ID to deactivate
            
        Returns:
            True if successful, False if clinic not found
        """
        clinic = self.get_clinic(clinic_id)
        if not clinic:
            return False
        
        old_values = {"is_active": clinic.is_active}
        clinic.is_active = "no"
        clinic.updated_at = datetime.utcnow()
        
        # Log the deactivation
        self._log_audit("clinics", clinic_id, "DEACTIVATE", old_values, {"is_active": "no"})
        
        self.db.commit()
        return True
    
    def get_clinic_license(self, clinic_id: str) -> Optional[ClinicLicense]:
        """Get clinic license information."""
        return self.db.query(ClinicLicense).filter_by(clinic_id=clinic_id).first()
    
    def update_clinic_license(self, clinic_id: str, tier: str) -> bool:
        """
        Update clinic subscription tier and license.
        
        Args:
            clinic_id: Clinic ID
            tier: New subscription tier
            
        Returns:
            True if successful, False if clinic not found
        """
        clinic = self.get_clinic(clinic_id)
        license = self.get_clinic_license(clinic_id)
        
        if not clinic or not license:
            return False
        
        # Update clinic tier
        old_clinic_tier = clinic.subscription_tier
        clinic.subscription_tier = tier
        clinic.updated_at = datetime.utcnow()
        
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
        license.updated_at = datetime.utcnow()
        
        # Log the changes
        self._log_audit("clinics", clinic_id, "UPDATE_TIER", 
                       {"subscription_tier": old_clinic_tier}, 
                       {"subscription_tier": tier})
        self._log_audit("clinic_licenses", license.license_id, "UPDATE", 
                       old_license_values, license_data)
        
        self.db.commit()
        return True
    
    def get_clinic_config(self, clinic_id: str, config_key: str) -> Optional[str]:
        """Get a specific configuration value for a clinic."""
        config = self.db.query(SystemConfig).filter_by(
            config_key=f"{config_key}_{clinic_id}"
        ).first()
        return config.config_value if config else None
    
    def set_clinic_config(self, clinic_id: str, config_key: str, config_value: str, description: str = None) -> bool:
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
        existing_config = self.db.query(SystemConfig).filter_by(config_key=full_config_key).first()
        
        if existing_config:
            # Update existing
            old_value = existing_config.config_value
            existing_config.config_value = config_value
            existing_config.description = description or existing_config.description
            existing_config.updated_at = datetime.utcnow()
            
            self._log_audit("system_config", existing_config.config_id, "UPDATE",
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
            
            self._log_audit("system_config", config.config_id, "CREATE", None, {
                "config_key": config.config_key,
                "config_value": config.config_value,
                "description": config.description
            })
        
        self.db.commit()
        return True
    
    def _generate_clinic_id(self, phone_number: str) -> str:
        """Generate unique clinic ID from phone number."""
        # Use a hash of the phone number to ensure uniqueness
        import hashlib
        phone_hash = hashlib.md5(phone_number.encode()).hexdigest()[:8]
        unique_token = make_ulid_token('CLINIC')[:8]
        return f"CLINIC_{phone_hash}_{unique_token}"
    
    def _get_license_config(self, tier: str) -> Dict[str, Any]:
        """Get license configuration based on tier."""
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
    
    def _get_billing_cycle_start(self) -> datetime:
        """Get start of current billing cycle."""
        now = datetime.utcnow()
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    def _get_billing_cycle_end(self) -> datetime:
        """Get end of current billing cycle."""
        start = self._get_billing_cycle_start()
        if start.month == 12:
            return start.replace(year=start.year + 1, month=1) - timedelta(days=1)
        else:
            return start.replace(month=start.month + 1) - timedelta(days=1)
    
    def _get_next_billing_date(self) -> datetime:
        """Get next billing date."""
        start = self._get_billing_cycle_start()
        if start.month == 12:
            return start.replace(year=start.year + 1, month=1)
        else:
            return start.replace(month=start.month + 1)
    
    def _create_initial_configs(self, clinic_id: str, clinic_data: ClinicCreateRequest):
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
            self.set_clinic_config(
                clinic_id=clinic_id,
                config_key=config["key"],
                config_value=config["value"],
                description=config["description"]
            )
    
    def _log_audit(self, table_name: str, record_id: str, action_type: str, 
                   old_values: Optional[Dict], new_values: Optional[Dict]):
        """Log audit trail for changes."""
        details = ""
        if old_values:
            details += f"Old values: {old_values}. "
        if new_values:
            details += f"New values: {new_values}"
        
        audit_log = AuditLog(
            log_id=f"LOG_{make_ulid_token('AUDIT')[:8]}",
            table_name=table_name,
            record_id=record_id,
            action_type=action_type,
            details=details,
            user_id="system",  # TODO: Get from auth context
            ip_address="127.0.0.1",  # TODO: Get from request context
            user_agent="ClinicManagementService"
        )
        self.db.add(audit_log)
