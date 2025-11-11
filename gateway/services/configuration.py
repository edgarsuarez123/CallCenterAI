"""
Configuration Management with Pydantic

This module provides a comprehensive configuration management system using Pydantic
for type safety, validation, and environment-specific settings.

Key Features:
- Type safety at startup
- Validation before runtime
- Environment-specific configs
- Self-documenting configuration
- Default values
- Testing with overrides
- Caching for performance
- Secret validation
"""

import os
import base64
from typing import Optional, List, Dict, Any, Union
from functools import lru_cache
from pydantic import Field, field_validator, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
import logging

logger = logging.getLogger(__name__)


class DatabaseConfig(BaseSettings):
    """Database configuration with validation."""
    
    # Connection settings
    host: str = Field(default="localhost", description="Database host")
    port: int = Field(default=5432, ge=1, le=65535, description="Database port")
    name: str = Field(default="callcenter", description="Database name")
    user: str = Field(default="postgres", description="Database user")
    password: SecretStr = Field(default="", description="Database password")
    
    # Connection pooling
    pool_size: int = Field(default=10, ge=1, le=50, description="Database pool size")
    max_overflow: int = Field(default=20, ge=0, le=100, description="Maximum overflow connections")
    pool_timeout: int = Field(default=30, ge=1, le=300, description="Pool timeout in seconds")
    pool_recycle: int = Field(default=3600, ge=300, le=86400, description="Pool recycle time in seconds")
    pool_pre_ping: bool = Field(default=True, description="Enable pool pre-ping")
    
    # Connection arguments
    connect_timeout: int = Field(default=10, ge=1, le=60, description="Connection timeout in seconds")
    application_name: str = Field(default="CallCenterAI", description="Application name for database")
    default_transaction_isolation: str = Field(
        default="read committed", 
        pattern="^(read committed|repeatable read|serializable)$",
        description="Default transaction isolation level"
    )
    
    model_config = SettingsConfigDict(
        env_prefix="DB_",
        case_sensitive=False
    )


class SecurityConfig(BaseSettings):
    """Security configuration with validation."""
    
    # Encryption
    encryption_key: SecretStr = Field(..., description="32-byte encryption key for PHI")
    jwt_secret: SecretStr = Field(..., description="JWT signing secret")
    jwt_algorithm: str = Field(default="HS256", description="JWT algorithm")
    jwt_expiration_hours: int = Field(default=24, ge=1, le=168, description="JWT expiration in hours")
    
    # CORS
    cors_origins: str = Field(default='["*"]', description="Allowed CORS origins (JSON string)")
    cors_methods: str = Field(default='["GET", "POST", "PUT", "DELETE"]', description="Allowed CORS methods (JSON string)")
    cors_headers: str = Field(default='["*"]', description="Allowed CORS headers (JSON string)")
    
    @field_validator('cors_origins', 'cors_methods', 'cors_headers')
    @classmethod
    def parse_json_strings(cls, v):
        """Parse JSON strings or comma-separated values for CORS configuration."""
        # Handle None or empty values
        if v is None:
            return ["*"]
        
        if isinstance(v, str):
            # Handle empty string
            if len(v.strip()) == 0:
                return ["*"]
            
            # Handle special case where Azure CLI strips quotes: [*] -> ["*"]
            if v == "[*]":
                return ["*"]
            elif v.startswith("[") and v.endswith("]") and "*" in v:
                # Handle cases like [GET,POST,PUT,DELETE] -> ["GET","POST","PUT","DELETE"]
                content = v[1:-1]  # Remove brackets
                return [item.strip() for item in content.split(',') if item.strip()]
            
            # Try to parse as JSON first
            try:
                import json
                return json.loads(v)
            except (json.JSONDecodeError, TypeError):
                # Fall back to comma-separated values
                return [item.strip() for item in v.split(',') if item.strip()]
        
        # If it's already a list, return it
        if isinstance(v, list):
            return v
        
        return ["*"]
    
    # Rate limiting
    rate_limit_per_minute: int = Field(default=100, ge=1, le=1000, description="Rate limit per minute")
    rate_limit_burst: int = Field(default=200, ge=1, le=2000, description="Rate limit burst size")
    
    # Session security
    session_timeout_minutes: int = Field(default=30, ge=5, le=480, description="Session timeout in minutes")
    max_login_attempts: int = Field(default=5, ge=3, le=10, description="Maximum login attempts")
    lockout_duration_minutes: int = Field(default=15, ge=5, le=60, description="Lockout duration in minutes")
    
    @field_validator('encryption_key')
    @classmethod
    def validate_encryption_key(cls, v):
        """Validate encryption key is 32 bytes."""
        if not v:
            raise ValueError("Encryption key is required")
        
        # Handle None or empty SecretStr
        try:
            secret_value = v.get_secret_value()
            if not secret_value or len(secret_value.strip()) == 0:
                raise ValueError("Encryption key cannot be empty")
        except Exception as e:
            raise ValueError(f"Encryption key is invalid: {e}")
        
        # Try to decode as base64
        try:
            decoded = base64.b64decode(secret_value)
            if len(decoded) != 32:
                raise ValueError("Encryption key must be 32 bytes when base64 decoded")
        except Exception:
            # If not base64, check if it's 32 characters (assuming hex)
            if len(secret_value) != 64:  # 32 bytes = 64 hex characters
                raise ValueError("Encryption key must be 32 bytes (64 hex characters) or base64 encoded")
        
        return v
    
    @field_validator('jwt_secret')
    @classmethod
    def validate_jwt_secret(cls, v):
        """Validate JWT secret is strong enough."""
        secret = v.get_secret_value()
        if len(secret) < 32:
            raise ValueError("JWT secret must be at least 32 characters")
        return v
    
    model_config = SettingsConfigDict(
        env_prefix="SECURITY_",
        case_sensitive=False,
        json_schema_extra={
            "cors_origins": {"type": "string"},
            "cors_methods": {"type": "string"},
            "cors_headers": {"type": "string"}
        }
    )


class CryptoConfig(BaseSettings):
    """Cryptographic keys configuration."""
    clinic_token_hmac_key_base64: SecretStr = Field(..., description="HMAC key for clinic tokens (base64)")
    aes_gcm_key_base64: SecretStr = Field(..., description="AES-GCM key for encryption (base64)")
    
    @field_validator('clinic_token_hmac_key_base64', 'aes_gcm_key_base64')
    @classmethod
    def validate_base64_key(cls, v):
        if not v:
            raise ValueError("Crypto key is required")
        try:
            decoded = base64.b64decode(v.get_secret_value())
            if len(decoded) == 0:
                raise ValueError("Crypto key cannot be empty")
        except Exception as e:
            raise ValueError(f"Invalid base64 key: {e}")
        return v
    
    model_config = SettingsConfigDict(
        env_prefix="",  # No prefix, use exact names
        case_sensitive=False  # Allow lowercase env vars
    )


class LoggingConfig(BaseSettings):
    """Logging configuration with validation."""
    
    # Log levels
    level: str = Field(
        default="INFO", 
        pattern="^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$",
        description="Logging level"
    )
    format: str = Field(
        default="json", 
        pattern="^(json|text)$",
        description="Log format (json or text)"
    )
    
    # File logging (disabled for Azure Log Analytics)
    file_enabled: bool = Field(default=False, description="Enable file logging")
    file_path: str = Field(default="logs/app.log", description="Log file path")
    file_max_size_mb: int = Field(default=100, ge=1, le=1000, description="Max log file size in MB")
    file_backup_count: int = Field(default=5, ge=1, le=20, description="Number of backup files")
    
    # Structured logging
    structured_enabled: bool = Field(default=True, description="Enable structured logging")
    phi_masking_enabled: bool = Field(default=True, description="Enable PHI masking")
    performance_logging_enabled: bool = Field(default=True, description="Enable performance logging")
    security_logging_enabled: bool = Field(default=True, description="Enable security logging")
    
    # Audit logging
    audit_enabled: bool = Field(default=True, description="Enable audit logging")
    audit_file_path: str = Field(default="logs/audit.log", description="Audit log file path")
    audit_retention_days: int = Field(default=2555, ge=365, le=3650, description="Audit log retention in days (7 years)")
    
    model_config = SettingsConfigDict(
        env_prefix="LOG_",
        case_sensitive=False
    )


class GoogleCalendarConfig(BaseSettings):
    """Google Calendar configuration with validation."""
    
    # OAuth settings
    client_id: str = Field(default="182784858615-03lp1s2iq84989j22v4mabnaomp8uco8.apps.googleusercontent.com", description="Google OAuth client ID")
    client_secret: SecretStr = Field(default="", description="Google OAuth client secret")
    redirect_uri: str = Field(default="http://localhost:8443/auth/callback", description="Google OAuth redirect URI")
    
    # API settings
    api_key: SecretStr = Field(default="", description="Google Calendar API key")
    hipaa_compliant: bool = Field(default=False, description="HIPAA compliant workspace")
    scopes: List[str] = Field(
        default=["https://www.googleapis.com/auth/calendar"],
        description="Google Calendar API scopes"
    )
    
    # Rate limiting
    requests_per_minute: int = Field(default=100, ge=1, le=1000, description="API requests per minute")
    requests_per_day: int = Field(default=10000, ge=100, le=100000, description="API requests per day")
    
    # Sync settings
    sync_interval_minutes: int = Field(default=5, ge=1, le=60, description="Sync interval in minutes")
    max_sync_retries: int = Field(default=3, ge=1, le=10, description="Maximum sync retries")
    sync_timeout_seconds: int = Field(default=30, ge=5, le=120, description="Sync timeout in seconds")
    
    @field_validator('client_id')
    @classmethod
    def validate_client_id(cls, v):
        """Validate Google client ID format."""
        if not v or not v.endswith('.apps.googleusercontent.com'):
            raise ValueError("Invalid Google client ID format")
        return v
    
    @field_validator('redirect_uri')
    @classmethod
    def validate_redirect_uri(cls, v):
        """Validate redirect URI format."""
        if not v or not v.startswith(('http://', 'https://')):
            raise ValueError("Redirect URI must be a valid HTTP/HTTPS URL")
        return v
    
    model_config = SettingsConfigDict(
        env_prefix="GOOGLE_",
        case_sensitive=False
    )


class AzureCommunicationConfig(BaseSettings):
    """Azure Communication Services configuration with validation."""
    
    # Core ACS settings
    connection_string: SecretStr = Field(default="endpoint=https://test.communication.azure.com/;accesskey=test", description="Azure Communication Services connection string")
    phone_number: str = Field(default="+15551234567", description="Azure Communication Services phone number")
    callback_url: str = Field(default="https://localhost:8443/api/v1/callbacks", description="Webhook callback URL for ACS events")
    webhook_secret: SecretStr = Field(..., description="Webhook secret for signature verification")
    
    # Call settings
    max_call_duration_minutes: int = Field(default=30, ge=1, le=120, description="Maximum call duration in minutes")
    
    # Rate limiting
    requests_per_minute: int = Field(default=100, ge=1, le=1000, description="ACS requests per minute")
    
    @field_validator('connection_string')
    @classmethod
    def validate_connection_string(cls, v):
        """Validate ACS connection string format."""
        if not v or not v.get_secret_value().startswith('endpoint='):
            raise ValueError("Invalid ACS connection string format")
        return v
    
    @field_validator('phone_number')
    @classmethod
    def validate_phone_number(cls, v):
        """Validate phone number format."""
        if not v or not v.startswith('+'):
            raise ValueError("Phone number must include country code (e.g., +1234567890)")
        return v
    
    @field_validator('callback_url')
    @classmethod
    def validate_callback_url(cls, v):
        """Validate callback URL format."""
        if not v or not (v.startswith('https://') or v.startswith('http://')):
            raise ValueError("Callback URL must be a valid HTTP or HTTPS URL")
        return v
    
    model_config = SettingsConfigDict(
        env_prefix="ACS_",
        case_sensitive=False
    )


class AzureSpeechConfig(BaseSettings):
    """Azure Speech Services configuration with validation."""
    
    # Core Speech settings
    speech_key: SecretStr = Field(default="test_speech_key_32_characters_long", description="Azure Speech Services API key")
    speech_region: str = Field(default="eastus", description="Azure Speech Services region")
    
    # STT settings
    stt_language_primary: str = Field(default="en-US", description="Primary STT language")
    stt_language_secondary: str = Field(default="es-ES", description="Secondary STT language")
    
    # TTS settings
    tts_voice_en: str = Field(default="en-US-JennyNeural", description="English TTS voice")
    tts_voice_es: str = Field(default="es-MX-DaliaNeural", description="Spanish TTS voice")
    
    # Processing settings
    enable_profanity_filter: bool = Field(default=True, description="Enable profanity filtering")
    
    # Rate limiting
    requests_per_minute: int = Field(default=60, ge=1, le=1000, description="Speech requests per minute")
    
    @field_validator('speech_region')
    @classmethod
    def validate_speech_region(cls, v):
        """Validate Azure region."""
        valid_regions = ['eastus', 'eastus2', 'westus', 'westus2', 'centralus', 'northcentralus', 
                        'southcentralus', 'westcentralus', 'canadacentral', 'canadaeast', 
                        'brazilsouth', 'eastasia', 'southeastasia', 'australiaeast', 'australiasoutheast',
                        'centralindia', 'southindia', 'westindia', 'japaneast', 'japanwest',
                        'koreacentral', 'koreasouth', 'northeurope', 'westeurope', 'francecentral',
                        'francesouth', 'germanywestcentral', 'germanynorth', 'norwayeast', 'norwaywest',
                        'switzerlandnorth', 'switzerlandwest', 'uksouth', 'ukwest', 'uaenorth', 'uaecentral']
        if not v or v.lower() not in valid_regions:
            raise ValueError(f"Invalid Azure region. Must be one of: {', '.join(valid_regions)}")
        return v.lower()
    
    model_config = SettingsConfigDict(
        env_prefix="AZURE_SPEECH_",
        case_sensitive=False
    )


class AzureOpenAIConfig(BaseSettings):
    """Azure OpenAI configuration with validation."""
    
    # Core OpenAI settings
    endpoint: str = Field(default="https://test.openai.azure.com/", description="Azure OpenAI endpoint")
    api_key: SecretStr = Field(default="test_key", description="Azure OpenAI API key")
    api_version: str = Field(default="2024-02-15-preview", description="Azure OpenAI API version")
    deployment_name: str = Field(default="test_deployment", description="Azure OpenAI deployment name")
    
    # Conversation settings
    max_tokens: int = Field(default=500, ge=1, le=4000, description="Maximum tokens per response")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="Response creativity (0-2)")
    system_prompt_en: str = Field(default="You are a helpful medical receptionist assistant.", description="English system prompt for healthcare context")
    system_prompt_es: str = Field(default="Eres un asistente útil de recepción médica.", description="Spanish system prompt for healthcare context")
    
    # History settings
    enable_conversation_history: bool = Field(default=True, description="Enable conversation history")
    max_history_messages: int = Field(default=10, ge=1, le=50, description="Maximum conversation history messages")
    
    # Intent classification settings
    enable_intent_classification: bool = Field(default=True, description="Enable intent classification")
    intent_confidence_threshold: float = Field(default=0.7, ge=0.0, le=1.0, description="Minimum confidence for intent classification")
    max_intent_retries: int = Field(default=3, ge=1, le=5, description="Maximum intent classification retries")
    
    # Response generation settings
    enable_response_generation: bool = Field(default=True, description="Enable response generation")
    response_timeout_seconds: int = Field(default=30, ge=5, le=120, description="Response generation timeout")
    enable_streaming_responses: bool = Field(default=True, description="Enable streaming responses")
    
    # Context management
    enable_context_awareness: bool = Field(default=True, description="Enable context-aware responses")
    context_window_size: int = Field(default=5, ge=1, le=20, description="Number of previous messages to include in context")
    enable_entity_extraction: bool = Field(default=True, description="Enable entity extraction from conversations")
    
    # Fallback settings
    enable_fallback_responses: bool = Field(default=True, description="Enable fallback responses when OpenAI fails")
    fallback_response_en: str = Field(default="I'm sorry, I didn't understand that. Could you please repeat?", description="English fallback response")
    fallback_response_es: str = Field(default="Lo siento, no entendí eso. ¿Podrías repetir por favor?", description="Spanish fallback response")
    
    # Rate limiting
    requests_per_minute: int = Field(default=60, ge=1, le=1000, description="OpenAI requests per minute")
    
    @field_validator('endpoint')
    @classmethod
    def validate_endpoint(cls, v):
        """Validate OpenAI endpoint format."""
        if not v or not v.startswith('https://'):
            raise ValueError("OpenAI endpoint must be a valid HTTPS URL")
        return v
    
    model_config = SettingsConfigDict(
        env_prefix="AZURE_OPENAI_",
        case_sensitive=False
    )


class RedisCacheConfig(BaseSettings):
    """Redis cache configuration with validation."""
    
    # Connection settings
    host: str = Field(default="localhost", description="Redis host")
    port: int = Field(default=6379, ge=1, le=65535, description="Redis port")
    db: int = Field(default=0, ge=0, le=15, description="Redis database number")
    password: Optional[SecretStr] = Field(default=None, description="Redis password")
    
    # Connection pooling
    max_connections: int = Field(default=50, ge=1, le=200, description="Maximum Redis connections")
    socket_timeout: int = Field(default=5, ge=1, le=60, description="Socket timeout in seconds")
    socket_connect_timeout: int = Field(default=5, ge=1, le=60, description="Socket connect timeout in seconds")
    retry_on_timeout: bool = Field(default=True, description="Retry on timeout")
    health_check_interval: int = Field(default=30, ge=5, le=300, description="Health check interval in seconds")
    
    # Cache settings
    default_ttl: int = Field(default=300, ge=60, le=86400, description="Default TTL in seconds")
    key_prefix: str = Field(default="callcenter:", description="Key prefix for all cache keys")
    
    @field_validator('host')
    @classmethod
    def validate_host(cls, v):
        """Validate Redis host."""
        if not v or not v.strip():
            raise ValueError("Redis host cannot be empty")
        return v.strip()
    
    @field_validator('key_prefix')
    @classmethod
    def validate_key_prefix(cls, v):
        """Validate key prefix format."""
        if not v.endswith(':'):
            v = v + ':'
        return v
    
    model_config = SettingsConfigDict(
        env_prefix="REDIS_",
        case_sensitive=False
    )


class RedisConfig(BaseSettings):
    """Redis configuration for call store."""
    enabled: bool = Field(default=False, description="Enable Redis call store")
    host: str = Field(default="localhost", description="Redis host")
    port: int = Field(default=6379, description="Redis port")
    password: SecretStr = Field(default="", description="Redis password")
    db: int = Field(default=0, description="Redis database number")
    ttl_seconds: int = Field(default=3600, description="Call context TTL")
    
    model_config = SettingsConfigDict(env_prefix="REDIS_")


class AzureConfig(BaseSettings):
    """Azure configuration with validation."""
    
    # Sub-configurations
    communication: AzureCommunicationConfig = Field(default_factory=AzureCommunicationConfig)
    speech: AzureSpeechConfig = Field(default_factory=AzureSpeechConfig)
    openai: AzureOpenAIConfig = Field(default_factory=AzureOpenAIConfig)
    
    # Storage
    storage_account_name: str = Field(default="teststorageaccount", description="Azure Storage account name")
    storage_account_key: SecretStr = Field(default="test_storage_key_64_characters_long_for_development_purposes_only", description="Azure Storage account key")
    storage_container_name: str = Field(default="callcenter", description="Azure Storage container name")
    
    model_config = SettingsConfigDict(
        env_prefix="AZURE_",
        case_sensitive=False
    )


class ApplicationConfig(BaseSettings):
    """Main application configuration."""
    
    # Environment
    environment: str = Field(
        default="development", 
        pattern="^(development|staging|production)$",
        description="Application environment"
    )
    debug: bool = Field(default=False, description="Enable debug mode")
    
    # Server settings
    host: str = Field(default="0.0.0.0", description="Server host")
    port: int = Field(default=8080, ge=1, le=65535, description="Server port")
    workers: int = Field(default=1, ge=1, le=32, description="Number of worker processes")
    
    # API settings
    api_prefix: str = Field(default="/api/v1", description="API prefix")
    api_version: str = Field(default="1.0.0", description="API version")
    api_title: str = Field(default="CallCenter AI API", description="API title")
    api_description: str = Field(default="AI-powered call center management system", description="API description")
    
    # Health checks
    health_check_interval: int = Field(default=30, ge=5, le=300, description="Health check interval in seconds")
    health_check_timeout: int = Field(default=10, ge=1, le=60, description="Health check timeout in seconds")
    
    # Performance
    max_request_size: int = Field(default=10485760, ge=1024, le=104857600, description="Max request size in bytes (10MB)")
    request_timeout: int = Field(default=30, ge=5, le=300, description="Request timeout in seconds")
    
    # Sub-configurations
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    crypto: CryptoConfig = Field(default_factory=CryptoConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    google_calendar: GoogleCalendarConfig = Field(default_factory=GoogleCalendarConfig)
    azure: AzureConfig = Field(default_factory=AzureConfig)
    redis_cache: RedisCacheConfig = Field(default_factory=RedisCacheConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)
    
    model_config = SettingsConfigDict(
        env_prefix="APP_",
        case_sensitive=False
    )


class ConfigurationError(Exception):
    """Raised when required configuration is missing or invalid."""
    pass

def validate_required_settings(settings: ApplicationConfig) -> None:
    """Validate critical settings exist and are properly configured."""
    critical_checks = []
    
    # Azure Communication Services
    try:
        conn_str = settings.azure.communication.connection_string.get_secret_value()
        if not conn_str or len(conn_str) < 10:
            critical_checks.append("azure.communication.connection_string is empty")
    except Exception as e:
        critical_checks.append(f"azure.communication.connection_string: {e}")
    
    # Azure Speech Services
    try:
        speech_key = settings.azure.speech.speech_key.get_secret_value()
        if not speech_key:
            critical_checks.append("azure.speech.speech_key is empty")
        if not settings.azure.speech.speech_region:
            critical_checks.append("azure.speech.speech_region is missing")
    except Exception as e:
        critical_checks.append(f"azure.speech: {e}")
    
    # Database
    try:
        db_pass = settings.database.password.get_secret_value()
        if not db_pass:
            critical_checks.append("database.password is empty")
    except Exception as e:
        critical_checks.append(f"database: {e}")
    
    if critical_checks:
        error_msg = "Critical configuration missing:\n" + "\n".join(f"  - {c}" for c in critical_checks)
        raise ConfigurationError(error_msg)
    
    logger.info("Configuration validation passed")


class TestConfig(ApplicationConfig):
    """Test configuration with overrides."""
    
    # Override database for testing
    database: DatabaseConfig = Field(default_factory=lambda: DatabaseConfig(
        host="localhost",
        port=5432,
        name="callcenter_test",
        user="postgres",
        password="test_password",
        pool_size=5,
        max_overflow=10
    ))
    
    # Override security for testing
    security: SecurityConfig = Field(default_factory=lambda: SecurityConfig(
        encryption_key="test_encryption_key_32_bytes_long_12345",
        jwt_secret="test_jwt_secret_32_characters_long_12345",
        cors_origins=["http://localhost:3000"],
        rate_limit_per_minute=1000
    ))
    
    # Override logging for testing
    logging: LoggingConfig = Field(default_factory=lambda: LoggingConfig(
        level="DEBUG",
        format="text",
        file_enabled=False,
        structured_enabled=False
    ))
    
    # Override Google Calendar for testing
    google_calendar: GoogleCalendarConfig = Field(default_factory=lambda: GoogleCalendarConfig(
        client_id="test_client_id.apps.googleusercontent.com",
        client_secret="test_client_secret",
        redirect_uri="http://localhost:8000/auth/callback",
        api_key="test_api_key"
    ))
    
    # Override Azure for testing
    azure: AzureConfig = Field(default_factory=lambda: AzureConfig(
        communication=AzureCommunicationConfig(
            connection_string="endpoint=https://test.communication.azure.com/;accesskey=test",
            phone_number="+1234567890",
            callback_url="https://test.example.com/webhooks/acs",
            webhook_secret="test_webhook_secret"
        ),
        speech=AzureSpeechConfig(
            speech_key="test_speech_key",
            speech_region="eastus"
        ),
        openai=AzureOpenAIConfig(
            endpoint="https://test.openai.azure.com/",
            api_key="test_api_key",
            deployment_name="test_deployment",
            system_prompt_en="You are a helpful healthcare assistant.",
            system_prompt_es="Eres un asistente de salud útil.",
            enable_intent_classification=True,
            intent_confidence_threshold=0.7,
            max_intent_retries=3,
            enable_response_generation=True,
            response_timeout_seconds=30,
            enable_streaming_responses=True,
            enable_context_awareness=True,
            context_window_size=5,
            enable_entity_extraction=True,
            enable_fallback_responses=True,
            fallback_response_en="I'm sorry, I didn't understand that. Could you please repeat?",
            fallback_response_es="Lo siento, no entendí eso. ¿Podrías repetir por favor?"
        ),
        storage_account_name="teststorage",
        storage_account_key="test_storage_key"
    ))


@lru_cache()
def get_settings() -> ApplicationConfig:
    """
    Get application settings with caching.
    
    Returns:
        ApplicationConfig: Cached application configuration
        
    Raises:
        ValidationError: If configuration validation fails
    """
    try:
        settings = ApplicationConfig()
        logger.info("Configuration loaded successfully", extra={
            "environment": settings.environment,
            "debug": settings.debug,
            "api_version": settings.api_version
        })
        return settings
    except Exception as e:
        logger.error(f"Failed to load configuration: {e}")
        raise


@lru_cache()
def get_test_settings(**overrides) -> TestConfig:
    """
    Get test settings with overrides.
    
    Args:
        **overrides: Configuration overrides for testing
        
    Returns:
        TestConfig: Test configuration with overrides
    """
    try:
        # Create test config with overrides
        test_config = TestConfig()
        
        # Apply overrides
        for key, value in overrides.items():
            if hasattr(test_config, key):
                setattr(test_config, key, value)
        
        logger.info("Test configuration loaded successfully", extra={
            "overrides": list(overrides.keys())
        })
        return test_config
    except Exception as e:
        logger.error(f"Failed to load test configuration: {e}")
        raise


def validate_configuration() -> Dict[str, Any]:
    """
    Validate all configuration settings.
    
    Returns:
        Dict[str, Any]: Validation results
    """
    validation_results = {
        "valid": True,
        "errors": [],
        "warnings": [],
        "settings": {}
    }
    
    try:
        settings = get_settings()
        validation_results["settings"] = {
            "environment": settings.environment,
            "debug": settings.debug,
            "api_version": settings.api_version,
            "database_configured": bool(settings.database.password),
            "security_configured": bool(settings.security.encryption_key),
            "google_calendar_configured": bool(settings.google_calendar.client_id),
            "azure_configured": bool(settings.azure.communication.connection_string)
        }
        
        # Check for common configuration issues
        if settings.environment == "production" and settings.debug:
            validation_results["warnings"].append("Debug mode enabled in production")
        
        if not settings.database.password:
            validation_results["errors"].append("Database password not configured")
            validation_results["valid"] = False
        
        if not settings.security.encryption_key:
            validation_results["errors"].append("Encryption key not configured")
            validation_results["valid"] = False
        
        if settings.database.pool_size > 20 and settings.environment == "development":
            validation_results["warnings"].append("Large pool size for development environment")
        
        # Add checks for crypto keys:
        try:
            if not settings.crypto.clinic_token_hmac_key_base64:
                validation_results["errors"].append("Clinic token HMAC key not configured")
                validation_results["valid"] = False
            
            if not settings.crypto.aes_gcm_key_base64:
                validation_results["errors"].append("AES-GCM key not configured")
                validation_results["valid"] = False
        except Exception as e:
            validation_results["errors"].append(f"Crypto configuration error: {e}")
            validation_results["valid"] = False

        # Add checks for Google Calendar (if client_id is set, require secret):
        if settings.google_calendar.client_id:
            if not settings.google_calendar.client_secret.get_secret_value():
                validation_results["warnings"].append("Google Calendar client ID set but client secret missing")
            if not settings.google_calendar.api_key.get_secret_value():
                validation_results["warnings"].append("Google Calendar client ID set but API key missing")

        # Add checks for Azure services:
        if not settings.azure.communication.webhook_secret.get_secret_value():
            validation_results["warnings"].append("ACS webhook secret not configured - webhooks will fail")

        # Check for test/placeholder values in production:
        if settings.environment == "production":
            if "test" in settings.azure.communication.connection_string.get_secret_value().lower():
                validation_results["errors"].append("Test Azure Communication Services connection string in production")
                validation_results["valid"] = False
            
            if settings.azure.openai.api_key.get_secret_value() == "test_key":
                validation_results["errors"].append("Test Azure OpenAI API key in production")
                validation_results["valid"] = False
            
            if "your_" in settings.google_calendar.api_key.get_secret_value().lower():
                validation_results["warnings"].append("Placeholder Google API key detected")

        # CORS validation:
        if settings.environment == "production" and "*" in settings.security.cors_origins:
            validation_results["errors"].append("Wildcard CORS origins not allowed in production")
            validation_results["valid"] = False
        
        logger.info("Configuration validation completed", extra=validation_results)
        
    except Exception as e:
        validation_results["valid"] = False
        validation_results["errors"].append(f"Configuration validation failed: {e}")
        logger.error(f"Configuration validation failed: {e}")
    
    return validation_results


def get_database_url() -> str:
    """
    Get database URL from configuration.
    
    Returns:
        str: Database URL
    """
    settings = get_settings()
    return f"postgresql://{settings.database.user}:{settings.database.password.get_secret_value()}@{settings.database.host}:{settings.database.port}/{settings.database.name}"


def get_redis_url() -> str:
    """
    Get Redis URL from configuration.
    
    Returns:
        str: Redis URL
    """
    settings = get_settings()
    redis_config = settings.redis_cache
    
    # Build Redis URL with authentication if password is provided
    if redis_config.password:
        password = redis_config.password.get_secret_value()
        return f"redis://:{password}@{redis_config.host}:{redis_config.port}/{redis_config.db}"
    else:
        return f"redis://{redis_config.host}:{redis_config.port}/{redis_config.db}"


def get_environment_info() -> Dict[str, Any]:
    """
    Get environment information for debugging.
    
    Returns:
        Dict[str, Any]: Environment information
    """
    settings = get_settings()
    
    return {
        "environment": settings.environment,
        "debug": settings.debug,
        "api_version": settings.api_version,
        "database_host": settings.database.host,
        "database_port": settings.database.port,
        "database_name": settings.database.name,
        "pool_size": settings.database.pool_size,
        "log_level": settings.logging.level,
        "log_format": settings.logging.format,
        "cors_origins": settings.security.cors_origins,
        "rate_limit": settings.security.rate_limit_per_minute,
        "health_check_interval": settings.health_check_interval,
        "max_request_size": settings.max_request_size,
        "request_timeout": settings.request_timeout
    }


# Global settings instance
settings = get_settings()
