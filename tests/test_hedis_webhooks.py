"""Tests for HEDIS campaign Retell webhook helpers and routes."""

import os
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("APP_ENVIRONMENT", "development")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only")
os.environ.setdefault("PHI_ENCRYPTION_KEY", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")


@pytest.mark.unit
def test_map_disconnection_voicemail() -> None:
    from Clinic_app.Routes.retell import _map_disconnection_to_outcome
    from Clinic_app.data.enums import ContactStatus

    assert _map_disconnection_to_outcome("voicemail_reached", False) == ContactStatus.VOICEMAIL
    assert _map_disconnection_to_outcome("machine_detected", False) == ContactStatus.VOICEMAIL


@pytest.mark.unit
def test_map_disconnection_booked_on_hangup_with_appt() -> None:
    from Clinic_app.Routes.retell import _map_disconnection_to_outcome
    from Clinic_app.data.enums import ContactStatus

    assert _map_disconnection_to_outcome("user_hangup", True) == ContactStatus.BOOKED
    assert _map_disconnection_to_outcome("user_hangup", False) == ContactStatus.DECLINED


@pytest.mark.unit
def test_hedis_metadata_merge() -> None:
    from Clinic_app.Routes.retell import _hedis_metadata_from_call

    md = _hedis_metadata_from_call(
        {"metadata": {"call_type": "hedis_campaign", "a": "1"}},
        {"b": "2"},
    )
    assert md["call_type"] == "hedis_campaign"
    assert md["a"] == "1"
    assert md["b"] == "2"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_apply_hedis_call_ended_voicemail_sets_pending_retry() -> None:
    from Clinic_app.Routes.retell import _apply_hedis_call_ended, CallEndedWebhook
    from Clinic_app.data.enums import ContactStatus

    clinic_id = uuid.uuid4()
    camp_id = uuid.uuid4()
    contact_id = uuid.uuid4()

    call_log = MagicMock()
    call_log.clinic_id = clinic_id

    webhook = CallEndedWebhook(
        call_id="c1",
        disconnection_reason="voicemail_reached",
        metadata={"call_type": "hedis_campaign", "campaign_contact_id": str(contact_id)},
    )

    contact = MagicMock()
    contact.id = contact_id
    contact.clinic_id = clinic_id
    contact.campaign_id = camp_id
    contact.attempt_count = 1
    contact.ehr_appointment_id = None
    contact.status = ContactStatus.CALLING.value

    campaign = MagicMock()
    campaign.id = camp_id
    campaign.clinic_id = clinic_id
    campaign.max_attempts = 3
    campaign.voicemail_retry_hours = 4
    campaign.no_answer_retry_hours = 2
    campaign.error_retry_hours = 1
    campaign.failed_count = 0
    campaign.booked_count = 0

    mock_db = AsyncMock()

    from Clinic_app.data.models.campaign_contact import CampaignContact as CC
    from Clinic_app.data.models.campaign import Campaign as Camp

    async def get_side_effect(model, pk):
        if model is CC:
            return contact if pk == contact_id else None
        if model is Camp:
            return campaign if pk == camp_id else None
        return None

    mock_db.get = AsyncMock(side_effect=get_side_effect)

    with patch("Clinic_app.Routes.retell.maybe_mark_campaign_completed", new_callable=AsyncMock):
        await _apply_hedis_call_ended(
            mock_db,
            call_log,
            webhook,
            {"metadata": webhook.metadata},
            datetime.now(timezone.utc),
        )

    assert contact.status == ContactStatus.PENDING.value
    assert contact.next_attempt_after is not None


@pytest.mark.unit
def test_campaign_start_route_registered() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from Clinic_app.Routes.campaigns import campaign_router
    from Clinic_app.common.database import get_db
    from Clinic_app.common.jwt import require_scoped_staff

    app = FastAPI()
    app.include_router(campaign_router)

    async def mock_db():
        yield AsyncMock()

    cid = uuid.uuid4()

    async def fake_staff():
        tok = MagicMock()
        tok.clinic_id = cid
        tok.role = "admin"
        tok.google_sub = "x"
        return tok

    app.dependency_overrides[get_db] = mock_db
    app.dependency_overrides[require_scoped_staff] = fake_staff

    with patch(
        "Clinic_app.Routes.campaigns.start_campaign",
        new_callable=AsyncMock,
    ) as sc, patch(
        "Clinic_app.Routes.campaigns.campaign_worker_manager.start_clinic_worker",
        new_callable=AsyncMock,
    ) as wk:
        mock_c = MagicMock()
        mock_c.id = uuid.uuid4()
        mock_c.name = "n"
        mock_c.measurement_year = 2026
        mock_c.status = "active"
        mock_c.total_contacts = 0
        mock_c.called_count = 0
        mock_c.booked_count = 0
        mock_c.failed_count = 0
        mock_c.calling_hours_start = "09:00"
        mock_c.calling_hours_end = "18:00"
        mock_c.max_attempts = 3
        mock_c.campaign_concurrency_limit = 3
        mock_c.created_at = datetime.now(timezone.utc)
        mock_c.updated_at = datetime.now(timezone.utc)
        sc.return_value = mock_c
        client = TestClient(app)
        r = client.post(f"/campaigns/{uuid.uuid4()}/start")
    app.dependency_overrides.clear()
    assert r.status_code == 200
    sc.assert_called_once()
    wk.assert_called_once()
