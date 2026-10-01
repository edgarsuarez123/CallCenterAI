# tests/test_campaign_routes.py
"""
Unit tests for Routes/campaigns.py.
All DB calls and service functions are mocked.
get_db is overridden via app.dependency_overrides (not patched).
"""

import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from Clinic_app.data.enums import CampaignStatus
from Clinic_app.Routes.campaigns import campaign_router
from Clinic_app.common.jwt import require_scoped_staff
from Clinic_app.common.database import get_db


# ── Test app setup ─────────────────────────────────────────────────────────────


def _make_app(staff):
    """Build a minimal FastAPI test app for campaign routes with mocked DB."""

    async def mock_db():
        yield AsyncMock()

    app = FastAPI()
    app.include_router(campaign_router)
    app.dependency_overrides[require_scoped_staff] = lambda: staff
    app.dependency_overrides[get_db] = mock_db
    return app


def _make_staff(role: str = "admin"):
    staff = MagicMock()
    staff.clinic_id = uuid.uuid4()
    staff.google_sub = "google_sub_abc"
    staff.role = role
    staff.token_type = "scoped"
    return staff


def _make_campaign(status: str = CampaignStatus.PENDING.value):
    c = MagicMock()
    c.id = uuid.uuid4()
    c.clinic_id = uuid.uuid4()
    c.name = "Q1 2026 HEDIS"
    c.measurement_year = 2026
    c.status = status
    c.total_contacts = 50
    c.called_count = 10
    c.booked_count = 5
    c.failed_count = 2
    c.calling_hours_start = "09:00"
    c.calling_hours_end = "18:00"
    c.max_attempts = 3
    c.campaign_concurrency_limit = 3
    c.created_at = datetime(2026, 3, 20, 10, 0, 0)
    c.updated_at = datetime(2026, 3, 20, 10, 0, 0)
    return c


def _make_upload_result():
    from Clinic_app.services.campaign_service import CampaignCreateResult

    return CampaignCreateResult(
        campaign_id=uuid.uuid4(),
        name="Q1 2026 HEDIS",
        measurement_year=2026,
        total_contacts=45,
    )


def _make_csv_bytes(rows: int = 3) -> bytes:
    lines = ["Member Phone,HEDIS Measure,Language"]
    for i in range(rows):
        lines.append(f"787555{1000 + i},COL,en")
    return "\n".join(lines).encode("utf-8")


def _make_parsed_rows(n: int = 3):
    from Clinic_app.services.csv_parser import ParsedRow
    from Clinic_app.data.enums import GapType

    return [
        ParsedRow(f"+1787555{1000 + i}", GapType.COLORECTAL, "en", raw_row_number=i + 2)
        for i in range(n)
    ]


# ── POST /campaigns/upload ─────────────────────────────────────────────────────


@pytest.mark.unit
class TestUploadEndpoint:
    def test_valid_csv_upload_returns_201(self):
        staff = _make_staff("admin")
        client = TestClient(_make_app(staff))
        upload_result = _make_upload_result()

        with patch(
            "Clinic_app.Routes.campaigns.parse_file", return_value=(_make_parsed_rows(), [])
        ), patch(
            "Clinic_app.Routes.campaigns.get_clinic_settings",
            new=AsyncMock(return_value=MagicMock()),
        ), patch(
            "Clinic_app.Routes.campaigns.get_staff_for_clinic",
            new=AsyncMock(return_value=MagicMock()),
        ), patch(
            "Clinic_app.Routes.campaigns.create_campaign", new=AsyncMock(return_value=upload_result)
        ):
            response = client.post(
                "/campaigns/upload",
                data={"name": "Q1 2026 HEDIS", "measurement_year": "2026"},
                files={"file": ("patients.csv", _make_csv_bytes(), "text/csv")},
            )

        assert response.status_code == 201
        data = response.json()
        assert "campaign_id" in data
        assert data["total_contacts"] == 45

    def test_viewer_cannot_upload_403(self):
        staff = _make_staff("viewer")
        client = TestClient(_make_app(staff))

        response = client.post(
            "/campaigns/upload",
            data={"name": "Test", "measurement_year": "2026"},
            files={"file": ("patients.csv", _make_csv_bytes(), "text/csv")},
        )
        assert response.status_code == 403

    def test_file_over_10mb_returns_422(self):
        staff = _make_staff("admin")
        client = TestClient(_make_app(staff))
        big_file = b"x" * (10 * 1024 * 1024 + 1)

        response = client.post(
            "/campaigns/upload",
            data={"name": "Test", "measurement_year": "2026"},
            files={"file": ("big.csv", big_file, "text/csv")},
        )
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "FILE_TOO_LARGE"

    def test_no_valid_rows_returns_422(self):
        staff = _make_staff("admin")
        client = TestClient(_make_app(staff))

        with patch("Clinic_app.Routes.campaigns.parse_file", return_value=([], [])):
            response = client.post(
                "/campaigns/upload",
                data={"name": "Test", "measurement_year": "2026"},
                files={"file": ("patients.csv", _make_csv_bytes(), "text/csv")},
            )
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "NO_VALID_ROWS"

    def test_parse_error_raises_422(self):
        staff = _make_staff("admin")
        client = TestClient(_make_app(staff))

        with patch(
            "Clinic_app.Routes.campaigns.parse_file",
            side_effect=ValueError("CSV has no phone column"),
        ):
            response = client.post(
                "/campaigns/upload",
                data={"name": "Test", "measurement_year": "2026"},
                files={"file": ("patients.csv", _make_csv_bytes(), "text/csv")},
            )
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "PARSE_ERROR"

    def test_over_2000_rows_returns_422(self):
        staff = _make_staff("admin")
        client = TestClient(_make_app(staff))
        too_many = _make_parsed_rows(2001)

        with patch("Clinic_app.Routes.campaigns.parse_file", return_value=(too_many, [])):
            response = client.post(
                "/campaigns/upload",
                data={"name": "Test", "measurement_year": "2026"},
                files={"file": ("patients.csv", _make_csv_bytes(), "text/csv")},
            )
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "TOO_MANY_ROWS"

    def test_excel_content_type_accepted(self):
        staff = _make_staff("admin")
        client = TestClient(_make_app(staff))
        upload_result = _make_upload_result()

        with patch(
            "Clinic_app.Routes.campaigns.parse_file", return_value=(_make_parsed_rows(), [])
        ), patch(
            "Clinic_app.Routes.campaigns.get_clinic_settings",
            new=AsyncMock(return_value=MagicMock()),
        ), patch(
            "Clinic_app.Routes.campaigns.get_staff_for_clinic",
            new=AsyncMock(return_value=MagicMock()),
        ), patch(
            "Clinic_app.Routes.campaigns.create_campaign", new=AsyncMock(return_value=upload_result)
        ):
            response = client.post(
                "/campaigns/upload",
                data={"name": "Test", "measurement_year": "2026"},
                files={
                    "file": (
                        "patients.xlsx",
                        b"xlsxdata",
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                },
            )
        assert response.status_code == 201


# ── GET /campaigns ─────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestListCampaignsRoute:
    def test_returns_list_for_clinic(self):
        staff = _make_staff("viewer")
        client = TestClient(_make_app(staff))
        campaigns = [_make_campaign(), _make_campaign()]

        with patch(
            "Clinic_app.Routes.campaigns.list_campaigns", new=AsyncMock(return_value=campaigns)
        ):
            response = client.get("/campaigns")

        assert response.status_code == 200
        assert len(response.json()) == 2

    def test_empty_list_returns_200(self):
        staff = _make_staff("viewer")
        client = TestClient(_make_app(staff))

        with patch("Clinic_app.Routes.campaigns.list_campaigns", new=AsyncMock(return_value=[])):
            response = client.get("/campaigns")

        assert response.status_code == 200
        assert response.json() == []

    def test_invalid_status_filter_returns_422(self):
        staff = _make_staff("viewer")
        client = TestClient(_make_app(staff))

        # No service call needed — validated before DB query
        with patch("Clinic_app.Routes.campaigns.list_campaigns", new=AsyncMock(return_value=[])):
            response = client.get("/campaigns?status=INVALID_STATUS")

        assert response.status_code == 422


# ── GET /campaigns/{id} ────────────────────────────────────────────────────────


@pytest.mark.unit
class TestGetCampaignRoute:
    def test_returns_campaign(self):
        staff = _make_staff("viewer")
        client = TestClient(_make_app(staff))
        campaign = _make_campaign()

        with patch(
            "Clinic_app.Routes.campaigns.get_campaign", new=AsyncMock(return_value=campaign)
        ):
            response = client.get(f"/campaigns/{campaign.id}")

        assert response.status_code == 200
        assert response.json()["name"] == "Q1 2026 HEDIS"


# ── POST /campaigns/{id}/pause ─────────────────────────────────────────────────


@pytest.mark.unit
class TestPauseCampaignRoute:
    def test_admin_can_pause(self):
        staff = _make_staff("admin")
        client = TestClient(_make_app(staff))
        campaign = _make_campaign(CampaignStatus.PAUSED.value)

        with patch(
            "Clinic_app.Routes.campaigns.pause_campaign", new=AsyncMock(return_value=campaign)
        ):
            response = client.post(f"/campaigns/{uuid.uuid4()}/pause")

        assert response.status_code == 200
        assert response.json()["status"] == CampaignStatus.PAUSED.value

    def test_viewer_cannot_pause(self):
        staff = _make_staff("viewer")
        client = TestClient(_make_app(staff))

        response = client.post(f"/campaigns/{uuid.uuid4()}/pause")
        assert response.status_code == 403


# ── GET /campaigns/{id}/export — PHI safety ────────────────────────────────────


@pytest.mark.unit
class TestExportRoute:
    def test_export_contains_no_phi(self):
        """Export CSV must not contain decrypted phone numbers or patient names."""
        staff = _make_staff("viewer")
        client = TestClient(_make_app(staff))
        campaign = _make_campaign()

        contact = MagicMock()
        contact.id = uuid.uuid4()
        contact.phone_hash = "abc123deadbeef"
        contact.gap_type = "colorectal"
        contact.preferred_language = "en"
        contact.status = "pending"
        contact.attempt_count = 0
        contact.last_attempted_at = None
        contact.ehr_appointment_id = None
        contact.created_at = datetime(2026, 3, 20)

        with patch(
            "Clinic_app.Routes.campaigns.get_campaign", new=AsyncMock(return_value=campaign)
        ), patch(
            "Clinic_app.Routes.campaigns.get_campaign_contacts",
            new=AsyncMock(return_value=[contact]),
        ):
            response = client.get(f"/campaigns/{campaign.id}/export")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")

        csv_content = response.content.decode("utf-8")
        # Phone hash should be present
        assert "abc123deadbeef" in csv_content
        # No raw E.164 phone numbers
        assert "+1787" not in csv_content
        # No patient_name column in header
        header_line = csv_content.split("\n")[0]
        assert "patient_name" not in header_line
        assert "name" not in header_line
