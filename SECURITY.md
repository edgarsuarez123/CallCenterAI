# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 1.0.x   | :white_check_mark: |

## Security Considerations

### Sensitive Data Handling

This repository contains a HIPAA-compliant healthcare communication system. The following security measures are implemented:

1. **PHI Tokenization**: All Protected Health Information (PHI) is encrypted using AES-GCM encryption and stored with tokenized references
2. **Environment Variables**: Sensitive configuration data is stored in environment variables, not in code
3. **Database Security**: All database connections use encrypted connections and secure authentication

### Files NOT to Commit

The following files contain sensitive information and should NEVER be committed to version control:

- `google_credentials.json` - Google OAuth credentials
- `.env` files - Environment variables with secrets
- `data/` directory - Database files and patient data
- Any files containing actual API keys, passwords, or patient information

### Environment Variables Required

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

### Security Best Practices

1. **Never commit secrets**: All sensitive data should be in environment variables
2. **Use strong encryption keys**: Generate cryptographically secure keys for production
3. **Regular security updates**: Keep all dependencies updated
4. **Access control**: Limit repository access to authorized personnel only
5. **Audit logging**: Monitor all access to patient data

### Reporting Security Vulnerabilities

If you discover a security vulnerability, please report it privately:

1. **DO NOT** create a public GitHub issue
2. Email security concerns to: [your-security-email@domain.com]
3. Include detailed information about the vulnerability
4. Allow reasonable time for response before public disclosure

### HIPAA Compliance

This system is designed to be HIPAA-compliant when properly configured:

- All PHI is encrypted at rest and in transit
- Access controls are implemented
- Audit trails are maintained
- Data retention policies are enforced

**Important**: Ensure your deployment meets all HIPAA requirements for your specific use case.

## Security Checklist for Deployment

- [ ] All environment variables are set with secure values
- [ ] Database is configured with strong passwords
- [ ] SSL/TLS certificates are properly configured
- [ ] Firewall rules are properly configured
- [ ] Regular security updates are scheduled
- [ ] Backup and recovery procedures are tested
- [ ] Access logs are monitored
- [ ] HIPAA compliance requirements are met
