# tests/test_clinic_settings.py
"""
Unit tests for:
  - services/clinic_service.py (validation logic)
  - Routes/clinic.py (GET/PATCH /clinic/settings)
All DB calls are mocked.
"""

import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient


# ── validate_hhmm ──────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestValidateHHMM:
    def test_valid_time(self):
        from Clinic_app.services.clinic_service import validate_hhmm
        # Should not raise
        validate_hhmm("09:00", "calling_hours_start")
        validate_hhmm("18:00", "calling_hours_end")
        validate_hhmm("00:00", "test")
        validate_hhmm("23:59", "test")

    def test_invalid_format_raises_422(self):
        from Clinic_app.services.clinic_service import validate_hhmm
        with pytest.raises(HTTPException) as exc_info:
            validate_hhmm("9am", "calling_hours_start")
        assert exc_info.value.status_code == 422

    def test_out_of_range_hour_raises_422(self):
        from Clinic_app.services.clinic_service import validate_hhmm
        with pytest.raises(HTTPException):
            validate_hhmm("25:00", "calling_hours_start")

    def test_out_of_range_minute_raises_422(self):
        from Clinic_app.services.clinic_service import validate_hhmm
        with pytest.raises(HTTPException):
            validate_hhmm("09:99", "calling_hours_start")

    def test_empty_string_raises_422(self):
        from Clinic_app.services.clinic_service import validate_hhmm
        with pytest.raises(HTTPException):
            validate_hhmm("", "calling_hours_start")


# ── update_clinic_settings validation ─────────────────────────────────────────

@pytest.mark.unit
@pytest.mark.asyncio
class TestUpdateClinicSettingsValidation:
    def _make_mock_integration(self, start="09:00", end="18:00"):
        ci = MagicMock()
        ci.calling_hours_start = start
        ci.calling_hours_end = end
        ci.campaign_concurrency_limit = 3
        ci.max_attempts = 3
        ci.voicemail_retry_hours = 4
        ci.no_answer_retry_hours = 2
        ci.error_retry_hours = 24
        ci.timezone = "America/New_York"
        return ci

    async def test_start_after_end_raises_422(self):
        from Clinic_app.services.clinic_service import update_clinic_settings
        mock_db = AsyncMock()
        ci = self._make_mock_integration()
        with patch("Clinic_app.services.clinic_service.get_clinic_settings",
                   new=AsyncMock(return_value=ci)):
            with pytest.raises(HTTPException) as exc_info:
                await update_clinic_settings(
                    mock_db, uuid.uuid4(),
                    calling_hours_start="18:00",
                    calling_hours_end="09:00",
                )
        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "INVALID_HOURS"

    async def test_equal_start_end_raises_422(self):
        from Clinic_app.services.clinic_service import update_clinic_settings
        mock_db = AsyncMock()
        ci = self._make_mock_integration()
        with patch("Clinic_app.services.clinic_service.get_clinic_settings",
                   new=AsyncMock(return_value=ci)):
            with pytest.raises(HTTPException) as exc_info:
                await update_clinic_settings(
                    mock_db, uuid.uuid4(),
                    calling_hours_start="09:00",
                    calling_hours_end="09:00",
                )
        assert exc_info.value.status_code == 422

    async def test_concurrency_limit_too_high_raises_422(self):
        from Clinic_app.services.clinic_service import update_clinic_settings
        mock_db = AsyncMock()
        ci = self._make_mock_integration()
        with patch("Clinic_app.services.clinic_service.get_clinic_settings",
                   new=AsyncMock(return_value=ci)):
            with pytest.raises(HTTPException) as exc_info:
                await update_clinic_settings(
                    mock_db, uuid.uuid4(),
                    campaign_concurrency_limit=11,
                )
        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "INVALID_CONCURRENCY"

    async def test_concurrency_limit_zero_raises_422(self):
        from Clinic_app.services.clinic_service import update_clinic_settings
        mock_db = AsyncMock()
        ci = self._make_mock_integration()
        with patch("Clinic_app.services.clinic_service.get_clinic_settings",
                   new=AsyncMock(return_value=ci)):
            with pytest.raises(HTTPException):
                await update_clinic_settings(
                    mock_db, uuid.uuid4(),
                    campaign_concurrency_limit=0,
                )

    async def test_max_attempts_too_high_raises_422(self):
        from Clinic_app.services.clinic_service import update_clinic_settings
        mock_db = AsyncMock()
        ci = self._make_mock_integration()
        with patch("Clinic_app.services.clinic_service.get_clinic_settings",
                   new=AsyncMock(return_value=ci)):
            with pytest.raises(HTTPException) as exc_info:
                await update_clinic_settings(
                    mock_db, uuid.uuid4(),
                    max_attempts=6,
                )
        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "INVALID_ATTEMPTS"

    async def test_invalid_timezone_raises_422(self):
        from Clinic_app.services.clinic_service import update_clinic_settings
        mock_db = AsyncMock()
        ci = self._make_mock_integration()
        with patch("Clinic_app.services.clinic_service.get_clinic_settings",
                   new=AsyncMock(return_value=ci)):
            with pytest.raises(HTTPException) as exc_info:
                await update_clinic_settings(
                    mock_db, uuid.uuid4(),
                    timezone="Not/ATimezone",
                )
        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "INVALID_TIMEZONE"

    async def test_valid_update_applies_changes(self):
        from Clinic_app.services.clinic_service import update_clinic_settings
        mock_db = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()
        ci = self._make_mock_integration()
        with patch("Clinic_app.services.clinic_service.get_clinic_settings",
                   new=AsyncMock(return_value=ci)):
            result = await update_clinic_settings(
                mock_db, uuid.uuid4(),
                calling_hours_start="08:00",
                calling_hours_end="17:00",
                max_attempts=2,
                timezone="America/Chicago",
            )
        assert ci.calling_hours_start == "08:00"
        assert ci.calling_hours_end == "17:00"
        assert ci.max_attempts == 2
        assert ci.timezone == "America/Chicago"

    async def test_retry_hours_too_high_raises_422(self):
        from Clinic_app.services.clinic_service import update_clinic_settings
        mock_db = AsyncMock()
        ci = self._make_mock_integration()
        with patch("Clinic_app.services.clinic_service.get_clinic_settings",
                   new=AsyncMock(return_value=ci)):
            with pytest.raises(HTTPException) as exc_info:
                await update_clinic_settings(
                    mock_db, uuid.uuid4(),
                    voicemail_retry_hours=73,
                )
        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "INVALID_RETRY_HOURS"

    async def test_valid_iana_timezone_passes(self):
        from Clinic_app.services.clinic_service import update_clinic_settings
        mock_db = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()
        ci = self._make_mock_integration()
        with patch("Clinic_app.services.clinic_service.get_clinic_settings",
                   new=AsyncMock(return_value=ci)):
            # These are all valid IANA timezones — should not raise
            for tz in ["America/New_York", "America/Chicago", "America/Los_Angeles",
                       "America/Puerto_Rico", "Pacific/Honolulu"]:
                await update_clinic_settings(mock_db, uuid.uuid4(), timezone=tz)


# ── Route: GET /clinic/settings ────────────────────────────────────────────────

@pytest.mark.unit
class TestClinicSettingsRoute:
    def _make_app_and_client(self, scoped_staff):
        """Build a minimal FastAPI test app with the clinic router."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from Clinic_app.Routes.clinic import clinic_router
        from Clinic_app.common.jwt import require_scoped_staff
        from Clinic_app.common.database import get_db

        async def mock_db():
            yield AsyncMock()

        app = FastAPI()
        app.include_router(clinic_router)
        app.dependency_overrides[require_scoped_staff] = lambda: scoped_staff
        app.dependency_overrides[get_db] = mock_db
        return TestClient(app)

    def _make_staff(self, role: str = "admin"):
        staff = MagicMock()
        staff.clinic_id = uuid.uuid4()
        staff.google_sub = "google_sub_123"
        staff.role = role
        staff.token_type = "scoped"
        return staff

    def _make_integration_response(self):
        ci = MagicMock()
        ci.timezone = "America/New_York"
        ci.calling_hours_start = "09:00"
        ci.calling_hours_end = "18:00"
        ci.campaign_concurrency_limit = 3
        ci.max_attempts = 3
        ci.voicemail_retry_hours = 4
        ci.no_answer_retry_hours = 2
        ci.error_retry_hours = 24
        return ci

    def test_get_settings_returns_200(self):
        staff = self._make_staff("viewer")
        client = self._make_app_and_client(staff)
        ci = self._make_integration_response()

        with patch("Clinic_app.Routes.clinic.get_clinic_settings",
                   new=AsyncMock(return_value=ci)), \
             patch("Clinic_app.Routes.clinic.get_db", new=AsyncMock()):
            response = client.get("/clinic/settings")

        assert response.status_code == 200
        data = response.json()
        assert data["timezone"] == "America/New_York"
        assert data["calling_hours_start"] == "09:00"

    def test_patch_settings_as_viewer_returns_403(self):
        staff = self._make_staff("viewer")
        client = self._make_app_and_client(staff)

        with patch("Clinic_app.Routes.clinic.get_db", new=AsyncMock()):
            response = client.patch("/clinic/settings", json={"max_attempts": 2})

        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "FORBIDDEN"

    def test_patch_settings_as_admin_returns_200(self):
        staff = self._make_staff("admin")
        client = self._make_app_and_client(staff)
        ci = self._make_integration_response()

        with patch("Clinic_app.Routes.clinic.get_db", new=AsyncMock()), \
             patch("Clinic_app.Routes.clinic.update_clinic_settings",
                   new=AsyncMock(return_value=ci)):
            response = client.patch("/clinic/settings", json={"max_attempts": 2})

        assert response.status_code == 200
