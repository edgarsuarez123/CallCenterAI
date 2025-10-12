# Google Calendar Integration Setup Guide

## 🎉 Current Status
✅ **Google Calendar API packages installed**  
✅ **Service initialization working**  
✅ **OAuth configuration ready**  
✅ **Event data preparation successful**  
✅ **Appointment sync preparation working**

## 📋 Setup Steps

### 1. Google Cloud Console Setup

1. **Go to Google Cloud Console**
   - Visit: https://console.cloud.google.com/
   - Sign in with your Google account

2. **Create a New Project**
   - Click "Select a project" → "New Project"
   - Name: "CallCenterAI Calendar Integration"
   - Click "Create"

3. **Enable Google Calendar API**
   - Go to "APIs & Services" → "Library"
   - Search for "Google Calendar API"
   - Click on it and press "Enable"

### 2. Create OAuth 2.0 Credentials

1. **Go to Credentials**
   - Navigate to "APIs & Services" → "Credentials"
   - Click "Create Credentials" → "OAuth 2.0 Client IDs"

2. **Configure OAuth Consent Screen**
   - If prompted, configure the OAuth consent screen:
     - User Type: External
     - App name: "CallCenterAI"
     - User support email: Your email
     - Developer contact: Your email
     - Add scopes: `https://www.googleapis.com/auth/calendar`

3. **Create OAuth Client**
   - Application type: "Web application"
   - Name: "CallCenterAI Gateway"
   - Authorized redirect URIs:
     - `http://localhost:8443/api/google-calendar/oauth/callback`
     - `https://yourdomain.com/api/google-calendar/oauth/callback` (for production)

4. **Download Credentials**
   - Download the JSON file
   - Save as `google_credentials.json` in the gateway directory

### 3. Environment Configuration

Create a `.env` file in the gateway directory:

```bash
# Google Calendar Integration
GOOGLE_CLIENT_ID=your_client_id_here
GOOGLE_CLIENT_SECRET=your_client_secret_here
GOOGLE_REDIRECT_URI=http://localhost:8443/api/google-calendar/oauth/callback

# Optional: For production
GOOGLE_CALENDAR_TIMEZONE=America/New_York
```

### 4. Test the Integration

1. **Start the services:**
   ```bash
   docker-compose -f compose/gateway.yaml up -d
   ```

2. **Test OAuth flow:**
   - Visit: http://localhost:8443/api/google-calendar/oauth/start
   - This will redirect you to Google for authorization
   - After authorization, you'll be redirected back with a code

3. **Test appointment creation:**
   - Use the web simulator: http://localhost:8443/call-simulator
   - Book an appointment
   - Check your Google Calendar for the new event

## 🔧 API Endpoints

The system provides these Google Calendar endpoints:

- `GET /api/google-calendar/oauth/start` - Start OAuth flow
- `GET /api/google-calendar/oauth/callback` - OAuth callback
- `POST /api/google-calendar/sync-slots/{provider_id}` - Sync appointment slots
- `POST /api/google-calendar/events` - Create calendar event
- `PUT /api/google-calendar/events/{event_id}` - Update calendar event
- `DELETE /api/google-calendar/events/{event_id}` - Delete calendar event

## 📊 What Gets Synced

When an appointment is booked through the call flow:

1. **Event Created** in provider's Google Calendar
2. **Event Details:**
   - Title: "Appointment - [type]"
   - Description: Patient info, appointment details
   - Start/End: Exact appointment times
   - Attendees: Provider email
   - Location: Clinic address (if configured)

3. **Automatic Updates:**
   - Event updated when appointment is modified
   - Event deleted when appointment is cancelled

## 🚨 Important Notes

1. **Provider Email Required:**
   - Each provider needs a Google Calendar email
   - Add `email` field to Provider model if not present
   - Or use a shared clinic calendar

2. **Timezone Handling:**
   - All times are stored in UTC in the database
   - Converted to clinic timezone for Google Calendar
   - Default: America/New_York (configurable)

3. **Error Handling:**
   - If Google Calendar sync fails, appointment still gets booked
   - Errors are logged for debugging
   - Manual sync available via API

## 🧪 Testing

Run the test script to verify everything works:

```bash
docker-compose -f compose/gateway.yaml exec gateway python test_google_calendar.py
```

## 🔒 Security Considerations

1. **Credentials Storage:**
   - Never commit `google_credentials.json` to version control
   - Use environment variables in production
   - Rotate credentials regularly

2. **OAuth Scopes:**
   - Only request necessary permissions
   - Current scopes: calendar read/write
   - Consider calendar.events for more granular control

3. **HTTPS in Production:**
   - OAuth requires HTTPS in production
   - Update redirect URIs accordingly
   - Use proper SSL certificates

## 🆘 Troubleshooting

### Common Issues:

1. **"Invalid redirect URI"**
   - Check that redirect URI matches exactly in Google Console
   - Ensure no trailing slashes or extra characters

2. **"Access blocked"**
   - OAuth consent screen needs to be configured
   - Add your email to test users

3. **"Calendar not found"**
   - Provider needs to have Google Calendar enabled
   - Check provider email is correct

4. **"Permission denied"**
   - User needs to grant calendar permissions
   - Re-run OAuth flow

### Debug Mode:

Enable debug logging by setting:
```bash
export GOOGLE_CALENDAR_DEBUG=true
```

## 📞 Support

If you encounter issues:
1. Check the logs: `docker-compose -f compose/gateway.yaml logs gateway`
2. Run the test script: `python test_google_calendar.py`
3. Verify Google Cloud Console settings
4. Check OAuth consent screen configuration

---

**Ready to sync appointments with Google Calendar! 🗓️✨**
