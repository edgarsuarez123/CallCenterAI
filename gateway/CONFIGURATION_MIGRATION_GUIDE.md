# Configuration Management Migration Guide

## Overview

This guide helps you migrate from the old manual configuration system to the new Pydantic-based configuration management system. The new system provides type safety, validation, environment-specific configs, and self-documenting configuration.

## What's New

### Benefits of the New System
- **Type Safety**: Configuration values are validated at startup
- **Validation**: Range checks, format validation, and business rule enforcement
- **Environment-Specific**: Easy management of dev/staging/production configs
- **Self-Documenting**: Clear descriptions and validation rules
- **Default Values**: Works out-of-the-box with sensible defaults
- **Testing Support**: Easy configuration overrides for tests
- **Performance**: Cached configuration for fast access
- **Security**: Proper secret handling and validation

### New Configuration Structure
The new system organizes configuration into logical groups:
- **Application**: Server settings, API configuration, health checks
- **Database**: Connection settings, pooling, transaction isolation
- **Security**: Encryption, JWT, CORS, rate limiting, session management
- **Logging**: Log levels, formats, file settings, structured logging
- **Google Calendar**: OAuth, API settings, rate limiting, sync settings
- **Azure**: Communication Services, OpenAI, Storage configuration

## Migration Steps

### Step 1: Backup Current Configuration

Before making any changes, backup your current configuration:

```bash
# Backup current environment variables
cp .env .env.backup

# Backup docker-compose files
cp compose/gateway.yaml compose/gateway.yaml.backup
```

### Step 2: Update Environment Variables

#### Old Environment Variables
```bash
# Old format
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_DB=callcenterai
POSTGRES_USER=callcenterai
POSTGRES_PASSWORD=ChangeThisNow_!
APP_ENV=dev
PYTHONPATH=/app
CLINIC_TOKEN_HMAC_KEY_BASE64=your_key
AES_GCM_KEY_BASE64=your_key
GOOGLE_CLIENT_ID=your_id
GOOGLE_CLIENT_SECRET=your_secret
GOOGLE_REDIRECT_URI=http://localhost:8443/api/v1/google-calendar/oauth/callback
```

#### New Environment Variables
```bash
# Application Configuration
APP_ENVIRONMENT=development
APP_DEBUG=false
APP_HOST=0.0.0.0
APP_PORT=8000
APP_WORKERS=1
APP_API_PREFIX=/api/v1
APP_API_VERSION=1.0.0
APP_API_TITLE=CallCenter AI API
APP_API_DESCRIPTION=AI-powered call center management system

# Database Configuration
DB_HOST=postgres
DB_PORT=5432
DB_NAME=callcenterai
DB_USER=callcenterai
DB_PASSWORD=ChangeThisNow_!
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=20
DB_POOL_TIMEOUT=30
DB_POOL_RECYCLE=3600
DB_POOL_PRE_PING=true

# Security Configuration
SECURITY_ENCRYPTION_KEY=your_32_byte_encryption_key_here
SECURITY_JWT_SECRET=your_jwt_secret_at_least_32_characters_long
SECURITY_CORS_ORIGINS=["*"]
SECURITY_RATE_LIMIT_PER_MINUTE=100

# Logging Configuration
LOG_LEVEL=INFO
LOG_FORMAT=json
LOG_STRUCTURED_ENABLED=true
LOG_PHI_MASKING_ENABLED=true

# Google Calendar Configuration
GOOGLE_CLIENT_ID=your_client_id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your_client_secret
GOOGLE_REDIRECT_URI=http://localhost:8000/auth/callback

# Legacy Configuration (for backward compatibility)
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_DB=callcenterai
POSTGRES_USER=callcenterai
POSTGRES_PASSWORD=ChangeThisNow_!
APP_ENV=dev
PYTHONPATH=/app
CLINIC_TOKEN_HMAC_KEY_BASE64=your_key
AES_GCM_KEY_BASE64=your_key
```

### Step 3: Generate New Configuration

Use the configuration manager to generate a new configuration file:

```bash
# Generate development configuration
python config_manager.py generate --environment development --output .env.new

# Review the generated configuration
cat .env.new

# Replace old configuration
mv .env.new .env
```

### Step 4: Update Docker Compose

Update your `docker-compose.yaml` or `compose/gateway.yaml` file:

```yaml
services:
  gateway:
    environment:
      # Application Configuration
      - APP_ENVIRONMENT=development
      - APP_DEBUG=true
      - APP_HOST=0.0.0.0
      - APP_PORT=8000
      
      # Database Configuration
      - DB_HOST=postgres
      - DB_PORT=5432
      - DB_NAME=callcenterai
      - DB_USER=callcenterai
      - DB_PASSWORD=ChangeThisNow_!
      - DB_POOL_SIZE=5
      - DB_MAX_OVERFLOW=10
      
      # Security Configuration
      - SECURITY_ENCRYPTION_KEY=your_32_byte_encryption_key_here
      - SECURITY_JWT_SECRET=your_jwt_secret_at_least_32_characters_long
      - SECURITY_CORS_ORIGINS=["http://localhost:3000", "http://localhost:8000"]
      
      # Logging Configuration
      - LOG_LEVEL=DEBUG
      - LOG_FORMAT=json
      - LOG_STRUCTURED_ENABLED=true
      
      # Google Calendar Configuration
      - GOOGLE_CLIENT_ID=your_client_id.apps.googleusercontent.com
      - GOOGLE_CLIENT_SECRET=your_client_secret
      - GOOGLE_REDIRECT_URI=http://localhost:8000/auth/callback
      
      # Legacy Configuration (for backward compatibility)
      - PYTHONPATH=/app
      - APP_ENV=dev
```

### Step 5: Validate Configuration

Validate your new configuration:

```bash
# Validate configuration
python validate_config.py

# Test configuration loading
python config_manager.py test

# Show current configuration
python config_manager.py show
```

### Step 6: Update Application Code

The application code has been updated to use the new configuration system. Key changes:

#### Database Configuration
```python
# Old way
import os
DB_HOST = os.getenv("POSTGRES_HOST", "localhost")
DB_PORT = int(os.getenv("POSTGRES_PORT", "5432"))

# New way
from services.configuration import get_settings
settings = get_settings()
db_host = settings.database.host
db_port = settings.database.port
```

#### Security Configuration
```python
# Old way
import os
JWT_SECRET = os.getenv("JWT_SECRET", "default_secret")

# New way
from services.configuration import get_settings
settings = get_settings()
jwt_secret = settings.security.jwt_secret.get_secret_value()
```

#### Google Calendar Configuration
```python
# Old way
import os
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")

# New way
from services.configuration import get_settings
settings = get_settings()
client_id = settings.google_calendar.client_id
```

### Step 7: Test the Migration

1. **Start the application**:
   ```bash
   # Using Docker Compose
   docker-compose up -d

   # Or directly
   python main.py
   ```

2. **Check health endpoints**:
   ```bash
   curl http://localhost:8000/healthz
   curl http://localhost:8000/health/database
   ```

3. **Validate configuration**:
   ```bash
   python validate_config.py --verbose
   ```

4. **Test API endpoints**:
   ```bash
   curl http://localhost:8000/api/v1/clinics
   ```

## Environment-Specific Migration

### Development Environment
```bash
# Generate development configuration
python config_manager.py generate --environment development --output .env.dev

# Key settings for development
APP_ENVIRONMENT=development
APP_DEBUG=true
LOG_LEVEL=DEBUG
DB_POOL_SIZE=5
SECURITY_CORS_ORIGINS=["http://localhost:3000", "http://localhost:8000"]
SECURITY_RATE_LIMIT_PER_MINUTE=1000
```

### Staging Environment
```bash
# Generate staging configuration
python config_manager.py generate --environment staging --output .env.staging

# Key settings for staging
APP_ENVIRONMENT=staging
APP_DEBUG=false
LOG_LEVEL=INFO
DB_POOL_SIZE=10
SECURITY_CORS_ORIGINS=["https://staging.yourdomain.com"]
SECURITY_RATE_LIMIT_PER_MINUTE=200
```

### Production Environment
```bash
# Generate production configuration
python config_manager.py generate --environment production --output .env.prod

# Key settings for production
APP_ENVIRONMENT=production
APP_DEBUG=false
LOG_LEVEL=WARNING
DB_POOL_SIZE=20
SECURITY_CORS_ORIGINS=["https://yourdomain.com"]
SECURITY_RATE_LIMIT_PER_MINUTE=100
```

## Common Migration Issues

### Issue 1: Missing Required Environment Variables
```
Error: Encryption key is required
Solution: Set SECURITY_ENCRYPTION_KEY environment variable
```

**Fix**:
```bash
# Generate a secure encryption key
python -c "import secrets, base64; print(base64.b64encode(secrets.token_bytes(32)).decode())"

# Set the environment variable
export SECURITY_ENCRYPTION_KEY=your_generated_key_here
```

### Issue 2: Invalid Configuration Values
```
Error: pool_size must be between 1 and 50
Solution: Check DB_POOL_SIZE value
```

**Fix**:
```bash
# Check current value
echo $DB_POOL_SIZE

# Set valid value
export DB_POOL_SIZE=10
```

### Issue 3: Google Calendar Configuration
```
Error: Invalid Google client ID format
Solution: Ensure client ID ends with .apps.googleusercontent.com
```

**Fix**:
```bash
# Check current value
echo $GOOGLE_CLIENT_ID

# Ensure it ends with .apps.googleusercontent.com
export GOOGLE_CLIENT_ID=your_client_id.apps.googleusercontent.com
```

### Issue 4: CORS Configuration
```
Error: CORS origins must be a list
Solution: Use proper JSON array format
```

**Fix**:
```bash
# Wrong format
SECURITY_CORS_ORIGINS=*

# Correct format
SECURITY_CORS_ORIGINS=["*"]

# Or for specific origins
SECURITY_CORS_ORIGINS=["http://localhost:3000", "https://yourdomain.com"]
```

## Rollback Plan

If you need to rollback to the old configuration system:

1. **Restore backup files**:
   ```bash
   cp .env.backup .env
   cp compose/gateway.yaml.backup compose/gateway.yaml
   ```

2. **Revert code changes**:
   ```bash
   git checkout HEAD~1 -- gateway/main.py
   git checkout HEAD~1 -- gateway/services/database.py
   ```

3. **Restart services**:
   ```bash
   docker-compose down
   docker-compose up -d
   ```

## Validation Checklist

Before considering the migration complete, verify:

- [ ] All environment variables are set correctly
- [ ] Configuration validation passes without errors
- [ ] Application starts successfully
- [ ] Health check endpoints respond correctly
- [ ] Database connection works
- [ ] Google Calendar integration works (if configured)
- [ ] Logging is working correctly
- [ ] API endpoints respond correctly
- [ ] No configuration warnings in logs

## Post-Migration Tasks

### 1. Update Documentation
- Update deployment documentation
- Update environment variable documentation
- Update troubleshooting guides

### 2. Update CI/CD Pipelines
- Update environment variable configuration
- Update validation steps
- Update deployment scripts

### 3. Monitor Application
- Monitor logs for configuration-related errors
- Monitor performance metrics
- Monitor health check endpoints

### 4. Clean Up
- Remove old environment variables (after confirming everything works)
- Update team documentation
- Train team on new configuration system

## Support and Troubleshooting

### Configuration Validation
```bash
# Validate configuration
python validate_config.py

# Show detailed validation results
python validate_config.py --verbose

# Validate specific environment
python validate_config.py --environment production
```

### Configuration Management
```bash
# Generate new configuration
python config_manager.py generate --environment production

# Show current configuration
python config_manager.py show

# Test configuration
python config_manager.py test
```

### Common Commands
```bash
# Check environment variables
env | grep -E "(APP_|DB_|SECURITY_|LOG_|GOOGLE_|AZURE_)"

# Test database connection
python -c "from services.database import test_database_connection; test_database_connection()"

# Test configuration loading
python -c "from services.configuration import get_settings; print(get_settings().environment)"
```

## Conclusion

The new configuration management system provides significant improvements in type safety, validation, and maintainability. While the migration requires some effort, the benefits far outweigh the costs:

- **Reduced Runtime Errors**: Configuration validation catches errors at startup
- **Better Security**: Proper secret handling and validation
- **Easier Maintenance**: Self-documenting configuration with clear validation rules
- **Environment Management**: Easy switching between development, staging, and production
- **Testing Support**: Easy configuration overrides for tests

Follow this guide carefully, and you'll have a robust, maintainable configuration system that will serve your application well into the future.
