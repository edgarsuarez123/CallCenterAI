# CallCenterAI Testing Setup Checklist

This comprehensive checklist will guide you through setting up your CallCenterAI system for testing. Follow these steps in order to ensure everything is properly configured.

## Prerequisites

- [ ] Docker and Docker Compose installed
- [ ] Azure account with active subscription
- [ ] Google Cloud Console account (for Google Calendar integration)

---

## 1. Environment Variables Setup

### 1.1 Update `.env` File

**File Location**: `.env` (root directory)

**Critical Changes Needed**:

#### Database Configuration
```bash
# For local testing, these are already correct:
DB_HOST=postgres
DB_USER=postgres
DB_PASSWORD=YourSecurePassword123!
DB_NAME=callcenterai
```

#### Google Calendar Configuration
```bash
# Replace with your actual Google Cloud Console credentials:
GOOGLE_CLIENT_ID=your_actual_client_id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your_actual_client_secret
GOOGLE_REDIRECT_URI=http://localhost:8443/api/v1/google-calendar/oauth/callback
GOOGLE_API_KEY=your_actual_api_key
```

#### Azure Services Configuration
```bash
# Azure Communication Services
ACS_CONNECTION_STRING=endpoint=https://your-acs.communication.azure.com/;accesskey=your_real_acs_key
ACS_PHONE_NUMBER=+15551234567
ACS_CALLBACK_URL=http://localhost:8443/api/v1/callbacks

# Azure Speech Services
AZURE_SPEECH_KEY=your_real_speech_key_32_characters_long
AZURE_SPEECH_REGION=eastus

# Azure OpenAI
AZURE_OPENAI_ENDPOINT=https://your-openai.openai.azure.com/
AZURE_OPENAI_API_KEY=your_real_openai_api_key
AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4
```

#### AI Prompts (Customize for Your Clinic)
```bash
# English prompt
AZURE_OPENAI_SYSTEM_PROMPT_EN=You are a helpful healthcare assistant for appointment scheduling. When registering new patients, collect: full name, phone number, email, date of birth, and complete address (street, city, state, zip code). Always confirm the address for accuracy. Be professional, empathetic, and clear.

# Spanish prompt
AZURE_OPENAI_SYSTEM_PROMPT_ES=Eres un asistente de salud útil para programar citas. Al registrar nuevos pacientes, recopila: nombre completo, número de teléfono, correo electrónico, fecha de nacimiento y dirección completa (calle, ciudad, estado, código postal). Siempre confirma la dirección para mayor precisión. Sé profesional, empático y claro.
```

---

## 2. Start the System

### 2.1 Start Docker Containers
```bash
# Navigate to your project directory
cd C:\Users\Edgar\Desktop\CallCenterAI

# Start the system
docker compose -f compose/gateway.yaml up -d
```

### 2.2 Verify System Health
```bash
# Check if containers are running
docker compose -f compose/gateway.yaml ps

# Check logs
docker compose -f compose/gateway.yaml logs gateway
```

### 2.3 Test API Health
```bash
# Test health endpoint
curl http://localhost:8443/healthz
```

---

## 3. Create Demo Data

### 3.1 Run Demo Setup Script

**File Location**: `gateway/demo_setup.py`

```bash
# Execute the demo setup script
docker compose -f compose/gateway.yaml exec gateway python demo_setup.py
```

This script will create:
- A demo clinic: "St. Peters Medical Center"
- 3 demo providers with different specialties
- **Business hours appointment slots**: Monday to Friday, 9 AM to 5 PM, every 30 minutes for the **entire year**
  - Each provider gets 16 slots per weekday (9:00, 9:30, 10:00, 10:30, 11:00, 11:30, 12:00, 12:30, 1:00, 1:30, 2:00, 2:30, 3:00, 3:30, 4:00, 4:30)
  - Weekends are excluded (Saturday and Sunday)
  - **Total: ~4,160 slots per provider** (52 weeks × 5 weekdays × 16 slots)
  - **Total: ~12,480 slots** for all 3 providers combined
  - Patients can book appointments up to 1 year in advance

### 3.2 Verify Demo Data Creation

**Check via API**:
```bash
# List all clinics
curl http://localhost:8443/api/v1/clinics

# Get clinic details (replace CLINIC_ID with actual ID from response)
curl http://localhost:8443/api/v1/clinics/{CLINIC_ID}

# List providers for the clinic
curl http://localhost:8443/api/v1/clinics/{CLINIC_ID}/providers
```

---

## 4. Manual Clinic Creation (Alternative)

If you prefer to create your own clinic instead of using demo data:

### 4.1 Create Clinic via API

**File Location**: `gateway/routes/clinics.py`

```bash
curl -X POST http://localhost:8443/api/v1/clinics \
  -H "Content-Type: application/json" \
  -d '{
    "clinic_name": "Your Clinic Name",
    "phone_number": "+1234567890",
    "timezone": "America/New_York",
    "default_language": "en",
    "supported_languages": "en,es",
    "ehr_system": "google_calendar",
    "max_concurrent_calls": 10,
    "queue_timeout_seconds": 30,
    "subscription_tier": "professional"
  }'
```

### 4.2 Add Providers to Your Clinic

**File Location**: `gateway/routes/providers.py`

```bash
# Replace {CLINIC_ID} with your actual clinic ID
curl -X POST http://localhost:8443/api/v1/clinics/{CLINIC_ID}/providers \
  -H "Content-Type: application/json" \
  -d '{
    "name_token": "Dr. John Smith",
    "title": "Dr.",
    "specialty": "Family Medicine",
    "email": "dr.smith@yourclinic.com"
  }'
```

---

## 5. Google Calendar Integration Setup

### 5.1 Google Cloud Console Setup

1. **Create Google Cloud Project**:
   - Go to [Google Cloud Console](https://console.cloud.google.com/)
   - Create a new project or select existing one

2. **Enable Google Calendar API**:
   - Navigate to "APIs & Services" > "Library"
   - Search for "Google Calendar API"
   - Click "Enable"

3. **Create OAuth 2.0 Credentials**:
   - Go to "APIs & Services" > "Credentials"
   - Click "Create Credentials" > "OAuth 2.0 Client IDs"
   - Application type: "Web application"
   - Authorized redirect URIs: `http://localhost:8443/api/v1/google-calendar/oauth/callback`

4. **Create API Key**:
   - Go to "APIs & Services" > "Credentials"
   - Click "Create Credentials" > "API Key"
   - Copy the API key

### 5.2 Update Environment Variables

Update these values in your `.env` file:
```bash
GOOGLE_CLIENT_ID=your_actual_client_id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your_actual_client_secret
GOOGLE_API_KEY=your_actual_api_key
```

### 5.3 Test Google Calendar Integration

```bash
# Test Google Calendar authentication endpoint
curl http://localhost:8443/api/v1/google-calendar/oauth/authorize?provider_id=PROVIDER_ID
```

---

## 6. Azure Services Setup

### 6.1 Azure Communication Services

1. **Create ACS Resource**:
   - Go to Azure Portal
   - Create "Communication Services" resource
   - Copy the connection string and phone number

2. **Update Environment Variables**:
```bash
ACS_CONNECTION_STRING=endpoint=https://your-acs.communication.azure.com/;accesskey=your_real_key
ACS_PHONE_NUMBER=+15551234567
```

### 6.2 Azure Speech Services

1. **Create Speech Service**:
   - Go to Azure Portal
   - Create "Speech Services" resource
   - Copy the key and region

2. **Update Environment Variables**:
```bash
AZURE_SPEECH_KEY=your_real_speech_key
AZURE_SPEECH_REGION=eastus
```

### 6.3 Azure OpenAI

1. **Request Access**:
   - Go to Azure Portal
   - Request access to Azure OpenAI
   - Create Azure OpenAI resource once approved

2. **Deploy Model**:
   - Deploy GPT-4 model in your Azure OpenAI resource
   - Copy endpoint, API key, and deployment name

3. **Update Environment Variables**:
```bash
AZURE_OPENAI_ENDPOINT=https://your-openai.openai.azure.com/
AZURE_OPENAI_API_KEY=your_real_openai_key
AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4
```

---

## 7. Testing the Complete System with Real Phone Calls

### 7.1 Prerequisites for Real Phone Testing

**Before testing with actual phone calls, ensure you have:**

- [ ] **Azure Communication Services (ACS) resource created and active**
- [ ] **Phone number purchased in Azure ACS** (toll-free or local number)
- [ ] **Valid Azure credentials** with proper permissions
- [ ] **Webhook endpoint accessible** from the internet (use ngrok for local testing)
- [ ] **Demo data created** (clinic, providers, appointment slots)

### 7.2 Set Up Public Webhook Access (Required for ACS)

**ACS needs to call back to your system, so you need a public URL:**

#### Option A: Using ngrok (Recommended for Testing)
```bash
# Install ngrok if not already installed
# Download from: https://ngrok.com/download

# Start ngrok to expose your local server
ngrok http 8443

# Copy the HTTPS URL (e.g., https://abc123.ngrok.io)
# This will be your public webhook URL
```

#### Option B: Deploy to Cloud (Production)
- Deploy your application to Azure, AWS, or similar
- Use the production domain for webhooks

### 7.3 Update Environment Variables for Real Testing

**Update your `.env` file with real ACS credentials:**

```bash
# Azure Communication Services (REQUIRED - Use your real values)
ACS_CONNECTION_STRING=endpoint=https://your-acs-resource.communication.azure.com/;accesskey=your_real_access_key
ACS_PHONE_NUMBER=+15551234567  # Your purchased ACS phone number
ACS_CALLBACK_URL=https://your-ngrok-url.ngrok.io/api/v1/callbacks  # Your public webhook URL

# Azure Speech Services (REQUIRED for voice interaction)
AZURE_SPEECH_KEY=your_real_32_character_speech_key
AZURE_SPEECH_REGION=eastus  # Your speech service region

# Azure OpenAI (REQUIRED for AI conversation)
AZURE_OPENAI_ENDPOINT=https://your-openai-resource.openai.azure.com/
AZURE_OPENAI_API_KEY=your_real_openai_api_key
AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4  # Your deployed model name

# System Configuration
CALLBACK_BASE_URL=https://your-ngrok-url.ngrok.io  # Your public base URL
```

### 7.4 Restart System with New Configuration

```bash
# Stop the system
docker compose -f compose/gateway.yaml down

# Start with new environment variables
docker compose -f compose/gateway.yaml up -d

# Verify system is running
docker compose -f compose/gateway.yaml ps
```

### 7.5 Test Real Phone Call Flow

#### Step 1: Verify System Health
```bash
# Check if system is healthy
curl http://localhost:8443/health

# Check if ACS webhook endpoint is accessible
curl https://your-ngrok-url.ngrok.io/health
```

#### Step 2: Create Demo Data (If Not Already Done)
```bash
# Create clinic and providers
docker compose -f compose/gateway.yaml exec gateway python demo_setup.py

# Verify clinic was created
curl http://localhost:8443/api/v1/clinics
```

#### Step 3: Test Inbound Call (Call Your ACS Number)

1. **Call your ACS phone number** from any phone
2. **The system should automatically:**
   - Answer the call
   - Start voice recognition
   - Begin AI conversation
   - Log the call in the system

#### Step 4: Monitor Call in Real-Time

**Check call logs:**
```bash
# View real-time logs
docker compose -f compose/gateway.yaml logs -f gateway

# Check for call-related logs
docker compose -f compose/gateway.yaml logs gateway | grep -i "call\|acs\|speech"
```

**Check call status via API:**
```bash
# List all calls
curl http://localhost:8443/api/v1/calls

# Get specific call details (replace CALL_ID with actual ID)
curl http://localhost:8443/api/v1/calls/{CALL_ID}
```

#### Step 5: Test Appointment Booking via Phone

**During the phone call, try these scenarios:**

1. **Say**: "I want to book an appointment"
2. **Provide information when prompted:**
   - Your name
   - Phone number
   - Preferred date/time
   - Reason for visit

3. **Verify appointment was created:**
```bash
# Check appointments
curl http://localhost:8443/api/v1/appointments

# Check appointment slots (should show booked slots)
curl http://localhost:8443/api/v1/providers/{PROVIDER_ID}/slots
```

### 7.6 Test Outbound Call (Call Patient Back)

#### Step 1: Create a Test Appointment First
```bash
curl -X POST http://localhost:8443/api/v1/appointments \
  -H "Content-Type: application/json" \
  -d '{
    "clinic_id": "YOUR_CLINIC_ID",
    "provider_id": "YOUR_PROVIDER_ID",
    "appointment_type": "consultation",
    "appointment_date": "2025-02-15",
    "appointment_time": "10:00:00",
    "duration_minutes": 30,
    "patient_name": "John Doe",
    "patient_phone": "+1234567890",
    "patient_email": "john@example.com"
  }'
```

#### Step 2: Initiate Outbound Call
```bash
curl -X POST http://localhost:8443/api/v1/calls/initiate \
  -H "Content-Type: application/json" \
  -d '{
    "phone_number": "+1234567890",
    "clinic_id": "YOUR_CLINIC_ID",
    "call_type": "outbound",
    "purpose": "appointment_reminder"
  }'
```

#### Step 3: Monitor Outbound Call
```bash
# Check call status
curl http://localhost:8443/api/v1/calls/{CALL_ID}/status

# Monitor logs
docker compose -f compose/gateway.yaml logs -f gateway
```

### 7.7 Test Google Calendar Integration

#### Step 1: Set Up Google Calendar OAuth
```bash
# Get OAuth URL for provider
curl "http://localhost:8443/api/v1/google-calendar/oauth/authorize?provider_id=YOUR_PROVIDER_ID"

# Follow the OAuth flow in browser
# Complete authorization
```

#### Step 2: Test Calendar Sync
```bash
# Create appointment (should sync to Google Calendar)
curl -X POST http://localhost:8443/api/v1/appointments \
  -H "Content-Type: application/json" \
  -d '{
    "clinic_id": "YOUR_CLINIC_ID",
    "provider_id": "YOUR_PROVIDER_ID",
    "appointment_type": "consultation",
    "appointment_date": "2025-02-15",
    "appointment_time": "10:00:00",
    "duration_minutes": 30,
    "patient_name": "Jane Smith",
    "patient_phone": "+1987654321",
    "patient_email": "jane@example.com"
  }'
```

#### Step 3: Verify in Google Calendar
- Check the provider's Google Calendar
- Verify appointment appears with correct details
- Confirm HIPAA compliance (patient ID vs name based on settings)

## 8. Complete Testing Checklist

### 8.1 Pre-Testing Setup Checklist

**Azure Services Setup:**
- [ ] Azure Communication Services resource created
- [ ] Phone number purchased in ACS (toll-free or local)
- [ ] ACS connection string copied to `.env`
- [ ] Azure Speech Services resource created
- [ ] Speech service key and region added to `.env`
- [ ] Azure OpenAI resource created and GPT-4 deployed
- [ ] OpenAI endpoint, API key, and deployment name added to `.env`

**Google Services Setup:**
- [ ] Google Cloud Console project created
- [ ] Google Calendar API enabled
- [ ] OAuth 2.0 credentials created
- [ ] API key created
- [ ] Google credentials added to `.env`

**System Setup:**
- [ ] ngrok installed and running (`ngrok http 8443`)
- [ ] Public webhook URL updated in `.env`
- [ ] System restarted with new configuration
- [ ] Demo data created (clinic, providers, appointment slots)

### 8.2 Real Phone Call Testing Checklist

**Inbound Call Testing:**
- [ ] Call your ACS phone number from any phone
- [ ] System answers the call automatically
- [ ] Voice recognition starts working
- [ ] AI conversation begins
- [ ] Call is logged in the system
- [ ] Patient information is collected
- [ ] Appointment can be booked via voice
- [ ] Call ends properly

**Outbound Call Testing:**
- [ ] Create test appointment via API
- [ ] Initiate outbound call to patient
- [ ] System calls patient successfully
- [ ] AI conversation works for reminders
- [ ] Call is logged and tracked

**API Testing:**
- [ ] Health endpoint responds (`/health`)
- [ ] Clinics endpoint works (`/api/v1/clinics`)
- [ ] Providers endpoint works (`/api/v1/providers`)
- [ ] Appointments endpoint works (`/api/v1/appointments`)
- [ ] Calls endpoint works (`/api/v1/calls`)

**Google Calendar Integration:**
- [ ] OAuth flow completes successfully
- [ ] Appointments sync to Google Calendar
- [ ] HIPAA compliance settings work correctly
- [ ] Calendar events show correct information

### 8.3 Performance and Reliability Testing

**Load Testing:**
- [ ] Multiple simultaneous calls handled
- [ ] System remains responsive under load
- [ ] Database performance is acceptable
- [ ] Memory usage is stable

**Error Handling:**
- [ ] Invalid phone numbers handled gracefully
- [ ] Network interruptions don't crash system
- [ ] Failed API calls are retried
- [ ] Error logs are clear and actionable

**Security Testing:**
- [ ] PHI data is properly tokenized
- [ ] Audit logs are created for all actions
- [ ] Webhook endpoints are secure
- [ ] API endpoints require proper authentication

---

## 8. Database Verification

### 8.1 Check Database Tables

```bash
# Connect to database
docker compose -f compose/gateway.yaml exec postgres psql -U postgres -d callcenterai

# List all tables
\dt

# Check clinics table
SELECT clinic_id, clinic_name, phone_number FROM clinics;

# Check providers table
SELECT provider_id, name_token, specialty FROM providers;

# Check calls table (should show tokenized phone numbers)
SELECT call_id, caller_phone_token, status FROM calls;

# Check mappings table (encrypted PHI)
SELECT token, value_type, call_id FROM mappings;
```

### 8.2 Verify PHI Tokenization

```bash
# Check that phone numbers are tokenized
SELECT caller_phone_token FROM calls;
# Should show tokens like: PHONE_ABC123DEF456

# Check that encrypted values exist in mappings
SELECT token, value_type FROM mappings WHERE value_type = 'PHONE';
```

---

## 9. Troubleshooting Real Phone Call Issues

### 9.1 ACS (Azure Communication Services) Issues

**Phone Number Not Working:**
```bash
# Check ACS connection string format
echo $ACS_CONNECTION_STRING
# Should be: endpoint=https://your-resource.communication.azure.com/;accesskey=your_key

# Verify phone number format
echo $ACS_PHONE_NUMBER
# Should be: +15551234567 (with country code)

# Test ACS connectivity
curl -X POST "https://your-resource.communication.azure.com/calling/callConnections" \
  -H "Authorization: Bearer your_access_token" \
  -H "Content-Type: application/json"
```

**Webhook Not Receiving Calls:**
```bash
# Check if ngrok is running and accessible
curl https://your-ngrok-url.ngrok.io/health

# Check webhook endpoint
curl https://your-ngrok-url.ngrok.io/api/v1/callbacks

# Verify webhook URL in ACS configuration
# Go to Azure Portal > ACS Resource > Call Automation > Webhooks
```

**Call Not Answering:**
```bash
# Check gateway logs for ACS errors
docker compose -f compose/gateway.yaml logs gateway | grep -i "acs\|call"

# Verify ACS callback URL in environment
echo $ACS_CALLBACK_URL

# Check if webhook endpoint is properly configured
curl -X POST https://your-ngrok-url.ngrok.io/api/v1/callbacks \
  -H "Content-Type: application/json" \
  -d '{"test": "webhook"}'
```

### 9.2 Speech Recognition Issues

**Voice Not Being Recognized:**
```bash
# Check Azure Speech service status
curl -X POST "https://eastus.stt.speech.microsoft.com/speech/recognition/conversation/cognitiveservices/v1" \
  -H "Ocp-Apim-Subscription-Key: $AZURE_SPEECH_KEY" \
  -H "Content-Type: audio/wav"

# Verify speech key and region
echo $AZURE_SPEECH_KEY
echo $AZURE_SPEECH_REGION

# Check speech service logs
docker compose -f compose/gateway.yaml logs gateway | grep -i "speech\|audio"
```

**Poor Audio Quality:**
- Check microphone quality on calling device
- Verify Azure Speech service region matches your location
- Test with different phone numbers
- Check network connectivity

### 9.3 AI Conversation Issues

**AI Not Responding:**
```bash
# Check Azure OpenAI service
curl -X POST "$AZURE_OPENAI_ENDPOINT/openai/deployments/$AZURE_OPENAI_DEPLOYMENT_NAME/chat/completions?api-version=2024-02-15-preview" \
  -H "api-key: $AZURE_OPENAI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Hello"}], "max_tokens": 100}'

# Verify OpenAI configuration
echo $AZURE_OPENAI_ENDPOINT
echo $AZURE_OPENAI_API_KEY
echo $AZURE_OPENAI_DEPLOYMENT_NAME
```

**AI Giving Wrong Responses:**
- Check system prompts in environment variables
- Verify language settings match your requirements
- Test with simple questions first
- Check AI model deployment status in Azure

### 9.4 Database and System Issues

**Database Connection Issues**:
```bash
# Check if postgres container is running
docker compose -f compose/gateway.yaml ps postgres

# Check postgres logs
docker compose -f compose/gateway.yaml logs postgres

# Test database connection
docker compose -f compose/gateway.yaml exec gateway python -c "
from services.database import SessionLocal
db = SessionLocal()
print('Database connected successfully')
db.close()
"
```

**API Not Responding**:
```bash
# Check gateway logs
docker compose -f compose/gateway.yaml logs gateway

# Restart gateway service
docker compose -f compose/gateway.yaml restart gateway

# Check system health
curl http://localhost:8443/health
```

**Memory or Performance Issues**:
```bash
# Check container resource usage
docker stats

# Check system logs for memory errors
docker compose -f compose/gateway.yaml logs gateway | grep -i "memory\|error\|exception"

# Restart all services
docker compose -f compose/gateway.yaml down
docker compose -f compose/gateway.yaml up -d
```

### 9.5 Google Calendar Integration Issues

**OAuth Authentication Failing:**
```bash
# Check Google credentials
echo $GOOGLE_CLIENT_ID
echo $GOOGLE_CLIENT_SECRET
echo $GOOGLE_REDIRECT_URI

# Test OAuth endpoint
curl "http://localhost:8443/api/v1/google-calendar/oauth/authorize?provider_id=TEST_PROVIDER"

# Verify redirect URI matches exactly in Google Console
```

**Calendar Sync Not Working:**
```bash
# Check Google API key
echo $GOOGLE_API_KEY

# Test Google Calendar API access
curl "https://www.googleapis.com/calendar/v3/calendars/primary/events?key=$GOOGLE_API_KEY"

# Check calendar service logs
docker compose -f compose/gateway.yaml logs gateway | grep -i "google\|calendar"
```

### 9.6 Network and Connectivity Issues

**ngrok Connection Problems:**
```bash
# Check if ngrok is running
ps aux | grep ngrok

# Restart ngrok
pkill ngrok
ngrok http 8443

# Verify ngrok URL is accessible
curl https://your-ngrok-url.ngrok.io/health
```

**Firewall or Port Issues:**
```bash
# Check if port 8443 is accessible
netstat -tlnp | grep 8443

# Test local connectivity
curl http://localhost:8443/health

# Check if Docker ports are properly mapped
docker compose -f compose/gateway.yaml ps
```

### 9.2 Log Analysis

**Check Application Logs**:
```bash
# View real-time logs
docker compose -f compose/gateway.yaml logs -f gateway

# Check for specific errors
docker compose -f compose/gateway.yaml logs gateway | grep ERROR
```

---

## 10. Production Readiness Checklist

Before deploying to production:

- [ ] All environment variables updated with real Azure/Google credentials
- [ ] Database password changed from default
- [ ] Encryption keys regenerated (optional but recommended)
- [ ] Google Calendar redirect URI updated to production domain
- [ ] Azure callback URLs updated to production domain
- [ ] CORS origins updated in environment variables
- [ ] SSL certificates configured for HTTPS
- [ ] Azure Key Vault configured for secret management
- [ ] Monitoring and alerting configured
- [ ] Backup strategy implemented

---

## 10. Step-by-Step Real Phone Testing Guide

### 10.1 Complete Setup for Real Phone Calls

**Step 1: Azure Setup (30 minutes)**
1. Create Azure Communication Services resource
2. Purchase a phone number (toll-free recommended for testing)
3. Create Azure Speech Services resource
4. Create Azure OpenAI resource and deploy GPT-4
5. Copy all credentials to `.env` file

**Step 2: Google Setup (15 minutes)**
1. Create Google Cloud Console project
2. Enable Google Calendar API
3. Create OAuth 2.0 credentials
4. Create API key
5. Update `.env` with Google credentials

**Step 3: Local Setup (10 minutes)**
1. Install ngrok: `npm install -g ngrok` or download from ngrok.com
2. Start ngrok: `ngrok http 8443`
3. Copy HTTPS URL to `.env` as `CALLBACK_BASE_URL`
4. Restart system: `docker compose -f compose/gateway.yaml down && docker compose -f compose/gateway.yaml up -d`

**Step 4: Create Demo Data (5 minutes)**
```bash
# Create clinic and providers
docker compose -f compose/gateway.yaml exec gateway python demo_setup.py

# Verify everything is working
curl http://localhost:8443/health
curl http://localhost:8443/api/v1/clinics
```

**Step 5: Test Real Phone Call (2 minutes)**
1. Call your ACS phone number from any phone
2. System should answer and start AI conversation
3. Try booking an appointment via voice
4. Check logs: `docker compose -f compose/gateway.yaml logs -f gateway`

### 10.2 Expected Call Flow

**When someone calls your ACS number:**

1. **Call Answered**: System automatically answers
2. **Greeting**: AI says "Hello, thank you for calling [Clinic Name]"
3. **Intent Recognition**: AI asks "How can I help you today?"
4. **Appointment Booking**: If patient says "book appointment":
   - AI collects: name, phone, preferred date/time, reason
   - AI checks availability
   - AI confirms appointment details
   - Appointment is created in system
   - Google Calendar is updated (if configured)
5. **Call End**: AI says goodbye and ends call

### 10.3 Monitoring and Verification

**Real-time Monitoring:**
```bash
# Watch logs in real-time
docker compose -f compose/gateway.yaml logs -f gateway

# Check call status
curl http://localhost:8443/api/v1/calls

# Verify appointments were created
curl http://localhost:8443/api/v1/appointments
```

**Success Indicators:**
- ✅ Call is answered automatically
- ✅ Voice recognition works (AI understands speech)
- ✅ AI responds appropriately
- ✅ Patient information is collected
- ✅ Appointment is booked successfully
- ✅ Call appears in system logs
- ✅ Appointment appears in database
- ✅ Google Calendar is updated (if configured)

## Quick Start Commands

```bash
# 1. Start the system
docker compose -f compose/gateway.yaml up -d

# 2. Create demo data
docker compose -f compose/gateway.yaml exec gateway python demo_setup.py

# 3. Test health
curl http://localhost:8443/health

# 4. List clinics
curl http://localhost:8443/api/v1/clinics

# 5. Check logs
docker compose -f compose/gateway.yaml logs -f gateway

# 6. Test real phone call
# Call your ACS phone number and try booking an appointment!
```

---

## File Locations Reference

- **Environment Variables**: `.env`
- **Docker Compose**: `compose/gateway.yaml`
- **Demo Setup Script**: `gateway/demo_setup.py`
- **Clinic API Routes**: `gateway/routes/clinics.py`
- **Provider API Routes**: `gateway/routes/providers.py`
- **Appointment API Routes**: `gateway/routes/appointments.py`
- **Database Models**: `gateway/models/models.py`
- **Configuration**: `gateway/services/configuration.py`
- **Clinic Management**: `gateway/services/clinic_management.py`
- **Provider Management**: `gateway/services/provider_management.py`

This checklist ensures your CallCenterAI system is properly configured and ready for testing!
