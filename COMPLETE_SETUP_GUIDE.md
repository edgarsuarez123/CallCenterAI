# CallCenterAI - Complete Setup Guide

## Overview

This guide provides step-by-step instructions for setting up CallCenterAI with proper security, database configuration, and Google Calendar integration for both development and production environments.

## Step 1: Set Up PostgreSQL Database

### 1.1 Install PostgreSQL (if not already installed)

```bash
# Windows (using Chocolatey)
choco install postgresql

# Or download from: https://www.postgresql.org/download/windows/
```

### 1.2 Set Up Database User and Password

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

### 1.3 Alternative: Use Docker PostgreSQL (Recommended for Development)

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

## Step 2: Generate Your Encryption Keys

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

## Step 3: Create Your Local .env File

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

## Step 4: Set Up Google Calendar API

### 4.1 Development Setup (Single Test Account)

For development and testing, you can use a single Google account:

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing one
3. Enable Google Calendar API
4. Create OAuth 2.0 credentials
5. Replace the placeholder values in your `.env` file

### 4.2 Production Setup (Per-Clinic Integration)

**⚠️ IMPORTANT: For production, each clinic MUST use their own Google account!**

#### Why Each Clinic Needs Their Own Google Account:

1. **Data Isolation**: Each clinic's calendar data must be completely separate
2. **HIPAA Compliance**: Patient appointment data cannot be shared between clinics
3. **Access Control**: Clinics should only access their own calendar data
4. **Legal Requirements**: Each clinic is responsible for their own data

#### Production Google Calendar Setup Process:

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

#### Production Implementation Steps:

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

## Step 5: Set Up GitHub Secrets

Go to your GitHub repository: `https://github.com/edgarsuarez123/CallCenterAI`

### 5.1 Navigate to Secrets

1. Click **Settings** (top menu)
2. Click **Secrets and variables** → **Actions**

### 5.2 Add Repository Secrets

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

## Step 6: Create GitHub Actions Environment (Optional)

### 6.1 Create Environment

1. In your GitHub repository, go to **Settings**
2. Click **Environments** (left sidebar)
3. Click **"New environment"**
4. Name it: `production`
5. Click **"Configure environment"**

### 6.2 Add Environment Secrets

1. In the environment settings, scroll down to **"Environment secrets"**
2. Click **"Add secret"**
3. Add the same secrets as above, but with production values

## Step 7: Test Your Setup

### 7.1 Start the System

```bash
docker-compose -f compose/gateway.yaml up -d
```

### 7.2 Check Health

```bash
curl http://localhost:8443/healthz
```

### 7.3 Access the Application

- **API Documentation**: http://localhost:8443/docs
- **Call Simulator**: http://localhost:8443/call-simulator

## Step 8: Push to GitHub

```bash
git add .
git commit -m "Add environment configuration and documentation"
git push origin main
```

## Summary of Credentials

### For Development (Docker)

- **Database Username**: `postgres`
- **Database Password**: `ChangeThisNow_!`
- **Database Name**: `postgres`
- **Database URL**: `postgresql://postgres:ChangeThisNow_!@postgres:5432/postgres`

### For Production (Local PostgreSQL)

- **Database Username**: `callcenterai`
- **Database Password**: `YourSecurePassword123!`
- **Database Name**: `callcenter_db`
- **Database URL**: `postgresql://callcenterai:YourSecurePassword123!@localhost:5432/callcenter_db`

### Encryption Keys

- **HMAC Key**: `xyvpXrGOZtSIHND24L7BjEVNr4WgTjsrPK5TkRLthnc=`
- **AES Key**: `oGyEbmXBzJwbpwwwthU5hhhZ87nUGCr0UUpfbhps5XA=`

## Production Deployment Considerations

### Google Calendar Integration

- ✅ **Each clinic uses their own Google account**
- ✅ **Each provider authenticates with clinic's Google account**
- ✅ **Complete data isolation between clinics**
- ✅ **HIPAA-compliant data handling**
- ✅ **Audit logging for all calendar access**

### Security Best Practices

- ✅ **Never commit** `.env` files to Git
- ✅ **Use different passwords** for development and production
- ✅ **Generate new encryption keys** for production
- ✅ **Store secrets** in GitHub Secrets, not in code
- ✅ **Use strong passwords** (at least 12 characters with mixed case, numbers, symbols)
- ✅ **Regular security audits** and updates
- ✅ **Monitor access logs** for suspicious activity

### Multi-Tenant Architecture

- ✅ **Database-level isolation** using `clinic_id` fields
- ✅ **Application-level access controls**
- ✅ **Separate OAuth credentials** per clinic
- ✅ **Encrypted credential storage** in database
- ✅ **Comprehensive audit trails**

## Troubleshooting

### Common Issues

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

### Support

For deployment issues:
1. Check logs: `docker-compose logs -f`
2. Verify environment variables
3. Test individual components
4. Review security configuration

## Next Steps

After completing this setup:

1. **Set up CI/CD pipeline** (GitHub Actions)
2. **Configure automated testing**
3. **Set up deployment automation**
4. **Implement monitoring and alerting**
5. **Create backup and disaster recovery procedures**
6. **Plan clinic onboarding process**
7. **Develop provider authentication workflow**

Your CallCenterAI system is now properly configured with secure credentials and ready for GitHub deployment! 🚀
