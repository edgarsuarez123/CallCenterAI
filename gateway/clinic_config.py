#!/usr/bin/env python3
"""
Clinic Configuration Manager
Centralized tool for managing clinic configuration including:
- Subscription tiers and limits
- Clinic information
- AI system prompts
- License status (suspend/activate)

Usage:
    python clinic_config.py setup <clinic_id> --name "Clinic Name" --tier professional
    python clinic_config.py suspend <clinic_id>
    python clinic_config.py activate <clinic_id>
    python clinic_config.py update-tier <clinic_id> --tier enterprise
    python clinic_config.py update-limits <clinic_id> --max-concurrent 20
    python clinic_config.py set-prompt <clinic_id> --language en --prompt "Custom prompt"
    python clinic_config.py show <clinic_id>
"""

import argparse
import sys
import os
import json
from typing import Dict, Any, Optional
from datetime import datetime, timezone

# Add the current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services.database import SessionLocal
from services.clinic_management import ClinicManagementService
from models.models import Clinic, ClinicLicense, SystemConfig
from services.clinic_template_variables import get_clinic_template_variables

# ============================================================================
# Subscription Tier Configuration
# ============================================================================

# Centralized tier limits - modify here to change limits for all clinics
SUBSCRIPTION_TIER_LIMITS = {
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

# Default AI system prompts - can be overridden per clinic
DEFAULT_SYSTEM_PROMPTS = {
    'en': "You are a helpful medical receptionist assistant for {clinic_name}. Your role is to help patients schedule appointments, answer questions about services, and provide information about the clinic. Be professional, courteous, and empathetic.",
    'es': "Eres un asistente útil de recepción médica para {clinic_name}. Tu función es ayudar a los pacientes a programar citas, responder preguntas sobre servicios y proporcionar información sobre la clínica. Sé profesional, cortés y empático."
}


# ============================================================================
# Helper Functions
# ============================================================================

def get_tier_limits(tier: str) -> Dict[str, Any]:
    """Get subscription tier limits."""
    return SUBSCRIPTION_TIER_LIMITS.get(tier.lower(), SUBSCRIPTION_TIER_LIMITS['basic'])


def print_success(message: str):
    """Print success message."""
    print(f"✅ {message}")


def print_error(message: str):
    """Print error message."""
    print(f"❌ {message}")


def print_info(message: str):
    """Print info message."""
    print(f"ℹ️  {message}")


def print_section(title: str):
    """Print section header."""
    print(f"\n{'='*60}")
    print(f" {title}")
    print(f"{'='*60}")


# ============================================================================
# Clinic Management Functions
# ============================================================================

def setup_clinic(clinic_id: str, name: str, tier: str, **kwargs):
    """Setup a new clinic with configuration."""
    db = SessionLocal()
    try:
        service = ClinicManagementService(db)
        
        # Check if clinic exists
        clinic = service.get_clinic(clinic_id)
        if clinic:
            print_error(f"Clinic {clinic_id} already exists")
            return False
        
        # Create clinic
        from models.schemas import ClinicCreateRequest
        clinic_data = ClinicCreateRequest(
            clinic_name=name,
            phone_number=kwargs.get('phone', '+1-555-000-0000'),
            timezone=kwargs.get('timezone', 'America/New_York'),
            default_language=kwargs.get('default_language', 'en'),
            supported_languages=kwargs.get('supported_languages', 'en,es'),
            ehr_system=kwargs.get('ehr_system', 'Google Calendar'),
            max_concurrent_calls=kwargs.get('max_concurrent_calls'),
            queue_timeout_seconds=kwargs.get('queue_timeout_seconds', 45),
            subscription_tier=tier
        )
        
        clinic = service.create_clinic(clinic_data)
        print_success(f"Created clinic {clinic_id}: {name}")
        
        # Set clinic template variables if provided
        if kwargs.get('address'):
            service.set_clinic_config(clinic_id, 'clinic_address', kwargs['address'])
        if kwargs.get('email'):
            service.set_clinic_config(clinic_id, 'clinic_email', kwargs['email'])
        if kwargs.get('business_hours'):
            service.set_clinic_config(clinic_id, 'business_hours', kwargs['business_hours'])
        if kwargs.get('services'):
            service.set_clinic_config(clinic_id, 'clinic_services', kwargs['services'])
        if kwargs.get('insurance_plans'):
            service.set_clinic_config(clinic_id, 'insurance_plans', kwargs['insurance_plans'])
        if kwargs.get('pharmacy_phone'):
            service.set_clinic_config(clinic_id, 'pharmacy_phone', kwargs['pharmacy_phone'])
        
        # Set AI system prompts if provided
        if kwargs.get('system_prompt_en'):
            service.set_clinic_config(clinic_id, 'ai_system_prompt_en', kwargs['system_prompt_en'])
        if kwargs.get('system_prompt_es'):
            service.set_clinic_config(clinic_id, 'ai_system_prompt_es', kwargs['system_prompt_es'])
        
        print_success(f"Clinic {clinic_id} setup complete")
        return True
        
    except Exception as e:
        print_error(f"Failed to setup clinic: {e}")
        db.rollback()
        return False
    finally:
        db.close()


def suspend_clinic(clinic_id: str):
    """Suspend a clinic (disable calls)."""
    db = SessionLocal()
    try:
        service = ClinicManagementService(db)
        clinic = service.get_clinic(clinic_id)
        
        if not clinic:
            print_error(f"Clinic {clinic_id} not found")
            return False
        
        # Get license
        license = service.get_clinic_license(clinic_id)
        if not license:
            print_error(f"License not found for clinic {clinic_id}")
            return False
        
        # Suspend license
        license.license_status = 'suspended'
        license.updated_at = datetime.now(timezone.utc)
        db.commit()
        
        print_success(f"Clinic {clinic_id} suspended - calls will be rejected")
        return True
        
    except Exception as e:
        print_error(f"Failed to suspend clinic: {e}")
        db.rollback()
        return False
    finally:
        db.close()


def activate_clinic(clinic_id: str):
    """Activate a clinic (enable calls)."""
    db = SessionLocal()
    try:
        service = ClinicManagementService(db)
        clinic = service.get_clinic(clinic_id)
        
        if not clinic:
            print_error(f"Clinic {clinic_id} not found")
            return False
        
        # Get license
        license = service.get_clinic_license(clinic_id)
        if not license:
            print_error(f"License not found for clinic {clinic_id}")
            return False
        
        # Activate license
        license.license_status = 'active'
        license.updated_at = datetime.now(timezone.utc)
        db.commit()
        
        print_success(f"Clinic {clinic_id} activated - calls will be accepted")
        return True
        
    except Exception as e:
        print_error(f"Failed to activate clinic: {e}")
        db.rollback()
        return False
    finally:
        db.close()


def update_tier(clinic_id: str, tier: str):
    """Update clinic subscription tier."""
    db = SessionLocal()
    try:
        service = ClinicManagementService(db)
        
        if tier.lower() not in SUBSCRIPTION_TIER_LIMITS:
            print_error(f"Invalid tier: {tier}. Valid tiers: {', '.join(SUBSCRIPTION_TIER_LIMITS.keys())}")
            return False
        
        success = service.update_clinic_license(clinic_id, tier)
        
        if success:
            limits = get_tier_limits(tier)
            print_success(f"Updated clinic {clinic_id} to {tier} tier")
            print_info(f"  Max concurrent calls: {limits['max_concurrent_calls']}")
            print_info(f"  Max calls per month: {limits['max_calls_per_month'] or 'unlimited'}")
            print_info(f"  Max providers: {limits['max_providers'] or 'unlimited'}")
            return True
        else:
            print_error(f"Failed to update tier for clinic {clinic_id}")
            return False
        
    except Exception as e:
        print_error(f"Failed to update tier: {e}")
        return False
    finally:
        db.close()


def update_limits(clinic_id: str, max_concurrent: Optional[int] = None, max_calls_per_month: Optional[int] = None, max_providers: Optional[int] = None):
    """Update clinic limits (override tier defaults)."""
    db = SessionLocal()
    try:
        license = db.query(ClinicLicense).filter_by(clinic_id=clinic_id).first()
        
        if not license:
            print_error(f"License not found for clinic {clinic_id}")
            return False
        
        if max_concurrent is not None:
            license.max_concurrent_calls = max_concurrent
            print_info(f"Updated max concurrent calls to {max_concurrent}")
        
        if max_calls_per_month is not None:
            license.max_calls_per_month = max_calls_per_month
            print_info(f"Updated max calls per month to {max_calls_per_month}")
        
        if max_providers is not None:
            license.max_providers = max_providers
            print_info(f"Updated max providers to {max_providers}")
        
        license.updated_at = datetime.now(timezone.utc)
        db.commit()
        
        print_success(f"Updated limits for clinic {clinic_id}")
        return True
        
    except Exception as e:
        print_error(f"Failed to update limits: {e}")
        db.rollback()
        return False
    finally:
        db.close()


def set_system_prompt(clinic_id: str, language: str, prompt: str):
    """Set AI system prompt for clinic."""
    db = SessionLocal()
    try:
        service = ClinicManagementService(db)
        clinic = service.get_clinic(clinic_id)
        
        if not clinic:
            print_error(f"Clinic {clinic_id} not found")
            return False
        
        if language.lower() not in ['en', 'es']:
            print_error(f"Invalid language: {language}. Valid languages: en, es")
            return False
        
        config_key = f'ai_system_prompt_{language.lower()}'
        service.set_clinic_config(clinic_id, config_key, prompt, f"AI system prompt for {language}")
        
        print_success(f"Set {language} system prompt for clinic {clinic_id}")
        return True
        
    except Exception as e:
        print_error(f"Failed to set system prompt: {e}")
        return False
    finally:
        db.close()


def show_clinic(clinic_id: str):
    """Show clinic configuration."""
    db = SessionLocal()
    try:
        service = ClinicManagementService(db)
        clinic = service.get_clinic(clinic_id)
        
        if not clinic:
            print_error(f"Clinic {clinic_id} not found")
            return False
        
        print_section(f"Clinic Configuration: {clinic_id}")
        
        # Basic Info
        print_section("Basic Information")
        print_info(f"Name: {clinic.clinic_name}")
        print_info(f"Phone: {clinic.phone_number}")
        print_info(f"Timezone: {clinic.timezone}")
        print_info(f"Default Language: {clinic.default_language}")
        print_info(f"Supported Languages: {clinic.supported_languages}")
        print_info(f"Subscription Tier: {clinic.subscription_tier}")
        print_info(f"Active: {clinic.is_active}")
        
        # License Info
        license = service.get_clinic_license(clinic_id)
        if license:
            print_section("License & Limits")
            print_info(f"Status: {license.license_status}")
            print_info(f"Tier: {license.tier}")
            print_info(f"Max Concurrent Calls: {license.max_concurrent_calls}")
            print_info(f"Current Concurrent Calls: {license.current_concurrent_calls}")
            print_info(f"Max Calls Per Month: {license.max_calls_per_month or 'unlimited'}")
            print_info(f"Current Month Calls: {license.current_month_calls}")
            print_info(f"Max Providers: {license.max_providers or 'unlimited'}")
            print_info(f"Monthly Fee: ${license.monthly_fee_usd}")
        
        # Template Variables
        print_section("Template Variables")
        template_vars = get_clinic_template_variables(clinic_id, db)
        for key, value in template_vars.items():
            print_info(f"{key}: {value}")
        
        # AI System Prompts
        print_section("AI System Prompts")
        prompt_en = service.get_clinic_config(clinic_id, 'ai_system_prompt_en')
        prompt_es = service.get_clinic_config(clinic_id, 'ai_system_prompt_es')
        
        if prompt_en:
            print_info(f"English: {prompt_en}")
        else:
            default_en = DEFAULT_SYSTEM_PROMPTS['en'].format(clinic_name=clinic.clinic_name)
            print_info(f"English (default): {default_en}")
        
        if prompt_es:
            print_info(f"Spanish: {prompt_es}")
        else:
            default_es = DEFAULT_SYSTEM_PROMPTS['es'].format(clinic_name=clinic.clinic_name)
            print_info(f"Spanish (default): {default_es}")
        
        return True
        
    except Exception as e:
        print_error(f"Failed to show clinic: {e}")
        return False
    finally:
        db.close()


# ============================================================================
# Main Entry Point
# ============================================================================

def main():
    """Main function."""
    parser = argparse.ArgumentParser(description="Clinic Configuration Manager")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # Setup command
    setup_parser = subparsers.add_parser("setup", help="Setup a new clinic")
    setup_parser.add_argument("clinic_id", help="Clinic ID")
    setup_parser.add_argument("--name", required=True, help="Clinic name")
    setup_parser.add_argument("--tier", default="basic", choices=["basic", "professional", "enterprise"], help="Subscription tier")
    setup_parser.add_argument("--phone", help="Phone number")
    setup_parser.add_argument("--timezone", help="Timezone")
    setup_parser.add_argument("--address", help="Physical address")
    setup_parser.add_argument("--email", help="Email address")
    setup_parser.add_argument("--business-hours", help="Business hours")
    setup_parser.add_argument("--services", help="Services offered")
    setup_parser.add_argument("--insurance-plans", help="Insurance plans accepted")
    setup_parser.add_argument("--pharmacy-phone", help="Pharmacy phone")
    setup_parser.add_argument("--system-prompt-en", help="English AI system prompt")
    setup_parser.add_argument("--system-prompt-es", help="Spanish AI system prompt")
    
    # Suspend command
    suspend_parser = subparsers.add_parser("suspend", help="Suspend a clinic (disable calls)")
    suspend_parser.add_argument("clinic_id", help="Clinic ID")
    
    # Activate command
    activate_parser = subparsers.add_parser("activate", help="Activate a clinic (enable calls)")
    activate_parser.add_argument("clinic_id", help="Clinic ID")
    
    # Update tier command
    tier_parser = subparsers.add_parser("update-tier", help="Update subscription tier")
    tier_parser.add_argument("clinic_id", help="Clinic ID")
    tier_parser.add_argument("--tier", required=True, choices=["basic", "professional", "enterprise"], help="New tier")
    
    # Update limits command
    limits_parser = subparsers.add_parser("update-limits", help="Update clinic limits (override tier defaults)")
    limits_parser.add_argument("clinic_id", help="Clinic ID")
    limits_parser.add_argument("--max-concurrent", type=int, help="Max concurrent calls")
    limits_parser.add_argument("--max-calls-per-month", type=int, help="Max calls per month")
    limits_parser.add_argument("--max-providers", type=int, help="Max providers")
    
    # Set prompt command
    prompt_parser = subparsers.add_parser("set-prompt", help="Set AI system prompt")
    prompt_parser.add_argument("clinic_id", help="Clinic ID")
    prompt_parser.add_argument("--language", required=True, choices=["en", "es"], help="Language")
    prompt_parser.add_argument("--prompt", required=True, help="System prompt text")
    
    # Show command
    show_parser = subparsers.add_parser("show", help="Show clinic configuration")
    show_parser.add_argument("clinic_id", help="Clinic ID")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    if args.command == "setup":
        kwargs = {
            'phone': args.phone,
            'timezone': args.timezone,
            'address': args.address,
            'email': args.email,
            'business_hours': getattr(args, 'business_hours', None),
            'services': args.services,
            'insurance_plans': getattr(args, 'insurance_plans', None),
            'pharmacy_phone': getattr(args, 'pharmacy_phone', None),
            'system_prompt_en': getattr(args, 'system_prompt_en', None),
            'system_prompt_es': getattr(args, 'system_prompt_es', None)
        }
        if setup_clinic(args.clinic_id, args.name, args.tier, **kwargs):
            return 0
        else:
            return 1
    
    elif args.command == "suspend":
        if suspend_clinic(args.clinic_id):
            return 0
        else:
            return 1
    
    elif args.command == "activate":
        if activate_clinic(args.clinic_id):
            return 0
        else:
            return 1
    
    elif args.command == "update-tier":
        if update_tier(args.clinic_id, args.tier):
            return 0
        else:
            return 1
    
    elif args.command == "update-limits":
        if update_limits(args.clinic_id, args.max_concurrent, args.max_calls_per_month, args.max_providers):
            return 0
        else:
            return 1
    
    elif args.command == "set-prompt":
        if set_system_prompt(args.clinic_id, args.language, args.prompt):
            return 0
        else:
            return 1
    
    elif args.command == "show":
        if show_clinic(args.clinic_id):
            return 0
        else:
            return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

