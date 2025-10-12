# CallCenterAI

A HIPAA-compliant, multi-tenant call center automation system for medical clinics with natural language processing, appointment scheduling, and Google Calendar integration.

## 🏥 Features

- **HIPAA-Compliant PHI Tokenization** - All sensitive patient data is encrypted and tokenized
- **Multi-Tenant Architecture** - Support for multiple clinics with complete data isolation
- **Natural Language Processing** - Advanced conversational AI for appointment booking
- **Google Calendar Integration** - OAuth authentication and automatic event creation
- **Web-Based Call Simulator** - Interactive testing interface for demos
- **Comprehensive API** - RESTful endpoints for all operations
- **Docker Containerization** - Easy deployment and scaling

## 🚀 Quick Start

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

## 📚 Documentation

- **[Technical Specification](CALL_CENTER_AI_TECHNICAL_SPECIFICATION.md)** - Complete implementation details
- **[Engineering Documentation](CALL_CENTER_AI_ENGINEERING_DOCUMENTATION.md)** - System design and architecture
- **[Security Policy](SECURITY.md)** - Security considerations and best practices
- **[Deployment Guide](DEPLOYMENT_GUIDE.md)** - Production deployment instructions
- **[GitHub Setup Guide](GITHUB_SETUP_GUIDE.md)** - Repository setup and security

## 🔒 Security

This system handles Protected Health Information (PHI) and implements HIPAA-compliant security measures:

- All PHI data is encrypted using AES-GCM encryption
- Deterministic and non-deterministic tokenization for data references
- Secure OAuth 2.0 integration with Google Calendar
- Environment variable-based configuration management
- Comprehensive audit logging and access controls

**⚠️ Important**: Never commit sensitive files like `google_credentials.json`, `.env` files, or database data to version control.

## 🏗️ Architecture

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

## 🛠️ Development

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

## 📋 API Endpoints

- `GET /healthz` - Health check
- `POST /api/v1/call-simulator/start` - Start call simulation
- `POST /api/v1/call-simulator/input` - Process call input
- `GET /api/v1/clinics` - Clinic management
- `GET /api/v1/providers` - Provider management
- `POST /api/v1/appointments` - Appointment scheduling
- `GET /api/v1/google-calendar/oauth/start` - Google Calendar OAuth

## 🧪 Testing

### Call Flow Testing
```bash
# Start call simulation
curl -X POST http://localhost:8443/api/v1/call-simulator/start \
  -H "Content-Type: application/json" \
  -d '{"caller_phone": "(555) 123-4567", "clinic_id": "CLINIC_STPETERS_001"}'
```

### Web Interface
Open http://localhost:8443/call-simulator in your browser for interactive testing.

## 🔧 Configuration

### Required Environment Variables
```bash
DATABASE_URL=postgresql://user:password@localhost:5432/callcenter_db
CLINIC_TOKEN_HMAC_KEY_BASE64=your_hmac_key_here
AES_GCM_KEY_BASE64=your_aes_key_here
GOOGLE_CLIENT_ID=your_google_client_id
GOOGLE_CLIENT_SECRET=your_google_client_secret
GOOGLE_REDIRECT_URI=http://localhost:8443/api/v1/google-calendar/oauth/callback
```

## 📄 License

This project is proprietary software. All rights reserved.

## 🤝 Support

For technical support and questions:
1. Review the documentation files
2. Check the security policy
3. Verify environment configuration
4. Test individual components

## ⚠️ Disclaimer

This software is designed for healthcare communication automation. Ensure compliance with all applicable healthcare regulations (HIPAA, etc.) in your jurisdiction before deployment.