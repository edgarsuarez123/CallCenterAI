#!/usr/bin/env python3
"""
Configuration Validation Script

This script validates the application configuration and provides
detailed feedback on any issues found.

Usage:
    python validate_config.py
    python validate_config.py --environment production
    python validate_config.py --verbose
"""

import argparse
import sys
import os
from typing import Dict, Any

# Add the current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services.configuration import (
    validate_configuration,
    get_environment_info,
    get_settings,
    get_database_url,
    get_redis_url
)


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
        
        # Check database connection parameters
        print_info(f"Database Host: {settings.database.host}")
        print_info(f"Database Port: {settings.database.port}")
        print_info(f"Database Name: {settings.database.name}")
        print_info(f"Database User: {settings.database.user}")
        print_info(f"Pool Size: {settings.database.pool_size}")
        print_info(f"Max Overflow: {settings.database.max_overflow}")
        print_info(f"Pool Timeout: {settings.database.pool_timeout}")
        print_info(f"Pool Recycle: {settings.database.pool_recycle}")
        print_info(f"Pool Pre-ping: {settings.database.pool_pre_ping}")
        
        # Check if password is set
        if settings.database.password.get_secret_value():
            print_success("Database password is configured")
        else:
            print_warning("Database password is not set")
        
        # Generate database URL (without exposing password)
        db_url = get_database_url()
        # Mask password in URL for display
        masked_url = db_url.split('@')[0].split('://')[0] + '://' + db_url.split('@')[1]
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
        
        # Check encryption key
        if settings.security.encryption_key.get_secret_value():
            print_success("Encryption key is configured")
        else:
            print_error("Encryption key is not configured")
        
        # Check JWT secret
        if settings.security.jwt_secret.get_secret_value():
            print_success("JWT secret is configured")
        else:
            print_error("JWT secret is not configured")
        
        # Check CORS configuration
        print_info(f"CORS Origins: {settings.security.cors_origins}")
        print_info(f"CORS Methods: {settings.security.cors_methods}")
        print_info(f"CORS Headers: {settings.security.cors_headers}")
        
        # Check rate limiting
        print_info(f"Rate Limit: {settings.security.rate_limit_per_minute} requests/minute")
        print_info(f"Rate Limit Burst: {settings.security.rate_limit_burst}")
        
        # Check session security
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
        
        # Check OAuth settings
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
        
        # Check API settings
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
        
        # Check Communication Services
        if settings.azure.acs_connection_string.get_secret_value():
            print_success("ACS Connection String is configured")
        else:
            print_warning("ACS Connection String is not configured")
        
        if settings.azure.acs_phone_number:
            print_success("ACS Phone Number is configured")
        else:
            print_warning("ACS Phone Number is not configured")
        
        # Check OpenAI
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
        
        # Check Storage
        if settings.azure.storage_account_name:
            print_success("Storage Account Name is configured")
        else:
            print_warning("Storage Account Name is not configured")
        
        if settings.azure.storage_account_key.get_secret_value():
            print_success("Storage Account Key is configured")
        else:
            print_warning("Storage Account Key is not configured")
        
        # Check API settings
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
        
        # Environment-specific recommendations
        if settings.environment == "production":
            if settings.debug:
                recommendations.append("Disable debug mode in production")
            
            if settings.security.cors_origins == ["*"]:
                recommendations.append("Restrict CORS origins in production")
            
            if settings.logging.level == "DEBUG":
                recommendations.append("Use INFO or WARNING log level in production")
        
        # Database recommendations
        if settings.database.pool_size < 5:
            recommendations.append("Consider increasing database pool size for better performance")
        
        if settings.database.pool_size > 20 and settings.environment == "development":
            recommendations.append("Consider reducing database pool size for development")
        
        # Security recommendations
        if settings.security.rate_limit_per_minute > 200:
            recommendations.append("Consider reducing rate limit for better security")
        
        # Logging recommendations
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


def main():
    """Main validation function."""
    parser = argparse.ArgumentParser(description="Validate CallCenterAI configuration")
    parser.add_argument("--environment", help="Set environment for validation")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose output")
    
    args = parser.parse_args()
    
    # Set environment if specified
    if args.environment:
        os.environ["APP_ENVIRONMENT"] = args.environment
    
    print_header("CallCenterAI Configuration Validation")
    
    # Track validation results
    validation_results = []
    
    # Run all validation functions
    validation_results.append(("Environment Variables", validate_environment_variables()))
    validation_results.append(("Configuration Structure", validate_configuration_structure()))
    validation_results.append(("Database Configuration", validate_database_configuration()))
    validation_results.append(("Security Configuration", validate_security_configuration()))
    validation_results.append(("Logging Configuration", validate_logging_configuration()))
    validation_results.append(("Google Calendar Configuration", validate_google_calendar_configuration()))
    validation_results.append(("Azure Configuration", validate_azure_configuration()))
    validation_results.append(("Application Configuration", validate_application_configuration()))
    validation_results.append(("Environment Information", print_environment_info()))
    validation_results.append(("Recommendations", print_recommendations()))
    
    # Print summary
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
        return 0
    else:
        print_error(f"{failed} validation(s) failed!")
        return 1


if __name__ == "__main__":
    sys.exit(main())
