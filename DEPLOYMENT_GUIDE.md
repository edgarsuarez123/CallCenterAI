# CallCenterAI Deployment Guide

## Pre-Deployment Security Checklist

Before deploying CallCenterAI, ensure you have completed the following security measures:

### 1. Environment Variables Setup

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

### 2. Google Calendar Setup

1. Create a Google Cloud Console project
2. Enable Google Calendar API
3. Create OAuth 2.0 credentials
4. Configure authorized redirect URIs:
   - Development: `http://localhost:8443/api/v1/google-calendar/oauth/callback`
   - Production: `https://yourdomain.com/api/v1/google-calendar/oauth/callback`
5. Download credentials JSON file (DO NOT commit to repository)

### 3. Database Security

1. Use strong database passwords
2. Enable SSL connections
3. Configure proper firewall rules
4. Set up regular backups
5. Use connection pooling for production

### 4. Production Security

1. Use HTTPS with valid SSL certificates
2. Configure proper firewall rules
3. Set up monitoring and logging
4. Implement rate limiting
5. Regular security updates

## Deployment Steps

### 1. Repository Setup

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

### 2. Docker Deployment

```bash
# Start the services
docker-compose -f compose/gateway.yaml up -d

# Check service status
docker-compose -f compose/gateway.yaml ps

# View logs
docker-compose -f compose/gateway.yaml logs -f
```

### 3. Database Migration

```bash
# Run database migrations
docker-compose -f compose/gateway.yaml exec gateway python migrate_provider_email.py
```

### 4. Google Calendar Integration

1. Access the OAuth start URL:
   ```
   http://localhost:8443/api/v1/google-calendar/oauth/start?provider_id=PROVIDER_ID&clinic_id=CLINIC_ID
   ```
2. Complete OAuth flow in browser
3. Verify integration status

#### OAuth Token Management (Important for Production)

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

### 5. Testing

```bash
# Test API endpoints
curl http://localhost:8443/healthz

# Test call simulator
# Open http://localhost:8443/call-simulator in browser
```

## Production Deployment

### 1. Environment Configuration

- Use production-grade database (managed PostgreSQL service)
- Set up proper SSL certificates
- Configure production domain names
- Use secure environment variable management

### 2. Security Hardening

- Enable database encryption at rest
- Configure network security groups
- Set up monitoring and alerting
- Implement backup and disaster recovery

### 3. Scaling Considerations

- Use container orchestration (Kubernetes, Docker Swarm)
- Implement load balancing
- Set up horizontal scaling
- Configure auto-scaling policies

## Monitoring and Maintenance

### 1. Health Checks

- API health endpoint: `/healthz`
- Database connectivity monitoring
- Google Calendar integration status
- OAuth token expiration monitoring
- System resource monitoring

### 2. Logging

- Application logs
- Database query logs
- Security event logs
- Performance metrics

### 3. Backup Strategy

- Database backups (daily)
- Configuration backups
- Code repository backups
- Disaster recovery testing

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
   - Check token expiration and refresh status
   - Verify provider has proper Google account access

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

## Security Reminders

- **NEVER** commit sensitive data to version control
- **ALWAYS** use environment variables for secrets
- **REGULARLY** update dependencies and security patches
- **MONITOR** system access and usage
- **BACKUP** data regularly and test recovery procedures
