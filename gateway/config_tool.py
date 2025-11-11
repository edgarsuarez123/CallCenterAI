#!/usr/bin/env python3
"""
Configuration Management Tool
Consolidated tool for managing application configuration.

This script provides utilities for managing application configuration,
including generating configuration files, validating settings, and
managing environment-specific configurations.

Usage:
    python config_tool.py generate --environment production
    python config_tool.py validate
    python config_tool.py show --environment development
    python config_tool.py test
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
    get_environment_info,
    get_database_url,
    get_redis_url
)


# ============================================================================
# Helper Functions
# ============================================================================

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


def print_header(title: str):
    """Print a formatted header."""
    print(f"\n{'='*60}")
    print(f" {title}")
    print(f"{'='*60}")


def print_section(title: str):
    """Print a formatted section header."""
    print(f"\n{'-'*40}")
    print(f" {title}")
    print(f"{'-'*40}")


def print_success(message: str):
    """Print a success message."""
    print(f"✅ {message}")


def print_warning(message: str):
    """Print a warning message."""
    print(f"⚠️  {message}")


def print_error(message: str):
    """Print an error message."""
    print(f"❌ {message}")


def print_info(message: str):
    """Print an info message."""
    print(f"ℹ️  {message}")


# ============================================================================
# Configuration Generation
# ============================================================================

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
        
        # Legacy Configuration (deprecated)
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
# Generated on {os.popen('date').read().strip() if os.name != 'nt' else 'Windows'}
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
        ("Legacy Configuration (Deprecated)", "POSTGRES_"),
        ("Legacy Configuration (Deprecated)", "APP_ENV"),
        ("Legacy Configuration (Deprecated)", "PYTHONPATH"),
        ("Legacy Configuration (Deprecated)", "CLINIC_TOKEN_HMAC_KEY_BASE64"),
        ("Legacy Configuration (Deprecated)", "AES_GCM_KEY_BASE64")
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
        print_success(f"Configuration saved to {filename}")
        return True
    except Exception as e:
        print_error(f"Failed to save configuration: {e}")
        return False


# ============================================================================
# Configuration Display
# ============================================================================

def show_configuration(environment: Optional[str] = None):
    """Show current configuration."""
    if environment:
        os.environ["APP_ENVIRONMENT"] = environment
    
    try:
        settings = get_settings()
        
        print_header(f"Configuration for {settings.environment.upper()}")
        
        # Application settings
        print_section("Application")
        print_info(f"Environment: {settings.environment}")
        print_info(f"Debug: {settings.debug}")
        print_info(f"Host: {settings.host}")
        print_info(f"Port: {settings.port}")
        print_info(f"Workers: {settings.workers}")
        print_info(f"API Version: {settings.api_version}")
        
        # Database settings
        print_section("Database")
        print_info(f"Host: {settings.database.host}")
        print_info(f"Port: {settings.database.port}")
        print_info(f"Name: {settings.database.name}")
        print_info(f"User: {settings.database.user}")
        print_info(f"Pool Size: {settings.database.pool_size}")
        print_info(f"Max Overflow: {settings.database.max_overflow}")
        
        # Security settings
        print_section("Security")
        print_success("Encryption Key: configured")
        print_success("JWT Secret: configured")
        print_info(f"CORS Origins: {settings.security.cors_origins}")
        print_info(f"Rate Limit: {settings.security.rate_limit_per_minute} req/min")
        
        # Logging settings
        print_section("Logging")
        print_info(f"Level: {settings.logging.level}")
        print_info(f"Format: {settings.logging.format}")
        print_info(f"Structured: {settings.logging.structured_enabled}")
        print_info(f"PHI Masking: {settings.logging.phi_masking_enabled}")
        
        return True
        
    except Exception as e:
        print_error(f"Failed to show configuration: {e}")
        return False


# ============================================================================
# Configuration Validation
# ============================================================================

def validate_environment_variables():
    """Validate that required environment variables are set."""
    print_section("Environment Variables")
    
    required_vars = [
        "SECURITY_ENCRYPTION_KEY",
        "SECURITY_JWT_SECRET"
    ]
    
    missing_vars = []
    for var in required_vars:
        if not os.getenv(var):
            missing_vars.append(var)
    
    if missing_vars:
        print_error(f"Missing required environment variables: {', '.join(missing_vars)}")
        return False
    else:
        print_success("All required environment variables are set")
        return True


def validate_configuration_structure():
    """Validate the configuration structure and values."""
    print_section("Configuration Structure")
    
    try:
        validation_results = validate_configuration()
        
        if validation_results["valid"]:
            print_success("Configuration structure is valid")
        else:
            print_error("Configuration structure has errors:")
            for error in validation_results["errors"]:
                print_error(f"  - {error}")
        
        if validation_results["warnings"]:
            print_warning("Configuration warnings:")
            for warning in validation_results["warnings"]:
                print_warning(f"  - {warning}")
        
        return validation_results["valid"]
    
    except Exception as e:
        print_error(f"Configuration validation failed: {e}")
        return False


def validate_database_configuration():
    """Validate database configuration."""
    print_section("Database Configuration")
    
    try:
        settings = get_settings()
        
        print_info(f"Database Host: {settings.database.host}")
        print_info(f"Database Port: {settings.database.port}")
        print_info(f"Database Name: {settings.database.name}")
        print_info(f"Database User: {settings.database.user}")
        print_info(f"Pool Size: {settings.database.pool_size}")
        print_info(f"Max Overflow: {settings.database.max_overflow}")
        print_info(f"Pool Timeout: {settings.database.pool_timeout}")
        print_info(f"Pool Recycle: {settings.database.pool_recycle}")
        print_info(f"Pool Pre-ping: {settings.database.pool_pre_ping}")
        
        if settings.database.password.get_secret_value():
            print_success("Database password is configured")
        else:
            print_warning("Database password is not set")
        
        db_url = get_database_url()
        masked_url = db_url.split('@')[0].split('://')[0] + '://' + db_url.split('@')[1] if '@' in db_url else db_url
        print_info(f"Database URL: {masked_url}")
        
        return True
    
    except Exception as e:
        print_error(f"Database configuration validation failed: {e}")
        return False


def validate_security_configuration():
    """Validate security configuration."""
    print_section("Security Configuration")
    
    try:
        settings = get_settings()
        
        if settings.security.encryption_key.get_secret_value():
            print_success("Encryption key is configured")
        else:
            print_error("Encryption key is not configured")
        
        if settings.security.jwt_secret.get_secret_value():
            print_success("JWT secret is configured")
        else:
            print_error("JWT secret is not configured")
        
        print_info(f"CORS Origins: {settings.security.cors_origins}")
        print_info(f"CORS Methods: {settings.security.cors_methods}")
        print_info(f"CORS Headers: {settings.security.cors_headers}")
        print_info(f"Rate Limit: {settings.security.rate_limit_per_minute} requests/minute")
        print_info(f"Rate Limit Burst: {settings.security.rate_limit_burst}")
        print_info(f"Session Timeout: {settings.security.session_timeout_minutes} minutes")
        print_info(f"Max Login Attempts: {settings.security.max_login_attempts}")
        print_info(f"Lockout Duration: {settings.security.lockout_duration_minutes} minutes")
        
        return True
    
    except Exception as e:
        print_error(f"Security configuration validation failed: {e}")
        return False


def validate_logging_configuration():
    """Validate logging configuration."""
    print_section("Logging Configuration")
    
    try:
        settings = get_settings()
        
        print_info(f"Log Level: {settings.logging.level}")
        print_info(f"Log Format: {settings.logging.format}")
        print_info(f"File Logging: {settings.logging.file_enabled}")
        print_info(f"File Path: {settings.logging.file_path}")
        print_info(f"Max File Size: {settings.logging.file_max_size_mb} MB")
        print_info(f"Backup Count: {settings.logging.file_backup_count}")
        print_info(f"Structured Logging: {settings.logging.structured_enabled}")
        print_info(f"PHI Masking: {settings.logging.phi_masking_enabled}")
        print_info(f"Performance Logging: {settings.logging.performance_logging_enabled}")
        print_info(f"Security Logging: {settings.logging.security_logging_enabled}")
        print_info(f"Audit Logging: {settings.logging.audit_enabled}")
        print_info(f"Audit File Path: {settings.logging.audit_file_path}")
        print_info(f"Audit Retention: {settings.logging.audit_retention_days} days")
        
        return True
    
    except Exception as e:
        print_error(f"Logging configuration validation failed: {e}")
        return False


def validate_google_calendar_configuration():
    """Validate Google Calendar configuration."""
    print_section("Google Calendar Configuration")
    
    try:
        settings = get_settings()
        
        if settings.google_calendar.client_id:
            print_success("Google Client ID is configured")
        else:
            print_warning("Google Client ID is not configured")
        
        if settings.google_calendar.client_secret.get_secret_value():
            print_success("Google Client Secret is configured")
        else:
            print_warning("Google Client Secret is not configured")
        
        if settings.google_calendar.redirect_uri:
            print_success("Google Redirect URI is configured")
        else:
            print_warning("Google Redirect URI is not configured")
        
        if settings.google_calendar.api_key.get_secret_value():
            print_success("Google API Key is configured")
        else:
            print_warning("Google API Key is not configured")
        
        print_info(f"Scopes: {settings.google_calendar.scopes}")
        print_info(f"Requests Per Minute: {settings.google_calendar.requests_per_minute}")
        print_info(f"Requests Per Day: {settings.google_calendar.requests_per_day}")
        print_info(f"Sync Interval: {settings.google_calendar.sync_interval_minutes} minutes")
        print_info(f"Max Sync Retries: {settings.google_calendar.max_sync_retries}")
        print_info(f"Sync Timeout: {settings.google_calendar.sync_timeout_seconds} seconds")
        
        return True
    
    except Exception as e:
        print_error(f"Google Calendar configuration validation failed: {e}")
        return False


def validate_azure_configuration():
    """Validate Azure configuration."""
    print_section("Azure Configuration")
    
    try:
        settings = get_settings()
        
        if settings.azure.communication.connection_string.get_secret_value():
            print_success("ACS Connection String is configured")
        else:
            print_warning("ACS Connection String is not configured")
        
        if settings.azure.communication.phone_number:
            print_success("ACS Phone Number is configured")
        else:
            print_warning("ACS Phone Number is not configured")
        
        if settings.azure.openai_endpoint:
            print_success("OpenAI Endpoint is configured")
        else:
            print_warning("OpenAI Endpoint is not configured")
        
        if settings.azure.openai_api_key.get_secret_value():
            print_success("OpenAI API Key is configured")
        else:
            print_warning("OpenAI API Key is not configured")
        
        if settings.azure.openai_deployment_name:
            print_success("OpenAI Deployment Name is configured")
        else:
            print_warning("OpenAI Deployment Name is not configured")
        
        if settings.azure.storage_account_name:
            print_success("Storage Account Name is configured")
        else:
            print_warning("Storage Account Name is not configured")
        
        if settings.azure.storage_account_key.get_secret_value():
            print_success("Storage Account Key is configured")
        else:
            print_warning("Storage Account Key is not configured")
        
        print_info(f"OpenAI API Version: {settings.azure.openai_api_version}")
        print_info(f"Storage Container: {settings.azure.storage_container_name}")
        print_info(f"ACS Requests Per Minute: {settings.azure.acs_requests_per_minute}")
        print_info(f"OpenAI Requests Per Minute: {settings.azure.openai_requests_per_minute}")
        
        return True
    
    except Exception as e:
        print_error(f"Azure configuration validation failed: {e}")
        return False


def validate_application_configuration():
    """Validate application configuration."""
    print_section("Application Configuration")
    
    try:
        settings = get_settings()
        
        print_info(f"Environment: {settings.environment}")
        print_info(f"Debug Mode: {settings.debug}")
        print_info(f"Host: {settings.host}")
        print_info(f"Port: {settings.port}")
        print_info(f"Workers: {settings.workers}")
        print_info(f"API Prefix: {settings.api_prefix}")
        print_info(f"API Version: {settings.api_version}")
        print_info(f"API Title: {settings.api_title}")
        print_info(f"API Description: {settings.api_description}")
        print_info(f"Health Check Interval: {settings.health_check_interval} seconds")
        print_info(f"Health Check Timeout: {settings.health_check_timeout} seconds")
        print_info(f"Max Request Size: {settings.max_request_size} bytes")
        print_info(f"Request Timeout: {settings.request_timeout} seconds")
        
        return True
    
    except Exception as e:
        print_error(f"Application configuration validation failed: {e}")
        return False


def print_environment_info():
    """Print environment information."""
    print_section("Environment Information")
    
    try:
        env_info = get_environment_info()
        
        for key, value in env_info.items():
            print_info(f"{key}: {value}")
        
        return True
    
    except Exception as e:
        print_error(f"Failed to get environment information: {e}")
        return False


def print_recommendations():
    """Print configuration recommendations."""
    print_section("Recommendations")
    
    try:
        settings = get_settings()
        
        recommendations = []
        
        if settings.environment == "production":
            if settings.debug:
                recommendations.append("Disable debug mode in production")
            
            if settings.security.cors_origins == ["*"]:
                recommendations.append("Restrict CORS origins in production")
            
            if settings.logging.level == "DEBUG":
                recommendations.append("Use INFO or WARNING log level in production")
        
        if settings.database.pool_size < 5:
            recommendations.append("Consider increasing database pool size for better performance")
        
        if settings.database.pool_size > 20 and settings.environment == "development":
            recommendations.append("Consider reducing database pool size for development")
        
        if settings.security.rate_limit_per_minute > 200:
            recommendations.append("Consider reducing rate limit for better security")
        
        if not settings.logging.structured_enabled:
            recommendations.append("Enable structured logging for better monitoring")
        
        if not settings.logging.phi_masking_enabled:
            recommendations.append("Enable PHI masking for HIPAA compliance")
        
        if recommendations:
            for recommendation in recommendations:
                print_warning(recommendation)
        else:
            print_success("No specific recommendations at this time")
        
        return True
    
    except Exception as e:
        print_error(f"Failed to generate recommendations: {e}")
        return False


def validate_config(verbose: bool = False):
    """Validate current configuration with detailed feedback."""
    print_header("CallCenterAI Configuration Validation")
    
    validation_results = []
    
    validation_results.append(("Environment Variables", validate_environment_variables()))
    validation_results.append(("Configuration Structure", validate_configuration_structure()))
    
    if verbose:
        validation_results.append(("Database Configuration", validate_database_configuration()))
        validation_results.append(("Security Configuration", validate_security_configuration()))
        validation_results.append(("Logging Configuration", validate_logging_configuration()))
        validation_results.append(("Google Calendar Configuration", validate_google_calendar_configuration()))
        validation_results.append(("Azure Configuration", validate_azure_configuration()))
        validation_results.append(("Application Configuration", validate_application_configuration()))
        validation_results.append(("Environment Information", print_environment_info()))
        validation_results.append(("Recommendations", print_recommendations()))
    
    print_header("Validation Summary")
    
    passed = 0
    failed = 0
    
    for name, result in validation_results:
        if result:
            print_success(f"{name}: PASSED")
            passed += 1
        else:
            print_error(f"{name}: FAILED")
            failed += 1
    
    print(f"\nTotal: {passed + failed}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    
    if failed == 0:
        print_success("All validations passed!")
        return True
    else:
        print_error(f"{failed} validation(s) failed!")
        return False


# ============================================================================
# Configuration Testing
# ============================================================================

def test_configuration():
    """Test configuration loading and validation."""
    print_header("Configuration Test")
    
    try:
        print_section("1. Testing configuration loading")
        settings = get_settings()
        print_success("Configuration loaded successfully")
        
        print_section("2. Testing configuration validation")
        validation_results = validate_configuration()
        if validation_results["valid"]:
            print_success("Configuration validation passed")
        else:
            print_error("Configuration validation failed:")
            for error in validation_results["errors"]:
                print_error(f"   - {error}")
        
        print_section("3. Testing test configuration")
        test_settings = get_test_settings()
        print_success("Test configuration loaded successfully")
        
        print_section("4. Testing environment info")
        env_info = get_environment_info()
        print_success("Environment info retrieved successfully")
        
        print_success("All configuration tests passed!")
        return True
        
    except Exception as e:
        print_error(f"Configuration test failed: {e}")
        return False


# ============================================================================
# Main Entry Point
# ============================================================================

def main():
    """Main function."""
    parser = argparse.ArgumentParser(description="CallCenterAI Configuration Tool")
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
    validate_parser.add_argument("--verbose", "-v", action="store_true",
                                help="Enable verbose validation output")
    validate_parser.add_argument("--environment", "-e",
                                choices=["development", "staging", "production"],
                                help="Set environment for validation")
    
    # Test command
    test_parser = subparsers.add_parser("test", help="Test configuration")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    # Set environment if specified
    if hasattr(args, 'environment') and args.environment:
        os.environ["APP_ENVIRONMENT"] = args.environment
    
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
        if show_configuration(getattr(args, 'environment', None)):
            return 0
        else:
            return 1
    
    elif args.command == "validate":
        if validate_config(verbose=getattr(args, 'verbose', False)):
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

