# Breaking Changes

## Port Standardization
- Default port changed from 8000 to 8443
- Update `APP_PORT=8443` in container configuration
- Update `--ports 8443` in Azure container create command

## New Required Environment Variables
- `CLINIC_TOKEN_HMAC_KEY_BASE64` - Required for clinic token generation
- `AES_GCM_KEY_BASE64` - Required for data encryption

## Google Calendar Configuration
- Variables now use `GOOGLE_` prefix (already implemented)
- `GOOGLE_WORKSPACE_HIPAA_COMPLIANT` renamed to `GOOGLE_HIPAA_COMPLIANT`
- Google Calendar is now optional (won't block startup if not configured)

## Database Configuration
- Removed fallback to `POSTGRES_*` variables in migrations
- Use `DB_*` variables consistently
- `ChangeThisNow_!` fallback passwords removed

## Security
- Wildcard CORS (`*`) blocked in production environment
- Production deployments must specify explicit CORS origins
