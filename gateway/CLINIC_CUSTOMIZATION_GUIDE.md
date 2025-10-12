# 🏥 Clinic Customization Guide

This guide explains how to customize the CallCenterAI system for different clinics.

## 📋 Overview

The CallCenterAI system is designed for multi-tenancy, allowing you to easily set up and customize it for different medical clinics. Each clinic gets:

- ✅ **Isolated data** (patients, appointments, providers)
- ✅ **Custom branding** (clinic name, phone number, timezone)
- ✅ **Provider management** (doctors, nurses, staff)
- ✅ **Google Calendar integration** (with clinic-specific emails)
- ✅ **Customized call flows** (greetings, languages, business hours)

## 🚀 Quick Setup for New Clinic

### 1. **Create Clinic Configuration**

Create a JSON file for your clinic (e.g., `new_clinic_setup.json`):

```json
{
  "clinic": {
    "clinic_name": "Your Clinic Name",
    "phone_number": "+1234567890",
    "timezone": "America/New_York",
    "default_language": "en",
    "supported_languages": "en,es",
    "ehr_system": "google_calendar",
    "ehr_api_endpoint": null,
    "ehr_credentials_vault_key": null,
    "max_concurrent_calls": 10,
    "queue_timeout_seconds": 45,
    "subscription_tier": "professional"
  },
  "providers": [
    {
      "name_token": "PROVIDER_DR_SMITH_001",
      "title": "Dr.",
      "specialty": "Internal Medicine",
      "license_number": "NY123456",
      "npi_number": "1234567890",
      "email": "dr.smith@yourclinic.com"
    },
    {
      "name_token": "PROVIDER_DR_JOHNSON_001", 
      "title": "Dr.",
      "specialty": "Cardiology",
      "license_number": "NY789012",
      "npi_number": "0987654321",
      "email": "dr.johnson@yourclinic.com"
    }
  ],
  "system_configs": [
    {
      "config_key": "emergency_keywords_yourclinic",
      "config_value": "emergency,urgent,heart attack,stroke,chest pain",
      "config_type": "string",
      "category": "emergency",
      "description": "Keywords that trigger emergency routing"
    },
    {
      "config_key": "clinic_hours_yourclinic",
      "config_value": "Monday-Friday: 8:00 AM - 5:00 PM, Saturday: 9:00 AM - 1:00 PM",
      "config_type": "string", 
      "category": "clinic_settings",
      "description": "Business hours for appointment scheduling"
    }
  ]
}
```

### 2. **Run Setup Script**

```bash
# Navigate to gateway directory
cd gateway

# Run the setup script
python setup_clinic.py new_clinic_setup.json
```

### 3. **Configure Google Calendar Integration**

For each provider who needs Google Calendar integration:

```bash
# Authenticate provider with Google Calendar
curl -X POST "http://localhost:8443/api/v1/google-calendar/providers/{provider_id}/authenticate" \
  -H "Content-Type: application/json" \
  -d '{"auth_code": "YOUR_GOOGLE_AUTH_CODE"}'
```

## 🔧 Customization Options

### **Clinic Information**
- **clinic_name**: Your clinic's business name
- **phone_number**: Main phone number (gets dedicated Twilio number)
- **timezone**: For appointment scheduling (e.g., "America/New_York", "America/Chicago")
- **default_language**: Primary language ("en" or "es")
- **supported_languages**: Comma-separated list ("en,es", "en", "es")

### **Provider Configuration**
- **name_token**: Unique identifier for the provider
- **title**: Professional title ("Dr.", "RN", "PA", etc.)
- **specialty**: Medical specialty ("Internal Medicine", "Cardiology", etc.)
- **license_number**: Medical license number
- **npi_number**: National Provider Identifier
- **email**: Provider's email for Google Calendar integration

### **System Configuration**
- **emergency_keywords**: Words that trigger emergency routing
- **clinic_hours**: Business hours for scheduling
- **appointment_duration**: Default appointment length
- **reminder_settings**: When to send appointment reminders

## 📞 Call Flow Customization

### **Greeting Message**
The system automatically uses your clinic name in greetings:
```
"Hello! Thank you for calling {clinic_name}. How can I help you today?"
```

### **Language Support**
- **Bilingual AI**: Automatically detects English/Spanish
- **Custom greetings**: Can be configured per clinic
- **Appointment confirmations**: Sent in patient's preferred language

### **Emergency Routing**
Configure emergency keywords to automatically route urgent calls to human staff:
```json
{
  "config_key": "emergency_keywords_yourclinic",
  "config_value": "emergency,urgent,heart attack,stroke,chest pain,can't breathe"
}
```

## 📅 Google Calendar Integration

### **Provider Email Setup**
Each provider needs a unique email address for Google Calendar:

```json
{
  "name_token": "PROVIDER_DR_SMITH_001",
  "email": "dr.smith@yourclinic.com"
}
```

### **Calendar Event Details**
Events automatically include:
- ✅ **Clinic name** in event title
- ✅ **Provider email** as attendee
- ✅ **Clinic timezone** for proper scheduling
- ✅ **Clinic phone number** in event description
- ✅ **Patient information** (tokenized for HIPAA compliance)

### **OAuth Setup**
1. **Google Cloud Console**: Create OAuth 2.0 credentials
2. **Redirect URI**: `http://your-domain.com/api/v1/google-calendar/oauth/callback`
3. **Scopes**: `https://www.googleapis.com/auth/calendar`
4. **Provider Authentication**: Each provider authenticates once

## 🏗️ Multi-Tenant Architecture

### **Data Isolation**
- ✅ **Clinic ID**: Every record includes clinic_id
- ✅ **Provider Isolation**: Providers belong to specific clinics
- ✅ **Patient Isolation**: Patients are clinic-specific
- ✅ **Appointment Isolation**: Appointments are clinic-specific

### **Scalability**
- ✅ **Unlimited Clinics**: Add as many clinics as needed
- ✅ **Provider Limits**: Configurable per subscription tier
- ✅ **Call Capacity**: Configurable concurrent call limits
- ✅ **Billing**: Per-clinic usage tracking

## 🔐 Security & Compliance

### **HIPAA Compliance**
- ✅ **PHI Tokenization**: All sensitive data is encrypted
- ✅ **Audit Logging**: Complete audit trail for all actions
- ✅ **Access Control**: Role-based permissions
- ✅ **Data Encryption**: AES-GCM encryption for all PHI

### **Credential Management**
- ✅ **Google OAuth**: Stored encrypted in database
- ✅ **EHR Integration**: Credentials in Azure Key Vault
- ✅ **API Keys**: Never stored in plain text
- ✅ **Token Refresh**: Automatic OAuth token renewal

## 📊 Monitoring & Analytics

### **Call Analytics**
- ✅ **Call Volume**: Per-clinic call statistics
- ✅ **Appointment Success Rate**: Booking conversion rates
- ✅ **Provider Utilization**: Appointment distribution
- ✅ **Patient Satisfaction**: Call outcome tracking

### **System Health**
- ✅ **Uptime Monitoring**: 24/7 system availability
- ✅ **Error Tracking**: Automatic error detection
- ✅ **Performance Metrics**: Response time monitoring
- ✅ **Capacity Planning**: Usage trend analysis

## 🚀 Deployment Options

### **Cloud Deployment**
- ✅ **Azure**: Full Azure integration with Key Vault
- ✅ **AWS**: Compatible with AWS services
- ✅ **Google Cloud**: Native Google Calendar integration
- ✅ **Docker**: Containerized deployment

### **On-Premise**
- ✅ **Self-Hosted**: Complete on-premise installation
- ✅ **Hybrid**: Cloud + on-premise hybrid setup
- ✅ **Air-Gapped**: Completely offline deployment
- ✅ **Custom Integration**: Custom EHR/EMR integration

## 📞 Support & Maintenance

### **Setup Assistance**
- ✅ **Initial Configuration**: Help with clinic setup
- ✅ **Google Calendar Setup**: OAuth configuration assistance
- ✅ **Provider Training**: Staff training on system usage
- ✅ **Custom Development**: Custom features and integrations

### **Ongoing Support**
- ✅ **24/7 Monitoring**: System health monitoring
- ✅ **Regular Updates**: Feature updates and security patches
- ✅ **Backup & Recovery**: Automated data backup
- ✅ **Performance Optimization**: Continuous performance tuning

## 📝 Example: Complete Clinic Setup

Here's a complete example for "Sunshine Medical Center":

```json
{
  "clinic": {
    "clinic_name": "Sunshine Medical Center",
    "phone_number": "+14075551234",
    "timezone": "America/New_York",
    "default_language": "en",
    "supported_languages": "en,es",
    "ehr_system": "google_calendar",
    "max_concurrent_calls": 15,
    "queue_timeout_seconds": 60,
    "subscription_tier": "professional"
  },
  "providers": [
    {
      "name_token": "PROVIDER_DR_MARTINEZ_001",
      "title": "Dr.",
      "specialty": "Family Medicine",
      "license_number": "FL123456",
      "npi_number": "1234567890",
      "email": "dr.martinez@sunshinemedical.com"
    },
    {
      "name_token": "PROVIDER_DR_LEE_001",
      "title": "Dr.", 
      "specialty": "Pediatrics",
      "license_number": "FL789012",
      "npi_number": "0987654321",
      "email": "dr.lee@sunshinemedical.com"
    },
    {
      "name_token": "PROVIDER_NURSE_GARCIA_001",
      "title": "RN",
      "specialty": "Nursing",
      "license_number": "RN345678",
      "npi_number": "1122334455",
      "email": "nurse.garcia@sunshinemedical.com"
    }
  ],
  "system_configs": [
    {
      "config_key": "emergency_keywords_sunshine",
      "config_value": "emergency,urgent,heart attack,stroke,chest pain,can't breathe,severe pain",
      "config_type": "string",
      "category": "emergency",
      "description": "Emergency keywords for Sunshine Medical Center"
    },
    {
      "config_key": "clinic_hours_sunshine",
      "config_value": "Monday-Friday: 8:00 AM - 6:00 PM, Saturday: 9:00 AM - 2:00 PM",
      "config_type": "string",
      "category": "clinic_settings", 
      "description": "Business hours for Sunshine Medical Center"
    },
    {
      "config_key": "appointment_duration_sunshine",
      "config_value": "30",
      "config_type": "number",
      "category": "clinic_settings",
      "description": "Default appointment duration in minutes"
    }
  ]
}
```

## 🎯 Next Steps

1. **Create your clinic configuration** using the examples above
2. **Run the setup script** to create your clinic
3. **Configure Google Calendar** for your providers
4. **Test the system** with the call simulator
5. **Go live** with real patient calls!

For additional support or custom requirements, contact the CallCenterAI team.

---

**CallCenterAI** - HIPAA-Compliant AI-Powered Call Center for Medical Clinics
