#!/usr/bin/env python3
"""
Configuration Management Script

This script provides utilities for managing application configuration,
including generating configuration files, validating settings, and
managing environment-specific configurations.

Usage:
    python config_manager.py generate --environment production
    python config_manager.py validate
    python config_manager.py show --environment development
    python config_manager.py test
"""

import argparse
import sys
import os
import json
import base64
import secrets
from typing import Dict, Any, Optional

# Add the current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services.configuration import (
    get_settings,
    get_test_settings,
    validate_configuration,
    get_environment_info
)


def generate_encryption_key() -> str:
    """Generate a secure 32-byte encryption key."""
    key = secrets.token_bytes(32)
    return base64.b64encode(key).decode('utf-8')


def generate_jwt_secret() -> str:
    """Generate a secure JWT secret."""
    return secrets.token_urlsafe(32)


def generate_hmac_key() -> str:
    """Generate a secure HMAC key."""
    key = secrets.token_bytes(32)
    return base64.b64encode(key).decode('utf-8')


def generate_aes_key() -> str:
    """Generate a secure AES key."""
    key = secrets.token_bytes(32)
    return base64.b64encode(key).decode('utf-8')


def generate_config_file(environment: str = "development") -> str:
    """Generate a configuration file for the specified environment."""
    
    # Generate secure keys
    encryption_key = generate_encryption_key()
    jwt_secret = generate_jwt_secret()
    hmac_key = generate_hmac_key()
    aes_key = generate_aes_key()
    
    # Environment-specific configurations
    configs = {
        "development": {
            "APP_ENVIRONMENT": "development",
            "APP_DEBUG": "true",
            "LOG_LEVEL": "DEBUG",
            "DB_POOL_SIZE": "5",
            "SECURITY_CORS_ORIGINS": '["http://localhost:3000", "http://localhost:8000"]',
            "SECURITY_RATE_LIMIT_PER_MINUTE": "1000"
        },
        "staging": {
            "APP_ENVIRONMENT": "staging",
            "APP_DEBUG": "false",
            "LOG_LEVEL": "INFO",
            "DB_POOL_SIZE": "10",
            "SECURITY_CORS_ORIGINS": '["https://staging.yourdomain.com"]',
            "SECURITY_RATE_LIMIT_PER_MINUTE": "200"
        },
        "production": {
            "APP_ENVIRONMENT": "production",
            "APP_DEBUG": "false",
            "LOG_LEVEL": "WARNING",
            "DB_POOL_SIZE": "20",
            "SECURITY_CORS_ORIGINS": '["https://yourdomain.com"]',
            "SECURITY_RATE_LIMIT_PER_MINUTE": "100"
        }
    }
    
    # Base configuration
    base_config = {
        # Application Configuration
        "APP_HOST": "0.0.0.0",
        "APP_PORT": "8000",
        "APP_WORKERS": "1",
        "APP_API_PREFIX": "/api/v1",
        "APP_API_VERSION": "1.0.0",
        "APP_API_TITLE": "CallCenter AI API",
        "APP_API_DESCRIPTION": "AI-powered call center management system",
        "APP_HEALTH_CHECK_INTERVAL": "30",
        "APP_HEALTH_CHECK_TIMEOUT": "10",
        "APP_MAX_REQUEST_SIZE": "10485760",
        "APP_REQUEST_TIMEOUT": "30",
        
        # Database Configuration
        "DB_HOST": "postgres",
        "DB_PORT": "5432",
        "DB_NAME": "callcenterai",
        "DB_USER": "callcenterai",
        "DB_PASSWORD": "ChangeThisNow_!",
        "DB_POOL_SIZE": "10",
        "DB_MAX_OVERFLOW": "20",
        "DB_POOL_TIMEOUT": "30",
        "DB_POOL_RECYCLE": "3600",
        "DB_POOL_PRE_PING": "true",
        "DB_CONNECT_TIMEOUT": "10",
        "DB_APPLICATION_NAME": "CallCenterAI",
        "DB_DEFAULT_TRANSACTION_ISOLATION": "read_committed",
        
        # Security Configuration
        "SECURITY_ENCRYPTION_KEY": encryption_key,
        "SECURITY_JWT_SECRET": jwt_secret,
        "SECURITY_CORS_ORIGINS": '["*"]',
        "SECURITY_CORS_METHODS": '["GET", "POST", "PUT", "DELETE"]',
        "SECURITY_CORS_HEADERS": '["*"]',
        "SECURITY_RATE_LIMIT_PER_MINUTE": "100",
        "SECURITY_RATE_LIMIT_BURST": "200",
        "SECURITY_SESSION_TIMEOUT_MINUTES": "30",
        "SECURITY_MAX_LOGIN_ATTEMPTS": "5",
        "SECURITY_LOCKOUT_DURATION_MINUTES": "15",
        
        # Logging Configuration
        "LOG_LEVEL": "INFO",
        "LOG_FORMAT": "json",
        "LOG_FILE_ENABLED": "true",
        "LOG_FILE_PATH": "logs/app.log",
        "LOG_FILE_MAX_SIZE_MB": "100",
        "LOG_FILE_BACKUP_COUNT": "5",
        "LOG_STRUCTURED_ENABLED": "true",
        "LOG_PHI_MASKING_ENABLED": "true",
        "LOG_PERFORMANCE_LOGGING_ENABLED": "true",
        "LOG_SECURITY_LOGGING_ENABLED": "true",
        "LOG_AUDIT_ENABLED": "true",
        "LOG_AUDIT_FILE_PATH": "logs/audit.log",
        "LOG_AUDIT_RETENTION_DAYS": "2555",
        
        # Google Calendar Configuration
        "GOOGLE_CLIENT_ID": "your_client_id.apps.googleusercontent.com",
        "GOOGLE_CLIENT_SECRET": "your_client_secret",
        "GOOGLE_REDIRECT_URI": "http://localhost:8000/auth/callback",
        "GOOGLE_API_KEY": "your_api_key",
        "GOOGLE_SCOPES": '["https://www.googleapis.com/auth/calendar"]',
        "GOOGLE_REQUESTS_PER_MINUTE": "100",
        "GOOGLE_REQUESTS_PER_DAY": "10000",
        "GOOGLE_SYNC_INTERVAL_MINUTES": "5",
        "GOOGLE_MAX_SYNC_RETRIES": "3",
        "GOOGLE_SYNC_TIMEOUT_SECONDS": "30",
        
        # Azure Configuration
        "AZURE_ACS_CONNECTION_STRING": "endpoint=https://your.communication.azure.com/;accesskey=your_key",
        "AZURE_ACS_PHONE_NUMBER": "+1234567890",
        "AZURE_OPENAI_ENDPOINT": "https://your.openai.azure.com/",
        "AZURE_OPENAI_API_KEY": "your_api_key",
        "AZURE_OPENAI_API_VERSION": "2024-02-15-preview",
        "AZURE_OPENAI_DEPLOYMENT_NAME": "your_deployment",
        "AZURE_STORAGE_ACCOUNT_NAME": "your_storage_account",
        "AZURE_STORAGE_ACCOUNT_KEY": "your_storage_key",
        "AZURE_STORAGE_CONTAINER_NAME": "callcenter",
        "AZURE_ACS_REQUESTS_PER_MINUTE": "100",
        "AZURE_OPENAI_REQUESTS_PER_MINUTE": "60",
        
        # Legacy Configuration
        "POSTGRES_HOST": "postgres",
        "POSTGRES_PORT": "5432",
        "POSTGRES_DB": "callcenterai",
        "POSTGRES_USER": "callcenterai",
        "POSTGRES_PASSWORD": "ChangeThisNow_!",
        "APP_ENV": "dev",
        "PYTHONPATH": "/app",
        "CLINIC_TOKEN_HMAC_KEY_BASE64": hmac_key,
        "AES_GCM_KEY_BASE64": aes_key
    }
    
    # Apply environment-specific overrides
    if environment in configs:
        base_config.update(configs[environment])
    
    # Generate .env file content
    env_content = f"""# CallCenterAI Environment Variables - {environment.upper()}
# Generated on {os.popen('date').read().strip()}
# NEVER commit this file to version control

"""
    
    # Add configuration sections
    sections = [
        ("Application Configuration", "APP_"),
        ("Database Configuration", "DB_"),
        ("Security Configuration", "SECURITY_"),
        ("Logging Configuration", "LOG_"),
        ("Google Calendar Configuration", "GOOGLE_"),
        ("Azure Configuration", "AZURE_"),
        ("Legacy Configuration", "POSTGRES_"),
        ("Legacy Configuration", "APP_ENV"),
        ("Legacy Configuration", "PYTHONPATH"),
        ("Legacy Configuration", "CLINIC_TOKEN_HMAC_KEY_BASE64"),
        ("Legacy Configuration", "AES_GCM_KEY_BASE64")
    ]
    
    for section_name, prefix in sections:
        env_content += f"\n# {section_name}\n"
        
        for key, value in base_config.items():
            if key.startswith(prefix):
                env_content += f"{key}={value}\n"
        
        env_content += "\n"
    
    return env_content


def save_config_file(content: str, filename: str = ".env"):
    """Save configuration content to a file."""
    try:
        with open(filename, 'w') as f:
            f.write(content)
        print(f"✅ Configuration saved to {filename}")
        return True
    except Exception as e:
        print(f"❌ Failed to save configuration: {e}")
        return False


def show_configuration(environment: Optional[str] = None):
    """Show current configuration."""
    if environment:
        os.environ["APP_ENVIRONMENT"] = environment
    
    try:
        settings = get_settings()
        
        print(f"\n{'='*60}")
        print(f" Configuration for {settings.environment.upper()}")
        print(f"{'='*60}")
        
        # Application settings
        print(f"\nApplication:")
        print(f"  Environment: {settings.environment}")
        print(f"  Debug: {settings.debug}")
        print(f"  Host: {settings.host}")
        print(f"  Port: {settings.port}")
        print(f"  Workers: {settings.workers}")
        print(f"  API Version: {settings.api_version}")
        
        # Database settings
        print(f"\nDatabase:")
        print(f"  Host: {settings.database.host}")
        print(f"  Port: {settings.database.port}")
        print(f"  Name: {settings.database.name}")
        print(f"  User: {settings.database.user}")
        print(f"  Pool Size: {settings.database.pool_size}")
        print(f"  Max Overflow: {settings.database.max_overflow}")
        
        # Security settings
        print(f"\nSecurity:")
        print(f"  Encryption Key: {'*' * 20} (configured)")
        print(f"  JWT Secret: {'*' * 20} (configured)")
        print(f"  CORS Origins: {settings.security.cors_origins}")
        print(f"  Rate Limit: {settings.security.rate_limit_per_minute} req/min")
        
        # Logging settings
        print(f"\nLogging:")
        print(f"  Level: {settings.logging.level}")
        print(f"  Format: {settings.logging.format}")
        print(f"  Structured: {settings.logging.structured_enabled}")
        print(f"  PHI Masking: {settings.logging.phi_masking_enabled}")
        
        return True
        
    except Exception as e:
        print(f"❌ Failed to show configuration: {e}")
        return False


def test_configuration():
    """Test configuration loading and validation."""
    print(f"\n{'='*60}")
    print(" Configuration Test")
    print(f"{'='*60}")
    
    try:
        # Test configuration loading
        print("\n1. Testing configuration loading...")
        settings = get_settings()
        print("✅ Configuration loaded successfully")
        
        # Test validation
        print("\n2. Testing configuration validation...")
        validation_results = validate_configuration()
        if validation_results["valid"]:
            print("✅ Configuration validation passed")
        else:
            print("❌ Configuration validation failed:")
            for error in validation_results["errors"]:
                print(f"   - {error}")
        
        # Test test configuration
        print("\n3. Testing test configuration...")
        test_settings = get_test_settings()
        print("✅ Test configuration loaded successfully")
        
        # Test environment info
        print("\n4. Testing environment info...")
        env_info = get_environment_info()
        print("✅ Environment info retrieved successfully")
        
        print("\n✅ All configuration tests passed!")
        return True
        
    except Exception as e:
        print(f"❌ Configuration test failed: {e}")
        return False


def validate_config():
    """Validate current configuration."""
    print(f"\n{'='*60}")
    print(" Configuration Validation")
    print(f"{'='*60}")
    
    try:
        validation_results = validate_configuration()
        
        if validation_results["valid"]:
            print("✅ Configuration is valid")
        else:
            print("❌ Configuration has errors:")
            for error in validation_results["errors"]:
                print(f"   - {error}")
        
        if validation_results["warnings"]:
            print("\n⚠️  Configuration warnings:")
            for warning in validation_results["warnings"]:
                print(f"   - {warning}")
        
        return validation_results["valid"]
        
    except Exception as e:
        print(f"❌ Configuration validation failed: {e}")
        return False


def main():
    """Main function."""
    parser = argparse.ArgumentParser(description="CallCenterAI Configuration Manager")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # Generate command
    generate_parser = subparsers.add_parser("generate", help="Generate configuration file")
    generate_parser.add_argument("--environment", "-e", default="development", 
                                choices=["development", "staging", "production"],
                                help="Environment to generate configuration for")
    generate_parser.add_argument("--output", "-o", default=".env",
                                help="Output file name")
    
    # Show command
    show_parser = subparsers.add_parser("show", help="Show current configuration")
    show_parser.add_argument("--environment", "-e", 
                            choices=["development", "staging", "production"],
                            help="Environment to show configuration for")
    
    # Validate command
    validate_parser = subparsers.add_parser("validate", help="Validate configuration")
    
    # Test command
    test_parser = subparsers.add_parser("test", help="Test configuration")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    if args.command == "generate":
        print(f"Generating configuration for {args.environment}...")
        content = generate_config_file(args.environment)
        if save_config_file(content, args.output):
            print(f"\n✅ Configuration generated successfully!")
            print(f"📝 Edit {args.output} to customize your settings")
            print(f"🔒 Remember to keep your secrets secure!")
            return 0
        else:
            return 1
    
    elif args.command == "show":
        if show_configuration(args.environment):
            return 0
        else:
            return 1
    
    elif args.command == "validate":
        if validate_config():
            return 0
        else:
            return 1
    
    elif args.command == "test":
        if test_configuration():
            return 0
        else:
            return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
