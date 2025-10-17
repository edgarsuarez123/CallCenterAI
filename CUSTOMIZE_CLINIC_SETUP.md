# Customize Your Clinic Setup

The `demo_setup.py` script has been updated to allow you to easily customize your clinic and provider information. Here's how to modify it for your specific needs.

## 🏥 Customizing Your Clinic

### **Step 1: Edit Clinic Information**

**File**: `gateway/demo_setup.py`  
**Function**: `create_custom_clinic()` (lines 35-61)

```python
clinic_data = ClinicCreateRequest(
    clinic_name="Your Medical Center",  # ← Change this to your clinic name
    phone_number="+1234567890",  # ← Change this to your clinic phone
    timezone="America/New_York",  # ← Change this to your timezone
    default_language="en",  # ← Change this to your default language
    supported_languages="en,es",  # ← Change this to your supported languages
    ehr_system="Google Calendar",  # ← Keep this for Google Calendar integration
    ehr_api_endpoint=None,  # ← Optional: your EHR API endpoint
    ehr_credentials_vault_key=None,  # ← Optional: your EHR credentials vault key
    max_concurrent_calls=10,  # ← Change this to your max concurrent calls
    queue_timeout_seconds=45,  # ← Change this to your queue timeout
    subscription_tier="professional"  # ← Change this to your subscription tier
)
```

### **Example Customizations:**

#### **Family Practice Example:**
```python
clinic_data = ClinicCreateRequest(
    clinic_name="Sunshine Family Practice",
    phone_number="+13055551234",
    timezone="America/New_York",
    default_language="en",
    supported_languages="en,es",
    ehr_system="Google Calendar",
    ehr_api_endpoint=None,
    ehr_credentials_vault_key=None,
    max_concurrent_calls=15,
    queue_timeout_seconds=60,
    subscription_tier="professional"
)
```

#### **Specialty Clinic Example:**
```python
clinic_data = ClinicCreateRequest(
    clinic_name="Cardiovascular Associates",
    phone_number="+12145551234",
    timezone="America/Chicago",
    default_language="en",
    supported_languages="en",
    ehr_system="Google Calendar",
    ehr_api_endpoint=None,
    ehr_credentials_vault_key=None,
    max_concurrent_calls=8,
    queue_timeout_seconds=30,
    subscription_tier="professional"
)
```

---

## 👨‍⚕️ Customizing Your Providers

### **Step 2: Edit Provider Information**

**File**: `gateway/demo_setup.py`  
**Function**: `create_custom_providers()` (lines 80-114)

```python
providers_data = [
    {
        "name_token": "Dr. John Smith",  # ← Change this to your provider's name
        "title": "Dr.",  # ← Dr., Mr., Ms., etc.
        "specialty": "Family Medicine",  # ← Change this to their specialty
        "email": "dr.smith@yourclinic.com"  # ← Change this to their email
    },
    {
        "name_token": "Dr. Jane Doe",  # ← Add more providers as needed
        "title": "Dr.",
        "specialty": "Cardiology",
        "email": "dr.doe@yourclinic.com"
    },
    # Add more providers here if needed
]
```

### **Example Provider Customizations:**

#### **Family Practice Providers:**
```python
providers_data = [
    {
        "name_token": "Dr. Maria Rodriguez",
        "title": "Dr.",
        "specialty": "Family Medicine",
        "email": "dr.rodriguez@sunshinefamily.com"
    },
    {
        "name_token": "Dr. James Wilson",
        "title": "Dr.",
        "specialty": "Internal Medicine",
        "email": "dr.wilson@sunshinefamily.com"
    },
    {
        "name_token": "Dr. Sarah Chen",
        "title": "Dr.",
        "specialty": "Pediatrics",
        "email": "dr.chen@sunshinefamily.com"
    }
]
```

#### **Specialty Clinic Providers:**
```python
providers_data = [
    {
        "name_token": "Dr. Michael Thompson",
        "title": "Dr.",
        "specialty": "Cardiology",
        "email": "dr.thompson@cardioassoc.com"
    },
    {
        "name_token": "Dr. Lisa Park",
        "title": "Dr.",
        "specialty": "Interventional Cardiology",
        "email": "dr.park@cardioassoc.com"
    }
]
```

---

## 🚀 Running Your Custom Setup

### **Step 3: Run the Setup Script**

```bash
# 1. Start your system
docker compose -f compose/gateway.yaml up -d

# 2. Run your customized setup
docker compose -f compose/gateway.yaml exec gateway python demo_setup.py
```

### **Expected Output:**
```
Starting custom clinic setup...
Database tables created/verified
Creating custom clinic...
Created custom clinic: CLINIC_ABC123DEF456
Creating custom providers...
Created provider: PROVIDER_ABC123_001 - Dr. John Smith
Created provider: PROVIDER_ABC123_002 - Dr. Jane Doe
Creating appointment slots for the entire year...
Creating appointment slots for Dr. John Smith for the entire year
Created 100 slots for Dr. John Smith up to 2024-01-20
...
Finished creating 4160 slots for Dr. John Smith
Finished creating 12480 total appointment slots for the year
Custom clinic setup completed successfully!
Clinic ID: CLINIC_ABC123DEF456
Created 3 providers
Created appointment slots for the entire year
Patients will be created automatically when they call
```

---

## 📋 What Gets Created

### **Your Custom Clinic:**
- ✅ Clinic with your name, address, phone, email
- ✅ Your business hours and timezone
- ✅ Google Calendar integration ready
- ✅ Emergency keywords configured

### **Your Custom Providers:**
- ✅ Each provider with their name, title, specialty
- ✅ Email addresses for each provider
- ✅ Year-long appointment slots (9 AM - 5 PM, Mon-Fri)

### **Appointment Slots:**
- ✅ **~4,160 slots per provider** for the entire year
- ✅ **30-minute intervals** (9:00, 9:30, 10:00, etc.)
- ✅ **Monday to Friday only** (weekends excluded)
- ✅ **Available for booking** immediately

### **Patient Creation:**
- ✅ **No demo patients created** (as requested)
- ✅ **Patients created automatically** when they call
- ✅ **AI collects information** and creates patient records
- ✅ **HIPAA-compliant** tokenization and storage

---

## 🔄 Making Changes

### **To Update Your Clinic:**
1. Edit the `clinic_data` in `create_custom_clinic()`
2. Run the setup script again
3. The script will find your existing clinic and update it

### **To Add/Remove Providers:**
1. Edit the `providers_data` list in `create_custom_providers()`
2. Run the setup script again
3. New providers will be added, existing ones will be found

### **To Change Appointment Hours:**
1. Edit the `business_hours` in `clinic_data`
2. The appointment slots will still be created for 9 AM - 5 PM
3. You can modify the slot creation logic if needed

---

## 🎯 Quick Start Template

Here's a minimal template to get you started:

```python
# In create_custom_clinic():
clinic_data = ClinicCreateRequest(
    clinic_name="My Medical Practice",  # ← Your clinic name
    phone_number="+1234567890",  # ← Your phone
    timezone="America/New_York",  # ← Your timezone
    default_language="en",  # ← Your default language
    supported_languages="en,es",  # ← Your supported languages
    ehr_system="Google Calendar",
    ehr_api_endpoint=None,  # ← Optional
    ehr_credentials_vault_key=None,  # ← Optional
    max_concurrent_calls=10,  # ← Your max concurrent calls
    queue_timeout_seconds=45,  # ← Your queue timeout
    subscription_tier="professional"  # ← Your subscription tier
)

# In create_custom_providers():
providers_data = [
    {
        "name_token": "Dr. Your Name",  # ← Your name
        "title": "Dr.",
        "specialty": "Your Specialty",  # ← Your specialty
        "email": "dr.you@mymedical.com"  # ← Your email
    }
]
```

This gives you complete control over your clinic setup while maintaining the automated appointment slot creation and patient management system!
