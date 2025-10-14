# Configuration Management with Pydantic Guide

## Overview

This guide explains the comprehensive configuration management system implemented using Pydantic for the CallCenterAI application. The system provides type safety, validation, environment-specific configs, and self-documenting configuration.

## Why Configuration Management with Pydantic is Critical

### 1. Type Safety at Startup
- **Prevents Runtime Errors**: `pool_size: int` ensures it's a number, not "ten"
- **Early Failure Detection**: Catches config errors before code runs
- **No Runtime Type Errors**: Prevents crashes from bad configuration
- **Better Error Messages**: Clear validation errors instead of cryptic runtime failures

### 2. Validation Before Runtime
- **Range Validation**: `Field(ge=1, le=50)` ensures pool_size between 1-50
- **Format Validation**: Validates email formats, URL formats, etc.
- **Business Rule Enforcement**: Ensures configuration values make sense
- **Clear Error Messages**: "pool_size must be between 1 and 50"

### 3. Environment-Specific Configs
- **Development**: `DEBUG=true`, `LOG_LEVEL=DEBUG`
- **Staging**: `DEBUG=false`, `LOG_LEVEL=INFO`
- **Production**: `DEBUG=false`, `LOG_LEVEL=WARNING`
- **Same Code, Different Config**: Easy to manage multiple environments

### 4. Self-Documenting Configuration
- **Field Descriptions**: `Field(description="Database pool size")` explains purpose
- **Automatic Documentation**: Generate docs from configuration schema
- **Developer Clarity**: New developers understand config options
- **Reduces Questions**: "What does this setting do?" becomes self-evident

### 5. Default Values
- **Out-of-Box Experience**: `pool_size: int = 10` provides sensible default
- **Minimal Configuration**: Works without extensive setup
- **Override Only What You Need**: Change only necessary values
- **Reduces Complexity**: Less configuration to manage

### 6. Testing with Overrides
- **Easy Test Configs**: `get_test_settings(database_url="test_db")`
- **Isolated Testing**: No need to modify environment variables
- **Test-Specific Settings**: Different configs for different test scenarios
- **No Environment Pollution**: Tests don't affect each other

### 7. Caching for Performance
- **Single Load**: `@lru_cache()` loads config once
- **Fast Access**: No repeated file reads or environment variable parsing
- **Consistent Values**: Same config throughout application lifecycle
- **Memory Efficient**: Cached in memory, not recreated

### 8. Secret Validation
- **Encryption Key Validation**: Ensures 32-byte keys for PHI encryption
- **JWT Secret Strength**: Validates minimum length for security
- **Format Validation**: Validates base64 encoding, URL formats, etc.
- **Early Error Detection**: Catches setup errors before runtime

## Configuration Structure

### Main Configuration Classes

#### 1. DatabaseConfig
```python
class DatabaseConfig(BaseSettings):
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
```

#### 2. SecurityConfig
```python
class SecurityConfig(BaseSettings):
    # Encryption
    encryption_key: SecretStr = Field(..., description="32-byte encryption key for PHI")
    jwt_secret: SecretStr = Field(..., description="JWT signing secret")
    jwt_algorithm: str = Field(default="HS256", description="JWT algorithm")
    jwt_expiration_hours: int = Field(default=24, ge=1, le=168, description="JWT expiration in hours")
    
    # CORS
    cors_origins: List[str] = Field(default=["*"], description="Allowed CORS origins")
    cors_methods: List[str] = Field(default=["GET", "POST", "PUT", "DELETE"], description="Allowed CORS methods")
    cors_headers: List[str] = Field(default=["*"], description="Allowed CORS headers")
    
    # Rate limiting
    rate_limit_per_minute: int = Field(default=100, ge=1, le=1000, description="Rate limit per minute")
    rate_limit_burst: int = Field(default=200, ge=1, le=2000, description="Rate limit burst size")
```

#### 3. LoggingConfig
```python
class LoggingConfig(BaseSettings):
    # Log levels
    level: str = Field(default="INFO", regex="^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$", description="Logging level")
    format: str = Field(default="json", regex="^(json|text)$", description="Log format (json or text)")
    
    # File logging
    file_enabled: bool = Field(default=True, description="Enable file logging")
    file_path: str = Field(default="logs/app.log", description="Log file path")
    file_max_size_mb: int = Field(default=100, ge=1, le=1000, description="Max log file size in MB")
    file_backup_count: int = Field(default=5, ge=1, le=20, description="Number of backup files")
    
    # Structured logging
    structured_enabled: bool = Field(default=True, description="Enable structured logging")
    phi_masking_enabled: bool = Field(default=True, description="Enable PHI masking")
    performance_logging_enabled: bool = Field(default=True, description="Enable performance logging")
    security_logging_enabled: bool = Field(default=True, description="Enable security logging")
```

#### 4. GoogleCalendarConfig
```python
class GoogleCalendarConfig(BaseSettings):
    # OAuth settings
    client_id: str = Field(..., description="Google OAuth client ID")
    client_secret: SecretStr = Field(..., description="Google OAuth client secret")
    redirect_uri: str = Field(..., description="Google OAuth redirect URI")
    
    # API settings
    api_key: SecretStr = Field(..., description="Google Calendar API key")
    scopes: List[str] = Field(default=["https://www.googleapis.com/auth/calendar"], description="Google Calendar API scopes")
    
    # Rate limiting
    requests_per_minute: int = Field(default=100, ge=1, le=1000, description="API requests per minute")
    requests_per_day: int = Field(default=10000, ge=100, le=100000, description="API requests per day")
```

#### 5. AzureConfig
```python
class AzureConfig(BaseSettings):
    # Communication Services
    acs_connection_string: SecretStr = Field(..., description="Azure Communication Services connection string")
    acs_phone_number: str = Field(..., description="Azure Communication Services phone number")
    
    # OpenAI
    openai_endpoint: str = Field(..., description="Azure OpenAI endpoint")
    openai_api_key: SecretStr = Field(..., description="Azure OpenAI API key")
    openai_api_version: str = Field(default="2024-02-15-preview", description="Azure OpenAI API version")
    openai_deployment_name: str = Field(..., description="Azure OpenAI deployment name")
    
    # Storage
    storage_account_name: str = Field(..., description="Azure Storage account name")
    storage_account_key: SecretStr = Field(..., description="Azure Storage account key")
    storage_container_name: str = Field(default="callcenter", description="Azure Storage container name")
```

## Environment Variables

### Database Configuration
```bash
# Database connection
DB_HOST=localhost
DB_PORT=5432
DB_NAME=callcenter
DB_USER=postgres
DB_PASSWORD=your_password

# Connection pooling
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=20
DB_POOL_TIMEOUT=30
DB_POOL_RECYCLE=3600
DB_POOL_PRE_PING=true

# Connection arguments
DB_CONNECT_TIMEOUT=10
DB_APPLICATION_NAME=CallCenterAI
DB_DEFAULT_TRANSACTION_ISOLATION=read_committed
```

### Security Configuration
```bash
# Encryption
SECURITY_ENCRYPTION_KEY=your_32_byte_encryption_key_here
SECURITY_JWT_SECRET=your_jwt_secret_at_least_32_characters_long

# CORS
SECURITY_CORS_ORIGINS=["http://localhost:3000", "https://yourdomain.com"]
SECURITY_CORS_METHODS=["GET", "POST", "PUT", "DELETE"]
SECURITY_CORS_HEADERS=["*"]

# Rate limiting
SECURITY_RATE_LIMIT_PER_MINUTE=100
SECURITY_RATE_LIMIT_BURST=200

# Session security
SECURITY_SESSION_TIMEOUT_MINUTES=30
SECURITY_MAX_LOGIN_ATTEMPTS=5
SECURITY_LOCKOUT_DURATION_MINUTES=15
```

### Logging Configuration
```bash
# Log levels
LOG_LEVEL=INFO
LOG_FORMAT=json

# File logging
LOG_FILE_ENABLED=true
LOG_FILE_PATH=logs/app.log
LOG_FILE_MAX_SIZE_MB=100
LOG_FILE_BACKUP_COUNT=5

# Structured logging
LOG_STRUCTURED_ENABLED=true
LOG_PHI_MASKING_ENABLED=true
LOG_PERFORMANCE_LOGGING_ENABLED=true
LOG_SECURITY_LOGGING_ENABLED=true

# Audit logging
LOG_AUDIT_ENABLED=true
LOG_AUDIT_FILE_PATH=logs/audit.log
LOG_AUDIT_RETENTION_DAYS=2555
```

### Google Calendar Configuration
```bash
# OAuth settings
GOOGLE_CLIENT_ID=your_client_id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your_client_secret
GOOGLE_REDIRECT_URI=http://localhost:8000/auth/callback

# API settings
GOOGLE_API_KEY=your_api_key
GOOGLE_SCOPES=["https://www.googleapis.com/auth/calendar"]

# Rate limiting
GOOGLE_REQUESTS_PER_MINUTE=100
GOOGLE_REQUESTS_PER_DAY=10000

# Sync settings
GOOGLE_SYNC_INTERVAL_MINUTES=5
GOOGLE_MAX_SYNC_RETRIES=3
GOOGLE_SYNC_TIMEOUT_SECONDS=30
```

### Azure Configuration
```bash
# Communication Services
AZURE_ACS_CONNECTION_STRING=endpoint=https://your.communication.azure.com/;accesskey=your_key
AZURE_ACS_PHONE_NUMBER=+1234567890

# OpenAI
AZURE_OPENAI_ENDPOINT=https://your.openai.azure.com/
AZURE_OPENAI_API_KEY=your_api_key
AZURE_OPENAI_API_VERSION=2024-02-15-preview
AZURE_OPENAI_DEPLOYMENT_NAME=your_deployment

# Storage
AZURE_STORAGE_ACCOUNT_NAME=your_storage_account
AZURE_STORAGE_ACCOUNT_KEY=your_storage_key
AZURE_STORAGE_CONTAINER_NAME=callcenter

# Rate limiting
AZURE_ACS_REQUESTS_PER_MINUTE=100
AZURE_OPENAI_REQUESTS_PER_MINUTE=60
```

### Application Configuration
```bash
# Environment
APP_ENVIRONMENT=development
APP_DEBUG=false

# Server settings
APP_HOST=0.0.0.0
APP_PORT=8000
APP_WORKERS=1

# API settings
APP_API_PREFIX=/api/v1
APP_API_VERSION=1.0.0
APP_API_TITLE=CallCenter AI API
APP_API_DESCRIPTION=AI-powered call center management system

# Health checks
APP_HEALTH_CHECK_INTERVAL=30
APP_HEALTH_CHECK_TIMEOUT=10

# Performance
APP_MAX_REQUEST_SIZE=10485760
APP_REQUEST_TIMEOUT=30
```

## Usage Examples

### Basic Usage
```python
from services.configuration import get_settings

# Get configuration (cached)
settings = get_settings()

# Access configuration values
print(f"Environment: {settings.environment}")
print(f"Database host: {settings.database.host}")
print(f"Pool size: {settings.database.pool_size}")

# Access secrets
encryption_key = settings.security.encryption_key.get_secret_value()
jwt_secret = settings.security.jwt_secret.get_secret_value()
```

### Testing with Overrides
```python
from services.configuration import get_test_settings

# Get test configuration with overrides
test_settings = get_test_settings(
    environment="testing",
    debug=True,
    port=9000
)

# Use in tests
assert test_settings.environment == "testing"
assert test_settings.debug is True
assert test_settings.port == 9000
```

### Configuration Validation
```python
from services.configuration import validate_configuration

# Validate configuration
validation_results = validate_configuration()

if validation_results["valid"]:
    print("Configuration is valid")
else:
    print("Configuration errors:")
    for error in validation_results["errors"]:
        print(f"  - {error}")
    
    print("Configuration warnings:")
    for warning in validation_results["warnings"]:
        print(f"  - {warning}")
```

### Environment Information
```python
from services.configuration import get_environment_info

# Get environment information for debugging
env_info = get_environment_info()
print(f"Environment: {env_info['environment']}")
print(f"Debug mode: {env_info['debug']}")
print(f"Database host: {env_info['database_host']}")
print(f"Pool size: {env_info['pool_size']}")
```

### Database URL Generation
```python
from services.configuration import get_database_url, get_redis_url

# Get database URL
db_url = get_database_url()
print(f"Database URL: {db_url}")

# Get Redis URL
redis_url = get_redis_url()
print(f"Redis URL: {redis_url}")
```

## Validation Rules

### Database Configuration Validation
- **Port**: Must be between 1 and 65535
- **Pool Size**: Must be between 1 and 50
- **Max Overflow**: Must be between 0 and 100
- **Pool Timeout**: Must be between 1 and 300 seconds
- **Pool Recycle**: Must be between 300 and 86400 seconds
- **Connect Timeout**: Must be between 1 and 60 seconds
- **Transaction Isolation**: Must be one of: read_committed, repeatable_read, serializable

### Security Configuration Validation
- **Encryption Key**: Must be 32 bytes (64 hex characters or base64 encoded)
- **JWT Secret**: Must be at least 32 characters
- **JWT Expiration**: Must be between 1 and 168 hours
- **Rate Limit**: Must be between 1 and 1000 per minute
- **Rate Limit Burst**: Must be between 1 and 2000
- **Session Timeout**: Must be between 5 and 480 minutes
- **Max Login Attempts**: Must be between 3 and 10
- **Lockout Duration**: Must be between 5 and 60 minutes

### Logging Configuration Validation
- **Log Level**: Must be one of: DEBUG, INFO, WARNING, ERROR, CRITICAL
- **Log Format**: Must be one of: json, text
- **File Max Size**: Must be between 1 and 1000 MB
- **File Backup Count**: Must be between 1 and 20
- **Audit Retention**: Must be between 365 and 3650 days (1-10 years)

### Google Calendar Configuration Validation
- **Client ID**: Must end with `.apps.googleusercontent.com`
- **Redirect URI**: Must be a valid HTTP/HTTPS URL
- **Requests Per Minute**: Must be between 1 and 1000
- **Requests Per Day**: Must be between 100 and 100000
- **Sync Interval**: Must be between 1 and 60 minutes
- **Max Sync Retries**: Must be between 1 and 10
- **Sync Timeout**: Must be between 5 and 120 seconds

### Azure Configuration Validation
- **ACS Connection String**: Must start with `endpoint=`
- **OpenAI Endpoint**: Must be a valid HTTPS URL
- **ACS Requests Per Minute**: Must be between 1 and 1000
- **OpenAI Requests Per Minute**: Must be between 1 and 1000

### Application Configuration Validation
- **Environment**: Must be one of: development, staging, production
- **Port**: Must be between 1 and 65535
- **Workers**: Must be between 1 and 32
- **Health Check Interval**: Must be between 5 and 300 seconds
- **Health Check Timeout**: Must be between 1 and 60 seconds
- **Max Request Size**: Must be between 1024 and 104857600 bytes
- **Request Timeout**: Must be between 5 and 300 seconds

## Best Practices

### 1. Environment-Specific Configuration
```bash
# Development
APP_ENVIRONMENT=development
APP_DEBUG=true
LOG_LEVEL=DEBUG
DB_POOL_SIZE=5

# Staging
APP_ENVIRONMENT=staging
APP_DEBUG=false
LOG_LEVEL=INFO
DB_POOL_SIZE=10

# Production
APP_ENVIRONMENT=production
APP_DEBUG=false
LOG_LEVEL=WARNING
DB_POOL_SIZE=20
```

### 2. Secret Management
```bash
# Use strong, unique secrets
SECURITY_ENCRYPTION_KEY=your_32_byte_encryption_key_here
SECURITY_JWT_SECRET=your_jwt_secret_at_least_32_characters_long

# Rotate secrets regularly
# Use environment-specific secrets
# Never commit secrets to version control
```

### 3. Performance Tuning
```bash
# Adjust pool size based on load
DB_POOL_SIZE=20  # For high-traffic applications
DB_MAX_OVERFLOW=40  # Allow temporary spikes

# Optimize rate limits
SECURITY_RATE_LIMIT_PER_MINUTE=200  # For high-traffic APIs
GOOGLE_REQUESTS_PER_MINUTE=150  # Based on API quotas
```

### 4. Monitoring and Alerting
```bash
# Enable comprehensive logging
LOG_STRUCTURED_ENABLED=true
LOG_PERFORMANCE_LOGGING_ENABLED=true
LOG_SECURITY_LOGGING_ENABLED=true

# Set appropriate log levels
LOG_LEVEL=INFO  # For production
LOG_LEVEL=DEBUG  # For development
```

### 5. Security Configuration
```bash
# Restrict CORS origins in production
SECURITY_CORS_ORIGINS=["https://yourdomain.com"]

# Use strong rate limiting
SECURITY_RATE_LIMIT_PER_MINUTE=100
SECURITY_MAX_LOGIN_ATTEMPTS=5

# Enable all security features
LOG_SECURITY_LOGGING_ENABLED=true
LOG_PHI_MASKING_ENABLED=true
```

## Troubleshooting

### Common Issues

#### 1. Configuration Validation Errors
```
Error: Encryption key is required
Solution: Set SECURITY_ENCRYPTION_KEY environment variable

Error: JWT secret must be at least 32 characters
Solution: Use a longer JWT secret

Error: Invalid Google client ID format
Solution: Ensure client ID ends with .apps.googleusercontent.com
```

#### 2. Environment Variable Issues
```
Error: Configuration not loading
Solution: Check environment variable names and prefixes

Error: Default values not applied
Solution: Ensure environment variables are not set incorrectly
```

#### 3. Secret Handling Issues
```
Error: Secret not accessible
Solution: Use .get_secret_value() method for SecretStr objects

Error: Secret exposed in logs
Solution: Secrets are automatically masked in string representations
```

#### 4. Caching Issues
```
Error: Configuration not updating
Solution: Clear cache with get_settings.cache_clear()

Error: Test configuration not isolated
Solution: Use get_test_settings() for tests
```

### Debugging Configuration

#### 1. Validate Configuration
```python
from services.configuration import validate_configuration

validation_results = validate_configuration()
print(f"Valid: {validation_results['valid']}")
print(f"Errors: {validation_results['errors']}")
print(f"Warnings: {validation_results['warnings']}")
```

#### 2. Check Environment Information
```python
from services.configuration import get_environment_info

env_info = get_environment_info()
for key, value in env_info.items():
    print(f"{key}: {value}")
```

#### 3. Test Configuration Loading
```python
from services.configuration import get_settings

try:
    settings = get_settings()
    print("Configuration loaded successfully")
    print(f"Environment: {settings.environment}")
    print(f"Debug: {settings.debug}")
except Exception as e:
    print(f"Configuration loading failed: {e}")
```

## Security Considerations

### 1. Secret Management
- **Never commit secrets to version control**
- **Use environment variables for secrets**
- **Rotate secrets regularly**
- **Use different secrets for different environments**

### 2. Configuration Validation
- **Validate all configuration values**
- **Use strong validation rules**
- **Check for common security misconfigurations**
- **Enable security logging**

### 3. Environment Isolation
- **Use different configurations for different environments**
- **Isolate test configurations**
- **Prevent configuration leakage between environments**

### 4. Access Control
- **Limit access to configuration files**
- **Use secure environment variable management**
- **Monitor configuration changes**
- **Audit configuration access**

## Performance Considerations

### 1. Caching
- **Configuration is cached after first load**
- **No repeated environment variable parsing**
- **Fast access throughout application lifecycle**
- **Memory efficient**

### 2. Validation Performance
- **Validation happens once at startup**
- **No runtime validation overhead**
- **Early error detection**
- **Fail fast approach**

### 3. Memory Usage
- **Configuration objects are lightweight**
- **Secrets are stored securely**
- **No unnecessary data duplication**
- **Efficient memory usage**

## Migration from Manual Configuration

### 1. Identify Current Configuration
```python
# Old way
import os
DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_PORT = int(os.getenv('DB_PORT', '5432'))
DB_PASSWORD = os.getenv('DB_PASSWORD', '')

# New way
from services.configuration import get_settings
settings = get_settings()
db_host = settings.database.host
db_port = settings.database.port
db_password = settings.database.password.get_secret_value()
```

### 2. Update Environment Variables
```bash
# Old format
DB_HOST=localhost
DB_PORT=5432
DB_PASSWORD=password

# New format (same, but with validation)
DB_HOST=localhost
DB_PORT=5432
DB_PASSWORD=password
```

### 3. Update Code
```python
# Old way
if not DB_PASSWORD:
    raise ValueError("Database password not configured")

# New way
# Validation happens automatically at startup
settings = get_settings()
```

### 4. Add Validation
```python
# Old way
if DB_POOL_SIZE < 1 or DB_POOL_SIZE > 50:
    raise ValueError("Invalid pool size")

# New way
# Validation happens automatically
settings = get_settings()
pool_size = settings.database.pool_size  # Guaranteed to be 1-50
```

## Conclusion

The Pydantic-based configuration management system provides:

- **Type Safety**: Prevents runtime errors from bad configuration
- **Validation**: Ensures configuration values are correct
- **Environment Support**: Easy management of different environments
- **Self-Documentation**: Clear understanding of configuration options
- **Default Values**: Works out-of-the-box with minimal setup
- **Testing Support**: Easy configuration overrides for tests
- **Performance**: Cached configuration for fast access
- **Security**: Proper secret handling and validation

This system prevents common configuration issues and provides a robust foundation for the CallCenterAI application.
