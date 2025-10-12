# **CallCenterAI - Complete Technical Specification**

## **System Overview**

CallCenterAI is a HIPAA-compliant, multi-tenant call center automation system for medical clinics. It provides natural language processing for appointment booking, cancellation, and patient management with Google Calendar integration and secure PHI tokenization.

## **Architecture**

### **Technology Stack**
- **Backend**: FastAPI (Python 3.11+)
- **Database**: PostgreSQL 16
- **ORM**: SQLAlchemy 2.0+
- **Containerization**: Docker & Docker Compose
- **Authentication**: OAuth 2.0 (Google Calendar)
- **Encryption**: AES-GCM for PHI data
- **Tokenization**: HMAC + ULID for deterministic tokens

### **Service Architecture**
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
```

## **Database Schema**

### **Core Tables**

#### **1. Mappings Table**
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

#### **2. Calls Table**
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

#### **3. Clinics Table**
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
    subscription_tier VARCHAR(20) DEFAULT 'basic',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```
**Purpose**: Multi-tenant clinic configuration and settings.

#### **4. Providers Table**
```sql
CREATE TABLE providers (
    provider_id VARCHAR(64) PRIMARY KEY,
    clinic_id VARCHAR(64) NOT NULL REFERENCES clinics(clinic_id),
    name_token VARCHAR(64) NOT NULL,
    title VARCHAR(50),
    specialty VARCHAR(100),
    license_number VARCHAR(50),
    npi_number VARCHAR(20),
    email VARCHAR(255),
    is_available VARCHAR(10) DEFAULT 'yes',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```
**Purpose**: Medical providers associated with clinics.

#### **5. Patients Table**
```sql
CREATE TABLE patients (
    patient_id VARCHAR(64) PRIMARY KEY,
    clinic_id VARCHAR(64) NOT NULL REFERENCES clinics(clinic_id),
    name_token VARCHAR(64) NOT NULL,
    dob_token VARCHAR(64),
    phone_token VARCHAR(64),
    email_token VARCHAR(64),
    insurance_provider_token VARCHAR(64),
    insurance_id_token VARCHAR(64),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```
**Purpose**: Patient records with tokenized PHI data.

#### **6. Appointments Table**
```sql
CREATE TABLE appointments (
    appointment_id VARCHAR(64) PRIMARY KEY,
    clinic_id VARCHAR(64) NOT NULL REFERENCES clinics(clinic_id),
    patient_id VARCHAR(64) NOT NULL REFERENCES patients(patient_id),
    provider_id VARCHAR(64) NOT NULL REFERENCES providers(provider_id),
    appointment_type VARCHAR(100) DEFAULT 'general',
    start_time TIMESTAMP WITH TIME ZONE NOT NULL,
    end_time TIMESTAMP WITH TIME ZONE NOT NULL,
    status VARCHAR(20) DEFAULT 'scheduled',
    notes_token VARCHAR(64),
    google_calendar_event_id VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```
**Purpose**: Appointment scheduling with Google Calendar integration.

#### **7. Google Calendar Credentials Table**
```sql
CREATE TABLE google_calendar_credentials (
    credential_id VARCHAR(64) PRIMARY KEY,
    provider_id VARCHAR(64) UNIQUE NOT NULL REFERENCES providers(provider_id),
    access_token_nonce BYTEA NOT NULL,
    access_token_ciphertext BYTEA NOT NULL,
    refresh_token_nonce BYTEA,
    refresh_token_ciphertext BYTEA,
    token_expires_at TIMESTAMP WITH TIME ZONE,
    scope TEXT NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    last_used_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```
**Purpose**: Encrypted OAuth credentials for Google Calendar integration.

### **Database Indexes**
```sql
-- Performance indexes
CREATE INDEX idx_calls_clinic_status ON calls(clinic_id, call_status);
CREATE INDEX idx_calls_started_at ON calls(started_at);
CREATE INDEX idx_appointments_provider_time ON appointments(provider_id, start_time);
CREATE INDEX idx_appointments_patient ON appointments(patient_id);
CREATE INDEX idx_patients_clinic_name ON patients(clinic_id, name_token);
CREATE INDEX idx_providers_clinic ON providers(clinic_id);
CREATE INDEX idx_credentials_provider ON google_calendar_credentials(provider_id);
CREATE INDEX idx_credentials_active ON google_calendar_credentials(is_active, last_used_at);
```

## **Core Services**

### **1. Natural Language Processor**

**File**: `gateway/services/natural_language_processor.py`

**Purpose**: Advanced NLP for conversational understanding with confidence scoring and entity extraction.

**Key Components**:

#### **Intent Types**
```python
class IntentType(Enum):
    APPOINTMENT_BOOKING = "appointment_booking"
    APPOINTMENT_CANCELLATION = "appointment_cancellation"
    APPOINTMENT_RESCHEDULING = "appointment_rescheduling"
    INSURANCE_INQUIRY = "insurance_inquiry"
    DOCTOR_INQUIRY = "doctor_inquiry"
    EMERGENCY = "emergency"
    GREETING = "greeting"
    GOODBYE = "goodbye"
    CONFIRMATION = "confirmation"
    NEGATION = "negation"
    UNCLEAR = "unclear"
```

#### **Entity Extraction**
```python
@dataclass
class ExtractedEntities:
    name: Optional[str] = None
    date_of_birth: Optional[str] = None
    insurance_provider: Optional[str] = None
    provider_name: Optional[str] = None
    appointment_date: Optional[str] = None
    appointment_time: Optional[str] = None
    phone_number: Optional[str] = None
    email: Optional[str] = None
    reason: Optional[str] = None
```

#### **Intent Patterns**
```python
self.intent_patterns = {
    IntentType.APPOINTMENT_BOOKING: [
        (r'\b(?:i need|i want|i would like|can i|could i|i\'d like)\s+(?:to\s+)?(?:book|schedule|make|get|set up)\s+(?:an?\s+)?(?:appointment|visit|meeting)\b', 0.9),
        (r'\b(?:book|schedule|make|get|set up)\s+(?:an?\s+)?(?:appointment|visit|meeting)\b', 0.8),
        (r'\b(?:i need|i want|i would like)\s+(?:to\s+)?(?:see|visit|meet with)\s+(?:a\s+)?(?:doctor|physician|provider)\b', 0.8),
    ],
    IntentType.APPOINTMENT_CANCELLATION: [
        (r'\b(?:i need|i want|i would like)\s+(?:to\s+)?(?:cancel|stop|remove)\s+(?:my\s+)?(?:appointment|visit|meeting)\b', 0.9),
        (r'\b(?:cancel|stop|remove)\s+(?:my\s+)?(?:appointment|visit|meeting)\b', 0.8),
        (r'\b(?:i can\'t make it|i won\'t be able to make it|i need to cancel)\b', 0.7),
    ],
    # ... more patterns
}
```

#### **Entity Extraction Patterns**
```python
self.name_patterns = [
    r'\b(?:my name is|i\'m|i am|this is|it\'s|it is|call me|i go by|you can call me)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)(?:\s|$|,|\.)',
    r'\b([A-Z][a-z]+\s+[A-Z][a-z]+)\b',  # First Last format
    r'\b(?:i\'m|i am)\s+([A-Z][a-z]+)\b',  # Just first name
]

self.dob_patterns = [
    r'\b(?:born|birthday|date of birth|dob)\s+(?:on\s+)?(\d{1,2}/\d{1,2}/\d{4})',
    r'\b(?:born|birthday|date of birth|dob)\s+(?:on\s+)?(\d{1,2}-\d{1,2}-\d{4})',
    r'\b(?:born|birthday|date of birth|dob)\s+(?:on\s+)?(\w+\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4})',
    r'\b(\d{1,2}/\d{1,2}/\d{4})\b',
    r'\b(\w+\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4})\b',
]
```

#### **Core Methods**
```python
def process_input(self, user_input: str, context: Dict[str, Any] = None) -> IntentResult:
    """Process user input and extract intent and entities"""
    
def _extract_intent(self, text: str, context: Dict[str, Any] = None) -> Tuple[IntentType, float]:
    """Extract intent from text with confidence scoring"""
    
def _extract_entities(self, text: str, context: Dict[str, Any] = None) -> ExtractedEntities:
    """Extract entities from text"""
    
def is_confirmation(self, text: str) -> bool:
    """Check if text is a confirmation"""
    
def is_negation(self, text: str) -> bool:
    """Check if text is a negation"""
```

### **2. Call Flow Service**

**File**: `gateway/services/call_flow_service.py`

**Purpose**: Orchestrates the entire conversation flow with state management and natural language understanding.

#### **Call Flow States**
```python
class CallFlowState(Enum):
    GREETING = "greeting"
    GET_INTENT = "get_intent"
    IDENTIFY_PATIENT = "identify_patient"
    RETURNING_PATIENT_INFO = "returning_patient_info"
    NEW_PATIENT_INFO = "new_patient_info"
    SELECT_PROVIDER = "select_provider"
    SELECT_DATE = "select_date"
    SELECT_TIME = "select_time"
    CONFIRM_APPOINTMENT = "confirm_appointment"
    APPOINTMENT_BOOKING = "appointment_booking"
    POST_BOOKING_HELP = "post_booking_help"
    CANCEL_APPOINTMENT = "cancel_appointment"
    INSURANCE_INQUIRY = "insurance_inquiry"
    DOCTOR_INQUIRY = "doctor_inquiry"
    EMERGENCY_ROUTING = "emergency_routing"
    TRANSFER_TO_HUMAN = "transfer_to_human"
    GOODBYE = "goodbye"
```

#### **Call Flow Context**
```python
@dataclass
class CallFlowContext:
    call_sid: str
    clinic_id: str
    current_state: CallFlowState
    call_type: Optional[str] = None
    patient_name: Optional[str] = None
    patient_id: Optional[str] = None
    patient_dob: Optional[str] = None
    insurance_provider: Optional[str] = None
    provider_id: Optional[str] = None
    appointment_date: Optional[date] = None
    appointment_time: Optional[time] = None
    appointment_type: str = "general"
    is_returning_patient: Optional[bool] = None
    last_mentioned_dates: List[date] = field(default_factory=list)
    last_mentioned_times: List[time] = field(default_factory=list)
    conversation_history: List[Dict[str, Any]] = field(default_factory=list)
```

#### **Core Methods**
```python
def initialize_call(self, call_sid: str, caller_phone: str, clinic_id: str) -> CallFlowResponse:
    """Initialize a new call and start the conversation flow"""
    
def process_input(self, call_sid: str, user_input: str) -> CallFlowResponse:
    """Process user input and return appropriate response"""
    
def _process_intent(self, context: CallFlowContext, user_input: str) -> CallFlowResponse:
    """Process user intent using natural language processing"""
    
def _handle_high_confidence_intent(self, result, context: CallFlowContext) -> CallFlowResponse:
    """Handle high confidence intent detection"""
    
def _handle_medium_confidence_intent(self, result, context: CallFlowContext) -> CallFlowResponse:
    """Handle medium confidence intent detection with clarification"""
    
def _handle_unclear_intent(self, result, context: CallFlowContext) -> CallFlowResponse:
    """Handle unclear or low confidence intent detection"""
```

### **3. Google Calendar Service**

**File**: `gateway/services/google_calendar_service.py`

**Purpose**: Handles Google Calendar OAuth authentication and event management.

#### **Configuration**
```python
@dataclass
class GoogleCalendarConfig:
    client_id: str
    client_secret: str
    redirect_uri: str
```

#### **Core Methods**
```python
def authenticate_provider(self, provider_id: str, auth_code: str = None) -> bool:
    """Authenticate provider with Google Calendar"""
    
def create_calendar_event(self, provider_id: str, appointment: Appointment, patient_name: str = None) -> Optional[str]:
    """Create a calendar event for an appointment"""
    
def update_calendar_event(self, provider_id: str, event_id: str, appointment: Appointment) -> bool:
    """Update an existing calendar event"""
    
def delete_calendar_event(self, provider_id: str, event_id: str) -> bool:
    """Delete a calendar event"""
    
def check_availability(self, provider_id: str, start_time: datetime, end_time: datetime) -> bool:
    """Check if provider is available during specified time"""
```

### **4. Google Calendar Credentials Service**

**File**: `gateway/services/google_calendar_credentials_service.py`

**Purpose**: Manages encrypted storage and retrieval of Google Calendar OAuth credentials.

#### **Core Methods**
```python
def store_credentials(self, provider_id: str, credentials: Credentials) -> bool:
    """Store encrypted Google Calendar credentials for a provider"""
    
def get_credentials(self, provider_id: str) -> Optional[Credentials]:
    """Retrieve and decrypt Google Calendar credentials for a provider"""
    
def delete_credentials(self, provider_id: str) -> bool:
    """Delete stored credentials for a provider"""
    
def get_credentials_status(self, provider_id: str) -> Dict[str, Any]:
    """Get status information about stored credentials"""
```

### **5. Appointment Service**

**File**: `gateway/services/appointment_service.py`

**Purpose**: Manages appointment creation, scheduling, and Google Calendar integration.

#### **Core Methods**
```python
def create_appointment(self, appointment_data: AppointmentCreateRequest, clinic_id: str) -> Appointment:
    """Create a new appointment with Google Calendar integration"""
    
def get_available_slots(self, provider_id: str, date: date) -> List[TimeSlotOption]:
    """Get available time slots for a provider on a specific date"""
    
def get_available_dates(self, provider_id: str, start_date: date = None) -> List[DateOption]:
    """Get available dates for a provider"""
    
def cancel_appointment(self, appointment_id: str) -> bool:
    """Cancel an appointment and remove from Google Calendar"""
```

### **6. Provider Management Service**

**File**: `gateway/services/provider_management.py`

**Purpose**: Manages provider CRUD operations and availability.

#### **Core Methods**
```python
def create_provider(self, clinic_id: str, provider_data: ProviderCreateRequest) -> Provider:
    """Create a new provider"""
    
def get_providers(self, clinic_id: str) -> List[Provider]:
    """Get all providers for a clinic"""
    
def update_provider(self, provider_id: str, provider_data: ProviderUpdateRequest) -> Optional[Provider]:
    """Update provider information"""
    
def delete_provider(self, provider_id: str) -> bool:
    """Delete a provider"""
```

### **7. Clinic Management Service**

**File**: `gateway/services/clinic_management.py`

**Purpose**: Manages clinic configuration and multi-tenant operations.

#### **Core Methods**
```python
def create_clinic(self, clinic_data: ClinicCreateRequest) -> Clinic:
    """Create a new clinic"""
    
def get_clinic(self, clinic_id: str) -> Optional[Clinic]:
    """Get clinic information"""
    
def update_clinic(self, clinic_id: str, clinic_data: ClinicUpdateRequest) -> Optional[Clinic]:
    """Update clinic configuration"""
    
def delete_clinic(self, clinic_id: str) -> bool:
    """Delete a clinic"""
```

## **API Endpoints**

### **Main Application**

**File**: `gateway/main.py`

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from services.database import Base, engine
from routes.tokens import router as tokens_router
from routes import api_router

app = FastAPI(
    title="CallCenterAI Gateway API",
    description="Comprehensive API for CallCenterAI system",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def on_startup():
    """Initialize database tables on startup."""
    Base.metadata.create_all(bind=engine)

@app.get("/healthz")
def healthz():
    """Health check endpoint."""
    return {"ok": True, "service": "gateway", "version": "1.0.0", "status": "healthy"}

@app.get("/call-simulator", response_class=HTMLResponse)
def call_simulator():
    """Serve the call simulator HTML interface."""
    # Returns HTML template for web-based call simulation

# Include routers
app.include_router(tokens_router)
app.include_router(api_router)
```

### **API Routes**

**File**: `gateway/routes/__init__.py`

```python
from fastapi import APIRouter
from .clinics import router as clinics_router
from .providers import router as providers_router
from .appointments import router as appointments_router
from .google_calendar import router as google_calendar_router
from .call_simulator import router as call_simulator_router

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(clinics_router, prefix="/clinics", tags=["clinics"])
api_router.include_router(providers_router, prefix="/providers", tags=["providers"])
api_router.include_router(appointments_router, prefix="/appointments", tags=["appointments"])
api_router.include_router(google_calendar_router, prefix="/google-calendar", tags=["google-calendar"])
api_router.include_router(call_simulator_router, prefix="/call-simulator", tags=["call-simulator"])
```

### **Clinic Management Endpoints**

**File**: `gateway/routes/clinics.py`

```python
@router.post("/", response_model=ClinicResponse)
def create_clinic(clinic_data: ClinicCreateRequest, db: Session = Depends(get_db)):
    """Create a new clinic"""

@router.get("/{clinic_id}", response_model=ClinicResponse)
def get_clinic(clinic_id: str, db: Session = Depends(get_db)):
    """Get clinic information"""

@router.put("/{clinic_id}", response_model=ClinicResponse)
def update_clinic(clinic_id: str, clinic_data: ClinicUpdateRequest, db: Session = Depends(get_db)):
    """Update clinic configuration"""

@router.delete("/{clinic_id}")
def delete_clinic(clinic_id: str, db: Session = Depends(get_db)):
    """Delete a clinic"""

@router.get("/", response_model=List[ClinicResponse])
def list_clinics(db: Session = Depends(get_db)):
    """List all clinics"""
```

### **Provider Management Endpoints**

**File**: `gateway/routes/providers.py`

```python
@router.post("/", response_model=ProviderResponse)
def create_provider(provider_data: ProviderCreateRequest, db: Session = Depends(get_db)):
    """Create a new provider"""

@router.get("/{provider_id}", response_model=ProviderResponse)
def get_provider(provider_id: str, db: Session = Depends(get_db)):
    """Get provider information"""

@router.put("/{provider_id}", response_model=ProviderResponse)
def update_provider(provider_id: str, provider_data: ProviderUpdateRequest, db: Session = Depends(get_db)):
    """Update provider information"""

@router.delete("/{provider_id}")
def delete_provider(provider_id: str, db: Session = Depends(get_db)):
    """Delete a provider"""

@router.get("/", response_model=List[ProviderResponse])
def list_providers(clinic_id: str, db: Session = Depends(get_db)):
    """List providers for a clinic"""
```

### **Appointment Management Endpoints**

**File**: `gateway/routes/appointments.py`

```python
@router.post("/", response_model=AppointmentResponse)
def create_appointment(appointment_data: AppointmentCreateRequest, db: Session = Depends(get_db)):
    """Create a new appointment"""

@router.get("/{appointment_id}", response_model=AppointmentResponse)
def get_appointment(appointment_id: str, db: Session = Depends(get_db)):
    """Get appointment information"""

@router.put("/{appointment_id}", response_model=AppointmentResponse)
def update_appointment(appointment_id: str, appointment_data: AppointmentUpdateRequest, db: Session = Depends(get_db)):
    """Update appointment"""

@router.delete("/{appointment_id}")
def cancel_appointment(appointment_id: str, db: Session = Depends(get_db)):
    """Cancel an appointment"""

@router.get("/", response_model=List[AppointmentResponse])
def list_appointments(clinic_id: str, provider_id: str = None, patient_id: str = None, db: Session = Depends(get_db)):
    """List appointments with optional filters"""
```

### **Google Calendar Integration Endpoints**

**File**: `gateway/routes/google_calendar.py`

```python
@router.get("/oauth/start")
def start_oauth_flow(provider_id: str, clinic_id: str):
    """Start Google Calendar OAuth flow"""

@router.get("/oauth/callback")
def oauth_callback(code: str, state: str):
    """Handle OAuth callback"""

@router.post("/providers/{provider_id}/authenticate")
def authenticate_provider(provider_id: str, request: AuthenticateProviderRequest, db: Session = Depends(get_db)):
    """Authenticate provider with authorization code"""

@router.get("/providers/{provider_id}/status")
def get_provider_calendar_status(provider_id: str, db: Session = Depends(get_db)):
    """Get provider's Google Calendar integration status"""

@router.post("/providers/{provider_id}/events")
def create_calendar_event(provider_id: str, event_data: CalendarEventRequest, db: Session = Depends(get_db)):
    """Create a calendar event"""

@router.put("/providers/{provider_id}/events/{event_id}")
def update_calendar_event(provider_id: str, event_id: str, event_data: CalendarEventRequest, db: Session = Depends(get_db)):
    """Update a calendar event"""

@router.delete("/providers/{provider_id}/events/{event_id}")
def delete_calendar_event(provider_id: str, event_id: str, db: Session = Depends(get_db)):
    """Delete a calendar event"""
```

### **Call Simulator Endpoints**

**File**: `gateway/routes/call_simulator.py`

```python
@router.post("/start")
def start_call(request: StartCallRequest, db: Session = Depends(get_db)):
    """Start a new call simulation"""

@router.post("/input")
def process_call_input(request: CallInputRequest, db: Session = Depends(get_db)):
    """Process user input in call simulation"""

@router.get("/status/{call_sid}")
def get_call_status(call_sid: str, db: Session = Depends(get_db)):
    """Get current call status"""

@router.post("/end/{call_sid}")
def end_call(call_sid: str, db: Session = Depends(get_db)):
    """End a call simulation"""
```

## **Data Models and Schemas**

### **Pydantic Schemas**

**File**: `gateway/models/schemas.py`

#### **Clinic Schemas**
```python
class ClinicCreateRequest(BaseModel):
    clinic_name: str = Field(..., min_length=1, max_length=255)
    phone_number: str = Field(..., min_length=10, max_length=20)
    timezone: str = Field(default="America/New_York", max_length=50)
    default_language: str = Field(default="en", max_length=10)
    supported_languages: str = Field(default="en", max_length=100)
    ehr_system: str = Field(default="google_calendar", max_length=50)
    max_concurrent_calls: int = Field(default=10, ge=1, le=100)
    queue_timeout_seconds: int = Field(default=60, ge=30, le=300)
    subscription_tier: str = Field(default="basic", max_length=20)

class ClinicResponse(BaseModel):
    clinic_id: str
    clinic_name: str
    phone_number: str
    timezone: str
    default_language: str
    supported_languages: str
    ehr_system: str
    max_concurrent_calls: int
    queue_timeout_seconds: int
    subscription_tier: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
```

#### **Provider Schemas**
```python
class ProviderCreateRequest(BaseModel):
    name_token: str = Field(..., min_length=1, max_length=64)
    title: str = Field(..., min_length=1, max_length=20)
    specialty: str = Field(..., min_length=1, max_length=100)
    license_number: Optional[str] = Field(None, max_length=50)
    npi_number: Optional[str] = Field(None, max_length=20)
    email: Optional[str] = Field(None, max_length=255)
    
    @validator('npi_number')
    def validate_npi_number(cls, v):
        if v and not v.isdigit():
            raise ValueError('NPI number must contain only digits')
        return v

class ProviderResponse(BaseModel):
    provider_id: str
    clinic_id: str
    name_token: str
    title: str
    specialty: str
    license_number: Optional[str]
    npi_number: Optional[str]
    email: Optional[str]
    is_available: str
    created_at: datetime
    updated_at: datetime
```

#### **Appointment Schemas**
```python
class AppointmentCreateRequest(BaseModel):
    patient_name: str = Field(..., min_length=1, max_length=255)
    patient_dob: Optional[str] = Field(None, max_length=50)
    patient_phone: Optional[str] = Field(None, max_length=20)
    patient_email: Optional[str] = Field(None, max_length=255)
    insurance_provider: Optional[str] = Field(None, max_length=100)
    provider_id: str = Field(..., min_length=1, max_length=64)
    appointment_type: str = Field(default="general", max_length=100)
    start_time: datetime
    end_time: datetime
    notes: Optional[str] = Field(None, max_length=1000)

class AppointmentResponse(BaseModel):
    appointment_id: str
    clinic_id: str
    patient_id: str
    provider_id: str
    appointment_type: str
    start_time: datetime
    end_time: datetime
    status: str
    notes_token: Optional[str]
    google_calendar_event_id: Optional[str]
    created_at: datetime
    updated_at: datetime
```

### **Call Flow Models**

**File**: `gateway/models/call_flow_models.py`

```python
@dataclass
class CallFlowResponse:
    next_state: CallFlowState
    message: str
    data: Dict[str, Any] = field(default_factory=dict)
    options: List[str] = field(default_factory=list)
    requires_input: bool = True
    is_complete: bool = False

@dataclass
class PatientIdentificationResult:
    is_found: bool
    patient_id: Optional[str] = None
    patient_name: Optional[str] = None
    confidence: float = 0.0

@dataclass
class ProviderOption:
    provider_id: str
    name: str
    specialty: str
    is_available: bool

@dataclass
class TimeSlotOption:
    time: time
    is_available: bool
    duration_minutes: int = 30

@dataclass
class DateOption:
    date: date
    day_name: str
    available_slots: int
    is_available: bool
```

## **Security and Encryption**

### **Crypto Service**

**File**: `gateway/services/crypto.py`

```python
import base64
import hmac
import hashlib
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from ulid import ULID

def aesgcm_encrypt(data: bytes) -> Tuple[bytes, bytes]:
    """Encrypt data using AES-GCM"""
    key = base64.b64decode(os.getenv('AES_GCM_KEY_BASE64'))
    nonce = os.urandom(12)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, data, None)
    return nonce, ciphertext

def aesgcm_decrypt(nonce: bytes, ciphertext: bytes) -> bytes:
    """Decrypt data using AES-GCM"""
    key = base64.b64decode(os.getenv('AES_GCM_KEY_BASE64'))
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ciphertext, None)

def make_hmac_token(value: str) -> str:
    """Create deterministic token for phone numbers, emails"""
    key = base64.b64decode(os.getenv('CLINIC_TOKEN_HMAC_KEY_BASE64'))
    return hmac.new(key, value.encode(), hashlib.sha256).hexdigest()[:16]

def make_ulid_token() -> str:
    """Create unique token for names, DOB"""
    return str(ULID())
```

### **Tokenization Service**

**File**: `gateway/services/tokens.py`

```python
def tokenize_text(text: str, call_id: str = None) -> str:
    """Tokenize text and store encrypted version in database"""
    token = make_ulid_token()
    
    # Encrypt and store
    nonce, ciphertext = aesgcm_encrypt(text.encode('utf-8'))
    
    # Store in database
    mapping = Mapping(
        token=token,
        value_nonce=nonce,
        value_ciphertext=ciphertext,
        value_type="text",
        call_id=call_id
    )
    db.add(mapping)
    db.commit()
    
    return token

def detokenize_text(token: str) -> Optional[str]:
    """Retrieve and decrypt text from token"""
    mapping = db.query(Mapping).filter(Mapping.token == token).first()
    if not mapping:
        return None
    
    try:
        decrypted = aesgcm_decrypt(mapping.value_nonce, mapping.value_ciphertext)
        return decrypted.decode('utf-8')
    except Exception:
        return None
```

## **Database Configuration**

### **Database Service**

**File**: `gateway/services/database.py`

```python
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os

DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://user:password@localhost:5432/callcenter_db')

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    """Dependency to get database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

## **Docker Configuration**

### **Dockerfile**

**File**: `gateway/Dockerfile`

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose port
EXPOSE 8443

# Run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8443"]
```

### **Docker Compose**

**File**: `compose/gateway.yaml`

```yaml
version: "3.9"
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_PASSWORD: ChangeThisNow_!
    volumes:
      - ./data/gateway/postgres:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U callcenterai -d callcenterai -h localhost"]
      interval: 10s
      timeout: 5s
      retries: 10
    restart: always
  
  gateway:
    build:
      context: ./gateway
      dockerfile: Dockerfile
    environment:
       - PYTHONPATH=/app
       - APP_ENV=dev
       - CLINIC_TOKEN_HMAC_KEY_BASE64=Q2FsbENlbnRlckFJX0Rldl9IYW1jS2V5XzMyQnl0ZXM=
       - AES_GCM_KEY_BASE64=Q2FsbENlbnRlckFJX0Rldl9BRVNfS2V5XzMyQnl0ZXM=
       - GOOGLE_CLIENT_ID=your_google_client_id
       - GOOGLE_CLIENT_SECRET=your_google_client_secret
       - GOOGLE_REDIRECT_URI=http://localhost:8443/api/v1/google-calendar/oauth/callback
    volumes:
      - ./gateway:/app:rw
    depends_on:
      postgres:
        condition: service_healthy
    ports:
      - "8443:8443"
    restart: always
    command: uvicorn main:app --host 0.0.0.0 --port 8443 --reload
```

## **Requirements**

**File**: `gateway/requirements.txt`

```
fastapi==0.104.1
uvicorn[standard]==0.24.0
sqlalchemy==2.0.23
psycopg2-binary==2.9.9
pydantic==2.5.0
python-multipart==0.0.6
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4
cryptography==41.0.8
ulid-py==1.1.0
google-api-python-client==2.108.0
google-auth-oauthlib==1.1.0
google-auth==2.25.2
python-dotenv==1.0.0
```

## **Web Interface**

### **Call Simulator Template**

**File**: `gateway/templates/call_simulator.html`

```html
<!DOCTYPE html>
<html>
<head>
    <title>CallCenterAI - Call Simulator</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        .container { max-width: 800px; margin: 0 auto; }
        .call-box { border: 2px solid #ccc; padding: 20px; margin: 20px 0; }
        .input-group { margin: 10px 0; }
        .input-group input { width: 100%; padding: 10px; }
        .input-group button { padding: 10px 20px; background: #007bff; color: white; border: none; cursor: pointer; }
        .response { background: #f8f9fa; padding: 15px; margin: 10px 0; border-left: 4px solid #007bff; }
        .error { background: #f8d7da; border-left-color: #dc3545; }
    </style>
</head>
<body>
    <div class="container">
        <h1>CallCenterAI - Call Simulator</h1>
        <div class="call-box">
            <div class="input-group">
                <input type="text" id="phoneInput" placeholder="Enter phone number (e.g., (555) 123-4567)" />
                <button onclick="startCall()">Start Call</button>
            </div>
            <div id="callStatus"></div>
            <div id="conversation"></div>
            <div class="input-group" id="inputGroup" style="display: none;">
                <input type="text" id="userInput" placeholder="Type what you want to say..." onkeypress="handleKeyPress(event)" />
                <button onclick="sendInput()">Send</button>
            </div>
        </div>
    </div>

    <script>
        let currentCallSid = null;

        async function startCall() {
            const phone = document.getElementById('phoneInput').value;
            if (!phone) {
                alert('Please enter a phone number');
                return;
            }

            try {
                const response = await fetch('/api/v1/call-simulator/start', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ caller_phone: phone, clinic_id: 'CLINIC_STPETERS_001' })
                });

                const data = await response.json();
                if (data.success) {
                    currentCallSid = data.call_sid;
                    document.getElementById('callStatus').innerHTML = `<div class="response">Call started: ${data.call_sid}</div>`;
                    document.getElementById('inputGroup').style.display = 'block';
                    addToConversation('System', data.message);
                } else {
                    document.getElementById('callStatus').innerHTML = `<div class="response error">Failed to start call: ${data.error}</div>`;
                }
            } catch (error) {
                document.getElementById('callStatus').innerHTML = `<div class="response error">Error: ${error.message}</div>`;
            }
        }

        async function sendInput() {
            const input = document.getElementById('userInput').value;
            if (!input || !currentCallSid) return;

            addToConversation('You', input);
            document.getElementById('userInput').value = '';

            try {
                const response = await fetch('/api/v1/call-simulator/input', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ call_sid: currentCallSid, user_input: input })
                });

                const data = await response.json();
                if (data.success) {
                    addToConversation('System', data.message);
                    if (data.is_complete) {
                        document.getElementById('inputGroup').style.display = 'none';
                        currentCallSid = null;
                    }
                } else {
                    addToConversation('System', `Error: ${data.error}`, true);
                }
            } catch (error) {
                addToConversation('System', `Error: ${error.message}`, true);
            }
        }

        function addToConversation(speaker, message, isError = false) {
            const conversation = document.getElementById('conversation');
            const div = document.createElement('div');
            div.className = `response ${isError ? 'error' : ''}`;
            div.innerHTML = `<strong>${speaker}:</strong> ${message}`;
            conversation.appendChild(div);
            conversation.scrollTop = conversation.scrollHeight;
        }

        function handleKeyPress(event) {
            if (event.key === 'Enter') {
                sendInput();
            }
        }
    </script>
</body>
</html>
```

## **Environment Variables**

```bash
# Database
DATABASE_URL=postgresql://user:password@localhost:5432/callcenter_db

# Encryption Keys (Base64 encoded)
CLINIC_TOKEN_HMAC_KEY_BASE64=Q2FsbENlbnRlckFJX0Rldl9IYW1jS2V5XzMyQnl0ZXM=
AES_GCM_KEY_BASE64=Q2FsbENlbnRlckFJX0Rldl9BRVNfS2V5XzMyQnl0ZXM=

# Google Calendar OAuth
GOOGLE_CLIENT_ID=your_google_client_id
GOOGLE_CLIENT_SECRET=your_google_client_secret
GOOGLE_REDIRECT_URI=http://localhost:8443/api/v1/google-calendar/oauth/callback

# Application
APP_ENV=dev
PYTHONPATH=/app
```

## **Deployment Instructions**

### **1. Prerequisites**
- Docker and Docker Compose
- Google Cloud Console project with Calendar API enabled
- OAuth 2.0 credentials configured

### **2. Setup Steps**
```bash
# Clone repository
git clone <repository-url>
cd CallCenterAI

# Create environment file
cp .env.example .env
# Edit .env with your configuration

# Start services
docker-compose -f compose/gateway.yaml up -d

# Run database migrations
docker-compose -f compose/gateway.yaml exec gateway python migrate_provider_email.py

# Access the application
# API: http://localhost:8443/docs
# Call Simulator: http://localhost:8443/call-simulator
```

### **3. Google Calendar Setup**
1. Create Google Cloud Console project
2. Enable Google Calendar API
3. Create OAuth 2.0 credentials
4. Configure authorized redirect URIs
5. Update environment variables with credentials

## **Testing**

### **Call Flow Testing**
```bash
# Start call simulation
curl -X POST http://localhost:8443/api/v1/call-simulator/start \
  -H "Content-Type: application/json" \
  -d '{"caller_phone": "(555) 123-4567", "clinic_id": "CLINIC_STPETERS_001"}'

# Send input
curl -X POST http://localhost:8443/api/v1/call-simulator/input \
  -H "Content-Type: application/json" \
  -d '{"call_sid": "CALL_SID", "user_input": "I need to book an appointment"}'
```

### **API Testing**
```bash
# Create clinic
curl -X POST http://localhost:8443/api/v1/clinics \
  -H "Content-Type: application/json" \
  -d '{"clinic_name": "Test Clinic", "phone_number": "+14071234567"}'

# Create provider
curl -X POST http://localhost:8443/api/v1/providers \
  -H "Content-Type: application/json" \
  -d '{"name_token": "PROVIDER_DR_TEST_001", "title": "Dr.", "specialty": "General Practice", "email": "dr.test@clinic.com"}'
```

## **Key Features Implemented**

1. **HIPAA-Compliant PHI Tokenization** - All sensitive data encrypted and tokenized
2. **Multi-Tenant Architecture** - Support for multiple clinics with data isolation
3. **Natural Language Processing** - Advanced conversational understanding
4. **Google Calendar Integration** - OAuth authentication and event management
5. **Call Flow Management** - State-based conversation orchestration
6. **Web-Based Call Simulator** - Interactive testing interface
7. **Comprehensive API** - RESTful endpoints for all operations
8. **Database-Backed Credential Storage** - Secure OAuth token management
9. **Context-Aware Conversations** - Remembers conversation state
10. **Confidence-Based Responses** - Adaptive responses based on understanding confidence

This specification provides complete implementation details for recreating the CallCenterAI system with identical functionality and architecture.
