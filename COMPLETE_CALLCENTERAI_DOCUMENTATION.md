# CallCenterAI - Complete Documentation

## Table of Contents

1. [System Overview](#system-overview)
2. [Quick Start Guide](#quick-start-guide)
3. [Technical Specification](#technical-specification)
4. [Architecture](#architecture)
5. [Database Schema](#database-schema)
6. [API Documentation](#api-documentation)
7. [Security & HIPAA Compliance](#security--hipaa-compliance)
8. [Setup & Configuration](#setup--configuration)
9. [Deployment Guide](#deployment-guide)
10. [Azure Integration](#azure-integration)
11. [MVP Launch Plan](#mvp-launch-plan)
12. [Troubleshooting](#troubleshooting)
13. [Development Guide](#development-guide)

---

## System Overview

CallCenterAI is a HIPAA-compliant, multi-tenant call center automation system for medical clinics. It provides advanced natural language processing, real-time voice communication, and intelligent appointment management with Azure Cloud Services integration, Google Calendar synchronization, and secure PHI tokenization.

### Key Features

- **HIPAA-Compliant PHI Tokenization** - All sensitive patient data is encrypted and tokenized
- **Multi-Tenant Architecture** - Support for multiple clinics with complete data isolation
- **Natural Language Processing** - Advanced conversational AI for appointment booking
- **Google Calendar Integration** - OAuth authentication and automatic event creation
- **Web-Based Call Simulator** - Interactive testing interface for demos
- **Comprehensive API** - RESTful endpoints for all operations
- **Docker Containerization** - Easy deployment and scaling
- **Azure Services Integration** - Communication Services, Speech Services, OpenAI
- **Real-time Communication** - WebSocket for audio streaming
- **Background Processing** - Async job management with retry logic

---

## Quick Start Guide

### Prerequisites
- Docker and Docker Compose
- Google Cloud Console project with Calendar API enabled
- OAuth 2.0 credentials configured

### Setup
1. **Clone the repository**
   ```bash
   git clone <your-private-repo-url>
   cd CallCenterAI
   ```

2. **Configure environment variables**
   ```bash
   cp env.example .env
   # Edit .env with your actual values
   ```

3. **Start the services**
   ```bash
   docker-compose -f compose/gateway.yaml up -d
   ```

4. **Access the application**
   - API Documentation: http://localhost:8443/docs
   - Call Simulator: http://localhost:8443/call-simulator

---

## Technical Specification

### Technology Stack
- **Backend**: FastAPI (Python 3.11+)
- **Database**: PostgreSQL 16 with Alembic migrations
- **ORM**: SQLAlchemy 2.0+
- **Containerization**: Docker & Docker Compose
- **Authentication**: OAuth 2.0 (Google Calendar)
- **Encryption**: AES-GCM for PHI data
- **Tokenization**: HMAC + ULID for deterministic tokens
- **Azure Services**: Communication Services, Speech Services, OpenAI
- **Real-time Communication**: WebSocket for audio streaming
- **Background Processing**: Async job management with retry logic

### Service Architecture
```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Call Simulator│    │   Gateway API   │    │   PostgreSQL    │
│   (Web UI)      │◄──►│   (FastAPI)     │◄──►│   Database      │
└─────────────────┘    └─────────────────┘    └─────────────────┘
                              │
                              ▼
                       ┌─────────────────┐
                       │ Google Calendar │
                       │   Integration   │
                       └─────────────────┘
                              │
                              ▼
                    ┌─────────────────────┐
                    │   Azure Services    │
                    │ ┌─────────────────┐ │
                    │ │ Communication   │ │
                    │ │ Services (ACS)  │ │
                    │ └─────────────────┘ │
                    │ ┌─────────────────┐ │
                    │ │ Speech Services │ │
                    │ │ (STT/TTS)       │ │
                    │ └─────────────────┘ │
                    │ ┌─────────────────┐ │
                    │ │ OpenAI Service  │ │
                    │ │ (Conversational)│ │
                    │ └─────────────────┘ │
                    └─────────────────────┘
```

---

## Architecture

### Project Structure
```
CallCenterAI/
├── gateway/                 # Main FastAPI application
│   ├── models/             # Database models and schemas
│   ├── routes/             # API endpoints
│   ├── services/           # Business logic
│   └── templates/          # Web templates
├── orchestrator/           # Orchestration service
├── compose/               # Docker compose files
└── docs/                  # Documentation
```

### Key Services
- **Natural Language Processor** - Intent recognition and entity extraction
- **Call Flow Service** - Conversation state management
- **Google Calendar Service** - OAuth and event management
- **Appointment Service** - Scheduling and availability
- **Provider Management** - Doctor and clinic management
- **Call Orchestrator** - Real-time call processing pipeline
- **Call Router** - Intelligent call routing based on caller type and capacity
- **Reminder Service** - Automated appointment reminder calls

---

## Database Schema

### Core Tables

#### 1. Mappings Table
```sql
CREATE TABLE mappings (
    token VARCHAR(64) PRIMARY KEY,
    value_nonce BYTEA NOT NULL,
    value_ciphertext BYTEA NOT NULL,
    value_type VARCHAR(32) NOT NULL,
    call_id VARCHAR(64),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    last_used_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
);
```
**Purpose**: Stores encrypted PHI data with deterministic tokens for HIPAA compliance.

#### 2. Calls Table
```sql
CREATE TABLE calls (
    call_sid VARCHAR(64) PRIMARY KEY,
    call_id VARCHAR(64) UNIQUE NOT NULL,
    caller_phone_token VARCHAR(64),
    clinic_id VARCHAR(64) NOT NULL,
    call_status VARCHAR(20) DEFAULT 'active',
    call_type VARCHAR(50),
    started_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    ended_at TIMESTAMP WITH TIME ZONE,
    duration_seconds INTEGER,
    call_notes_token VARCHAR(64),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```
**Purpose**: Tracks individual phone calls with tokenized caller information.

#### 3. Clinics Table
```sql
CREATE TABLE clinics (
    clinic_id VARCHAR(64) PRIMARY KEY,
    clinic_name VARCHAR(255) NOT NULL,
    phone_number VARCHAR(20) NOT NULL,
    timezone VARCHAR(50) DEFAULT 'America/New_York',
    default_language VARCHAR(10) DEFAULT 'en',
    supported_languages TEXT DEFAULT 'en',
    ehr_system VARCHAR(50) DEFAULT 'google_calendar',
    max_concurrent_calls INTEGER DEFAULT 10,
    queue_timeout_seconds INTEGER DEFAULT 60,
    is_active VARCHAR(10) DEFAULT 'yes',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```
**Purpose**: Multi-tenant clinic configuration with data isolation.

#### 4. Providers Table
```sql
CREATE TABLE providers (
    provider_id VARCHAR(64) PRIMARY KEY,
    clinic_id VARCHAR(64) NOT NULL,
    name_token VARCHAR(64) NOT NULL,
    title VARCHAR(20),
    specialty VARCHAR(100),
    email_token VARCHAR(64),
    phone_token VARCHAR(64),
    is_active VARCHAR(10) DEFAULT 'yes',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```
**Purpose**: Healthcare provider information with tokenized contact details.

#### 5. Appointments Table
```sql
CREATE TABLE appointments (
    appointment_id VARCHAR(64) PRIMARY KEY,
    clinic_id VARCHAR(64) NOT NULL,
    provider_id VARCHAR(64) NOT NULL,
    patient_name_token VARCHAR(64),
    patient_phone_token VARCHAR(64),
    appointment_date DATE NOT NULL,
    appointment_time TIME NOT NULL,
    appointment_type VARCHAR(50),
    status VARCHAR(20) DEFAULT 'scheduled',
    notes_token VARCHAR(64),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```
**Purpose**: Appointment scheduling with tokenized patient information.

---

## API Documentation

### Core Endpoints

#### Health Check
```http
GET /healthz
```
Returns system health status.

#### Call Simulator
```http
POST /api/v1/call-simulator/start
Content-Type: application/json

{
  "caller_phone": "(555) 123-4567",
  "clinic_id": "CLINIC_STPETERS_001"
}
```

```http
POST /api/v1/call-simulator/input
Content-Type: application/json

{
  "call_id": "CALL_123",
  "user_input": "I need to schedule an appointment"
}
```

#### Clinic Management
```http
GET /api/v1/clinics
POST /api/v1/clinics
GET /api/v1/clinics/{clinic_id}
PUT /api/v1/clinics/{clinic_id}
DELETE /api/v1/clinics/{clinic_id}
```

#### Provider Management
```http
GET /api/v1/providers
POST /api/v1/providers
GET /api/v1/providers/{provider_id}
PUT /api/v1/providers/{provider_id}
DELETE /api/v1/providers/{provider_id}
```

#### Appointment Management
```http
GET /api/v1/appointments
POST /api/v1/appointments
GET /api/v1/appointments/{appointment_id}
PUT /api/v1/appointments/{appointment_id}
DELETE /api/v1/appointments/{appointment_id}
```

#### Google Calendar Integration
```http
GET /api/v1/google-calendar/oauth/start
GET /api/v1/google-calendar/oauth/callback
GET /api/v1/google-calendar/events
POST /api/v1/google-calendar/events
```

---

## Security & HIPAA Compliance

### PHI Protection
- **AES-GCM Encryption**: All PHI data encrypted with 256-bit keys
- **Deterministic Tokenization**: Consistent tokens for same PHI values
- **Non-deterministic Tokenization**: Random tokens for unique identifiers
- **Secure Key Management**: Environment-based key configuration
- **Audit Logging**: Comprehensive access and modification tracking

### Security Measures
- **Environment Variables**: Sensitive configuration externalized
- **OAuth 2.0**: Secure Google Calendar integration
- **SSL/TLS**: Encrypted communication channels
- **Input Validation**: Comprehensive data validation and sanitization
- **Rate Limiting**: Protection against abuse and DoS attacks
- **Access Controls**: Role-based permissions and authentication

### HIPAA Compliance Features
- **Data Minimization**: Only necessary PHI collected and stored
- **Encryption at Rest**: All PHI encrypted in database
- **Encryption in Transit**: Secure communication protocols
- **Audit Trails**: Complete logging of PHI access and modifications
- **Access Controls**: Strict authentication and authorization
- **Data Retention**: Configurable retention policies
- **Breach Detection**: Monitoring and alerting systems

---

## Setup & Configuration

### Environment Variables

#### Required Variables
```bash
# Application Configuration
APP_ENVIRONMENT=development
APP_DEBUG=false
APP_HOST=0.0.0.0
APP_PORT=8443

# Database Configuration
DB_HOST=postgres
DB_PORT=5432
DB_NAME=callcenterai
DB_USER=postgres
DB_PASSWORD=ChangeThisNow_!

# Security Configuration
SECURITY_ENCRYPTION_KEY=your_32_byte_encryption_key_here
SECURITY_JWT_SECRET=your_jwt_secret_at_least_32_characters_long

# Google Calendar Configuration
GOOGLE_CLIENT_ID=your_client_id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your_client_secret
GOOGLE_REDIRECT_URI=http://localhost:8443/api/v1/google-calendar/oauth/callback

# Azure Configuration (when available)
AZURE_SPEECH_KEY=your_speech_key
AZURE_SPEECH_REGION=eastus
AZURE_OPENAI_ENDPOINT=https://your.openai.azure.com/
AZURE_OPENAI_API_KEY=your_api_key
```

### Database Setup

#### Using Docker (Recommended)
```bash
# Start PostgreSQL container
docker-compose -f compose/gateway.yaml up postgres -d

# Run migrations
docker-compose -f compose/gateway.yaml exec gateway python migrate.py upgrade
```

#### Manual PostgreSQL Setup
```bash
# Connect to PostgreSQL
psql -U postgres

# Create database and user
CREATE USER callcenterai WITH PASSWORD 'YourSecurePassword123!';
CREATE DATABASE callcenterai OWNER callcenterai;
GRANT ALL PRIVILEGES ON DATABASE callcenterai TO callcenterai;
```

### Google Calendar Setup

1. **Create Google Cloud Console Project**
   - Go to https://console.cloud.google.com/
   - Create new project or select existing

2. **Enable Google Calendar API**
   - Navigate to APIs & Services > Library
   - Search for "Google Calendar API"
   - Click Enable

3. **Create OAuth 2.0 Credentials**
   - Go to APIs & Services > Credentials
   - Click "Create Credentials" > "OAuth 2.0 Client IDs"
   - Configure authorized redirect URIs:
     - Development: `http://localhost:8443/api/v1/google-calendar/oauth/callback`
     - Production: `https://yourdomain.com/api/v1/google-calendar/oauth/callback`

4. **Download Credentials**
   - Download JSON file (DO NOT commit to repository)
   - Extract Client ID and Client Secret for environment variables

---

## Deployment Guide

### Pre-Deployment Security Checklist

1. **Environment Variables Setup**
   - Copy `env.example` to `.env`
   - Generate secure encryption keys
   - Configure Google Calendar OAuth credentials
   - Set up database connection with secure credentials

2. **Google Calendar Setup**
   - Create Google Cloud Console project
   - Enable Google Calendar API
   - Create OAuth 2.0 credentials
   - Configure authorized redirect URIs
   - Download credentials JSON file (DO NOT commit)

3. **Database Security**
   - Use strong database passwords
   - Enable SSL connections
   - Configure proper firewall rules
   - Set up regular backups
   - Use connection pooling for production

4. **Production Security**
   - Use HTTPS with valid SSL certificates
   - Configure proper firewall rules
   - Set up monitoring and logging
   - Implement rate limiting
   - Regular security updates

### Docker Deployment

```bash
# Start all services
docker-compose -f compose/gateway.yaml up -d

# Check service status
docker-compose -f compose/gateway.yaml ps

# View logs
docker-compose -f compose/gateway.yaml logs -f gateway

# Stop services
docker-compose -f compose/gateway.yaml down
```

### Production Deployment

1. **Set up production environment variables**
2. **Configure SSL certificates**
3. **Set up reverse proxy (nginx/Apache)**
4. **Configure monitoring and alerting**
5. **Set up automated backups**
6. **Implement CI/CD pipeline**

---

## Azure Integration

### Azure Services Required

#### 1. Azure Database for PostgreSQL
- **Service**: Azure Database for PostgreSQL Flexible Server
- **Tier**: B1ms (Free tier for development)
- **Purpose**: Production database hosting

#### 2. Azure Container Instances
- **Service**: Azure Container Instances
- **Purpose**: Application hosting
- **Cost**: ~$30/month for 1 vCPU, 1.5GB RAM

#### 3. Azure Container Registry
- **Service**: Azure Container Registry
- **Tier**: Basic ($5/month)
- **Purpose**: Docker image storage

#### 4. Azure Speech Services
- **Service**: Azure Cognitive Services Speech
- **Tier**: F0 (Free tier: 5 hours/month)
- **Purpose**: Speech-to-text and text-to-speech

#### 5. Azure Communication Services
- **Service**: Azure Communication Services
- **Cost**: ~$2/month for phone number
- **Purpose**: Telephony and call management

#### 6. Azure OpenAI (Optional)
- **Service**: Azure OpenAI
- **Status**: Requires approval (1-7 days)
- **Purpose**: Advanced conversational AI

### Azure Setup Commands

#### Create Resource Group
```bash
az group create --name callcenterai-rg --location eastus
```

#### Create PostgreSQL Database
```bash
az postgres flexible-server create \
  --resource-group callcenterai-rg \
  --name callcenterai-db-dev \
  --location eastus \
  --admin-user callcenterai \
  --admin-password "YourSecurePassword123!" \
  --sku-name Standard_B1ms \
  --tier Burstable \
  --storage-size 32 \
  --version 16 \
  --public-access 0.0.0.0

az postgres flexible-server db create \
  --resource-group callcenterai-rg \
  --server-name callcenterai-db-dev \
  --database-name callcenterai
```

#### Create Container Registry
```bash
az acr create \
  --resource-group callcenterai-rg \
  --name callcenteraicr \
  --sku Basic \
  --admin-enabled true
```

#### Create Speech Services
```bash
az cognitiveservices account create \
  --name callcenterai-speech \
  --resource-group callcenterai-rg \
  --kind SpeechServices \
  --sku F0 \
  --location eastus
```

#### Deploy Container Instance
```bash
az container create \
  --resource-group callcenterai-rg \
  --name callcenterai-gateway \
  --image callcenteraicr.azurecr.io/callcenterai-gateway:latest \
  --registry-login-server callcenteraicr.azurecr.io \
  --registry-username callcenteraicr \
  --registry-password [ACR_PASSWORD] \
  --dns-name-label callcenterai-mvp \
  --ports 8443 \
  --cpu 1 \
  --memory 1.5 \
  --environment-variables-file azure.env \
  --restart-policy Always
```

---

## MVP Launch Plan

### Phase 1: Fix Critical Issues (30 minutes)

#### 1.1 Fix Pydantic v2 Validator Syntax
**File:** `gateway/routes/azure_communication.py`

**Issue:** Using deprecated `@validator` decorator instead of `@field_validator`

**Changes needed:**
```python
# Lines 44-54: Replace old validator syntax
# OLD:
@validator('phone_number')
def validate_phone_number(cls, v):

# NEW:
@field_validator('phone_number')
@classmethod
def validate_phone_number(cls, v):
```

#### 1.2 Secure Environment Configuration
**File:** `compose/gateway.yaml`

**Issue:** Environment variables hardcoded in docker-compose file

**Changes needed:**
- Remove all environment variables from lines 22-78
- Replace with `env_file: - .env`
- Create `.env` file from `env.example`
- Update `.gitignore` to ensure `.env` is not committed

### Phase 2: Azure Resource Setup (2-3 hours)

#### 2.1 Create Azure Account and Resource Group
1. Sign up for Azure free account (12 months free tier)
2. Install Azure CLI: `az login`
3. Create resource group: `az group create --name callcenterai-rg --location eastus`

#### 2.2 Create Azure Database for PostgreSQL
- Create database server with B1ms tier
- Configure firewall for your IP
- Enable SSL and configure connection parameters

#### 2.3 Create Azure Container Registry
- Create registry with Basic tier
- Build and push Docker image

#### 2.4 Request Azure OpenAI Access
- Submit access request: https://aka.ms/oai/access
- Wait for approval (typically 1-7 days)
- Configure fallback NLP as primary until approved

#### 2.5 Create Azure Speech Services
- Create Speech resource with F0 free tier
- Get API keys and configure environment variables

#### 2.6 Create Azure Communication Services
- Create ACS resource
- Purchase phone number (manual via Azure Portal)
- Configure webhooks and callbacks

#### 2.7 Create Azure Storage Account
- Create storage account with Standard_LRS
- Create blob container for logs

### Phase 3: Deploy Application to Azure (1-2 hours)

#### 3.1 Create Azure Container Instance
- Create environment variable file `azure.env`
- Deploy container with proper configuration
- Access application at: `http://callcenterai-mvp.eastus.azurecontainer.io:8443`

#### 3.2 Run Database Migrations
- Connect to container
- Execute migrations: `python migrate.py upgrade`

#### 3.3 Configure DNS and SSL (Optional for MVP)
- Set up Azure DNS or use your domain provider
- Point domain to container instance public IP
- Use Azure Application Gateway or reverse proxy for SSL

### Phase 4: Initial Setup and Testing (1 hour)

#### 4.1 Create Test Clinic
```bash
curl -X POST https://callcenterai-mvp.eastus.azurecontainer.io:8443/api/v1/clinics \
  -H "Content-Type: application/json" \
  -d '{
    "clinic_name": "Test Medical Clinic",
    "phone_number": "+15551234567",
    "timezone": "America/New_York",
    "default_language": "en",
    "ehr_system": "google_calendar"
  }'
```

#### 4.2 Create Test Provider
```bash
curl -X POST https://callcenterai-mvp.eastus.azurecontainer.io:8443/api/v1/providers \
  -H "Content-Type: application/json" \
  -d '{
    "clinic_id": "CLINIC_001",
    "name_token": "Dr. John Smith",
    "title": "Dr.",
    "specialty": "General Practice",
    "email": "test@example.com"
  }'
```

#### 4.3 Test Google Calendar OAuth Flow
1. Navigate to `/api/v1/google-calendar/oauth/start`
2. Complete OAuth authorization
3. Verify credentials stored in database

#### 4.4 Test Call Simulator
1. Navigate to `/call-simulator`
2. Test appointment booking flow
3. Verify database records created
4. Check Google Calendar event created

### Phase 5: Monitoring and Optimization (Ongoing)

#### 5.1 Set Up Azure Monitor
- Enable container insights
- Configure basic monitoring

#### 5.2 Configure Alerts
- Database connection failures
- Container restart events
- API endpoint errors (5xx responses)
- High memory/CPU usage

#### 5.3 Cost Monitoring
- Azure Database: ~$15/month (B1ms tier)
- Container Instance: ~$30/month (1 vCPU, 1.5GB)
- Container Registry: ~$5/month (Basic tier)
- Speech Services: Free tier initially
- Storage: ~$1/month
- **Total MVP cost: ~$51/month**

### Success Criteria

**MVP is ready when:**
1. All Pydantic v2 issues fixed
2. Application deployed to Azure Container Instance
3. Azure PostgreSQL database created and migrated
4. At least one test clinic configured
5. Call simulator accessible and functional
6. Google Calendar OAuth flow working
7. Basic monitoring in place
8. Total monthly cost under $60

---

## Troubleshooting

### Common Issues

#### 1. Database Connection Issues
```bash
# Check if PostgreSQL is running
docker-compose -f compose/gateway.yaml ps postgres

# Check database logs
docker-compose -f compose/gateway.yaml logs postgres

# Test connection
docker-compose -f compose/gateway.yaml exec gateway python -c "from services.database import test_connection; test_connection()"
```

#### 2. Google Calendar OAuth Issues
- Verify redirect URI matches exactly
- Check client ID and secret are correct
- Ensure Google Calendar API is enabled
- Check browser console for JavaScript errors

#### 3. Environment Variable Issues
```bash
# Validate configuration
docker-compose -f compose/gateway.yaml exec gateway python validate_config.py

# Check environment variables
docker-compose -f compose/gateway.yaml exec gateway env | grep -E "(DB_|GOOGLE_|SECURITY_)"
```

#### 4. Migration Issues
```bash
# Check migration status
docker-compose -f compose/gateway.yaml exec gateway alembic current

# Run migrations manually
docker-compose -f compose/gateway.yaml exec gateway python migrate.py upgrade

# Check migration history
docker-compose -f compose/gateway.yaml exec gateway alembic history
```

#### 5. Azure Deployment Issues
```bash
# Check container logs
az container logs --resource-group callcenterai-rg --name callcenterai-gateway

# Check container status
az container show --resource-group callcenterai-rg --name callcenterai-gateway

# Restart container
az container restart --resource-group callcenterai-rg --name callcenterai-gateway
```

### Performance Issues

#### 1. Slow Database Queries
- Check database indexes
- Monitor query performance
- Consider connection pooling
- Review database configuration

#### 2. High Memory Usage
- Monitor container resource usage
- Check for memory leaks
- Optimize application code
- Consider scaling up resources

#### 3. API Response Times
- Check network latency
- Monitor external service calls
- Review application logs
- Consider caching strategies

---

## Development Guide

### Local Development Setup

1. **Clone Repository**
   ```bash
   git clone <your-repo-url>
   cd CallCenterAI
   ```

2. **Set Up Environment**
   ```bash
   cp env.example .env
   # Edit .env with your configuration
   ```

3. **Start Development Environment**
   ```bash
   docker-compose -f compose/gateway.yaml up -d
   ```

4. **Run Migrations**
   ```bash
   docker-compose -f compose/gateway.yaml exec gateway python migrate.py upgrade
   ```

5. **Access Application**
   - API: http://localhost:8443/docs
   - Call Simulator: http://localhost:8443/call-simulator

### Code Structure

#### Models (`gateway/models/`)
- `models.py` - SQLAlchemy ORM models
- `schemas.py` - Pydantic schemas for API
- `call_flow_models.py` - Call flow specific models

#### Services (`gateway/services/`)
- `database.py` - Database connection and session management
- `configuration.py` - Application configuration
- `google_calendar_service.py` - Google Calendar integration
- `call_orchestrator.py` - Call flow orchestration
- `natural_language_processor.py` - NLP processing
- `appointment_service.py` - Appointment management

#### Routes (`gateway/routes/`)
- `appointments.py` - Appointment API endpoints
- `clinics.py` - Clinic management endpoints
- `providers.py` - Provider management endpoints
- `google_calendar.py` - Google Calendar integration endpoints
- `call_simulator.py` - Call simulator endpoints

### Testing

#### Unit Tests
```bash
# Run unit tests
docker-compose -f compose/gateway.yaml exec gateway python -m pytest tests/

# Run specific test file
docker-compose -f compose/gateway.yaml exec gateway python -m pytest tests/test_models.py
```

#### Integration Tests
```bash
# Test API endpoints
curl -X GET http://localhost:8443/healthz

# Test call simulator
curl -X POST http://localhost:8443/api/v1/call-simulator/start \
  -H "Content-Type: application/json" \
  -d '{"caller_phone": "(555) 123-4567", "clinic_id": "CLINIC_001"}'
```

#### End-to-End Testing
1. Start call simulation
2. Test appointment booking flow
3. Verify Google Calendar integration
4. Check database records
5. Test error handling

### Code Quality

#### Linting
```bash
# Run flake8
docker-compose -f compose/gateway.yaml exec gateway flake8 .

# Run black formatter
docker-compose -f compose/gateway.yaml exec gateway black .
```

#### Type Checking
```bash
# Run mypy
docker-compose -f compose/gateway.yaml exec gateway mypy .
```

### Deployment

#### Development
```bash
# Start development environment
docker-compose -f compose/gateway.yaml up -d

# View logs
docker-compose -f compose/gateway.yaml logs -f gateway
```

#### Production
```bash
# Build production image
docker build -t callcenterai-gateway:latest gateway/

# Deploy to Azure
az container create --resource-group callcenterai-rg --name callcenterai-gateway --image callcenterai-gateway:latest
```

---

## Support and Maintenance

### Monitoring
- **Application Logs**: Check container logs regularly
- **Database Performance**: Monitor query performance and connection usage
- **API Health**: Use health check endpoints
- **Resource Usage**: Monitor CPU, memory, and disk usage

### Backup Strategy
- **Database Backups**: Automated daily backups with 7-day retention
- **Configuration Backups**: Version control for configuration files
- **Container Images**: Store in Azure Container Registry
- **Disaster Recovery**: Document recovery procedures

### Security Updates
- **Dependencies**: Regular updates of Python packages
- **Base Images**: Update Docker base images
- **Azure Services**: Keep Azure services updated
- **Security Patches**: Apply security patches promptly

### Performance Optimization
- **Database Indexing**: Optimize database queries
- **Caching**: Implement caching strategies
- **Connection Pooling**: Optimize database connections
- **Resource Scaling**: Scale resources based on usage

---

## License and Legal

This project is proprietary software. All rights reserved.

### Disclaimer
This software is designed for healthcare communication automation. Ensure compliance with all applicable healthcare regulations (HIPAA, etc.) in your jurisdiction before deployment.

### Support
For technical support and questions:
1. Review the documentation files
2. Check the security policy
3. Verify environment configuration
4. Test individual components
5. Check troubleshooting section
6. Review logs for error details

---

## Security Policy

### Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 1.0.x   | :white_check_mark: |

### Security Considerations

#### Sensitive Data Handling

This repository contains a HIPAA-compliant healthcare communication system. The following security measures are implemented:

1. **PHI Tokenization**: All Protected Health Information (PHI) is encrypted using AES-GCM encryption and stored with tokenized references
2. **Environment Variables**: Sensitive configuration data is stored in environment variables, not in code
3. **Database Security**: All database connections use encrypted connections and secure authentication

#### Files NOT to Commit

The following files contain sensitive information and should NEVER be committed to version control:

- `google_credentials.json` - Google OAuth credentials
- `.env` files - Environment variables with secrets
- `data/` directory - Database files and patient data
- Any files containing actual API keys, passwords, or patient information

#### Environment Variables Required

The following environment variables must be set in your deployment environment:

```bash
# Database
DATABASE_URL=postgresql://user:password@localhost:5432/callcenter_db

# Encryption Keys (Base64 encoded)
CLINIC_TOKEN_HMAC_KEY_BASE64=your_hmac_key_here
AES_GCM_KEY_BASE64=your_aes_key_here

# Google Calendar OAuth
GOOGLE_CLIENT_ID=your_google_client_id
GOOGLE_CLIENT_SECRET=your_google_client_secret
GOOGLE_REDIRECT_URI=http://localhost:8443/api/v1/google-calendar/oauth/callback

# Application
APP_ENV=dev
PYTHONPATH=/app
```

#### Security Best Practices

1. **Never commit secrets**: All sensitive data should be in environment variables
2. **Use strong encryption keys**: Generate cryptographically secure keys for production
3. **Regular security updates**: Keep all dependencies updated
4. **Access control**: Limit repository access to authorized personnel only
5. **Audit logging**: Monitor all access to patient data

#### Reporting Security Vulnerabilities

If you discover a security vulnerability, please report it privately:

1. **DO NOT** create a public GitHub issue
2. Email security concerns to: [your-security-email@domain.com]
3. Include detailed information about the vulnerability
4. Allow reasonable time for response before public disclosure

#### HIPAA Compliance

This system is designed to be HIPAA-compliant when properly configured:

- All PHI is encrypted at rest and in transit
- Access controls are implemented
- Audit trails are maintained
- Data retention policies are enforced

**Important**: Ensure your deployment meets all HIPAA requirements for your specific use case.

#### Security Checklist for Deployment

- [ ] All environment variables are set with secure values
- [ ] Database is configured with strong passwords
- [ ] SSL/TLS certificates are properly configured
- [ ] Firewall rules are properly configured
- [ ] Regular security updates are scheduled
- [ ] Backup and recovery procedures are tested
- [ ] Access logs are monitored
- [ ] HIPAA compliance requirements are met

---

## GitHub Repository Setup Guide

### ⚠️ CRITICAL SECURITY WARNINGS

**BEFORE PUSHING TO GITHUB, YOU MUST:**

1. **Remove all sensitive files** (see list below)
2. **Set up proper .gitignore** (already created)
3. **Use environment variables** for all secrets
4. **Verify no secrets are in code**

### Files to Remove Before Pushing

#### 1. Sensitive Configuration Files
```bash
# Remove these files (they contain secrets):
rm gateway/google_credentials.json
rm .env  # if it exists
rm *.env  # any environment files
```

#### 2. Database Data Directory
```bash
# Remove the entire data directory (contains database files):
rm -rf data/
```

#### 3. Python Cache Files
```bash
# Remove Python cache files:
find . -name "__pycache__" -type d -exec rm -rf {} +
find . -name "*.pyc" -delete
```

### Safe Files to Keep

✅ **These files are safe to commit:**
- All source code files (.py, .html, .yaml, .md)
- Configuration templates (env.example)
- Documentation files
- Docker files
- Requirements files
- Test files (optional)

### Step-by-Step GitHub Setup

#### 1. Clean the Repository
```bash
# Remove sensitive files
rm gateway/google_credentials.json
rm -rf data/
rm -rf gateway/__pycache__/
rm -rf gateway/models/__pycache__/
rm -rf gateway/routes/__pycache__/
rm -rf gateway/services/__pycache__/
find . -name "*.pyc" -delete

# Verify sensitive files are gone
ls -la gateway/google_credentials.json  # Should show "No such file"
ls -la data/  # Should show "No such file"
```

#### 2. Initialize Git Repository
```bash
# Initialize git (if not already done)
git init

# Add all files (respecting .gitignore)
git add .

# Check what will be committed
git status

# Verify no sensitive files are staged
git diff --cached --name-only | grep -E "(google_credentials|\.env|data/)"
# Should return nothing
```

#### 3. Create Initial Commit
```bash
# Create initial commit
git commit -m "Initial commit: CallCenterAI HIPAA-compliant healthcare communication system

- Multi-tenant architecture with clinic isolation
- Natural language processing for conversational AI
- Google Calendar integration with OAuth
- HIPAA-compliant PHI tokenization
- Comprehensive API and web interface
- Docker containerization and deployment ready"
```

#### 4. Create GitHub Repository
1. Go to GitHub.com
2. Click "New repository"
3. **IMPORTANT**: Select "Private" repository
4. Name it: `CallCenterAI` or `callcenter-ai`
5. **DO NOT** initialize with README (you already have files)
6. Click "Create repository"

#### 5. Push to GitHub
```bash
# Add remote origin
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO_NAME.git

# Push to GitHub
git push -u origin main
```

### Post-Push Security Checklist

#### 1. Verify Repository Contents
- [ ] No `google_credentials.json` file
- [ ] No `data/` directory
- [ ] No `.env` files
- [ ] No `__pycache__` directories
- [ ] All source code is present
- [ ] Documentation files are present

#### 2. Set Up Environment Variables
Create a secure way to manage environment variables:

**Option A: Local .env file (for development)**
```bash
# Create .env file locally (DO NOT commit)
cp env.example .env
# Edit .env with your actual values
```

**Option B: GitHub Secrets (for CI/CD)**
1. Go to repository Settings → Secrets and variables → Actions
2. Add these secrets:
   - `DATABASE_URL`
   - `CLINIC_TOKEN_HMAC_KEY_BASE64`
   - `AES_GCM_KEY_BASE64`
   - `GOOGLE_CLIENT_ID`
   - `GOOGLE_CLIENT_SECRET`

**Option C: Cloud Provider Secrets (for production)**
- AWS Secrets Manager
- Azure Key Vault
- Google Secret Manager
- HashiCorp Vault

#### 3. Update Documentation
- [ ] Update README.md with setup instructions
- [ ] Include environment variable setup guide
- [ ] Add Google Calendar setup instructions
- [ ] Include deployment guide

### Repository Structure After Push

```
CallCenterAI/
├── .gitignore                 # Git ignore rules
├── .github/                   # GitHub workflows (optional)
├── SECURITY.md               # Security policy
├── DEPLOYMENT_GUIDE.md       # Deployment instructions
├── env.example               # Environment variables template
├── CALL_CENTER_AI_TECHNICAL_SPECIFICATION.md
├── CALL_CENTER_AI_ENGINEERING_DOCUMENTATION.md
├── compose/                  # Docker compose files
│   ├── gateway.yaml
│   └── orchestrator.yaml
├── gateway/                  # Main application
│   ├── main.py
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── models/              # Database models
│   ├── routes/              # API routes
│   ├── services/            # Business logic
│   └── templates/           # Web templates
├── orchestrator/            # Orchestration service
└── README.md               # Project documentation
```

### Security Best Practices

#### 1. Repository Access
- [ ] Keep repository private
- [ ] Limit access to authorized personnel only
- [ ] Use branch protection rules
- [ ] Require pull request reviews

#### 2. Code Security
- [ ] Regular dependency updates
- [ ] Security scanning in CI/CD
- [ ] Code review for all changes
- [ ] No hardcoded secrets in code

#### 3. Deployment Security
- [ ] Use secure environment variable management
- [ ] Implement proper access controls
- [ ] Regular security audits
- [ ] Monitor for security vulnerabilities

### Troubleshooting

#### If You Accidentally Commit Secrets

1. **Immediately rotate the secrets** (change passwords, regenerate keys)
2. **Remove from git history**:
   ```bash
   git filter-branch --force --index-filter \
   'git rm --cached --ignore-unmatch gateway/google_credentials.json' \
   --prune-empty --tag-name-filter cat -- --all
   ```
3. **Force push** (if repository is private):
   ```bash
   git push origin --force --all
   ```

#### If Repository Becomes Public

1. **Immediately make it private**
2. **Rotate all secrets**
3. **Check GitHub's security advisory**
4. **Review access logs**

### Next Steps

After successfully pushing to GitHub:

1. **Set up CI/CD pipeline** (GitHub Actions)
2. **Configure automated testing**
3. **Set up deployment automation**
4. **Implement monitoring and alerting**
5. **Create backup and disaster recovery procedures**

### Support

If you encounter issues:
1. Check the SECURITY.md file
2. Review the DEPLOYMENT_GUIDE.md
3. Verify all sensitive files are removed
4. Ensure environment variables are properly configured

---

## Complete Setup Guide

### Overview

This guide provides step-by-step instructions for setting up CallCenterAI with proper security, database configuration, and Google Calendar integration for both development and production environments.

### Step 1: Set Up PostgreSQL Database

#### 1.1 Install PostgreSQL (if not already installed)

```bash
# Windows (using Chocolatey)
choco install postgresql

# Or download from: https://www.postgresql.org/download/windows/
```

#### 1.2 Set Up Database User and Password

```bash
# Connect to PostgreSQL as superuser
psql -U postgres

# Create a dedicated user for CallCenterAI
CREATE USER callcenterai WITH PASSWORD 'YourSecurePassword123!';

# Create the database
CREATE DATABASE callcenter_db OWNER callcenterai;

# Grant permissions
GRANT ALL PRIVILEGES ON DATABASE callcenter_db TO callcenterai;

# Exit PostgreSQL
\q
```

#### 1.3 Alternative: Use Docker PostgreSQL (Recommended for Development)

Your `compose/gateway.yaml` already sets up PostgreSQL in Docker:

```yaml
postgres:
  image: postgres:16
  environment:
    POSTGRES_PASSWORD: ChangeThisNow_!
```

**For Docker setup, your credentials are:**
- **Username**: `postgres`
- **Password**: `ChangeThisNow_!`
- **Database**: `postgres` (default)

### Step 2: Generate Your Encryption Keys

Run these commands to generate secure encryption keys:

```bash
# Generate HMAC key for deterministic tokens
python -c "import base64, os; print('HMAC Key:', base64.b64encode(os.urandom(32)).decode())"

# Generate AES key for PHI encryption
python -c "import base64, os; print('AES Key:', base64.b64encode(os.urandom(32)).decode())"
```

**Example output:**
```
HMAC Key: xyvpXrGOZtSIHND24L7BjEVNr4WgTjsrPK5TkRLthnc=
AES Key: oGyEbmXBzJwbpwwwthU5hhhZ87nUGCr0UUpfbhps5XA=
```

### Step 3: Create Your Local .env File

Create a `.env` file in your project root with these values:

```bash
# CallCenterAI Environment Variables
# NEVER commit this file to version control

# Database Configuration
# For Docker setup (recommended for development):
DATABASE_URL=postgresql://postgres:ChangeThisNow_!@postgres:5432/postgres

# For local PostgreSQL setup:
# DATABASE_URL=postgresql://callcenterai:YourSecurePassword123!@localhost:5432/callcenter_db

# Encryption Keys (Base64 encoded)
CLINIC_TOKEN_HMAC_KEY_BASE64=xyvpXrGOZtSIHND24L7BjEVNr4WgTjsrPK5TkRLthnc=
AES_GCM_KEY_BASE64=oGyEbmXBzJwbpwwwthU5hhhZ87nUGCr0UUpfbhps5XA=

# Google Calendar OAuth Configuration
# TODO: Replace with your actual Google Cloud Console credentials
GOOGLE_CLIENT_ID=your_google_client_id_here
GOOGLE_CLIENT_SECRET=your_google_client_secret_here
GOOGLE_REDIRECT_URI=http://localhost:8443/api/v1/google-calendar/oauth/callback

# Application Configuration
APP_ENV=dev
PYTHONPATH=/app
```

### Step 4: Set Up Google Calendar API

#### 4.1 Development Setup (Single Test Account)

For development and testing, you can use a single Google account:

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing one
3. Enable Google Calendar API
4. Create OAuth 2.0 credentials
5. Replace the placeholder values in your `.env` file

#### 4.2 Production Setup (Per-Clinic Integration)

**⚠️ IMPORTANT: For production, each clinic MUST use their own Google account!**

##### Why Each Clinic Needs Their Own Google Account:

1. **Data Isolation**: Each clinic's calendar data must be completely separate
2. **HIPAA Compliance**: Patient appointment data cannot be shared between clinics
3. **Access Control**: Clinics should only access their own calendar data
4. **Legal Requirements**: Each clinic is responsible for their own data

##### Production Google Calendar Setup Process:

**For Each Clinic:**

1. **Clinic Google Account Setup**
   - Clinic must have a Google Workspace account (recommended) or Gmail account
   - Clinic admin must have access to Google Cloud Console
   - Clinic must create their own Google Cloud project

2. **Create Clinic-Specific OAuth Credentials**
   ```bash
   # Each clinic gets their own credentials:
   GOOGLE_CLIENT_ID=clinic_specific_client_id
   GOOGLE_CLIENT_SECRET=clinic_specific_client_secret
   GOOGLE_REDIRECT_URI=https://yourdomain.com/api/v1/google-calendar/oauth/callback
   ```

3. **Provider-Level Authentication**
   - Each provider (doctor) in the clinic authenticates with the clinic's Google account
   - Providers grant access to their individual calendars
   - System stores encrypted OAuth tokens per provider

4. **Multi-Tenant Architecture**
   ```
   Clinic A (St. Peters Medical)
   ├── Dr. Rivera → Google Calendar A
   ├── Dr. Smith → Google Calendar B
   └── Nurse Johnson → Google Calendar C
   
   Clinic B (Downtown Medical)
   ├── Dr. Wilson → Google Calendar D
   └── Dr. Brown → Google Calendar E
   ```

##### Production Implementation Steps:

1. **Clinic Onboarding Process**
   ```bash
   # 1. Create clinic in system
   POST /api/v1/clinics
   {
     "clinic_name": "St. Peters Medical",
     "google_workspace_domain": "stpeters.com"
   }
   
   # 2. Clinic admin provides OAuth credentials
   PUT /api/v1/clinics/{clinic_id}/google-credentials
   {
     "client_id": "clinic_specific_client_id",
     "client_secret": "clinic_specific_client_secret"
   }
   ```

2. **Provider Authentication Flow**
   ```bash
   # 1. Provider starts OAuth flow
   GET /api/v1/google-calendar/oauth/start?provider_id=PROVIDER_123&clinic_id=CLINIC_456
   
   # 2. Provider authenticates with clinic's Google account
   # 3. System stores encrypted tokens for this provider
   # 4. Provider can now sync appointments to their calendar
   ```

3. **Data Isolation Verification**
   - Each clinic's data is completely isolated
   - No cross-clinic calendar access possible
   - Audit logs track all calendar access per clinic

### Step 5: Set Up GitHub Secrets

Go to your GitHub repository: `https://github.com/edgarsuarez123/CallCenterAI`

#### 5.1 Navigate to Secrets

1. Click **Settings** (top menu)
2. Click **Secrets and variables** → **Actions**

#### 5.2 Add Repository Secrets

Click **"New repository secret"** and add each of these:

**Secret 1: DATABASE_URL**
- **Name**: `DATABASE_URL`
- **Value**: `postgresql://postgres:ChangeThisNow_!@postgres:5432/postgres`

**Secret 2: CLINIC_TOKEN_HMAC_KEY_BASE64**
- **Name**: `CLINIC_TOKEN_HMAC_KEY_BASE64`
- **Value**: `xyvpXrGOZtSIHND24L7BjEVNr4WgTjsrPK5TkRLthnc=`

**Secret 3: AES_GCM_KEY_BASE64**
- **Name**: `AES_GCM_KEY_BASE64`
- **Value**: `oGyEbmXBzJwbpwwwthU5hhhZ87nUGCr0UUpfbhps5XA=`

**Secret 4: GOOGLE_CLIENT_ID**
- **Name**: `GOOGLE_CLIENT_ID`
- **Value**: `your_google_client_id_here`

**Secret 5: GOOGLE_CLIENT_SECRET**
- **Name**: `GOOGLE_CLIENT_SECRET`
- **Value**: `your_google_client_secret_here`

### Step 6: Create GitHub Actions Environment (Optional)

#### 6.1 Create Environment

1. In your GitHub repository, go to **Settings**
2. Click **Environments** (left sidebar)
3. Click **"New environment"**
4. Name it: `production`
5. Click **"Configure environment"**

#### 6.2 Add Environment Secrets

1. In the environment settings, scroll down to **"Environment secrets"**
2. Click **"Add secret"**
3. Add the same secrets as above, but with production values

### Step 7: Test Your Setup

#### 7.1 Start the System

```bash
docker-compose -f compose/gateway.yaml up -d
```

#### 7.2 Check Health

```bash
curl http://localhost:8443/healthz
```

#### 7.3 Access the Application

- **API Documentation**: http://localhost:8443/docs
- **Call Simulator**: http://localhost:8443/call-simulator

### Step 8: Push to GitHub

```bash
git add .
git commit -m "Add environment configuration and documentation"
git push origin main
```

### Summary of Credentials

#### For Development (Docker)

- **Database Username**: `postgres`
- **Database Password**: `ChangeThisNow_!`
- **Database Name**: `postgres`
- **Database URL**: `postgresql://postgres:ChangeThisNow_!@postgres:5432/postgres`

#### For Production (Local PostgreSQL)

- **Database Username**: `callcenterai`
- **Database Password**: `YourSecurePassword123!`
- **Database Name**: `callcenter_db`
- **Database URL**: `postgresql://callcenterai:YourSecurePassword123!@localhost:5432/callcenter_db`

#### Encryption Keys

- **HMAC Key**: `xyvpXrGOZtSIHND24L7BjEVNr4WgTjsrPK5TkRLthnc=`
- **AES Key**: `oGyEbmXBzJwbpwwwthU5hhhZ87nUGCr0UUpfbhps5XA=`

### Production Deployment Considerations

#### Google Calendar Integration

- ✅ **Each clinic uses their own Google account**
- ✅ **Each provider authenticates with clinic's Google account**
- ✅ **Complete data isolation between clinics**
- ✅ **HIPAA-compliant data handling**
- ✅ **Audit logging for all calendar access**

#### Security Best Practices

- ✅ **Never commit** `.env` files to Git
- ✅ **Use different passwords** for development and production
- ✅ **Generate new encryption keys** for production
- ✅ **Store secrets** in GitHub Secrets, not in code
- ✅ **Use strong passwords** (at least 12 characters with mixed case, numbers, symbols)
- ✅ **Regular security audits** and updates
- ✅ **Monitor access logs** for suspicious activity

#### Multi-Tenant Architecture

- ✅ **Database-level isolation** using `clinic_id` fields
- ✅ **Application-level access controls**
- ✅ **Separate OAuth credentials** per clinic
- ✅ **Encrypted credential storage** in database
- ✅ **Comprehensive audit trails**

### Troubleshooting

#### Common Issues

1. **Database Connection Errors**
   - Check DATABASE_URL format
   - Verify database server is running
   - Check network connectivity

2. **Google Calendar Integration Issues**
   - Verify OAuth credentials
   - Check redirect URI configuration
   - Ensure API is enabled
   - Confirm clinic has proper Google account access

3. **Encryption Key Issues**
   - Verify keys are base64 encoded
   - Check key length (32 bytes)
   - Ensure keys are properly set in environment

#### Support

For deployment issues:
1. Check logs: `docker-compose logs -f`
2. Verify environment variables
3. Test individual components
4. Review security configuration

### Next Steps

After completing this setup:

1. **Set up CI/CD pipeline** (GitHub Actions)
2. **Configure automated testing**
3. **Set up deployment automation**
4. **Implement monitoring and alerting**
5. **Create backup and disaster recovery procedures**
6. **Plan clinic onboarding process**
7. **Develop provider authentication workflow**

Your CallCenterAI system is now properly configured with secure credentials and ready for GitHub deployment! 🚀

---

## Deployment Guide

### Pre-Deployment Security Checklist

Before deploying CallCenterAI, ensure you have completed the following security measures:

#### 1. Environment Variables Setup

1. Copy `env.example` to `.env`
2. Generate secure encryption keys:
   ```bash
   # Generate HMAC key (32 bytes, base64 encoded)
   python -c "import base64, os; print(base64.b64encode(os.urandom(32)).decode())"
   
   # Generate AES-GCM key (32 bytes, base64 encoded)
   python -c "import base64, os; print(base64.b64encode(os.urandom(32)).decode())"
   ```
3. Set up Google Calendar OAuth credentials in Google Cloud Console
4. Configure database connection string with secure credentials

#### 2. Google Calendar Setup

1. Create a Google Cloud Console project
2. Enable Google Calendar API
3. Create OAuth 2.0 credentials
4. Configure authorized redirect URIs:
   - Development: `http://localhost:8443/api/v1/google-calendar/oauth/callback`
   - Production: `https://yourdomain.com/api/v1/google-calendar/oauth/callback`
5. Download credentials JSON file (DO NOT commit to repository)

#### 3. Database Security

1. Use strong database passwords
2. Enable SSL connections
3. Configure proper firewall rules
4. Set up regular backups
5. Use connection pooling for production

#### 4. Production Security

1. Use HTTPS with valid SSL certificates
2. Configure proper firewall rules
3. Set up monitoring and logging
4. Implement rate limiting
5. Regular security updates

### Deployment Steps

#### 1. Repository Setup

```bash
# Clone the repository
git clone <your-private-repo-url>
cd CallCenterAI

# Set up environment variables
cp env.example .env
# Edit .env with your actual values

# Initialize git (if not already done)
git init
git remote add origin <your-private-repo-url>
```

#### 2. Docker Deployment

```bash
# Start the services
docker-compose -f compose/gateway.yaml up -d

# Check service status
docker-compose -f compose/gateway.yaml ps

# View logs
docker-compose -f compose/gateway.yaml logs -f
```

#### 3. Database Migration

```bash
# Run database migrations
docker-compose -f compose/gateway.yaml exec gateway python migrate_provider_email.py
```

#### 4. Google Calendar Integration

1. Access the OAuth start URL:
   ```
   http://localhost:8443/api/v1/google-calendar/oauth/start?provider_id=PROVIDER_ID&clinic_id=CLINIC_ID
   ```
2. Complete OAuth flow in browser
3. Verify integration status

##### OAuth Token Management (Important for Production)

**How the system maintains persistent Google Calendar access:**

- **Initial Setup**: Each provider authenticates once with their clinic's Google account
- **Token Storage**: Access tokens and refresh tokens are encrypted and stored in the database
- **Automatic Refresh**: System automatically refreshes access tokens using refresh tokens
- **Seamless Operation**: No constant OAuth prompts - appointments are created automatically
- **Token Lifecycle**: 
  - Access tokens expire in ~1 hour
  - Refresh tokens expire in ~6 months
  - System proactively refreshes before expiration

**Production Considerations:**
- **Monitor token expiration** dates
- **Set up alerts** for failed token refreshes
- **Plan for re-authentication** when refresh tokens expire (rare, every 6+ months)
- **Each clinic uses their own Google account** for complete data isolation

#### 5. Testing

```bash
# Test API endpoints
curl http://localhost:8443/healthz

# Test call simulator
# Open http://localhost:8443/call-simulator in browser
```

### Production Deployment

#### 1. Environment Configuration

- Use production-grade database (managed PostgreSQL service)
- Set up proper SSL certificates
- Configure production domain names
- Use secure environment variable management

#### 2. Security Hardening

- Enable database encryption at rest
- Configure network security groups
- Set up monitoring and alerting
- Implement backup and disaster recovery

#### 3. Scaling Considerations

- Use container orchestration (Kubernetes, Docker Swarm)
- Implement load balancing
- Set up horizontal scaling
- Configure auto-scaling policies

### Monitoring and Maintenance

#### 1. Health Checks

- API health endpoint: `/healthz`
- Database connectivity monitoring
- Google Calendar integration status
- OAuth token expiration monitoring
- System resource monitoring

#### 2. Logging

- Application logs
- Database query logs
- Security event logs
- Performance metrics

#### 3. Backup Strategy

- Database backups (daily)
- Configuration backups
- Code repository backups
- Disaster recovery testing

### Troubleshooting

#### Common Issues

1. **Database Connection Errors**
   - Check DATABASE_URL format
   - Verify database server is running
   - Check network connectivity

2. **Google Calendar Integration Issues**
   - Verify OAuth credentials
   - Check redirect URI configuration
   - Ensure API is enabled
   - Check token expiration and refresh status
   - Verify provider has proper Google account access

3. **Encryption Key Issues**
   - Verify keys are base64 encoded
   - Check key length (32 bytes)
   - Ensure keys are properly set in environment

#### Support

For deployment issues:
1. Check logs: `docker-compose logs -f`
2. Verify environment variables
3. Test individual components
4. Review security configuration

### Security Reminders

- **NEVER** commit sensitive data to version control
- **ALWAYS** use environment variables for secrets
- **REGULARLY** update dependencies and security patches
- **MONITOR** system access and usage
- **BACKUP** data regularly and test recovery procedures

---

*Last Updated: December 2024*
*Version: 1.0*
