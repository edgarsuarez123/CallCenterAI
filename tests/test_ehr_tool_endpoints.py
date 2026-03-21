"""Unit tests for NextGen EHR Retell tool routes (/retell/tools/*)."""

import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("APP_ENVIRONMENT", "development")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")


def _retell_only_app():
    """Minimal app — avoids importing full main (lighter test deps)."""
    from Clinic_app.Routes.retell import retell_router
    from Clinic_app.common.database import get_db

    app = FastAPI()
    app.include_router(retell_router)

    async def mock_get_db():
        yield AsyncMock()

    app.dependency_overrides[get_db] = mock_get_db
    return app


@pytest.mark.unit
class TestEhrGetAvailableSlots:
    def test_returns_slots_when_ehr_configured(self):
        from fastapi.testclient import TestClient

        app = _retell_only_app()
        client = TestClient(app, raise_server_exceptions=False)

        clinic_id = uuid.uuid4()

        mock_cfg = MagicMock()
        mock_cfg.appt_type_mapping = {}

        with patch(
            "Clinic_app.Routes.retell._get_clinic_by_agent_id",
            new_callable=AsyncMock,
            return_value=clinic_id,
        ), patch(
            "Clinic_app.Routes.retell._get_ehr_config_row",
            new_callable=AsyncMock,
            return_value=mock_cfg,
        ), patch(
            "Clinic_app.Routes.retell.playwright_ehr_service"
        ) as mock_ehr:
            mock_ehr.get_available_slots = AsyncMock(
                return_value=[
                    {
                        "start_time": "2026-04-01T09:00:00-05:00",
                        "end_time": "2026-04-01T09:30:00-05:00",
                        "provider_name": "Dr. X",
                    }
                ]
            )
            body = {
                "call": {"agent_id": "agent-1", "call_id": "playground", "metadata": {}},
                "args": {"provider_name": "Dr. X", "date": "2026-04-01"},
            }
            r = client.post("/retell/tools/get_available_slots", json=body)
        app.dependency_overrides.clear()

        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert len(data["slots"]) == 1
        assert "April" in data["slots"][0] or "April" in data["slots"][0].replace(",", "")

    def test_missing_agent_id(self):
        from fastapi.testclient import TestClient

        app = _retell_only_app()
        client = TestClient(app, raise_server_exceptions=False)
        body = {"call": {"call_id": "playground"}, "args": {"provider_name": "Dr. X"}}
        r = client.post("/retell/tools/get_available_slots", json=body)
        app.dependency_overrides.clear()
        assert r.status_code == 200
        assert r.json()["success"] is False


@pytest.mark.unit
class TestEhrBookAppointment:
    def test_success_path(self):
        from fastapi.testclient import TestClient

        clinic_id = uuid.uuid4()

        app = _retell_only_app()
        client = TestClient(app, raise_server_exceptions=False)

        mock_cfg = MagicMock()
        mock_cfg.appt_type_mapping = {"colorectal_cancer_screening": "PREV"}

        with patch(
            "Clinic_app.Routes.retell._get_clinic_by_agent_id",
            new_callable=AsyncMock,
            return_value=clinic_id,
        ), patch(
            "Clinic_app.Routes.retell._get_ehr_config_row",
            new_callable=AsyncMock,
            return_value=mock_cfg,
        ), patch(
            "Clinic_app.Routes.retell.playwright_ehr_service"
        ) as mock_ehr:
            mock_ehr.book_appointment = AsyncMock(
                return_value={"success": True, "ehr_appointment_id": "NG-999"}
            )
            body = {
                "call": {"agent_id": "agent-1", "call_id": "playground"},
                "args": {
                    "provider_name": "Dr. X",
                    "chosen_slot": "2026-04-01T09:00:00-05:00",
                    "patient_name": "Jane Doe",
                    "patient_dob": "1980-01-15",
                    "gap_type": "colorectal_cancer_screening",
                },
            }
            r = client.post("/retell/tools/book_appointment", json=body)
            mock_ehr.book_appointment.assert_awaited_once()
        app.dependency_overrides.clear()

        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert data["ehr_appointment_id"] == "NG-999"

    def test_missing_fields(self):
        from fastapi.testclient import TestClient

        app = _retell_only_app()
        client = TestClient(app, raise_server_exceptions=False)

        mock_cfg = MagicMock()
        mock_cfg.appt_type_mapping = {}

        with patch(
            "Clinic_app.Routes.retell._get_clinic_by_agent_id",
            new_callable=AsyncMock,
            return_value=uuid.uuid4(),
        ), patch(
            "Clinic_app.Routes.retell._get_ehr_config_row",
            new_callable=AsyncMock,
            return_value=mock_cfg,
        ):
            body = {
                "call": {"agent_id": "agent-1", "call_id": "playground"},
                "args": {"provider_name": "Dr. X"},
            }
            r = client.post("/retell/tools/book_appointment", json=body)
        app.dependency_overrides.clear()
        assert r.json()["success"] is False
