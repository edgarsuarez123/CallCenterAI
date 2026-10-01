# CallCenterAI Deployment Guide

Complete guide for deploying the CallCenterAI application to Azure.

> **Note**: All commands use **PowerShell** syntax. Ensure you're logged into Azure CLI (`az login`).

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [External Service Setup](#2-external-service-setup)
3. [Environment Configuration](#3-environment-configuration)
4. [Build and Push Docker Image](#4-build-and-push-docker-image)
5. [Database Setup](#5-database-setup)
6. [Deploy to Azure Container Instances](#6-deploy-to-azure-container-instances)
7. [Create Clinics and Providers](#7-create-clinics-and-providers)
8. [Testing](#8-testing)
9. [Troubleshooting](#9-troubleshooting)

---

## 1. Prerequisites

Before starting deployment, ensure you have:

### Tools Installed
- [ ] Docker Desktop
- [ ] Azure CLI (`az login` completed)
- [ ] Python 3.11+

### Azure Resources Created
- [ ] Resource Group: `CallCenterAi-Test`
- [ ] Azure Container Registry: `callcenteracr`
- [ ] Azure Database for PostgreSQL: `callcenterai-db`

### Accounts Ready
- [ ] [Retell AI account](https://www.retellai.com/)
- [ ] Google Cloud project with Calendar API enabled

---

## 2. External Service Setup

**Complete these BEFORE deploying to Azure.**

### 2.1 Retell AI Setup

1. **Create Retell Account**: Go to [retellai.com](https://www.retellai.com/)

2. **Create an Agent**:
   - Dashboard → Agents → Create Agent
   - Configure voice, language, behavior
   - Save the **Agent ID** (starts with `agent_`)

3. **Purchase/Port Phone Number**:
   - Dashboard → Phone Numbers
   - Get a number and assign to your agent
   - Save the **Phone Number** in E.164 format (e.g., `+18005551234`)

4. **Get Webhook Secret**:
   - Dashboard → Settings → Webhooks
   - Copy the **Webhook Signing Secret**
   - You'll add this to your `.env` as `RETELL_WEBHOOK_SECRET`

5. **Configure Webhooks** (after deployment):
   - Add webhook URLs pointing to your deployed API:
   ```
   Call Started: https://your-domain.com/retell/webhook/call_started
   Call Ended:   https://your-domain.com/retell/webhook/call_ended
   ```

6. **Configure Custom Tools** (after deployment):
   | Tool Name | URL |
   |-----------|-----|
   | schedule | `https://your-domain.com/retell/schedule` |
   | confirm_booking | `https://your-domain.com/retell/confirm_booking` |
   | get_availability | `https://your-domain.com/retell/availability` |

### 2.2 Google Calendar Setup

1. **Create Google Cloud Project**:
   - Go to [console.cloud.google.com](https://console.cloud.google.com/)
   - Create new project or select existing

2. **Enable Calendar API**:
   - APIs & Services → Enable APIs → Search "Google Calendar API" → Enable

3. **Create Service Account**:
   - IAM & Admin → Service Accounts → Create
   - Name: `callcenter-calendar`
   - Grant no roles (permissions per-calendar)
   - Create JSON key → Download

4. **Share Calendars with Service Account**:
   - For each provider's calendar:
   - Google Calendar → Settings → Share with specific people
   - Add service account email (from JSON)
   - Permission: "Make changes to events"

5. **Prepare JSON for API**:
   ```powershell
   # Read and minify the service account JSON
   $saJson = Get-Content "path/to/service-account.json" -Raw | ConvertFrom-Json | ConvertTo-Json -Compress
   # Save for later use in clinic setup
   $saJson | Set-Clipboard
   Write-Host "Service account JSON copied to clipboard"
   ```

---

## 3. Environment Configuration

### 3.1 Create `.env` File

```powershell
Copy-Item env.example .env
notepad .env
```

### 3.2 Required Variables

Fill in your `.env` with these values:

```env
# Application
APP_ENVIRONMENT=production
APP_PORT=8080
APP_WORKERS=4

# Database (Azure PostgreSQL)
DB_HOST=callcenterai-db.postgres.database.azure.com
DB_PORT=5432
DB_NAME=postgres
DB_USER=callcenteradmin
DB_PASSWORD=YOUR_DB_PASSWORD

# Encryption (generate with command below)
PHI_ENCRYPTION_KEY=YOUR_32_BYTE_KEY

# Retell AI
RETELL_WEBHOOK_SECRET=YOUR_RETELL_SECRET
```

### 3.3 Generate Encryption Key

```powershell
python -c "import os, base64; print(base64.b64encode(os.urandom(32)).decode())"
```

Copy the output and paste as `PHI_ENCRYPTION_KEY` in your `.env`.

---

## 4. Build and Push Docker Image

### 4.1 Login to Azure Container Registry

```powershell
# Login to Azure
az login

# Login to ACR
az acr login --name callcenteracr
```

### 4.2 Build Docker Image

```powershell
# Set version tag (use date or version number)
$VERSION = Get-Date -Format "yyyyMMdd-HHmm"
$IMAGE = "callcenteracr.azurecr.io/callcenter-gateway:$VERSION"

# Build the image
docker build -t $IMAGE .

Write-Host "Built image: $IMAGE"
```

### 4.3 Push to Azure Container Registry

```powershell
# Push to ACR
docker push $IMAGE

Write-Host "Pushed image: $IMAGE"
```

### 4.4 Verify Upload

```powershell
# List images in ACR
az acr repository show-tags --name callcenteracr --repository callcenter-gateway --output table
```

---

## 5. Database Setup

### 5.1 Reset Database (Drop All Tables)

**⚠️ WARNING: This deletes ALL data!**

```powershell
# Set your database password
$DB_PASSWORD = "YOUR_DB_PASSWORD"

# Connect and reset schema
az postgres flexible-server execute `
  --name callcenterai-db `
  --admin-user callcenteradmin `
  --admin-password $DB_PASSWORD `
  --database-name postgres `
  --querytext "DROP SCHEMA public CASCADE; DROP TYPE IF EXISTS slotsource CASCADE; DROP TYPE IF EXISTS slotstatus CASCADE; DROP TYPE IF EXISTS bookingstatus CASCADE; CREATE SCHEMA public; GRANT ALL ON SCHEMA public TO callcenteradmin; GRANT ALL ON SCHEMA public TO public;"
```

Or using psql directly:

```powershell
# If you have psql installed
$env:PGPASSWORD = "YOUR_DB_PASSWORD"
psql -h callcenterai-db.postgres.database.azure.com -U callcenteradmin -d postgres -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public; GRANT ALL ON SCHEMA public TO callcenteradmin; GRANT ALL ON SCHEMA public TO public;"
```

### 5.2 Run Migrations

**Option A: Run locally (requires database access)**

```powershell
# Ensure .env has correct DB credentials
cd Clinic_app
alembic upgrade head
cd ..
```

**Option B: Run via Docker container**

```powershell
# Build and run migration container
docker build -t callcenter-migrate .

docker run --rm `
  -e DB_HOST=callcenterai-db.postgres.database.azure.com `
  -e DB_PORT=5432 `
  -e DB_NAME=postgres `
  -e DB_USER=callcenteradmin `
  -e DB_PASSWORD=$DB_PASSWORD `
  callcenter-migrate `
  sh -c "cd Clinic_app && alembic upgrade head"
```

### 5.3 Verify Migrations

```powershell
# Check migration status
cd Clinic_app
alembic current
alembic history
cd ..
```

---

## 6. Deploy to Azure Container Apps

### 6.1 Update Container App with New Image

```powershell
# Set image version (use the one you built earlier)
$VERSION = "20251203-1200"  # Replace with your version
$IMAGE = "callcenteracr.azurecr.io/callcenter-gateway:$VERSION"

# Update the container app with new image
az containerapp update `
  --name callcenterai-app `
  --resource-group CallCenterAi-Test `
  --image $IMAGE
```

### 6.2 Update Environment Variables (if needed)

```powershell
# Set your secrets
$DB_PASSWORD = "YOUR_DB_PASSWORD"
$PHI_KEY = "YOUR_PHI_ENCRYPTION_KEY"
$RETELL_SECRET = "YOUR_RETELL_WEBHOOK_SECRET"

# Update environment variables
az containerapp update `
  --name callcenterai-app `
  --resource-group CallCenterAi-Test `
  --set-env-vars `
    APP_ENVIRONMENT=production `
    APP_PORT=8080 `
    APP_WORKERS=4 `
    DB_HOST=callcenterai-db.postgres.database.azure.com `
    DB_PORT=5432 `
    DB_NAME=postgres `
    DB_USER=callcenteradmin `
    DB_PASSWORD=$DB_PASSWORD `
    PHI_ENCRYPTION_KEY=$PHI_KEY `
    RETELL_WEBHOOK_SECRET=$RETELL_SECRET
```

### 6.3 Get Container App URL

```powershell
# Get the FQDN
$FQDN = az containerapp show `
  --name callcenterai-app `
  --resource-group CallCenterAi-Test `
  --query properties.configuration.ingress.fqdn -o tsv

Write-Host "API URL: https://$FQDN"
Write-Host "Docs: https://$FQDN/docs"
Write-Host "Health: https://$FQDN/health"
```

Your app URL is: `https://callcenterai-app.lemonwater-53bbf57b.centralus.azurecontainerapps.io`

### 6.4 Verify Deployment

```powershell
# Check container app status
az containerapp show `
  --name callcenterai-app `
  --resource-group CallCenterAi-Test `
  --query "{Name:name, Status:properties.runningStatus, FQDN:properties.configuration.ingress.fqdn}" `
  -o table

# View logs (follow mode)
az containerapp logs show `
  --name callcenterai-app `
  --resource-group CallCenterAi-Test `
  --follow

# Test health endpoint
Invoke-RestMethod -Uri "https://callcenterai-app.lemonwater-53bbf57b.centralus.azurecontainerapps.io/health"
```

---

## 7. Create Clinics and Providers

**Now that your API is deployed, create the clinic data.**

### 7.1 Set API Base URL

```powershell
# Your Container App URL (HTTPS)
$API_BASE = "https://callcenterai-app.lemonwater-53bbf57b.centralus.azurecontainerapps.io"
```

### 7.2 Create Clinic with Integration

```powershell
# Prepare your Google service account JSON (minified, on one line)
$serviceAccountJson = '{"type":"service_account","project_id":"your-project",...}'

$clinicBody = @{
    clinic = @{
        name = "St Peters Medical Center"
        tier = "pro"
        status = "active"
        license_token = "clinic-001-license"
    }
    integration = @{
        retell_agent_id = "agent_xxxxxxxxxxxx"          # From Retell dashboard
        retell_did = "+18005551234"                      # Your Retell phone number
        google_service_account_json = $serviceAccountJson
        default_appointment_length_minutes = 30
        default_capacity = 1
    }
    license = @{
        token = "clinic-001-license"
        tier = "pro"
        status = "active"
        max_concurrency = 10
        features = @{}
    }
} | ConvertTo-Json -Depth 5

$clinicResponse = Invoke-RestMethod -Uri "$API_BASE/admin/clinics/setup" `
    -Method Post `
    -ContentType "application/json" `
    -Body $clinicBody

# Save clinic ID
$clinicId = $clinicResponse.data.clinic.id
Write-Host "Clinic created! ID: $clinicId"
$clinicResponse | ConvertTo-Json -Depth 5
```

### 7.3 Create Providers

```powershell
# Create first provider
$provider1 = @{
    display_name = "Dr. John Smith"
    google_calendar_id = "dr.smith@your-domain.com"  # Must be shared with service account
    timezone = "America/New_York"
    booking_duration_mins = 30
    capacity = 1
    active = $true
} | ConvertTo-Json

$providerResponse = Invoke-RestMethod -Uri "$API_BASE/admin/clinics/$clinicId/providers" `
    -Method Post `
    -ContentType "application/json" `
    -Body $provider1

Write-Host "Provider created! ID: $($providerResponse.data.id)"

# Create additional providers as needed
$provider2 = @{
    display_name = "Dr. Jane Doe"
    google_calendar_id = "dr.doe@your-domain.com"
    timezone = "America/New_York"
    booking_duration_mins = 30
    capacity = 1
    active = $true
} | ConvertTo-Json

Invoke-RestMethod -Uri "$API_BASE/admin/clinics/$clinicId/providers" `
    -Method Post `
    -ContentType "application/json" `
    -Body $provider2
```

### 7.4 List Created Providers

```powershell
$providers = Invoke-RestMethod -Uri "$API_BASE/admin/clinics/$clinicId/providers"
$providers.data | Format-Table id, display_name, timezone, active
```

---

## 8. Testing

### 8.1 Test Health Endpoint

```powershell
Invoke-RestMethod -Uri "$API_BASE/health"
```

### 8.2 Test Availability

```powershell
$testDate = Get-Date -Format "yyyy-MM-dd"
Invoke-RestMethod -Uri "$API_BASE/retell/availability?clinic_id=$clinicId&date=$testDate"
```

### 8.3 Update Retell Webhooks

Now that you have your API URL, go back to Retell Dashboard and set:

| Setting | Value |
|---------|-------|
| Call Started Webhook | `http://YOUR_FQDN:8080/retell/webhook/call_started` |
| Call Ended Webhook | `http://YOUR_FQDN:8080/retell/webhook/call_ended` |
| Schedule Tool URL | `http://YOUR_FQDN:8080/retell/schedule` |
| Confirm Booking Tool URL | `http://YOUR_FQDN:8080/retell/confirm_booking` |
| Availability Tool URL | `http://YOUR_FQDN:8080/retell/availability` |

### 8.4 Make a Test Call

1. Call your Retell phone number
2. Try booking an appointment
3. Check logs: `az container logs --resource-group CallCenterAi-Test --name callcenter-gateway`

---

## 9. Troubleshooting

### View Container Logs

```powershell
az containerapp logs show `
  --name callcenterai-app `
  --resource-group CallCenterAi-Test `
  --follow
```

### Restart Container App

```powershell
# Create a new revision (effectively restarts)
az containerapp update `
  --name callcenterai-app `
  --resource-group CallCenterAi-Test
```

### Check Container Status

```powershell
az containerapp show `
  --name callcenterai-app `
  --resource-group CallCenterAi-Test `
  --query "{Name:name, Status:properties.runningStatus, FQDN:properties.configuration.ingress.fqdn}" `
  -o table
```

### Database Connection Test

```powershell
# From container logs, look for:
# "Database engine created successfully"
# "Initializing database connection to..."
```

### Common Issues

| Issue | Solution |
|-------|----------|
| Container won't start | Check logs, verify image exists in ACR |
| Database connection failed | Verify DB credentials, check firewall rules |
| Webhook 401 errors | Verify RETELL_WEBHOOK_SECRET matches dashboard |
| Calendar auth errors | Verify service account JSON, check calendar sharing |

---

## Quick Reference Commands

```powershell
# === Build & Deploy ===
docker build -t callcenteracr.azurecr.io/callcenter-gateway:latest .
az acr login --name callcenteracr
docker push callcenteracr.azurecr.io/callcenter-gateway:latest
az containerapp update --name callcenterai-app --resource-group CallCenterAi-Test --image callcenteracr.azurecr.io/callcenter-gateway:latest

# === Container App Management ===
az containerapp logs show --name callcenterai-app --resource-group CallCenterAi-Test --follow
az containerapp show --name callcenterai-app --resource-group CallCenterAi-Test -o table

# === Database ===
cd Clinic_app && alembic upgrade head && cd ..
cd Clinic_app && alembic current && cd ..

# === API Testing ===
Invoke-RestMethod -Uri "https://callcenterai-app.lemonwater-53bbf57b.centralus.azurecontainerapps.io/health"
Invoke-RestMethod -Uri "https://callcenterai-app.lemonwater-53bbf57b.centralus.azurecontainerapps.io/admin/clinics/CLINIC_ID/providers"
```
