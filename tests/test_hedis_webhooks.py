"""Tests for HEDIS campaign Retell webhook helpers and routes."""

import os
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

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


@pytest.mark.asyncio
@pytest.mark.unit
async def test_apply_hedis_call_ended_order_based_hangup_sets_order_agreed() -> None:
    """Normal hangup without EHR appt maps to DECLINED in mapper; order-based → ORDER_AGREED."""
    from Clinic_app.Routes.retell import _apply_hedis_call_ended, CallEndedWebhook
    from Clinic_app.data.enums import ContactStatus, GapType

    clinic_id = uuid.uuid4()
    camp_id = uuid.uuid4()
    contact_id = uuid.uuid4()

    call_log = MagicMock()
    call_log.clinic_id = clinic_id

    webhook = CallEndedWebhook(
        call_id="c1",
        disconnection_reason="user_hangup",
        metadata={"call_type": "hedis_campaign", "campaign_contact_id": str(contact_id)},
    )

    contact = MagicMock()
    contact.id = contact_id
    contact.clinic_id = clinic_id
    contact.campaign_id = camp_id
    contact.attempt_count = 1
    contact.ehr_appointment_id = None
    contact.gap_type = GapType.COLORECTAL.value
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

    assert contact.status == ContactStatus.ORDER_AGREED.value


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


@pytest.mark.unit
def test_call_analyzed_order_based_decline_flips_to_order_declined() -> None:
    """Order-based + patient_agreed false: ORDER_AGREED -> ORDER_DECLINED."""
    from Clinic_app.Routes import retell as retell_mod
    from Clinic_app.common.database import get_db
    from Clinic_app.data.enums import ContactStatus, GapType

    clinic_id = uuid.uuid4()
    contact_id = uuid.uuid4()
    camp_id = uuid.uuid4()

    contact = MagicMock()
    contact.id = contact_id
    contact.clinic_id = clinic_id
    contact.campaign_id = camp_id
    contact.gap_type = GapType.COLORECTAL.value
    contact.status = ContactStatus.ORDER_AGREED.value
    contact.attempt_count = 1
    contact.ehr_appointment_id = None

    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=contact)
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()

    async def fake_db():
        yield mock_db

    app = FastAPI()
    app.include_router(retell_mod.retell_router)
    app.dependency_overrides[get_db] = fake_db

    def fake_extract(transcript: str, gap_type: str) -> dict:
        return {
            "patient_agreed": False,
            "action_for_staff": "",
            "note": "Patient refused the kit.",
        }

    with patch.object(
        retell_mod, "_get_clinic_by_agent_id", new_callable=AsyncMock, return_value=clinic_id
    ), patch.object(retell_mod, "extract_order_based_notes_sync", side_effect=fake_extract):
        client = TestClient(app)
        r = client.post(
            "/retell/webhook/call_analyzed",
            json={
                "call": {
                    "call_id": "test_call_analyzed_decline",
                    "agent_id": "agent_x",
                    "end_timestamp": 1_700_000_000_000,
                    "metadata": {
                        "call_type": "hedis_campaign",
                        "campaign_contact_id": str(contact_id),
                    },
                    "transcript": "user declined the kit",
                }
            },
        )

    assert r.status_code == 200
    assert contact.status == ContactStatus.ORDER_DECLINED.value
    mock_db.commit.assert_called()


@pytest.mark.unit
def test_call_analyzed_preventive_uses_summarizer_not_extractor() -> None:
    """Appointment-based gap uses summarize_transcript_sync."""
    from Clinic_app.Routes import retell as retell_mod
    from Clinic_app.common.database import get_db
    from Clinic_app.data.enums import ContactStatus, GapType

    clinic_id = uuid.uuid4()
    contact_id = uuid.uuid4()
    camp_id = uuid.uuid4()

    contact = MagicMock()
    contact.id = contact_id
    contact.clinic_id = clinic_id
    contact.campaign_id = camp_id
    contact.gap_type = GapType.PREVENTIVE_VISIT.value
    contact.status = ContactStatus.BOOKED.value
    contact.attempt_count = 1
    contact.ehr_appointment_id = "ehr-1"

    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=contact)
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()

    async def fake_db():
        yield mock_db

    app = FastAPI()
    app.include_router(retell_mod.retell_router)
    app.dependency_overrides[get_db] = fake_db

    with patch.object(
        retell_mod, "_get_clinic_by_agent_id", new_callable=AsyncMock, return_value=clinic_id
    ), patch.object(
        retell_mod, "summarize_transcript_sync", return_value="Booked annual visit."
    ) as sum_mock, patch.object(
        retell_mod, "extract_order_based_notes_sync"
    ) as ext_mock:
        client = TestClient(app)
        r = client.post(
            "/retell/webhook/call_analyzed",
            json={
                "call": {
                    "call_id": "test_call_analyzed_prev",
                    "agent_id": "agent_x",
                    "end_timestamp": 1_700_000_000_000,
                    "metadata": {
                        "call_type": "hedis_campaign",
                        "campaign_contact_id": str(contact_id),
                    },
                    "transcript": "appointment confirmed",
                }
            },
        )

    assert r.status_code == 200
    sum_mock.assert_called_once()
    ext_mock.assert_not_called()


@pytest.mark.unit
def test_call_analyzed_human_request_sets_human_requested() -> None:
    """Transcript requests human: escalates to HUMAN_REQUESTED (order-based path)."""
    from Clinic_app.Routes import retell as retell_mod
    from Clinic_app.common.database import get_db
    from Clinic_app.data.enums import ContactStatus, GapType

    clinic_id = uuid.uuid4()
    contact_id = uuid.uuid4()
    camp_id = uuid.uuid4()

    contact = MagicMock()
    contact.id = contact_id
    contact.clinic_id = clinic_id
    contact.campaign_id = camp_id
    contact.gap_type = GapType.COLORECTAL.value
    contact.status = ContactStatus.ORDER_AGREED.value
    contact.attempt_count = 1
    contact.ehr_appointment_id = None

    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=contact)
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()

    async def fake_db():
        yield mock_db

    app = FastAPI()
    app.include_router(retell_mod.retell_router)
    app.dependency_overrides[get_db] = fake_db

    def fake_extract(transcript: str, gap_type: str) -> dict:
        return {
            "patient_agreed": True,
            "action_for_staff": "",
            "note": "Patient agreed.",
        }

    with patch.object(
        retell_mod, "_get_clinic_by_agent_id", new_callable=AsyncMock, return_value=clinic_id
    ), patch.object(retell_mod, "extract_order_based_notes_sync", side_effect=fake_extract):
        client = TestClient(app)
        r = client.post(
            "/retell/webhook/call_analyzed",
            json={
                "call": {
                    "call_id": "test_call_analyzed_human",
                    "agent_id": "agent_x",
                    "end_timestamp": 1_700_000_000_000,
                    "metadata": {
                        "call_type": "hedis_campaign",
                        "campaign_contact_id": str(contact_id),
                    },
                    "transcript": "I need to speak to a human about this",
                }
            },
        )

    assert r.status_code == 200
    assert contact.status == ContactStatus.HUMAN_REQUESTED.value


@pytest.mark.unit
def test_call_analyzed_human_request_does_not_override_booked() -> None:
    """BOOKED + human phrase: keep BOOKED (successful appointment)."""
    from Clinic_app.Routes import retell as retell_mod
    from Clinic_app.common.database import get_db
    from Clinic_app.data.enums import ContactStatus, GapType

    clinic_id = uuid.uuid4()
    contact_id = uuid.uuid4()
    camp_id = uuid.uuid4()

    contact = MagicMock()
    contact.id = contact_id
    contact.clinic_id = clinic_id
    contact.campaign_id = camp_id
    contact.gap_type = GapType.PREVENTIVE_VISIT.value
    contact.status = ContactStatus.BOOKED.value
    contact.attempt_count = 1
    contact.ehr_appointment_id = "appt-1"

    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=contact)
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()

    async def fake_db():
        yield mock_db

    app = FastAPI()
    app.include_router(retell_mod.retell_router)
    app.dependency_overrides[get_db] = fake_db

    with patch.object(
        retell_mod, "_get_clinic_by_agent_id", new_callable=AsyncMock, return_value=clinic_id
    ), patch.object(
        retell_mod, "summarize_transcript_sync", return_value="Booked."
    ):
        client = TestClient(app)
        r = client.post(
            "/retell/webhook/call_analyzed",
            json={
                "call": {
                    "call_id": "test_call_analyzed_booked_human",
                    "agent_id": "agent_x",
                    "end_timestamp": 1_700_000_000_000,
                    "metadata": {
                        "call_type": "hedis_campaign",
                        "campaign_contact_id": str(contact_id),
                    },
                    "transcript": "speak to a human",
                }
            },
        )

    assert r.status_code == 200
    assert contact.status == ContactStatus.BOOKED.value
